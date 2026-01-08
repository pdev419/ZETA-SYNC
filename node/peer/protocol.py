from __future__ import annotations
from typing import TypedDict, Literal, Any, Dict, List, Optional

MsgType = Literal[
    "HELLO",
    "PEER_LIST_REQ",
    "PEER_LIST",
    "GOSSIP",
    "JOIN_REQUEST",
    "JOIN_RESPONSE",
    "METRICS_PUSH",
    "PING",
    "PONG",
]

class PeerMessage(TypedDict, total=False):
    type: MsgType
    node_id: str
    seq: int
    peers: List[str]
    params: Dict[str, Any]
    metrics: Dict[str, Any]
    reason: str
    ok: bool
