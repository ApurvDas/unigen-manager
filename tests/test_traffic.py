import ctypes, datetime, json, sys, threading
import pytest

import traffic, wifi

G = {"unigen": {"guid": "11111111-1111-1111-1111-111111111111", "on": True},
     "builtin": {"guid": "22222222-2222-2222-2222-222222222222", "on": False}}


class Rig:
    """A sampler on fake counters and a fake clock: counts[key] = (in, out) is what Windows would say now."""

    def __init__(self, monkeypatch, tmp_path, radios=None):
        self.t, self.day, self.counts, self.radios = 1000.0, "2026-10-19", {"unigen": (0, 0), "builtin": (0, 0)}, dict(radios or G)
        self.bad = set()
        by_guid = lambda g: next(k for k, v in G.items() if v["guid"] == g)

        def counters(guid):
            k = by_guid(guid)
            if k in self.bad:
                raise OSError("no counters")
            return self.counts[k]
        monkeypatch.setattr(traffic, "counters", counters)
        monkeypatch.setattr(traffic.wifi, "radios", lambda: self.radios)
        monkeypatch.setattr(traffic, "_now", lambda: self.t)
        monkeypatch.setattr(traffic, "_today", lambda: self.day)
        self.path = tmp_path / "traffic.json"
        self.s = traffic.Sampler(self.path)

    def tick(self, secs=1.0, **counts):
        self.t += secs
        self.counts.update(counts)
        self.s.tick()

    def ad(self, key="unigen"):
        return next(a for a in self.s.snapshot()["adapters"] if a["key"] == key)


@pytest.fixture
def rig(monkeypatch, tmp_path):
    return Rig(monkeypatch, tmp_path)


def test_mib_if_row2_matches_the_windows_sdk_layout():
    M = traffic.MIB_IF_ROW2
    if sys.maxsize > 2**32:
        assert ctypes.sizeof(M) == 1352  # sizeof(MIB_IF_ROW2) on x64
    assert [M.InterfaceGuid.offset, M.Alias.offset, M.Description.offset, M.PhysicalAddress.offset] == [12, 28, 542, 1060]
    assert M.InterfaceAndOperStatusFlags.size == 1  # the eight BOOLEAN bit flags are one byte
    assert [M.InterfaceAndOperStatusFlags.offset, M.OperStatus.offset, M.NetworkGuid.offset, M.TransmitLinkSpeed.offset] == [1152, 1156, 1168, 1192]
    assert [M.InOctets.offset, M.OutOctets.offset, M.OutQLen.offset] == [1208, 1280, 1344]


def test_first_sample_has_no_rate_then_rate_is_delta_over_time(rig):
    rig.tick(unigen=(1000, 500))
    a = rig.ad()
    assert a["down"] is None and a["up"] is None and a["history"] == []
    assert rig.s.rate("unigen") is None
    rig.tick(2.0, unigen=(5000, 1500))  # 4000 B down and 1000 B up in 2 s
    a = rig.ad()
    assert (a["down"], a["up"]) == (2000, 500) and a["history"] == [[2000, 500]]
    assert rig.s.rate("unigen") == (2000, 500)


def test_a_counter_that_goes_back_counts_as_zero_and_rebases(rig):
    rig.tick(unigen=(10_000, 10_000))
    rig.tick(unigen=(12_000, 11_000))
    rig.tick(unigen=(50, 9_000))  # reset or re-plug: both went backwards
    a = rig.ad()
    assert (a["down"], a["up"]) == (0, 0)
    assert rig.s.snapshot()["today"]["unigen"] == {"down": 2000, "up": 1000}  # nothing negative, nothing invented
    rig.tick(unigen=(1050, 9_500))  # counting again from the new base
    assert (rig.ad()["down"], rig.ad()["up"]) == (1000, 500)


def test_history_is_capped_at_60_oldest_first(rig):
    rig.tick(unigen=(0, 0))
    for i in range(1, 75):
        rig.tick(unigen=(i * 100, 0))
    h = rig.ad()["history"]
    assert len(h) == traffic.HISTORY == 60 and h[-1] == [100, 0]
    assert rig.s.snapshot()["tick"] == 75


def test_today_accumulates_per_adapter(rig):
    rig.tick(unigen=(0, 0), builtin=(100, 100))
    rig.tick(unigen=(3000, 200), builtin=(100, 100))
    rig.tick(unigen=(5000, 700), builtin=(400, 100))
    assert rig.s.snapshot()["today"] == {"unigen": {"down": 5000, "up": 700}, "builtin": {"down": 300, "up": 0}}


def test_midnight_starts_a_new_day_and_old_days_stay_30(rig):
    rig.tick(unigen=(0, 0))
    rig.tick(unigen=(1000, 0))
    rig.day = "2026-10-20"
    rig.tick(unigen=(1500, 0))
    snap = rig.s.snapshot()
    assert snap["today"]["unigen"] == {"down": 500, "up": 0}  # the new day counts from zero
    assert rig.s._days["2026-10-19"]["unigen"]["down"] == 1000
    for n in range(1, 41):  # forty more days: only the last 30 are kept
        rig.day = (datetime.date(2026, 10, 20) + datetime.timedelta(days=n)).isoformat()
        rig.tick(unigen=(rig.counts["unigen"][0] + 1, 0))
    assert len(rig.s._days) == traffic.KEEP_DAYS == 30
    assert "2026-10-19" not in rig.s._days and rig.day in rig.s._days


def test_totals_round_trip_through_the_file(monkeypatch, tmp_path, rig):
    rig.tick(unigen=(0, 0))
    rig.tick(unigen=(4000, 300))
    rig.s.stop()  # writes
    assert json.loads(rig.path.read_text(encoding="utf-8")) == {
        "2026-10-19": {"unigen": {"down": 4000, "up": 300}, "builtin": {"down": 0, "up": 0}}}
    again = traffic.Sampler(rig.path)  # a restart
    assert again._days["2026-10-19"]["unigen"] == {"down": 4000, "up": 300}
    rig.s.stop()  # twice is fine


def test_the_file_is_written_every_30_seconds_not_every_tick(rig):
    rig.tick(unigen=(0, 0))
    rig.tick(unigen=(100, 0))
    assert not rig.path.exists()
    rig.tick(30.0, unigen=(200, 0))
    assert json.loads(rig.path.read_text(encoding="utf-8"))["2026-10-19"]["unigen"]["down"] == 200


def test_a_corrupt_or_odd_file_is_ignored(monkeypatch, tmp_path):
    p = tmp_path / "traffic.json"
    for text in ("{not json", "[]", "null", '{"2026-10-19": 5}', '{"not-a-day": {"unigen": {"down": 1, "up": 1}}}',
                 '{"2026-10-19": {"unigen": {"down": "x", "up": 1}}}', '{"2026-10-19": {"unigen": {"down": -5, "up": 1}}}'):
        p.write_text(text, encoding="utf-8")
        assert traffic.Sampler(p)._days == {}, text
    p.write_text('{"2026-10-19": {"unigen": {"down": 7, "up": 8.9}, "junk": 1}}', encoding="utf-8")
    assert traffic.Sampler(p)._days == {"2026-10-19": {"unigen": {"down": 7, "up": 8}}}  # the good part is kept
    assert traffic.Sampler(tmp_path / "missing.json")._days == {}


def test_an_unwritable_file_does_not_raise(rig, monkeypatch):
    rig.tick(unigen=(0, 0))
    rig.tick(unigen=(1000, 0))
    monkeypatch.setattr(traffic.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    rig.s.save()  # logs, keeps the totals for the next try
    assert rig.s._dirty is True


def test_an_adapter_that_vanishes_and_comes_back_starts_again_without_a_rate(rig):
    rig.tick(unigen=(0, 0))
    rig.tick(unigen=(1000, 0))
    assert rig.ad()["down"] == 1000
    rig.bad.add("unigen")  # counters fail for one tick (unplugged): no exception reaches the caller
    rig.tick(unigen=(2000, 0))
    assert rig.ad()["down"] is None and rig.ad()["history"] == []
    rig.bad.clear()
    rig.tick(unigen=(9000, 0))  # back: this is a first sample again
    assert rig.ad()["down"] is None
    rig.tick(unigen=(9500, 0))
    assert rig.ad()["down"] == 500
    assert rig.s.snapshot()["today"]["unigen"]["down"] == 1500  # the time away adds nothing


def test_the_guid_map_is_refreshed_every_10_seconds(rig):
    rig.tick(unigen=(0, 0))
    assert set(rig.s.radios()) == {"unigen", "builtin"} and rig.s.radios()["unigen"] is True
    rig.radios = {"builtin": G["builtin"]}  # the dongle is pulled
    rig.tick(5.0, builtin=(0, 0))
    assert "unigen" in rig.s.radios()  # not yet read again
    rig.tick(6.0, builtin=(0, 0))
    assert set(rig.s.radios()) == {"builtin"}
    assert [a["key"] for a in rig.s.snapshot()["adapters"]] == ["builtin"]
    rig.radios = dict(G)  # and plugged back
    rig.tick(10.0)
    assert [a["key"] for a in rig.s.snapshot()["adapters"]] == ["unigen", "builtin"]


def test_a_failing_radio_list_keeps_the_last_map(rig, monkeypatch):
    rig.tick(unigen=(0, 0))
    def boom():
        raise wifi.WifiError("Windows' Wi-Fi service isn't running.")
    monkeypatch.setattr(traffic.wifi, "radios", boom)
    rig.tick(11.0, unigen=(10, 0))
    assert set(rig.s.radios()) == {"unigen", "builtin"} and rig.ad()["down"] is not None


def test_the_thread_survives_errors_and_stops_cleanly(rig, monkeypatch):
    calls = []
    def tick():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
    monkeypatch.setattr(rig.s, "tick", tick)
    monkeypatch.setattr(traffic, "TICK", 0.01)
    rig.s.start()
    rig.s.start()  # a second start does not add a thread
    for _ in range(200):
        if len(calls) >= 3:
            break
        threading.Event().wait(0.01)
    assert len(calls) >= 3  # it kept going after the error
    rig.s.stop()
    assert not rig.s._thread.is_alive()
    n = len(calls)
    threading.Event().wait(0.05)
    assert len(calls) == n


def test_snapshot_lists_the_dongle_first_with_names_and_zero_rows(rig):
    rig.tick()
    snap = rig.s.snapshot()
    assert [(a["key"], a["name"]) for a in snap["adapters"]] == [("unigen", "Unigen dongle"), ("builtin", "Built-in MediaTek")]
    assert snap["today"] == {"unigen": {"down": 0, "up": 0}, "builtin": {"down": 0, "up": 0}}


def test_rate_text():
    f = traffic.fmt_rate
    assert f(0, "bytes") == "0 KB/s" and f(512_000, "bytes") == "512 KB/s" and f(999_400, "bytes") == "999 KB/s"
    assert f(999_600, "bytes") == "1.0 MB/s" and f(4_200_000, "bytes") == "4.2 MB/s" and f(33_600_000, "bytes") == "33.6 MB/s"
    assert f(4_200_000, "bits") == "33.6 Mbps" and f(40_000, "bits") == "320 Kbps" and f(300_000, "bits") == "2.4 Mbps"
    assert traffic.rate_parts(4_200_000, "bytes") == ("4.2", "MB/s")


def test_if_index_reads_row(monkeypatch):
    row = traffic.MIB_IF_ROW2()
    row.InterfaceIndex = 17
    monkeypatch.setattr(traffic, "_row", lambda guid: row)
    assert traffic.if_index("{x}") == 17
