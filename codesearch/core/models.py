from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal, Optional

from lancedb.pydantic import LanceModel, Vector
from pydantic import BaseModel, Field


class IndexConfig(BaseModel):
    repo_root: Path
    store_dir: Path
    repo_id: str

    workers: int = 8
    follow_symlinks: bool = False
    max_file_bytes: int = 2_000_000

    # Fallback chunking
    fallback_max_chars: int = 4000
    fallback_overlap_chars: int = 400

    # Embedding
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_batch_size: int = 64

    # Ignore rules (simple, predictable defaults)
    ignore_dir_names: set[str] = Field(
        default_factory=lambda: {
            ".git",
            ".lancedb",
        }
    )
    ignore_exts: set[str] = Field(
        default_factory=lambda: {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".7z",
            ".dylib",
            ".so",
            ".dll",
            ".exe",
            ".bin",
        }
    )


class FileRecord(LanceModel):
    repo_id: str
    file_path: str  # repo-relative
    abs_path: Path
    language: str
    file_hash: str
    size_bytes: int


class ChunkRecord(LanceModel):
    chunk_id: str
    repo_id: str
    file_path: str
    language: str
    start_line: int
    end_line: int
    symbol_name: Optional[str] = None
    symbol_kind: Optional[str] = None
    parent_symbol: Optional[str] = None
    text: str
    file_hash: str
    chunk_hash: str
    vector: Vector(384) = None


class FileVectorRecord(LanceModel):
    file_id: str
    repo_id: str
    file_path: str
    language: str
    file_hash: str
    summary_text: Optional[str] = None
    vector: Vector(384)


ProgressEventType = Literal["file_done", "chunks_indexed", "error", "files_discovered"]


class ProgressEvent(BaseModel):
    type: ProgressEventType
    count: int = 1


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def stable_chunk_id(*, repo_id: str, file_path: str, start_line: int, end_line: int, file_hash: str) -> str:
    key = f"{repo_id}:{file_path}:{start_line}:{end_line}:{file_hash}"
    return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()


def stable_file_id(*, repo_id: str, file_path: str) -> str:
    return hashlib.sha256(f"{repo_id}:{file_path}".encode("utf-8", errors="replace")).hexdigest()

