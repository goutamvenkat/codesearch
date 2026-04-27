from __future__ import annotations

import threading
from typing import Optional

from tree_sitter import Parser

from ..core.models import ChunkRecord, FileRecord, IndexConfig, sha256_text, stable_chunk_id
from .languages import LanguageRegistry


class Chunker:
    def chunk(self, file: FileRecord, source_bytes: bytes) -> list[ChunkRecord]:
        raise NotImplementedError


class FallbackChunker(Chunker):
    def __init__(self, config: IndexConfig):
        self.config = config

    def chunk(self, file: FileRecord, source_bytes: bytes) -> list[ChunkRecord]:
        text = source_bytes.decode("utf-8", errors="replace")
        max_chars = self.config.fallback_max_chars
        overlap = min(self.config.fallback_overlap_chars, max_chars // 2)

        chunks: list[ChunkRecord] = []
        i = 0
        while i < len(text):
            j = min(len(text), i + max_chars)
            chunk_text = text[i:j]
            start_line = text.count("\n", 0, i) + 1
            end_line = text.count("\n", 0, j) + 1
            chunk_hash = sha256_text(chunk_text)
            chunk_id = stable_chunk_id(
                repo_id=file.repo_id,
                file_path=file.file_path,
                start_line=start_line,
                end_line=end_line,
                file_hash=file.file_hash,
            )
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    repo_id=file.repo_id,
                    file_path=file.file_path,
                    language=file.language,
                    start_line=start_line,
                    end_line=end_line,
                    symbol_kind="fallback",
                    text=chunk_text,
                    file_hash=file.file_hash,
                    chunk_hash=chunk_hash,
                )
            )
            if j == len(text):
                break
            i = max(0, j - overlap)
        return chunks


class AstChunker(Chunker):
    def __init__(self, config: IndexConfig, registry: LanguageRegistry):
        self.config = config
        self.registry = registry
        self._parser_cache: dict[str, Parser] = {}
        self._parser_lock = threading.Lock()

        self._symbol_types: dict[str, set[str]] = {
            "python": {"function_definition", "class_definition"},
            "javascript": {"function_declaration", "class_declaration", "method_definition"},
            "typescript": {"function_declaration", "class_declaration", "method_definition"},
            "tsx": {"function_declaration", "class_declaration", "method_definition"},
            "go": {"function_declaration", "method_declaration", "type_declaration"},
            "rust": {"function_item", "impl_item", "struct_item", "enum_item", "trait_item"},
            "java": {"class_declaration", "interface_declaration", "method_declaration", "constructor_declaration"},
            "kotlin": {"class_declaration", "object_declaration", "function_declaration"},
            "c": {"function_definition"},
            "cpp": {"function_definition"},
            "ruby": {"method", "class"},
            "php": {"function_definition", "class_declaration", "method_declaration"},
        }

    def _get_parser(self, language_id: str) -> Optional[Parser]:
        with self._parser_lock:
            if language_id in self._parser_cache:
                return self._parser_cache[language_id]

            ts_lang = self.registry.get_tree_sitter_language(language_id)
            if ts_lang is None:
                return None

            parser = Parser()
            parser.language = ts_lang
            self._parser_cache[language_id] = parser
            return parser

    def chunk(self, file: FileRecord, source_bytes: bytes) -> list[ChunkRecord]:
        parser = self._get_parser(file.language)
        if parser is None:
            return []

        try:
            tree = parser.parse(source_bytes)
        except Exception:
            return []

        root = tree.root_node
        wanted = self._symbol_types.get(file.language, set())

        chunks: list[ChunkRecord] = []

        def walk(node) -> None:
            if node.is_named and node.type in wanted:
                start_line = int(node.start_point[0]) + 1
                end_line = int(node.end_point[0]) + 1
                text = source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
                chunk_hash = sha256_text(text)
                chunk_id = stable_chunk_id(
                    repo_id=file.repo_id,
                    file_path=file.file_path,
                    start_line=start_line,
                    end_line=end_line,
                    file_hash=file.file_hash,
                )
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    symbol_name = source_bytes[name_node.start_byte : name_node.end_byte].decode(
                        "utf-8", errors="replace"
                    )

                chunks.append(
                    ChunkRecord(
                        chunk_id=chunk_id,
                        repo_id=file.repo_id,
                        file_path=file.file_path,
                        language=file.language,
                        start_line=start_line,
                        end_line=end_line,
                        symbol_name=symbol_name,
                        symbol_kind=node.type,
                        text=text,
                        file_hash=file.file_hash,
                        chunk_hash=chunk_hash,
                    )
                )
                return

            for child in node.children:
                walk(child)

        walk(root)
        return chunks

