from __future__ import annotations

from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeElapsedColumn

from codesearch.core.models import ProgressEvent
import logging

logger = logging.getLogger(__name__)

class ProgressCoordinator:
    def __init__(self, console: Console):
        self.console = console
        self.progress = Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )
        self.files_task: TaskID | None = None
        self.chunks_task: TaskID | None = None
        self.errors_task: TaskID | None = None

    def start(self, total_files_estimate: int) -> None:
        logger.info(f"Starting progress coordinator with total files estimate: {total_files_estimate}")
        self.progress.start()
        self.files_task = self.progress.add_task("Files indexed", total=total_files_estimate)
        self.chunks_task = self.progress.add_task("Chunks indexed", total=0)
        self.errors_task = self.progress.add_task("Errors", total=0)

    def stop(self) -> None:
        logger.info("Stopping progress coordinator")
        self.progress.stop()

    def apply_event(self, ev: ProgressEvent) -> None:
        if ev.type == "files_discovered" and self.files_task is not None:
            self.progress.update(self.files_task, total=self.progress.tasks[self.files_task].total + ev.count)
        elif ev.type == "file_done" and self.files_task is not None:
            self.progress.advance(self.files_task, ev.count)
        elif ev.type == "chunks_indexed" and self.chunks_task is not None:
            self.progress.advance(self.chunks_task, ev.count)
        elif ev.type == "error" and self.errors_task is not None:
            self.progress.advance(self.errors_task, ev.count)

