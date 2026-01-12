from __future__ import annotations

import asyncio
import json
import ssl
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

Handler = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]


def _peer_meta(writer: asyncio.StreamWriter) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    peer = writer.get_extra_info("peername")
    if peer:
        meta["peer_ip"] = peer[0]
        meta["peer_port"] = peer[1]
        meta["peer_id"] = f"{peer[0]}:{peer[1]}"
    sslobj = writer.get_extra_info("ssl_object")
    if sslobj is not None:
        try:
            meta["peer_cert"] = sslobj.getpeercert()  # dict
        except Exception:
            pass
    return meta


@dataclass
class PeerServer:
    host: str
    port: int
    handler: Handler
    ssl: Optional[ssl.SSLContext] = None

    _server: Optional[asyncio.AbstractServer] = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port, ssl=self.ssl)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        meta = _peer_meta(writer)
        try:
            data = await reader.readline()
            if not data:
                return
            msg = json.loads(data.decode("utf-8"))
            resp = await self.handler(msg, meta)
            writer.write((json.dumps(resp) + "\n").encode("utf-8"))
            await writer.drain()
        except Exception as e:
            try:
                writer.write((json.dumps({"type": "ERROR", "reason": str(e)}) + "\n").encode("utf-8"))
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
