import http.server, json, threading
import pytest
import speed

PING_EN = """
Pinging 192.168.0.1 from 192.168.0.111 with 32 bytes of data:
Reply from 192.168.0.1: bytes=32 time=1ms TTL=64
Reply from 192.168.0.1: bytes=32 time=16ms TTL=64

Ping statistics for 192.168.0.1:
    Packets: Sent = 10, Received = 10, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 1ms, Maximum = 16ms, Average = 2ms
"""


class Handler(http.server.BaseHTTPRequestHandler):
    received = 0

    def do_GET(self):
        n = 3_000_000
        self.send_response(200)
        self.send_header("Content-Length", str(n))
        self.end_headers()
        left = n
        while left:
            k = min(65536, left)
            self.wfile.write(b"\0" * k)
            left -= k

    def do_POST(self):
        left = int(self.headers["Content-Length"])
        while left:
            chunk = self.rfile.read(min(65536, left))
            if not chunk:
                break
            left -= len(chunk)
            Handler.received += len(chunk)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def local_server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"host": "127.0.0.1", "port": httpd.server_port, "tls": False, "down": "/down", "up": "/up"}
    httpd.shutdown()


def fast_clock():
    t = [0.0]
    def clock():
        t[0] += 0.05  # each read/send "takes" 50 ms, so samples come quickly
        return t[0]
    return clock


def test_parse_ping():
    assert speed.parse_ping(PING_EN) == 2
    with pytest.raises(speed.SpeedError, match="router didn't answer"):
        speed.parse_ping("Request timed out.\nRequest timed out.\n")


def test_download_samples_bound_to_adapter_ip(local_server):
    seen = []
    s = speed.download_samples("127.0.0.1", host=local_server["host"], port=local_server["port"], tls=False,
                               path=local_server["down"], rounds=1, on_sample=seen.append, clock=fast_clock())
    assert 1 <= len(s) <= 28 and all(v > 0 for v in s)
    assert seen == s


def test_download_stops_at_max_samples(local_server):
    s = speed.download_samples("127.0.0.1", host=local_server["host"], port=local_server["port"], tls=False,
                               path=local_server["down"], rounds=3, max_samples=5, clock=fast_clock())
    assert len(s) == 5


def test_upload_samples(local_server):
    Handler.received = 0
    s = speed.upload_samples("127.0.0.1", host=local_server["host"], port=local_server["port"], tls=False,
                             path=local_server["up"], size=2_000_000, clock=fast_clock())
    assert s and all(v > 0 for v in s)
    assert Handler.received == 2_000_000


def test_average_skips_ramp_up():
    assert speed.average([1, 2, 3, 50, 52, 48]) == 50
    assert speed.average([]) == 0
    assert speed.average([10, 20]) == 15  # too short to skip


def test_results_round_trip_and_corrupt_file(tmp_path):
    f = tmp_path / "results.json"
    assert speed.load_results(f) == {}
    speed.save_result(f, "unigen", {"down": 50})
    speed.save_result(f, "builtin", {"down": 53})
    assert speed.load_results(f) == {"unigen": {"down": 50}, "builtin": {"down": 53}}
    f.write_text("{not json", encoding="utf-8")
    assert speed.load_results(f) == {}


def test_addresses_passes_alias_as_param(monkeypatch):
    seen = {}
    def fake_ps(script, params, **kw):
        seen.update(script=script, params=params)
        return '{"ip":"192.168.0.111","gateway":"192.168.0.1"}'
    monkeypatch.setattr(speed, "_ps", fake_ps)
    assert speed.addresses("Wi-Fi 2") == {"ip": "192.168.0.111", "gateway": "192.168.0.1"}
    assert seen["params"] == {"alias": "Wi-Fi 2"} and "Wi-Fi 2" not in seen["script"]


def test_addresses_without_ip(monkeypatch):
    monkeypatch.setattr(speed, "_ps", lambda s, p, **k: '{"ip":null,"gateway":null}')
    with pytest.raises(speed.SpeedError, match="isn't connected"):
        speed.addresses("Wi-Fi 2")
