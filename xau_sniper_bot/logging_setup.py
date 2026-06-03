from __future__ import annotations

import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, TextIO

from .config import BotConfig


class TeeStream:
    def __init__(self, *streams: TextIO) -> None:
        self.streams = streams

    def write(self, data: str) -> int:
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


@contextmanager
def tee_console_to_log(config: BotConfig) -> Iterator[None]:
    if not config.log_to_file:
        yield
        return

    path = Path(config.log_file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log_file:
        stdout = TeeStream(sys.stdout, log_file)
        stderr = TeeStream(sys.stderr, log_file)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            print(f"\n--- bot session started {datetime.now(timezone.utc).isoformat()} ---")
            yield
            print(f"--- bot session ended {datetime.now(timezone.utc).isoformat()} ---")

