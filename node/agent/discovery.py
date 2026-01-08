from __future__ import annotations
import random
from typing import Set, List

def parse_hostport(s: str) -> tuple[str, int]:
    host, port = s.rsplit(":", 1)
    return host.strip(), int(port.strip())

class Discovery:
    def __init__(self, seeds: List[str]):
        self.known_peers: Set[str] = set(seeds)

    def merge(self, peers: List[str]) -> None:
        for p in peers:
            if isinstance(p, str) and ":" in p:
                self.known_peers.add(p)

    def pick_targets(self, k: int = 2) -> List[str]:
        peers = list(self.known_peers)
        random.shuffle(peers)
        return peers[:k]
