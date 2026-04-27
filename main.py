from __future__ import annotations

import argparse
from pathlib import Path

from codesearch.index.job import IndexJob
from codesearch.core.models import IndexConfig


def main() -> None:
    p = argparse.ArgumentParser(description="Index a repo into a vector store with AST chunking + embeddings.")
    p.add_argument("repo_root", type=str, help="Path to repository root")
    p.add_argument(
        "--db-dir",
        type=str,
        default="~/.lancedb",
        help="Base directory where vector stores live (default: ~/.lancedb). A repo_id subdirectory is created here.",
    )
    p.add_argument("--repo-id", type=str, default=None, help="Stable repo id (default: folder name)")
    p.add_argument("--workers", type=int, default=8, help="ThreadPool worker count")
    p.add_argument(
        "--model",
        type=str,
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Sentence-Transformers model name or path",
    )
    p.add_argument("--max-file-bytes", type=int, default=2_000_000, help="Skip files larger than this")
    args = p.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    repo_id = args.repo_id or repo_root.name
    db_base_dir = Path(args.db_dir).expanduser().resolve()
    db_dir = db_base_dir / repo_id

    cfg = IndexConfig(
        repo_root=repo_root,
        store_dir=db_dir,
        repo_id=repo_id,
        workers=int(args.workers),
        embedding_model_name=str(args.model),
        max_file_bytes=int(args.max_file_bytes),
    )

    IndexJob(cfg).run()


if __name__ == "__main__":
    main()
