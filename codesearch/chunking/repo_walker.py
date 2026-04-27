from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from codesearch.core.models import IndexConfig


class RepoWalker:
    def __init__(self, config: IndexConfig):
        self.config = config

    def iter_folders(self) -> list[Path]:
        root = self.config.repo_root
        folders: list[Path] = []
        for dirpath, dirnames, _filenames in os.walk(root, followlinks=self.config.follow_symlinks):
            dirpath_p = Path(dirpath)
            dirnames[:] = [d for d in dirnames if d not in self.config.ignore_dir_names]
            folders.append(dirpath_p)
        return folders

    def iter_files_in_folder(self, folder: Path) -> Iterable[Path]:
        for entry in folder.iterdir():
            try:
                if entry.is_dir():
                    continue
                if not entry.is_file():
                    continue
            except OSError:
                continue

            if entry.suffix.lower() in self.config.ignore_exts:
                continue
            yield entry

