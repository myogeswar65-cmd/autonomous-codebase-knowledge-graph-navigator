import uuid
import bisect
from typing import List, Optional, Set, Dict, Any
from tree_sitter import Language, Parser, Node
import tree_sitter_python as py_lang

from .base import BaseLanguageParser, ParseResult, format_line_range
from ..models import EntityNode, RelationshipEdge, UnresolvedCallNode
from ..id_generator import (
    generate_entity_ids,
    compute_signature_hash,
    compute_content_hash,
)

PY_LANGUAGE = Language(py_lang.language())


class PythonParser(BaseLanguageParser):
    def __init__(self):
        self.language = PY_LANGUAGE

    def parse_file(
        self,
        rel_file_path: str,
        code_bytes: bytes,
        repo_id: str,
        commit_sha: str,
    ) -> ParseResult:
        result = ParseResult()
        try:
            parser = Parser(self.language)
            tree = parser.parse(code_bytes)
        except Exception as e:
            result.syntax_errors.append(f"Failed to parse {rel_file_path}: {e}")
            return result

        root = tree.root_node
        if root.has_error:
            result.syntax_errors.append(f"Syntax error detected in {rel_file_path}, parsing available AST")

        code_len = len(code_bytes)

        # Precompute line start offsets for safe, zero-crash byte-to-line translation
        line_starts = [0]
        for idx, b in enumerate(code_bytes):
            if b == 10:  # ord('\n')
                line_starts.append(idx + 1)

        def byte_to_line(byte_offset: int) -> int:
            return bisect.bisect_right(line_starts, byte_offset)

        def node_line_range(node: Node) -> (int, int, str):
            s_byte = max(0, min(node.start_byte, code_len))
            e_byte = max(0, min(node.end_byte, code_len))
            s_line = byte_to_line(s_byte)
            e_line = byte_to_line(max(s_byte, e_byte - 1)) if e_byte > s_byte else s_line
            lr = f"{s_line}-{e_line}" if s_line != e_line else str(s_line)
            return s_line, e_line, lr

        def safe_text(node: Optional[Node]) -> str:
            if not node:
                return ""
            s, e = node.start_byte, node.end_byte
            if s < 0 or e < s or s > code_len:
                return ""
            e = min(e, code_len)
            return code_bytes[s:e].decode("utf-8", errors="replace").strip()

        def get_decorators(node: Node) -> List[str]:
            decs = []
            p = node.parent
            if p and p.type == "decorated_definition":
                for c in p.children:
                    if c.type == "decorator":
                        decs.append(safe_text(c))
            return decs

        # Phase 1: Pure primitive extraction (tuples/dicts)
        # Keeps AST traversal completely decoupled from Pydantic GC allocations
        raw_classes: List[Dict[str, Any]] = []
        raw_functions: List[Dict[str, Any]] = []
        raw_imports: List[tuple] = []
        raw_variables: List[Dict[str, Any]] = []
        raw_calls: List[tuple] = []

        def extract_calls(scope_node: Node, source_scope_key: str):
            stack = [scope_node]
            while stack:
                curr = stack.pop()
                for child in curr.children:
                    if child.type == "call":
                        fn_node = child.child_by_field_name("function")
                        if fn_node:
                            inv_name = safe_text(fn_node).split(".")[-1]
                            _, _, lr = node_line_range(child)
                            raw_calls.append((source_scope_key, inv_name, lr))
                    elif child.type not in ("function_definition", "class_definition"):
                        stack.append(child)

        def extract_func(fn_node: Node, parent_scope: str, parent_key: str):
            name_node = fn_node.child_by_field_name("name")
            fn_name = safe_text(name_node) if name_node else "anonymous"
            qual_name = f"{parent_scope}.{fn_name}" if parent_scope else fn_name
            fn_key = f"fn::{qual_name}"

            params = []
            param_list = fn_node.child_by_field_name("parameters")
            if param_list:
                for p in param_list.named_children:
                    params.append(safe_text(p))

            ret_type = ""
            ret_node = fn_node.child_by_field_name("return_type")
            if ret_node:
                ret_type = safe_text(ret_node)

            body_text = safe_text(fn_node)
            decorators = get_decorators(fn_node)
            s_row, e_row, _ = node_line_range(fn_node)

            raw_functions.append({
                "key": fn_key,
                "name": fn_name,
                "qual_name": qual_name,
                "params": params,
                "ret_type": ret_type,
                "body_text": body_text,
                "decorators": decorators,
                "s_row": s_row,
                "e_row": e_row,
                "parent_key": parent_key,
            })
            extract_calls(fn_node, fn_key)

            # Traverse nested functions or classes within function body
            body = fn_node.child_by_field_name("body")
            if body:
                for child in body.children:
                    if child.type == "function_definition":
                        extract_func(child, qual_name, fn_key)
                    elif child.type == "decorated_definition":
                        for sub in child.children:
                            if sub.type == "function_definition":
                                extract_func(sub, qual_name, fn_key)
                            elif sub.type == "class_definition":
                                extract_class(sub, qual_name, fn_key)
                    elif child.type == "class_definition":
                        extract_class(child, qual_name, fn_key)

        def extract_class(class_node: Node, parent_scope: str, parent_key: str):
            name_node = class_node.child_by_field_name("name")
            class_name = safe_text(name_node) if name_node else "anonymous"
            qual_name = f"{parent_scope}.{class_name}" if parent_scope else class_name
            class_key = f"class::{qual_name}"

            superclasses = []
            super_node = class_node.child_by_field_name("superclasses")
            if super_node:
                for arg in super_node.named_children:
                    superclasses.append(safe_text(arg))

            body_text = safe_text(class_node)
            s_row, e_row, _ = node_line_range(class_node)

            raw_classes.append({
                "key": class_key,
                "name": class_name,
                "qual_name": qual_name,
                "superclasses": superclasses,
                "body_text": body_text,
                "s_row": s_row,
                "e_row": e_row,
                "parent_key": parent_key,
            })

            # Class body: methods and inner classes
            body = class_node.child_by_field_name("body")
            if body:
                for child in body.children:
                    if child.type == "function_definition":
                        extract_func(child, qual_name, class_key)
                    elif child.type == "decorated_definition":
                        for sub in child.children:
                            if sub.type == "function_definition":
                                extract_func(sub, qual_name, class_key)
                            elif sub.type == "class_definition":
                                extract_class(sub, qual_name, class_key)
                    elif child.type == "class_definition":
                        extract_class(child, qual_name, class_key)

        norm_path = rel_file_path.replace("\\", "/")
        mod_name = norm_path.replace("/", ".").removesuffix(".py").removesuffix(".__init__")

        # Top-level traversal
        for child in root.children:
            try:
                if child.type == "function_definition":
                    extract_func(child, mod_name, "file")
                elif child.type == "decorated_definition":
                    for sub in child.children:
                        if sub.type == "function_definition":
                            extract_func(sub, mod_name, "file")
                        elif sub.type == "class_definition":
                            extract_class(sub, mod_name, "file")
                elif child.type == "class_definition":
                    extract_class(child, mod_name, "file")
                elif child.type in ("import_statement", "import_from_statement"):
                    imp_text = safe_text(child)
                    target = ""
                    if child.type == "import_statement":
                        for n in child.named_children:
                            target = safe_text(n)
                    else:
                        mn = child.child_by_field_name("module_name")
                        if mn:
                            target = safe_text(mn)
                    if target:
                        raw_imports.append((target, imp_text))
                elif child.type == "expression_statement":
                    for sub in child.children:
                        if sub.type == "assignment":
                            left = sub.child_by_field_name("left")
                            if left and left.type == "identifier":
                                v_name = safe_text(left)
                                qual_var = f"{mod_name}.{v_name}"
                                s_r, e_r, _ = node_line_range(child)
                                raw_variables.append({
                                    "name": v_name,
                                    "qual_name": qual_var,
                                    "body_text": safe_text(sub),
                                    "s_row": s_r,
                                    "e_row": e_r,
                                })
            except Exception as node_err:
                result.syntax_errors.append(f"Error processing AST node {child.type}: {node_err}")

        # Explicitly release native Tree-sitter tree and parser resources
        del tree
        del parser

        # Phase 2: Construct models and generate deterministic IDs
        code_text = code_bytes.decode("utf-8", errors="replace")
        lines = code_text.splitlines()
        total_lines = len(lines) if lines else 1

        file_ent_id, file_logical_id = generate_entity_ids(repo_id, commit_sha, "File", rel_file_path)
        file_node = EntityNode(
            entity_id=file_ent_id,
            logical_entity_id=file_logical_id,
            repo_id=repo_id,
            commit_sha=commit_sha,
            file_path=rel_file_path,
            name=rel_file_path.split("/")[-1],
            entity_type="File",
            content_hash=compute_content_hash(code_text),
            line_start=1,
            line_end=total_lines,
        )
        result.entities.append(file_node)

        mod_ent_id, mod_logical_id = generate_entity_ids(repo_id, commit_sha, "Module", mod_name)
        mod_node = EntityNode(
            entity_id=mod_ent_id,
            logical_entity_id=mod_logical_id,
            repo_id=repo_id,
            commit_sha=commit_sha,
            file_path=rel_file_path,
            name=mod_name,
            entity_type="Module",
            content_hash=compute_content_hash(code_text),
            line_start=1,
            line_end=total_lines,
        )
        result.entities.append(mod_node)
        result.relationships.append(
            RelationshipEdge(
                source_entity_id=file_ent_id,
                target_entity_id=mod_ent_id,
                rel_type="CONTAINS",
                repo_id=repo_id,
                commit_sha=commit_sha,
            )
        )

        key_to_id: Dict[str, str] = {"file": file_ent_id}

        for c_data in raw_classes:
            c_ent_id, c_logical_id = generate_entity_ids(repo_id, commit_sha, "Class", c_data["qual_name"])
            key_to_id[c_data["key"]] = c_ent_id
            parent_id = key_to_id.get(c_data["parent_key"], file_ent_id)
            c_node = EntityNode(
                entity_id=c_ent_id,
                logical_entity_id=c_logical_id,
                repo_id=repo_id,
                commit_sha=commit_sha,
                file_path=rel_file_path,
                name=c_data["name"],
                entity_type="Class",
                content_hash=compute_content_hash(c_data["body_text"]),
                line_start=c_data["s_row"],
                line_end=c_data["e_row"],
                properties={"superclasses": c_data["superclasses"]},
            )
            result.entities.append(c_node)
            result.relationships.append(
                RelationshipEdge(
                    source_entity_id=parent_id,
                    target_entity_id=c_ent_id,
                    rel_type="CONTAINS",
                    repo_id=repo_id,
                    commit_sha=commit_sha,
                )
            )

        for fn_data in raw_functions:
            sig_hash = compute_signature_hash(fn_data["params"], fn_data["ret_type"])
            fn_ent_id, fn_logical_id = generate_entity_ids(
                repo_id, commit_sha, "Function", fn_data["qual_name"], signature_hash=sig_hash
            )
            key_to_id[fn_data["key"]] = fn_ent_id
            parent_id = key_to_id.get(fn_data["parent_key"], file_ent_id)
            is_api = any(
                any(verb in d for verb in ["get(", "post(", "put(", "delete(", "patch(", "route("])
                for d in fn_data["decorators"]
            )
            fn_node = EntityNode(
                entity_id=fn_ent_id,
                logical_entity_id=fn_logical_id,
                repo_id=repo_id,
                commit_sha=commit_sha,
                file_path=rel_file_path,
                name=fn_data["name"],
                entity_type="API" if is_api else "Function",
                content_hash=compute_content_hash(fn_data["body_text"]),
                line_start=fn_data["s_row"],
                line_end=fn_data["e_row"],
                signature_hash=sig_hash,
                properties={
                    "parameters": fn_data["params"],
                    "return_type": fn_data["ret_type"],
                    "decorators": fn_data["decorators"],
                },
            )
            result.entities.append(fn_node)
            result.relationships.append(
                RelationshipEdge(
                    source_entity_id=parent_id,
                    target_entity_id=fn_ent_id,
                    rel_type="DEFINES" if parent_id != file_ent_id else "CONTAINS",
                    repo_id=repo_id,
                    commit_sha=commit_sha,
                )
            )

        for target, imp_stmt in raw_imports:
            t_id, _ = generate_entity_ids(repo_id, commit_sha, "Module", target)
            result.relationships.append(
                RelationshipEdge(
                    source_entity_id=file_ent_id,
                    target_entity_id=t_id,
                    rel_type="IMPORTS",
                    repo_id=repo_id,
                    commit_sha=commit_sha,
                    properties={"statement": imp_stmt},
                )
            )

        for v_data in raw_variables:
            v_ent_id, v_logical_id = generate_entity_ids(repo_id, commit_sha, "Variable", v_data["qual_name"])
            v_node = EntityNode(
                entity_id=v_ent_id,
                logical_entity_id=v_logical_id,
                repo_id=repo_id,
                commit_sha=commit_sha,
                file_path=rel_file_path,
                name=v_data["name"],
                entity_type="Variable",
                content_hash=compute_content_hash(v_data["body_text"]),
                line_start=v_data["s_row"],
                line_end=v_data["e_row"],
            )
            result.entities.append(v_node)
            result.relationships.append(
                RelationshipEdge(
                    source_entity_id=file_ent_id,
                    target_entity_id=v_ent_id,
                    rel_type="CONTAINS",
                    repo_id=repo_id,
                    commit_sha=commit_sha,
                )
            )

        for scope_key, inv_name, lr in raw_calls:
            source_id = key_to_id.get(scope_key, file_ent_id)
            call_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{repo_id}::{commit_sha}::{source_id}::{inv_name}::{rel_file_path}::{lr}"))
            uc = UnresolvedCallNode(
                call_id=f"{repo_id}::{commit_sha}::UnresolvedCall::{call_uuid}",
                repo_id=repo_id,
                commit_sha=commit_sha,
                source_entity_id=source_id,
                invoked_symbol_name=inv_name,
                file_path=rel_file_path,
                line_range=lr,
            )
            result.unresolved_calls.append(uc)

        return result
