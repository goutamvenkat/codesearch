from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
import pathspec

from codesearch.core.models import sha256_bytes, IndexConfig


@dataclass
class MerkleNode:
    name: str # The name of the file or directory. Root name is commonly empty or repo name
    is_dir: bool 
    hash_val: str
    children: dict[str, MerkleNode] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: dict) -> MerkleNode:
        children = {k: cls.from_dict(v) for k, v in data.get("children", {}).items()}
        return cls(
            name=data["name"],
            is_dir=data["is_dir"],
            hash_val=data["hash_val"],
            children=children
        )


def build_merkle_tree(root_path: Path, config: IndexConfig) -> Optional[MerkleNode]:
    """
    Recursively builds a Merkle tree of a directory.
    Returns None if the directory is empty after ignoring skipped files.
    """
    gitignore_path = root_path / ".gitignore"
    spec = None
    if gitignore_path.exists():
        try:
            with gitignore_path.open("r", encoding="utf-8") as f:
                spec = pathspec.PathSpec.from_lines("gitwildmatch", f)
        except Exception:
            pass

    def _build_recursive(current: Path) -> Optional[MerkleNode]:
        # Always respect static ignore rules for safety
        if current.name in config.ignore_dir_names:
            return None
        
        # Respect .gitignore if present
        if spec:
            try:
                rel_path = str(current.relative_to(root_path))
                # For directories, pathspec usually expects a trailing slash or handles it
                # If it's a directory, we check if it matches.
                if current.is_dir():
                    path_to_check = rel_path + "/"
                else:
                    path_to_check = rel_path
                
                if path_to_check != "." and path_to_check != "./":
                    if spec.match_file(path_to_check):
                        return None
            except ValueError:
                pass

        if current.is_file():
            if current.suffix.lower() in config.ignore_exts:
                return None
            try:
                st = current.stat()
                if st.st_size <= 0 or st.st_size > config.max_file_bytes:
                    return None
                data = current.read_bytes()
                return MerkleNode(
                    name=current.name,
                    is_dir=False,
                    hash_val=sha256_bytes(data)
                )
            except OSError:
                return None

        if current.is_dir():
            children = {}
            try:
                for entry in current.iterdir():
                    child_node = _build_recursive(entry)
                    if child_node:
                        children[child_node.name] = child_node
            except OSError:
                return None

            if not children:
                return None

            # Compute hash by hashing the sorted names+hashes of all children
            child_str = "".join(f"{k}:{v.hash_val}" for k, v in sorted(children.items()))
            return MerkleNode(
                name=current.name,
                is_dir=True,
                hash_val=sha256_bytes(child_str.encode("utf-8")),
                children=children
            )

        return None
    
    # We name the root after the repo_id conceptually.
    root_node = _build_recursive(root_path)
    if root_node:
        root_node.name = config.repo_id
    return root_node


@dataclass
class MerkleDiff:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

def diff_trees(old_node: Optional[MerkleNode], new_node: Optional[MerkleNode], rel_path: str = "") -> MerkleDiff:
    """
    Compare two Merkle trees and return paths (relative to root) that were added, modified, or deleted.
    """
    diff = MerkleDiff()

    # Case 1: Node was entirely deleted
    if old_node and not new_node:
        # If it's a file, mark deleted. If it's a directory, recursively mark all children deleted.
        if not old_node.is_dir:
            diff.deleted.append(rel_path)
        else:
            for child_name, child_node in old_node.children.items():
                child_rel = f"{rel_path}/{child_name}" if rel_path else child_name
                child_diff = diff_trees(child_node, None, child_rel)
                diff.added.extend(child_diff.added)
                diff.modified.extend(child_diff.modified)
                diff.deleted.extend(child_diff.deleted)
        return diff

    # Case 2: Node was newly added
    if new_node and not old_node:
        if not new_node.is_dir:
            diff.added.append(rel_path)
        else:
            for child_name, child_node in new_node.children.items():
                child_rel = f"{rel_path}/{child_name}" if rel_path else child_name
                child_diff = diff_trees(None, child_node, child_rel)
                diff.added.extend(child_diff.added)
                diff.modified.extend(child_diff.modified)
                diff.deleted.extend(child_diff.deleted)
        return diff
    
    # Case 3: Neither are None. Check if they match.
    if old_node and new_node:
        if old_node.hash_val == new_node.hash_val:
            return diff # identical
            
        if not old_node.is_dir and not new_node.is_dir:
            diff.modified.append(rel_path)
            return diff
            
        # Case 4: Directory contents changed
        old_children = old_node.children
        new_children = new_node.children
        all_keys = set(old_children.keys()).union(set(new_children.keys()))
        
        for k in all_keys:
            c_old = old_children.get(k)
            c_new = new_children.get(k)
            child_rel = f"{rel_path}/{k}" if rel_path else k
            
            child_diff = diff_trees(c_old, c_new, child_rel)
            diff.added.extend(child_diff.added)
            diff.modified.extend(child_diff.modified)
            diff.deleted.extend(child_diff.deleted)
            
    return diff


def save_tree(node: Optional[MerkleNode], path: Path) -> None:
    if node:
        path.write_text(json.dumps(asdict(node)))
    else:
        if path.exists():
            path.unlink()

def load_tree(path: Path) -> Optional[MerkleNode]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return MerkleNode.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return None
