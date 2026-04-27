from __future__ import annotations

import queue
import threading
from pathlib import Path

from rich.console import Console

from codesearch.chunking.chunkers import AstChunker, FallbackChunker
from codesearch.chunking.languages import LanguageRegistry
from codesearch.core.models import (
    ChunkRecord,
    FileRecord,
    FileVectorRecord,
    IndexConfig,
    ProgressEvent,
    sha256_bytes,
    stable_file_id,
)
from codesearch.embedding.embedder import SentenceTransformersEmbedder
from codesearch.storage.writer import VectorStoreWriter, default_writer_factory
from codesearch.ui.progress import ProgressCoordinator
from codesearch.concurrency.workstealing import WorkResult, WorkStealingPool
from codesearch.index.merkle import build_merkle_tree, load_tree, save_tree, diff_trees


class IndexJob:
    def __init__(self, config: IndexConfig, *, writer_factory=default_writer_factory):
        self.config = config
        self.registry = LanguageRegistry()
        self.ast_chunker = AstChunker(config, self.registry)
        self.fallback_chunker = FallbackChunker(config)
        self.embedder = SentenceTransformersEmbedder(config.embedding_model_name)
        self._writer_factory = writer_factory

        self._write_q: "queue.Queue[list[ChunkRecord] | None]" = queue.Queue(maxsize=64)
        self._filevec_q: "queue.Queue[list[FileVectorRecord] | None]" = queue.Queue(maxsize=64)
        self._progress_q: "queue.Queue[ProgressEvent]" = queue.Queue(maxsize=10_000)

    def run(self) -> None:
        console = Console()
        console.print("[cyan]Building Merkle Tree...[/cyan]")
        new_tree = build_merkle_tree(self.config.repo_root, self.config)
        merkle_path = self.config.store_dir / "merkle.json"
        
        old_tree = load_tree(merkle_path)
        diff = diff_trees(old_tree, new_tree)
        
        console.print(f"Merkle diff: {len(diff.added)} added, {len(diff.modified)} modified, {len(diff.deleted)} deleted")
        
        if not diff.added and not diff.modified and not diff.deleted:
            console.print("[green]No changes detected. Indexing skipped![/green]")
            return

        # Handle deletes first
        stale_paths = diff.deleted + diff.modified
        if stale_paths:
            console.print(f"[yellow]Removing obsolete vectors...[/yellow]")
            import lancedb
            try:
                db = lancedb.connect(str(self.config.store_dir))
                
                # Batch delete based on 50 items per query
                batch_size = 50
                for i in range(0, len(stale_paths), batch_size):
                    batch = stale_paths[i:i+batch_size]
                    pstr = ", ".join(f"'{p.replace(chr(39), chr(39)+chr(39))}'" for p in batch)
                    try:
                        db.open_table("chunks").delete(f"file_path IN ({pstr})")
                    except Exception:
                        pass
                    try:
                        db.open_table("files").delete(f"file_path IN ({pstr})")
                    except Exception:
                        pass
            except Exception as e:
                console.print(f"[red]Error deleting stale vectors: {e}[/red]")

        progress = ProgressCoordinator(console)
        files_to_process = [self.config.repo_root / p for p in diff.added + diff.modified]
        progress.start(total_files_estimate=len(files_to_process))

        writer: VectorStoreWriter = self._writer_factory(
            config=self.config, chunks_q=self._write_q, files_q=self._filevec_q
        )
        writer.start()

        stop_progress = threading.Event()

        def progress_loop() -> None:
            while not stop_progress.is_set() or not self._progress_q.empty():
                try:
                    ev = self._progress_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                progress.apply_event(ev)

        progress_thread = threading.Thread(target=progress_loop, daemon=True)
        progress_thread.start()

        def on_event(ev: ProgressEvent) -> None:
            self._progress_q.put(ev)

        def on_error(_e: BaseException) -> None:
            self._progress_q.put(ProgressEvent(type="error", count=1))

        pool: WorkStealingPool[Path, ProgressEvent] = WorkStealingPool(
            workers=self.config.workers,
            process_fn=self._process_file_task,
            on_event=on_event,
            on_error=on_error,
            queue_maxsize=0,
        )
        
        if files_to_process:
            pool.run(files_to_process)

        writer.stop()
        writer.join(timeout=10.0)

        stop_progress.set()
        progress_thread.join(timeout=2.0)
        progress.stop()
        
        save_tree(new_tree, merkle_path)
        console.print("[green]Saved new Merkle tree state.[/green]")

    def _process_file_task(self, item: Path) -> WorkResult[Path, ProgressEvent]:
        events: list[ProgressEvent] = [ProgressEvent(type="files_discovered", count=1)]
        try:
            self._process_file(item)
        except Exception:
            events.append(ProgressEvent(type="error", count=1))
            
        return WorkResult(new_items=[], events=events)

    def _process_file(self, abs_path: Path) -> None:
        try:
            st = abs_path.stat()
        except OSError:
            self._progress_q.put(ProgressEvent(type="error", count=1))
            return

        if st.st_size <= 0 or st.st_size > self.config.max_file_bytes:
            return

        try:
            data = abs_path.read_bytes()
        except OSError:
            self._progress_q.put(ProgressEvent(type="error", count=1))
            return

        repo_rel = str(abs_path.relative_to(self.config.repo_root))
        language_id = self.registry.detect_language(abs_path)
        file_hash = sha256_bytes(data)

        file_rec = FileRecord(
            repo_id=self.config.repo_id,
            file_path=repo_rel,
            abs_path=abs_path,
            language=language_id,
            file_hash=file_hash,
            size_bytes=len(data),
        )

        chunks = self.ast_chunker.chunk(file_rec, data)
        if not chunks:
            chunks = self.fallback_chunker.chunk(file_rec, data)

        texts = [c.text for c in chunks]
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.config.embedding_batch_size):
            vectors.extend(self.embedder.embed_texts(texts[i : i + self.config.embedding_batch_size]))

        for c, v in zip(chunks, vectors, strict=False):
            c.vector = v

        file_vecs: list[FileVectorRecord] = []
        if vectors:
            dim = len(vectors[0])
            mean = [0.0] * dim
            for v in vectors:
                for j, x in enumerate(v):
                    mean[j] += float(x)
            inv = 1.0 / float(len(vectors))
            mean = [x * inv for x in mean]
            file_vecs.append(
                FileVectorRecord(
                    file_id=stable_file_id(repo_id=self.config.repo_id, file_path=repo_rel),
                    repo_id=self.config.repo_id,
                    file_path=repo_rel,
                    language=language_id,
                    file_hash=file_hash,
                    summary_text=None,
                    vector=mean,
                )
            )

        self._write_q.put(chunks)
        if file_vecs:
            self._filevec_q.put(file_vecs)

        self._progress_q.put(ProgressEvent(type="file_done", count=1))
        self._progress_q.put(ProgressEvent(type="chunks_indexed", count=len(chunks)))

