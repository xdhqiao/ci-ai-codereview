from __future__ import annotations

import importlib
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from app.core.config import Settings
from app.services.exclusions import ReviewPathExcluder


@dataclass(frozen=True)
class SymbolLocation:
    name: str
    qualified_name: str
    kind: str
    file_path: str
    line: int
    column: int
    end_line: int
    signature: str = ""
    is_definition: bool = True
    backend: str = "tree-sitter"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SymbolReference:
    name: str
    file_path: str
    line: int
    column: int
    context: str
    reference_kind: str = "read"
    enclosing_symbol: str = ""
    backend: str = "tree-sitter"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CallEdge:
    caller: str
    callee: str
    file_path: str
    line: int
    column: int
    context: str
    backend: str = "tree-sitter"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SemanticIndex:
    """Task-scoped symbol/ref/relation index with Tree-sitter and lexical fallback."""

    _GRAMMARS: dict[str, tuple[str, str]] = {
        ".c": ("tree_sitter_c", "language"),
        ".h": ("tree_sitter_c", "language"),
        ".cc": ("tree_sitter_cpp", "language"),
        ".cpp": ("tree_sitter_cpp", "language"),
        ".hpp": ("tree_sitter_cpp", "language"),
        ".py": ("tree_sitter_python", "language"),
        ".js": ("tree_sitter_javascript", "language"),
        ".jsx": ("tree_sitter_javascript", "language"),
        ".ts": ("tree_sitter_typescript", "language_typescript"),
        ".tsx": ("tree_sitter_typescript", "language_tsx"),
        ".java": ("tree_sitter_java", "language"),
        ".go": ("tree_sitter_go", "language"),
    }
    _DEFINITION_KINDS = {
        "function_definition": "function",
        "function_declaration": "function",
        "method_definition": "method",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
        "function_item": "function",
        "method_declaration": "method",
        "class_definition": "class",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "struct_item": "struct",
        "struct_specifier": "struct",
        "enum_specifier": "enum",
        "enum_declaration": "enum",
        "type_declaration": "type",
    }
    _SCOPE_KINDS = {"function", "method", "constructor", "class", "interface", "struct"}
    _CALL_KINDS = {"call", "call_expression", "method_invocation", "function_call_expression"}
    _IDENTIFIER_KINDS = {
        "identifier",
        "field_identifier",
        "property_identifier",
        "type_identifier",
        "namespace_identifier",
    }
    _CONTROL_WORDS = {
        "if",
        "for",
        "while",
        "switch",
        "return",
        "sizeof",
        "catch",
        "new",
        "delete",
    }

    def __init__(
        self,
        root_dir: Path,
        settings: Settings,
        project_exclude_paths: list[str] | None = None,
    ) -> None:
        self.root_dir = root_dir.resolve()
        self.settings = settings
        self.path_excluder = ReviewPathExcluder(settings, project_exclude_paths)
        self.definitions: dict[str, list[SymbolLocation]] = {}
        self.references: dict[str, list[SymbolReference]] = {}
        self.call_edges: list[CallEdge] = []
        self._build_lock = threading.Lock()
        self._built = False
        self._stats: dict[str, Any] = {
            "files_indexed": 0,
            "tree_sitter_files": 0,
            "fallback_files": 0,
            "parse_errors": 0,
            "truncated": False,
        }

    def find_definition(
        self,
        symbol: str,
        current_file: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_built()
        normalized = self._normalize_symbol(symbol)
        candidates = list(self.definitions.get(normalized, []))
        candidates.sort(
            key=lambda item: (
                item.file_path != self._normalize_path(current_file),
                not item.is_definition,
                item.file_path,
                item.line,
            )
        )
        bounded = self._bounded_limit(limit)
        return {
            "symbol": symbol,
            "definitions": [item.as_dict() for item in candidates[:bounded]],
            "truncated": len(candidates) > bounded,
            "index": self.stats(),
        }

    def find_references(
        self,
        symbol: str,
        file_path: str = "",
        include_declarations: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._ensure_built()
        normalized = self._normalize_symbol(symbol)
        normalized_path = self._normalize_path(file_path)
        candidates = [
            item
            for item in self.references.get(normalized, [])
            if not normalized_path or item.file_path == normalized_path
        ]
        payload: list[dict[str, Any]] = []
        if include_declarations:
            payload.extend(
                {**item.as_dict(), "reference_kind": "definition"}
                for item in self.definitions.get(normalized, [])
                if not normalized_path or item.file_path == normalized_path
            )
        payload.extend(item.as_dict() for item in candidates)
        payload.sort(key=lambda item: (item["file_path"], item["line"], item["column"]))
        bounded = self._bounded_limit(limit)
        return {
            "symbol": symbol,
            "references": payload[:bounded],
            "truncated": len(payload) > bounded,
            "index": self.stats(),
        }

    def call_graph(
        self,
        symbol: str,
        direction: str = "both",
        depth: int = 1,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._ensure_built()
        direction = direction if direction in {"incoming", "outgoing", "both"} else "both"
        max_depth = min(3, max(1, int(depth)))
        start = self._normalize_symbol(symbol)
        frontier = {start}
        visited = {start}
        selected: list[CallEdge] = []
        for _ in range(max_depth):
            next_frontier: set[str] = set()
            for edge in self.call_edges:
                caller = self._normalize_symbol(edge.caller)
                callee = self._normalize_symbol(edge.callee)
                matched = False
                if direction in {"outgoing", "both"} and caller in frontier:
                    next_frontier.add(callee)
                    matched = True
                if direction in {"incoming", "both"} and callee in frontier:
                    next_frontier.add(caller)
                    matched = True
                if matched and edge not in selected:
                    selected.append(edge)
            frontier = next_frontier - visited
            visited.update(next_frontier)
            if not frontier:
                break
        selected.sort(key=lambda item: (item.file_path, item.line, item.column, item.caller, item.callee))
        bounded = self._bounded_limit(limit)
        return {
            "symbol": symbol,
            "direction": direction,
            "depth": max_depth,
            "edges": [item.as_dict() for item in selected[:bounded]],
            "truncated": len(selected) > bounded,
            "index": self.stats(),
        }

    def stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "definition_count": sum(len(items) for items in self.definitions.values()),
            "reference_count": sum(len(items) for items in self.references.values()),
            "call_edge_count": len(self.call_edges),
        }

    def _ensure_built(self) -> None:
        if self._built:
            return
        with self._build_lock:
            if self._built:
                return
            self._build()
            self._built = True

    def _build(self) -> None:
        started_at = time.monotonic()
        max_files = max(1, self.settings.review_semantic_index_max_files)
        timeout = max(1, self.settings.review_semantic_index_build_timeout_seconds)
        for path in self._iter_source_files():
            if self._stats["files_indexed"] >= max_files or time.monotonic() - started_at >= timeout:
                self._stats["truncated"] = True
                break
            try:
                source = path.read_bytes()
                parser = self._parser_for(path.suffix.lower())
                if parser is None:
                    self._index_with_lexical_fallback(path, source)
                    self._stats["fallback_files"] += 1
                else:
                    tree = parser.parse(source)
                    self._index_tree(path, source, tree.root_node)
                    self._stats["tree_sitter_files"] += 1
                self._stats["files_indexed"] += 1
            except Exception:
                self._stats["parse_errors"] += 1
                try:
                    self._index_with_lexical_fallback(path, path.read_bytes())
                    self._stats["fallback_files"] += 1
                    self._stats["files_indexed"] += 1
                except Exception:
                    continue

    def _parser_for(self, suffix: str):
        grammar = self._GRAMMARS.get(suffix)
        if grammar is None:
            return None
        try:
            from tree_sitter import Language, Parser

            module = importlib.import_module(grammar[0])
            language_factory = getattr(module, grammar[1])
            return Parser(Language(language_factory()))
        except (ImportError, AttributeError, TypeError, ValueError):
            return None

    def _index_tree(self, path: Path, source: bytes, root: Any) -> None:
        rel_path = path.relative_to(self.root_dir).as_posix()
        source_lines = source.decode("utf-8", errors="replace").splitlines()
        definition_name_ranges: set[tuple[int, int]] = set()

        def visit(node: Any, scopes: tuple[SymbolLocation, ...]) -> None:
            node_kind = node.type
            definition_kind = self._definition_kind(node)
            active_scopes = scopes
            if definition_kind:
                name_node = self._definition_name_node(node)
                if name_node is not None:
                    name = self._node_text(source, name_node)
                    if name and name not in self._CONTROL_WORDS:
                        parent_names = [scope.name for scope in scopes if scope.kind in self._SCOPE_KINDS]
                        qualified_name = ".".join([*parent_names, name])
                        location = SymbolLocation(
                            name=name,
                            qualified_name=qualified_name,
                            kind=definition_kind,
                            file_path=rel_path,
                            line=node.start_point.row + 1,
                            column=name_node.start_point.column + 1,
                            end_line=node.end_point.row + 1,
                            signature=self._signature(source, node),
                            is_definition=self._node_is_definition(node),
                        )
                        self._add_definition(location)
                        definition_name_ranges.add((name_node.start_byte, name_node.end_byte))
                        if definition_kind in self._SCOPE_KINDS:
                            active_scopes = (*scopes, location)

            if node_kind in self._CALL_KINDS:
                self._add_call_edge(node, source, rel_path, source_lines, active_scopes)

            if node_kind in self._IDENTIFIER_KINDS:
                node_range = (node.start_byte, node.end_byte)
                if node_range not in definition_name_ranges:
                    name = self._node_text(source, node)
                    if name and name not in self._CONTROL_WORDS:
                        enclosing = active_scopes[-1].qualified_name if active_scopes else ""
                        self._add_reference(
                            SymbolReference(
                                name=name,
                                file_path=rel_path,
                                line=node.start_point.row + 1,
                                column=node.start_point.column + 1,
                                context=self._line_context(source_lines, node.start_point.row),
                                reference_kind="call" if self._has_call_ancestor(node) else "read",
                                enclosing_symbol=enclosing,
                            )
                        )

            for child in node.named_children:
                visit(child, active_scopes)

        visit(root, ())

    def _definition_kind(self, node: Any) -> str:
        if node.type == "declaration" and self._find_descendant(node, {"function_declarator"}) is not None:
            return "function"
        return self._DEFINITION_KINDS.get(node.type, "")

    def _definition_name_node(self, node: Any):
        direct = node.child_by_field_name("name")
        if direct is not None:
            return direct
        declarator = node.child_by_field_name("declarator")
        if declarator is not None:
            candidate = self._declarator_identifier(declarator)
            if candidate is not None:
                return candidate
        return self._find_descendant(node, self._IDENTIFIER_KINDS)

    def _declarator_identifier(self, node: Any):
        direct = node.child_by_field_name("declarator")
        if direct is not None:
            return self._declarator_identifier(direct)
        if node.type in self._IDENTIFIER_KINDS:
            return node
        for child in node.named_children:
            if child.type in {"parameter_list", "parameters", "block", "compound_statement"}:
                continue
            candidate = self._declarator_identifier(child)
            if candidate is not None:
                return candidate
        return None

    def _add_call_edge(
        self,
        node: Any,
        source: bytes,
        rel_path: str,
        source_lines: list[str],
        scopes: tuple[SymbolLocation, ...],
    ) -> None:
        callee_node = node.child_by_field_name("function") or node.child_by_field_name("name")
        if callee_node is None:
            callee_node = self._find_descendant(node, self._IDENTIFIER_KINDS)
        if callee_node is None:
            return
        raw_callee = self._node_text(source, callee_node)
        identifiers = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", raw_callee)
        if not identifiers:
            return
        callee = identifiers[-1]
        if callee in self._CONTROL_WORDS:
            return
        caller_scope = next(
            (scope for scope in reversed(scopes) if scope.kind in {"function", "method", "constructor"}),
            None,
        )
        caller = caller_scope.qualified_name if caller_scope else "<module>"
        self.call_edges.append(
            CallEdge(
                caller=caller,
                callee=callee,
                file_path=rel_path,
                line=node.start_point.row + 1,
                column=node.start_point.column + 1,
                context=self._line_context(source_lines, node.start_point.row),
            )
        )

    def _index_with_lexical_fallback(self, path: Path, source: bytes) -> None:
        rel_path = path.relative_to(self.root_dir).as_posix()
        lines = source.decode("utf-8", errors="replace").splitlines()
        current_scope = ""
        definition_pattern = re.compile(
            r"^\s*(?:[A-Za-z_$][\w$<>:\[\]*&\s]+\s+)?([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*(?:\{|:)$"
        )
        call_pattern = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
        for line_number, line in enumerate(lines, start=1):
            definition_match = definition_pattern.search(line)
            defined_name = ""
            if definition_match and definition_match.group(1) not in self._CONTROL_WORDS:
                defined_name = definition_match.group(1)
                current_scope = defined_name
                self._add_definition(
                    SymbolLocation(
                        name=defined_name,
                        qualified_name=defined_name,
                        kind="function",
                        file_path=rel_path,
                        line=line_number,
                        column=definition_match.start(1) + 1,
                        end_line=line_number,
                        signature=line.strip()[:300],
                        backend="lexical-fallback",
                    )
                )
            for match in call_pattern.finditer(line):
                name = match.group(1)
                if name in self._CONTROL_WORDS or name == defined_name:
                    continue
                reference = SymbolReference(
                    name=name,
                    file_path=rel_path,
                    line=line_number,
                    column=match.start(1) + 1,
                    context=line.strip()[:500],
                    reference_kind="call",
                    enclosing_symbol=current_scope,
                    backend="lexical-fallback",
                )
                self._add_reference(reference)
                self.call_edges.append(
                    CallEdge(
                        caller=current_scope or "<module>",
                        callee=name,
                        file_path=rel_path,
                        line=line_number,
                        column=match.start(1) + 1,
                        context=line.strip()[:500],
                        backend="lexical-fallback",
                    )
                )

    def _add_definition(self, location: SymbolLocation) -> None:
        self.definitions.setdefault(self._normalize_symbol(location.name), []).append(location)

    def _add_reference(self, reference: SymbolReference) -> None:
        self.references.setdefault(self._normalize_symbol(reference.name), []).append(reference)

    def _iter_source_files(self) -> Iterable[Path]:
        max_bytes = max(1, self.settings.review_semantic_index_max_file_bytes)
        for path in sorted(self.root_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in self.settings.allowed_extension_set:
                continue
            rel_path = path.relative_to(self.root_dir)
            if self.path_excluder.is_excluded(rel_path):
                continue
            try:
                if path.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            yield path

    def _find_descendant(self, node: Any, kinds: set[str]):
        stack = list(reversed(node.named_children))
        while stack:
            candidate = stack.pop()
            if candidate.type in kinds:
                return candidate
            stack.extend(reversed(candidate.named_children))
        return None

    def _has_call_ancestor(self, node: Any) -> bool:
        parent = node.parent
        for _ in range(4):
            if parent is None:
                return False
            if parent.type in self._CALL_KINDS:
                return True
            parent = parent.parent
        return False

    def _node_is_definition(self, node: Any) -> bool:
        if node.type == "declaration":
            return False
        return node.child_by_field_name("body") is not None or node.type not in {
            "function_declaration",
            "method_declaration",
        }

    def _node_text(self, source: bytes, node: Any) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace").strip()

    def _signature(self, source: bytes, node: Any) -> str:
        body = node.child_by_field_name("body")
        end_byte = body.start_byte if body is not None else min(node.end_byte, node.start_byte + 500)
        value = source[node.start_byte:end_byte].decode("utf-8", errors="replace")
        return " ".join(value.split())[:300]

    def _line_context(self, lines: list[str], zero_based_line: int) -> str:
        if 0 <= zero_based_line < len(lines):
            return lines[zero_based_line].strip()[:500]
        return ""

    def _normalize_symbol(self, symbol: str) -> str:
        value = str(symbol or "").strip()
        if len(value) > 256 or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.:<>~-]*", value):
            raise ValueError("symbol must be a valid identifier or qualified name")
        return value.rsplit(".", 1)[-1].rsplit("::", 1)[-1].lower()

    def _normalize_path(self, file_path: str) -> str:
        return str(file_path or "").replace("\\", "/").strip().lstrip("./")

    def _bounded_limit(self, limit: int) -> int:
        try:
            requested = int(limit)
        except (TypeError, ValueError):
            requested = self.settings.review_semantic_index_max_results
        return min(
            max(1, requested),
            max(1, self.settings.review_semantic_index_max_results),
        )
