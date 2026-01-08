from __future__ import annotations
import asyncio
from typing import Awaitable, Callable, Optional
from .framing import read_frame, write_frame

Handler = Callable[[dict, str], Awaitable[dict]]

class PeerServer:
    def __init__(self, host: str, port: int, handler: Handler, ssl=None):
        self.host = host
        self.port = port
        self.handler = handler
        self.ssl = ssl
        self._server: Optional[asyncio.base_events.Server] = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port, ssl=self.ssl)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        peer_id = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        try:
            while True:
                msg = await read_frame(reader)
                resp = await self.handler(msg, peer_id)
                await write_frame(writer, resp)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
