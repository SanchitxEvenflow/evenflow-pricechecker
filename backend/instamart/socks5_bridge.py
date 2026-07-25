"""
instamart/socks5_bridge.py
In-process HTTP CONNECT -> authenticated SOCKS5 bridge.

Chromium/Playwright can use authenticated HTTP proxies but NOT authenticated
SOCKS5 proxies — passing username/password alongside a socks5:// server to
browser.new_context() fails with "Browser does not support socks5 proxy
authentication". This module runs a local, no-auth HTTP CONNECT proxy that
tunnels every connection through an upstream authenticated SOCKS5 gateway,
so Playwright only ever sees a plain http://127.0.0.1:<port> proxy and never
needs to know about the real credentials.

Runs as an asyncio.start_server task inside the caller's existing event
loop — no subprocess, no separate proxy binary.

Snowpad-specific quirk: gw.snowpad.io:9999 silently closes the connection if
the SOCKS5 greeting offers only method 0x02 (username/password) — it must be
offered alongside 0x00 (no-auth), even though the server always ends up
selecting 0x02. Confirmed via raw-socket testing against the gateway.
"""

import asyncio
import logging
import struct

logger = logging.getLogger(__name__)


async def _socks5_connect(
    upstream_host: str, upstream_port: int, user: str, password: str,
    target_host: str, target_port: int,
):
    reader, writer = await asyncio.open_connection(upstream_host, upstream_port)

    # Greeting must offer 2 methods (no-auth + user/pass) — Snowpad's gateway
    # closes the connection on a single-method (auth-only) greeting.
    writer.write(b"\x05\x02\x00\x02")
    await writer.drain()
    resp = await reader.readexactly(2)
    if resp[0] != 0x05:
        raise RuntimeError(f"bad SOCKS5 version in greeting response: {resp!r}")
    method = resp[1]

    if method == 0x02:
        u, p = user.encode(), password.encode()
        writer.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        await writer.drain()
        auth_resp = await reader.readexactly(2)
        if auth_resp != b"\x01\x00":
            raise RuntimeError(f"SOCKS5 auth failed: {auth_resp!r}")
    elif method == 0xFF:
        raise RuntimeError("SOCKS5 server rejected all auth methods")

    th = target_host.encode()
    writer.write(b"\x05\x01\x00\x03" + bytes([len(th)]) + th + struct.pack(">H", target_port))
    await writer.drain()

    header = await reader.readexactly(4)
    if header[1] != 0x00:
        raise RuntimeError(f"SOCKS5 CONNECT failed, rep={header[1]}")
    atyp = header[3]
    if atyp == 0x01:
        await reader.readexactly(6)
    elif atyp == 0x03:
        n = (await reader.readexactly(1))[0]
        await reader.readexactly(n + 2)
    elif atyp == 0x04:
        await reader.readexactly(18)
    else:
        raise RuntimeError(f"unknown SOCKS5 address type: {atyp}")

    return reader, writer


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(65536)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            dst.write_eof()
        except Exception:
            pass


class Socks5HttpBridge:
    """Local plain-HTTP CONNECT proxy tunneling through an authenticated upstream SOCKS5 server."""

    def __init__(self, upstream_host: str, upstream_port: int, user: str, password: str):
        self._upstream_host = upstream_host
        self._upstream_port = upstream_port
        self._user = user
        self._password = password
        self._server: asyncio.AbstractServer | None = None
        self.port: int | None = None

    async def _handle(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await client_reader.readline()
            if not request_line:
                return
            method, target, _ = request_line.decode(errors="replace").split(" ", 2)
            while True:
                line = await client_reader.readline()
                if line in (b"\r\n", b""):
                    break

            if method != "CONNECT":
                client_writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                await client_writer.drain()
                return

            target_host, _, target_port = target.partition(":")
            target_port_i = int(target_port or 443)

            try:
                remote_reader, remote_writer = await _socks5_connect(
                    self._upstream_host, self._upstream_port, self._user, self._password,
                    target_host, target_port_i,
                )
            except Exception as e:
                logger.warning("[Socks5HttpBridge] upstream SOCKS5 connect to %s:%d failed: %s",
                                target_host, target_port_i, e)
                client_writer.write(f"HTTP/1.1 502 Bad Gateway\r\n\r\n{e}".encode())
                await client_writer.drain()
                return

            client_writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await client_writer.drain()

            await asyncio.gather(
                _pipe(client_reader, remote_writer),
                _pipe(remote_reader, client_writer),
            )
        except Exception:
            logger.debug("[Socks5HttpBridge] client handler error", exc_info=True)
        finally:
            try:
                client_writer.close()
            except Exception:
                pass

    async def start(self) -> int:
        """Start listening on an ephemeral localhost port. Idempotent — returns the existing port if already running."""
        if self._server is not None:
            return self.port
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        logger.info("[Socks5HttpBridge] listening on 127.0.0.1:%d -> socks5://%s:%d",
                    self.port, self._upstream_host, self._upstream_port)
        return self.port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self.port = None
