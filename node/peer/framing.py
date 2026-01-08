from __future__ import annotations
import asyncio, json, struct
from typing import Dict, Any

MAX_FRAME = 2 * 1024 * 1024

async def read_frame(reader: asyncio.StreamReader) -> Dict[str, Any]:
    hdr = await reader.readexactly(4)
    (length,) = struct.unpack(">I", hdr)
    if length <= 0 or length > MAX_FRAME:
        raise ValueError(f"Invalid frame length {length}")
    payload = await reader.readexactly(length)
    msg = json.loads(payload.decode("utf-8"))
    if not isinstance(msg, dict):
        raise ValueError("Message must be a JSON object")
    return msg

async def write_frame(writer: asyncio.StreamWriter, msg: Dict[str, Any]) -> None:
    data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_FRAME:
        raise ValueError("Frame too large")
    writer.write(struct.pack(">I", len(data)))
    writer.write(data)
    await writer.drain()
