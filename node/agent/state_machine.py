from __future__ import annotations
from enum import Enum

class MemberState(str, Enum):
    BOOT = "BOOT"
    DISCOVERING = "DISCOVERING"
    JOINING = "JOINING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    OFFLINE = "OFFLINE"
