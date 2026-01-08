from __future__ import annotations
import asyncio
from typing import Dict, Any
from .framing import read_frame, write_frame

async def send_message(host: str, port: int, msg: Dict[str, Any], ssl=None, timeout: float = 3.0) -> Dict[str, Any]:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host=host, port=port, ssl=ssl), timeout=timeout)
    try:
        await write_frame(writer, msg)
        resp = await asyncio.wait_for(read_frame(reader), timeout=timeout)
        return resp
    finally:
        writer.close()
        await writer.wait_closed()
