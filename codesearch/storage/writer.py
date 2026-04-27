from __future__ import annotations

import queue
from typing import Protocol

from codesearch.core.models import ChunkRecord, FileVectorRecord, IndexConfig


class VectorStoreWriter(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...


def default_writer_factory(
    *,
    config: IndexConfig,
    chunks_q: "queue.Queue[list[ChunkRecord] | None]",
    files_q: "queue.Queue[list[FileVectorRecord] | None]",
) -> VectorStoreWriter:
    from .lancedb_writer import LanceWriter

    return LanceWriter(config=config, write_q=chunks_q, filevec_q=files_q)

