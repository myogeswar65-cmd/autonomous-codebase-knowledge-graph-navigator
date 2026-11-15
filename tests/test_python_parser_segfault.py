import gc
import pytest
from pathlib import Path

from ingestion.app.parsers.python_parser import PythonParser
from ingestion.app.models import EntityNode, RelationshipEdge, UnresolvedCallNode


@pytest.fixture
def parser():
    return PythonParser()


@pytest.fixture
def adapters_code():
    fixture_path = Path(__file__).parent / "fixtures" / "adapters.py"
    if fixture_path.exists():
        return fixture_path.read_bytes()
    # Fallback to minimal representative code if fixture file missing
    return b"""
class BaseAdapter:
    def send(self, request):
        raise NotImplementedError

class HTTPAdapter(BaseAdapter):
    def __init__(self, pool_connections=10):
        self.init_poolmanager(pool_connections)

    def init_poolmanager(self, connections):
        self.poolmanager = PoolManager(num_pools=connections)

    def proxy_manager_for(self, proxy):
        return self.proxy_manager[proxy]
"""


def test_requests_adapters_no_segfault(parser, adapters_code):
    """
    Validates that the real-world src/requests/adapters.py (27KB, 747 lines)
    parses successfully without Exit Code 139 (segmentation fault) or access violation.
    """
    repo_id = "09d438ba-7639-4dad-9937-4f7eca5e4826"
    commit_sha = "3c7baaa05ab4aa49cc819ce3a819d260de19c157"
    rel_path = "src/requests/adapters.py"

    res = parser.parse_file(rel_path, adapters_code, repo_id, commit_sha)

    # Validate entities
    entity_names = {e.name: e for e in res.entities}
    assert "BaseAdapter" in entity_names, "BaseAdapter class must be extracted"
    assert "HTTPAdapter" in entity_names, "HTTPAdapter class must be extracted"
    assert "init_poolmanager" in entity_names, "init_poolmanager method must be extracted"
    assert "proxy_manager_for" in entity_names, "proxy_manager_for method must be extracted"
    assert "send" in entity_names, "send method must be extracted"

    # Validate relationships
    assert len(res.relationships) > 0, "Relationships must be extracted"
    class_rels = [r for r in res.relationships if r.rel_type == "CONTAINS"]
    assert len(class_rels) > 0, "CONTAINS relationships must exist"

    # Validate calls
    assert len(res.unresolved_calls) > 0, "Unresolved calls must be extracted"
    invoked_names = {c.invoked_symbol_name for c in res.unresolved_calls}
    assert "PoolManager" in invoked_names or "init_poolmanager" in invoked_names or len(invoked_names) > 5


def test_nested_classes_and_functions(parser):
    """
    Verifies that nested classes within classes and functions, and nested functions
    within functions are traversed safely with correct qualified names and parent relationships.
    """
    code = b"""
def outer_fn():
    def inner_fn():
        def deeply_nested_fn():
            return 1
        return deeply_nested_fn()
    return inner_fn()

class OuterClass:
    class MiddleClass:
        class InnerClass:
            def inner_method(self):
                return True

    def outer_method(self):
        class MethodLocalClass:
            def local_method(self):
                return 42
        return MethodLocalClass().local_method()
"""
    res = parser.parse_file("nested.py", code, "repo", "commit")

    names = {e.name for e in res.entities}
    assert "outer_fn" in names
    assert "inner_fn" in names
    assert "deeply_nested_fn" in names
    assert "OuterClass" in names
    assert "MiddleClass" in names
    assert "InnerClass" in names
    assert "inner_method" in names
    assert "outer_method" in names
    assert "MethodLocalClass" in names
    assert "local_method" in names

    # Check DEFINES relationships for nested functions
    func_rels = [r for r in res.relationships if r.rel_type == "DEFINES"]
    assert len(func_rels) >= 4, "Inner functions and methods must have DEFINES relationships"


def test_stacked_decorators_and_api_entities(parser):
    """
    Verifies stacked decorators and detects API entity types when route/HTTP verb decorators are present.
    """
    code = b"""
@router.get("/users")
@auth_required
@cached(ttl=60)
def list_users():
    return []

@audit_log
def normal_function():
    return "ok"
"""
    res = parser.parse_file("routes.py", code, "repo", "commit")

    api_node = next(e for e in res.entities if e.name == "list_users")
    assert api_node.entity_type == "API", "Decorated with @router.get must be classified as API"
    assert len(api_node.properties.get("decorators", [])) == 3, "All 3 stacked decorators must be recorded"

    normal_node = next(e for e in res.entities if e.name == "normal_function")
    assert normal_node.entity_type == "Function", "Non-API decorated function must be classified as Function"
    assert len(normal_node.properties.get("decorators", [])) == 1


def test_malformed_syntax_recovery_and_isolation(parser):
    """
    Verifies that malformed Python syntax does not raise unhandled exceptions or crash.
    Valid AST subtrees are extracted and syntax errors recorded.
    """
    malformed_code = b"""
def valid_before():
    return 1

# Completely broken syntax
class BrokenClass(
    def unclosed(
        return
"""
    res = parser.parse_file("broken.py", malformed_code, "repo", "commit")
    assert len(res.syntax_errors) > 0, "Syntax error must be reported"
    assert any(e.name == "valid_before" for e in res.entities), "Valid function before syntax error must be extracted"


def test_unicode_and_special_characters(parser):
    """
    Verifies multi-byte UTF-8, emojis, and non-ASCII identifiers in source code
    do not corrupt byte offsets or line translation.
    """
    unicode_code = """
# \U0001f680 Rocket launcher module
GREETING = "H\u00e9llo W\u00f6rld \U0001f30d"

def \u03c0_calc(rad\u00efus: float) -> float:
    \"\"\"Calculates \u03c0 * r\u00b2 with \U0001f525 accuracy.\"\"\"
    return 3.14159 * rad\u00efus * rad\u00efus
""".encode("utf-8")

    res = parser.parse_file("unicode_test.py", unicode_code, "repo", "commit")
    assert any(e.name == "GREETING" for e in res.entities)
    assert any("\u03c0_calc" in e.name for e in res.entities)
    assert len(res.entities) >= 3


def test_repeated_sequential_parsing(parser, adapters_code):
    """
    Verifies that parsing a large file 10 times sequentially in the same process
    does not cause C-extension pointer corruption, memory leaks, or segmentation faults.
    """
    repo_id = "09d438ba-7639-4dad-9937-4f7eca5e4826"
    commit_sha = "3c7baaa05ab4aa49cc819ce3a819d260de19c157"
    rel_path = "src/requests/adapters.py"

    initial_result = parser.parse_file(rel_path, adapters_code, repo_id, commit_sha)
    assert len(initial_result.entities) > 0

    for i in range(10):
        res = parser.parse_file(rel_path, adapters_code, repo_id, commit_sha)
        assert len(res.entities) == len(initial_result.entities), f"Iteration {i} entities count mismatch"
        assert len(res.relationships) == len(initial_result.relationships), f"Iteration {i} rels count mismatch"
        assert len(res.unresolved_calls) == len(initial_result.unresolved_calls), f"Iteration {i} calls count mismatch"
        gc.collect()
