import asyncio, contextlib, socket

import pytest

import merge


def run(coro, t=5):
    """Every test body gets a timeout, so a proxy bug fails the test instead of hanging the suite."""
    return asyncio.run(asyncio.wait_for(coro, t))


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setattr(merge, "open_on", lambda link, addr, timeout=10.0: socket.create_connection(addr, timeout))
    p = merge.Pool()
    p.update({"a": (1, "127.0.0.1")})
    p.mark("a", True)
    p.released = 0
    real = p.release

    def release(link):
        p.released += 1
        real(link)

    monkeypatch.setattr(p, "release", release)
    return p


@contextlib.asynccontextmanager
async def serving(handler):
    s = await asyncio.start_server(handler, "127.0.0.1", 0)
    try:
        yield s.sockets[0].getsockname()[1]
    finally:
        s.close()


@contextlib.asynccontextmanager
async def proxied(pool):
    p = merge.Proxy(pool)
    port = await p.start(0)
    try:
        yield p, port
    finally:
        await p.stop()


async def echo(r, w):
    """Echoes until the client half-closes, then closes."""
    try:
        while d := await r.read(65536):
            w.write(d)
            await w.drain()
        w.close()
    except OSError:
        pass


async def settled(pool):
    while pool.links()[0].active:
        await asyncio.sleep(0.01)


def socks_req(host, port, cmd=1):
    try:
        addr = bytes([1]) + socket.inet_aton(host)
    except OSError:
        addr = bytes([3, len(host)]) + host.encode()
    return bytes([5, cmd, 0]) + addr + port.to_bytes(2, "big")


async def socks(port, req):
    """Greets, sends req, returns (reader, writer, first 10 reply bytes)."""
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(b"\x05\x01\x00")
    assert await r.readexactly(2) == b"\x05\x00"
    w.write(req)
    return r, w, await r.readexactly(10)


async def http(port, head):
    """Sends head, returns (reader, writer, response head up to the blank line)."""
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(head)
    return r, w, await r.readuntil(b"\r\n\r\n")


FAIL = lambda code: b"\x05" + bytes([code]) + b"\x00\x01" + b"\0" * 6


def test_socks5_connect_echo(pool):
    async def body():
        async with serving(echo) as eport, proxied(pool) as (p, port):
            for host in ("127.0.0.1", "localhost"):  # an address, then a name the proxy resolves
                r, w, rep = await socks(port, socks_req(host, eport))
                assert rep == b"\x05\x00\x00\x01" + b"\0" * 6
                w.write(b"hello")
                assert await r.readexactly(5) == b"hello"
                w.close()
    run(body())


def test_http_connect_echo(pool):
    async def body():
        async with serving(echo) as eport, proxied(pool) as (p, port):
            r, w, head = await http(port, f"CONNECT 127.0.0.1:{eport} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            assert head == b"HTTP/1.1 200 Connection established\r\n\r\n"
            w.write(b"hello")
            assert await r.readexactly(5) == b"hello"
            w.close()
    run(body())


def test_http_get_absolute_uri(pool):
    seen = []

    async def server(r, w):
        seen.append(await r.readuntil(b"\r\n\r\n"))
        w.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        w.close()

    async def body():
        async with serving(server) as sport, proxied(pool) as (p, port):
            req = (f"GET http://127.0.0.1:{sport}/x?y=1 HTTP/1.1\r\nHost: 127.0.0.1:{sport}\r\n"
                   "Proxy-Connection: keep-alive\r\nConnection: keep-alive\r\nAccept: */*\r\n\r\n")
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(req.encode())
            assert (await r.read()).endswith(b"\r\n\r\nok")
            w.close()
        head = seen[0].decode()
        assert head.startswith("GET /x?y=1 HTTP/1.1\r\n")
        assert "Connection: close\r\n" in head and "keep-alive" not in head and "Proxy-Connection" not in head
        assert "Accept: */*\r\n" in head
    run(body())


def test_serves_pac(pool):
    async def body():
        async with proxied(pool) as (p, port):
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(b"GET /proxy.pac HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            raw = await r.read()  # the proxy closes after the body
            head, _, text = raw.partition(b"\r\n\r\n")
            assert head.startswith(b"HTTP/1.1 200")
            assert b"Content-Type: application/x-ns-proxy-autoconfig" in head
            assert f"Content-Length: {len(text)}".encode() in head
            want = f'function FindProxyForURL(u, h) {{ return "PROXY 127.0.0.1:{port}; DIRECT"; }}'
            assert text.decode() == want == p.pac()
    run(body())


def test_no_links_fails_fast(monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: calls.append(a) or [])  # no DNS when there are no links

    async def body():
        async with proxied(merge.Pool()) as (p, port):
            for host in ("127.0.0.1", "example.com"):  # an address, then a name that must not be looked up
                r, w, rep = await socks(port, socks_req(host, 9))
                assert rep == FAIL(3)
                w.close()
                r, w, head = await http(port, f"CONNECT {host}:9 HTTP/1.1\r\n\r\n".encode())
                assert head.startswith(b"HTTP/1.1 502")
                w.close()
    run(body(), 1)
    assert calls == []


def test_active_released_once_on_early_close(pool):
    async def body():
        async with serving(echo) as eport, proxied(pool) as (p, port):
            r, w, head = await http(port, f"CONNECT 127.0.0.1:{eport} HTTP/1.1\r\n\r\n".encode())
            assert pool.links()[0].active == 1
            w.close()
            await settled(pool)
            assert pool.released == 1
            # a half-close still lets the server's reply through before the connection is released
            r, w, head = await http(port, f"CONNECT 127.0.0.1:{eport} HTTP/1.1\r\n\r\n".encode())
            w.write(b"bye")
            w.write_eof()
            assert await r.read() == b"bye"
            await settled(pool)
            assert pool.released == 2
            w.close()
    run(body())


def test_counts_bytes_per_link(pool):
    async def body():
        async with serving(echo) as eport, proxied(pool) as (p, port):
            r, w, head = await http(port, f"CONNECT 127.0.0.1:{eport} HTTP/1.1\r\n\r\n".encode())
            w.write(b"x" * 1000)
            assert await r.readexactly(1000) == b"x" * 1000
            assert p.bytes["a"] == [1000, 1000]
            w.close()
    run(body())


def test_port_busy_falls_back():
    async def body():
        held = socket.socket()
        try:
            held.bind(("127.0.0.1", merge.PORT))
            held.listen()
        except OSError:
            pass  # something else already holds it, which is the same situation
        try:
            p = merge.Proxy(merge.Pool())
            port = await p.start()
            assert port != merge.PORT and port == p.port
            await p.stop()
        finally:
            held.close()
    run(body())


def test_socks_refusals(pool):
    async def body():
        async with proxied(pool) as (p, port):
            r, w = await asyncio.open_connection("127.0.0.1", port)  # no acceptable method
            w.write(b"\x05\x01\x02")
            assert await r.read() == b"\x05\xff"
            w.close()
            r, w, rep = await socks(port, socks_req("127.0.0.1", 9, cmd=3))  # UDP ASSOCIATE
            assert rep == FAIL(7)
            w.close()
            r, w = await asyncio.open_connection("127.0.0.1", port)  # IPv6 address
            w.write(b"\x05\x01\x00")
            await r.readexactly(2)
            w.write(b"\x05\x01\x00\x04" + b"\0" * 18)
            assert await r.readexactly(10) == FAIL(8)
            w.close()
    run(body())


def test_dial_failures_never_kill_the_handler(pool, monkeypatch):
    async def boom(pool, host, port):
        raise RuntimeError("boom")
    monkeypatch.setattr(merge, "dial", boom)

    async def body():
        async with proxied(pool) as (p, port):
            r, w, rep = await socks(port, socks_req("127.0.0.1", 9))
            assert rep == FAIL(4)
            w.close()
            r, w, head = await http(port, b"CONNECT 127.0.0.1:9 HTTP/1.1\r\n\r\n")
            assert head.startswith(b"HTTP/1.1 502")
            w.close()
    run(body())


@pytest.mark.parametrize("req, status", [
    pytest.param(b"GET /nope HTTP/1.1\r\n\r\n", b"400", id="relative-path"),
    pytest.param(b"GET https://example.com/ HTTP/1.1\r\n\r\n", b"400", id="https-absolute"),
    pytest.param(b"GET /" + b"a" * 70000, b"431", id="head-too-big"),
])
def test_http_refusals(pool, req, status):
    async def body():
        async with proxied(pool) as (p, port):
            r, w, head = await http(port, req)
            assert head.startswith(b"HTTP/1.1 " + status)
            w.close()
    run(body())


def test_stop_cancels_live_connections(pool):
    async def body():
        async with serving(echo) as eport:
            async with proxied(pool) as (p, port):
                r, w, head = await http(port, f"CONNECT 127.0.0.1:{eport} HTTP/1.1\r\n\r\n".encode())
            assert await r.read() == b""  # stop() closed the tunnel
            assert pool.links()[0].active == 0 and pool.released == 1
    run(body())
