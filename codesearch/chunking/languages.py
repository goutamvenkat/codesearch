from __future__ import annotations

from pathlib import Path
from typing import Optional

from tree_sitter import Language


class LanguageRegistry:
    def __init__(self) -> None:
        self._ext_to_lang: dict[str, str] = {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".kt": "kotlin",
            ".c": "c",
            ".h": "c",
            ".cc": "cpp",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".cs": "c_sharp",
            ".rb": "ruby",
            ".php": "php",
        }
        self._language_cache: dict[str, Language] = {}

    def detect_language(self, path: Path) -> str:
        return self._ext_to_lang.get(path.suffix.lower(), "text")

    def get_tree_sitter_language(self, language_id: str) -> Optional[Language]:
        if language_id in self._language_cache:
            return self._language_cache[language_id]

        lang: Optional[Language] = None

        try:
            from tree_sitter_languages import get_language  # type: ignore

            lang = get_language(language_id)
        except Exception:
            lang = None

        if lang is None and language_id == "python":
            try:
                import tree_sitter_python as tspython  # type: ignore

                lang = Language(tspython.language())
            except Exception:
                lang = None

        if lang is not None:
            self._language_cache[language_id] = lang
        return lang

