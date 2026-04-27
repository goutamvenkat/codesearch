from __future__ import annotations

import queue
import threading
import time
from typing import Any

import lancedb
from lancedb.db import DBConnection, Table

from codesearch.core.models import ChunkRecord, FileVectorRecord, IndexConfig
import logging

logger = logging.getLogger(__name__)

class LanceWriter(threading.Thread):
    def __init__(
        self,
        *,
        config: IndexConfig,
        write_q: "queue.Queue[list[ChunkRecord] | None]",
        filevec_q: "queue.Queue[list[FileVectorRecord] | None]",
    ):
        logger.info(f"Initializing LanceWriter with config: {config}")
        super().__init__(daemon=True)
        self.config = config
        self.write_q = write_q
        self.filevec_q = filevec_q
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        logger.info("Stopping LanceWriter")
        self._stop_evt.set()

    def run(self) -> None:
        logger.info(f"Starting LanceWriter with config: {self.config}")
        db_dir = self.config.store_dir
        db_dir.mkdir(parents=True, exist_ok=True)

        db: DBConnection = lancedb.connect(str(db_dir))
        try:
            chunks_tbl = db.open_table("chunks")
        except Exception:
            chunks_tbl = db.create_table("chunks", schema=ChunkRecord)
            
        try:
            files_tbl = db.open_table("files")
        except Exception:
            files_tbl = db.create_table("files", schema=FileVectorRecord)

        while True:
            if self._stop_evt.is_set() and self.write_q.empty() and self.filevec_q.empty():
                break

            did_work = False

            try:
                batch = self.write_q.get(timeout=0.1)
            except queue.Empty:
                batch = None

            if batch is not None:
                did_work = True
                chunks_tbl = self._upsert_chunks(chunks_tbl, batch)

            try:
                file_batch = self.filevec_q.get_nowait()
            except queue.Empty:
                file_batch = None

            if file_batch is not None:
                did_work = True
                files_tbl = self._upsert_files(files_tbl, file_batch)

            if not did_work:
                time.sleep(0.01)

        logger.info("Writer queue finished. Creating FTS index on 'text' column for chunks table...")
        chunks_tbl.create_fts_index("text", replace=True)
        logger.info("FTS indexing complete.")


    @staticmethod
    def _ensure_table(db: DBConnection, name: str, rows: list[dict[str, Any]]) -> Table:
        try:
            return db.open_table(name)
        except Exception:
            return db.create_table(name, data=rows)

    def _upsert(self, tbl: Table, batch: list[Any], key_field: str) -> Table:
        deduped = {}
        for c in batch:
            deduped[getattr(c, key_field)] = c
        rows = [c.model_dump() for c in deduped.values()]
        mi = tbl.merge_insert(key_field)
        mi.when_matched_update_all().when_not_matched_insert_all().execute(rows)
        return tbl

    def _upsert_chunks(self, tbl: Table, batch: list[ChunkRecord]) -> Table:
        logger.debug(f"Upserting {len(batch)} chunks into LanceDB, table: {tbl}, batch: {batch}")
        return self._upsert(tbl, batch, "chunk_id")

    def _upsert_files(self, tbl: Table, batch: list[FileVectorRecord]) -> Table:
        logger.debug(f"Upserting {len(batch)} files into LanceDB, table: {tbl}, batch: {batch}")
        return self._upsert(tbl, batch, "file_id")

