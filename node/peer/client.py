from __future__ import annotations

import asyncio
import json
import ssl
from typing import Any, Dict, Optional


async def send_message(
    host: str,
    port: int,
    msg: Dict[str, Any],
    timeout: float = 3.0,
    ssl_ctx: Optional[ssl.SSLContext] = None,
) -> Dict[str, Any]:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    conn = asyncio.open_connection(host, port, ssl=ssl_ctx)
    reader, writer = await asyncio.wait_for(conn, timeout=timeout)

    try:
        writer.write((json.dumps(msg) + "\n").encode("utf-8"))
        await writer.drain()

        data = await asyncio.wait_for(reader.readline(), timeout=timeout)
        if not data:
            return {"type": "ERROR", "reason": "no_response"}
        return json.loads(data.decode("utf-8"))
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
