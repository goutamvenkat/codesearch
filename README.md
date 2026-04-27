# CodeSearch

CodeSearch is a cross-repository semantic code search TUI tool. It leverages the power of LanceDB to provide hybrid search capabilities directly from your terminal.

## Key Features

- **Textual TUI**: A rich, responsive terminal user interface to browse and search your repositories.
- **Hybrid Search**: Combines full-text BM25 matching with semantic search (via SentenceTransformers and LanceDB) so you can find code by intent, not just exact keywords.
- **Incremental Indexing**: Uses a Merkle tree-based system to hash directory structures, guaranteeing that only modified files are intelligently re-indexed. This saves vast amounts of time and computational resources.
- **Smart Gitignore Integration**: Dynamically parses and respects project `.gitignore` files to keep dependencies, build artifacts, and environment files out of your index.
- **Centralized Knowledge Base**: Consolidates indexed snippet embeddings into a central `~/.lancedb` store, making cross-repository code discovery effortless.

## Architecture

```mermaid
graph TD
    User([User]) -->|Queries| TUI[Textual TUI]

    subgraph Storage_and_Retrieval[Storage and Retrieval]
        LanceDB[("LanceDB ~/.lancedb")]
        Embedder["SentenceTransformers all-MiniLM-L6-v2"]
    end

    TUI -->|Search Query| Embedder
    Embedder -->|Query Vector| LanceDB
    LanceDB -->|"Hybrid Search (Vector + BM25 Text)"| TUI

    subgraph Indexing_Engine[Indexing Engine]
        CodeRepos[Local Repositories]
        Gitignore[.gitignore Parser]
        Merkle["Merkle Tree Diffing - Added/Modified/Deleted"]
        Workers["WorkStealingPool - Concurrent Processing"]
        AST["Chunkers - Tree-Sitter AST and Fallback"]
        Writer["LanceWriter - Async Queue Processing"]

        CodeRepos -->|Read Dir| Merkle
        CodeRepos -.->|Filter| Gitignore
        Gitignore -.->|Ignore rules| Merkle
        Merkle -->|Changed Files| Workers
        Workers -->|Source Code| AST
        AST -->|Code Chunks| Embedder
        Embedder -->|"Chunk Vectors and File Mean Vectors"| Writer
        Writer -->|Upsert Records| LanceDB
        Writer -->|Build FTS Index| LanceDB
    end
```

## Getting Started

To launch the interactive terminal UI, simply run:

```bash
uv run codesearch-ui
```

To run the standard CLI (if applicable):

```bash
uv run codesearch --help
```
