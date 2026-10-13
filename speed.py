"""Speed test bound to one adapter: ping the router, then sampled download and upload."""
import http.client, json, os, re, ssl, tempfile, time
from pathlib import Path

import winrun

_run, _ps = winrun.run, winrun.ps  # tests replace these
CLOUDFLARE = {"host": "speed.cloudflare.com", "port": 443, "tls": True, "down": "/__down?bytes=25000000", "up": "/__up"}
_ADDR_SCRIPT = """
$c = Get-NetIPConfiguration -InterfaceAlias $p.alias
@{ ip = ($c.IPv4Address | Select-Object -First 1).IPAddress; gateway = ($c.IPv4DefaultGateway | Select-Object -First 1).NextHop } | ConvertTo-Json -Compress
"""


class SpeedError(Exception):
    pass


def addresses(alias):
    a = json.loads(_ps(_ADDR_SCRIPT, {"alias": alias}))
    if not a.get("ip") or not a.get("gateway"):
        raise SpeedError("That adapter isn't connected to a network.")
    return a


def parse_ping(text):
    m = re.search(r"Average = (\d+)ms", text)
    if not m:
        raise SpeedError("The router didn't answer pings.")
    return int(m.group(1))


def ping(ip, gateway, count=10):
    try:
        out = _run(["ping", "-n", str(count), "-S", ip, gateway], timeout=count * 2 + 5)
    except winrun.CmdError:
        raise SpeedError("The router didn't answer pings.") from None
    return parse_ping(out)


def _conn(ip, host, port, tls):
    if tls:
        return http.client.HTTPSConnection(host, port, timeout=15, source_address=(ip, 0), context=ssl.create_default_context())
    return http.client.HTTPConnection(host, port, timeout=15, source_address=(ip, 0))


class _Sampler:
    """Turns byte counts into one Mbps sample per interval."""
    def __init__(self, interval, max_samples, on_sample, clock):
        self.interval, self.max, self.on, self.clock = interval, max_samples, on_sample, clock
        self.samples, self.bytes, self.t0 = [], 0, clock()

    def add(self, n):
        self.bytes += n
        now = self.clock()
        if now - self.t0 >= self.interval:
            self.samples.append(round(self.bytes * 8 / (now - self.t0) / 1e6, 1))
            self.bytes, self.t0 = 0, now
            if self.on:
                self.on(self.samples[-1])
        return len(self.samples) >= self.max


def download_samples(ip, *, host, port, tls, path, rounds=3, interval=0.2, max_samples=28, on_sample=None, clock=time.monotonic):
    s = _Sampler(interval, max_samples, on_sample, clock)
    for _ in range(rounds):
        c = _conn(ip, host, port, tls)
        try:
            c.request("GET", path)
            r = c.getresponse()
            if r.status != 200:
                raise SpeedError(f"The speed server answered {r.status}.")
            while chunk := r.read(65536):
                if s.add(len(chunk)):
                    return s.samples
        except (OSError, http.client.HTTPException) as e:
            raise SpeedError(f"The download stopped: {getattr(e, 'strerror', None) or e}.") from None
        finally:
            c.close()
    return s.samples


def upload_samples(ip, *, host, port, tls, path, size=25_000_000, interval=0.2, max_samples=12, on_sample=None, clock=time.monotonic):
    s, block, sent = _Sampler(interval, max_samples, on_sample, clock), b"\0" * 65536, 0
    c = _conn(ip, host, port, tls)
    try:
        c.putrequest("POST", path)
        c.putheader("Content-Type", "application/octet-stream")
        c.putheader("Content-Length", str(size))
        c.endheaders()
        while sent < size:
            n = min(len(block), size - sent)
            c.send(block[:n])
            sent += n
            if s.add(n):
                break
        if sent == size:
            c.getresponse().read()
    except (OSError, http.client.HTTPException) as e:
        raise SpeedError(f"The upload stopped: {getattr(e, 'strerror', None) or e}.") from None
    finally:
        c.close()
    return s.samples


def average(samples, skip=3):
    xs = samples[skip:] if len(samples) > skip else samples
    return round(sum(xs) / len(xs)) if xs else 0


def run_test(ip, gateway, *, on_sample=None, server=CLOUDFLARE):
    on = on_sample or (lambda phase, v: None)
    ping_ms = ping(ip, gateway)
    common = {"host": server["host"], "port": server["port"], "tls": server["tls"]}
    down = download_samples(ip, path=server["down"], on_sample=lambda v: on("down", v), **common)
    up = upload_samples(ip, path=server["up"], on_sample=lambda v: on("up", v), **common)
    return {"ping": ping_ms, "down": average(down), "up": average(up), "samples": down + up,
            "split": len(down), "at": time.strftime("%Y-%m-%d %H:%M")}


def load_results(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_result(path, key, result):
    path = Path(path)
    data = load_results(path)
    data[key] = result
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")  # write-then-replace: never a half file
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)
