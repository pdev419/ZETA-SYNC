from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class ProcStatus:
    running: bool
    pid: Optional[int]
    last_exit_code: Optional[int]

class ZetaSyncProcess:
    def __init__(self, cmd: List[str], workdir: str):
        self.cmd = cmd
        self.workdir = workdir
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.last_exit_code: Optional[int] = None

    async def start(self) -> None:
        if self.proc and self.proc.returncode is None:
            return
        self.proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            cwd=self.workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

    async def stop(self) -> None:
        if not self.proc or self.proc.returncode is not None:
            return
        self.proc.terminate()
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            self.proc.kill()
            await self.proc.wait()
        self.last_exit_code = self.proc.returncode

    def status(self) -> ProcStatus:
        running = self.proc is not None and self.proc.returncode is None
        pid = self.proc.pid if running else None
        return ProcStatus(running=running, pid=pid, last_exit_code=self.last_exit_code)

    async def stdout_lines(self):
        if not self.proc or not self.proc.stdout:
            return
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            yield line.decode("utf-8", errors="replace").rstrip("\n")
