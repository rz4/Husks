"""
test_4_layer_isolation.py -- Instrumentation boundary.

Gate: import isolation across all four layers, and the OracleBackend
protocol is content-keyed at the boundary.

Layer structure (imports flow upward only):

    Layer 0  core.py          permanent, stdlib-only
    Layer 1  transport.py     pure, imports core + stdlib
    Layer 2  build/ designs/ir.py engine, imports core/transport + stdlib
    Layer 3  llm.py tools.py  instrument, may import anything
             trace.py cli.py
"""

import ast as python_ast
import os

import pytest

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "husks")

# -- Layer definitions ---------------------------------------------------------

# Modules in each layer (Python source files only).
LAYER_0 = {"core"}
LAYER_1 = {"transport"}
LAYER_2 = {"build", "designs"}
LAYER_3 = {"llm", "tools", "trace", "cli", "kernel", "__init__", "__main__"}

# Allowed husks.* imports per layer (may import from same or higher layers)
ALLOWED_HUSKS_IMPORTS = {
    "core":      set(),                  # Layer 0: imports nothing from husks
    "transport": {"husks.core"},         # Layer 1: only core (designs/transport.py)
}


def _extract_imports(filepath):
    """Parse a Python file and return all import references as a set of strings."""
    with open(filepath, "r") as f:
        source = f.read()

    tree = python_ast.parse(source, filename=filepath)
    imports = set()

    for node in python_ast.walk(tree):
        if isinstance(node, python_ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, python_ast.ImportFrom):
            if node.module:
                imports.add(node.module)

    return imports


def _husks_imports(filepath):
    """Return the set of husks.* imports from a Python source file."""
    all_imports = _extract_imports(filepath)
    return {m for m in all_imports if m.startswith("husks.") or m == "husks"}


def _non_husks_imports(filepath):
    """Return the set of non-husks imports from a Python source file."""
    all_imports = _extract_imports(filepath)
    return {m.split(".")[0] for m in all_imports
            if not m.startswith("husks.") and m != "husks"}


# -- Gate: core imports nothing downward ---------------------------------------

class TestCoreIsolation:
    """Layer 0: core.py imports no husks modules and only uses stdlib."""

    @pytest.mark.alpha

    def test_no_husks_imports(self):
        path = os.path.join(SRC_DIR, "core.py")
        imports = _husks_imports(path)
        assert imports == set(), (
            f"core.py imports husks modules: {imports}"
        )

    @pytest.mark.alpha

    def test_stdlib_only(self):
        path = os.path.join(SRC_DIR, "core.py")
        imports = _non_husks_imports(path)
        allowed = {"hashlib", "os", "typing", "__future__"}
        assert imports == allowed, (
            f"core.py imports: {imports}, expected only {allowed}"
        )


# -- Gate: transport imports only from core ------------------------------------

class TestTransportIsolation:
    """Layer 1: transport.py imports only from husks.core and stdlib."""

    @pytest.mark.alpha

    def test_only_imports_core(self):
        path = os.path.join(SRC_DIR, "design", "transport.py")
        imports = _husks_imports(path)
        assert imports == {"husks.core"}, (
            f"transport.py husks imports: {imports}, expected only husks.core"
        )

    @pytest.mark.alpha

    def test_stdlib_only(self):
        path = os.path.join(SRC_DIR, "design", "transport.py")
        imports = _non_husks_imports(path)
        # json, typing, and __future__ are stdlib
        allowed_stdlib = {"json", "typing", "__future__"}
        assert imports == allowed_stdlib, (
            f"transport.py non-husks imports: {imports}, "
            f"expected only {allowed_stdlib}"
        )

    @pytest.mark.alpha

    def test_no_engine_imports(self):
        """transport must not import from engine or instrument layers."""
        path = os.path.join(SRC_DIR, "design", "transport.py")
        imports = _husks_imports(path)
        engine_instrument = {
            "husks.build", "husks.design", "husks.llm", "husks.tools",
            "husks.trace", "husks.cli", "husks.kernel",
        }
        violations = imports & engine_instrument
        assert violations == set(), (
            f"transport.py imports from engine/instrument: {violations}"
        )


# -- Gate: no upward layer violations -----------------------------------------

class TestLayerBoundaries:
    """No module imports from a layer below it."""

    @pytest.mark.alpha

    def test_core_never_imports_downward(self):
        """Core (Layer 0) imports nothing from Layers 1-3."""
        path = os.path.join(SRC_DIR, "core.py")
        imports = _husks_imports(path)
        assert imports == set()

    @pytest.mark.alpha

    def test_transport_never_imports_engine_or_instrument(self):
        """Transport (Layer 1) imports nothing from Layers 2-3."""
        path = os.path.join(SRC_DIR, "design", "transport.py")
        imports = _husks_imports(path)
        lower_layers = {f"husks.{m}" for m in (LAYER_2 | LAYER_3)}
        violations = imports & lower_layers
        assert violations == set(), (
            f"transport.py imports from lower layers: {violations}"
        )

    @pytest.mark.alpha

    def test_design_executor_does_not_import_instrument(self):
        """design/locke/_executor.py (Layer 2) should not directly import instrument modules
        at module scope. Lazy imports inside functions are acceptable
        (e.g. 'import hy' inside compile())."""
        path = os.path.join(SRC_DIR, "design", "locke", "_executor.py")
        # Parse only top-level imports (not inside functions)
        with open(path, "r") as f:
            source = f.read()
        tree = python_ast.parse(source)

        top_level_imports = set()
        for node in tree.body:
            if isinstance(node, python_ast.Import):
                for alias in node.names:
                    top_level_imports.add(alias.name)
            elif isinstance(node, python_ast.ImportFrom):
                if node.module:
                    top_level_imports.add(node.module)

        instrument_modules = {"husks.llm", "husks.tools", "husks.trace",
                              "husks.cli", "husks.kernel"}
        violations = {m for m in top_level_imports
                      if m in instrument_modules}
        assert violations == set(), (
            f"design/locke/_executor.py top-level imports from instrument layer: {violations}"
        )


# -- OracleBackend protocol ---------------------------------------------------

class TestOracleBackendProtocol:
    """The OracleBackend protocol is defined and content-keyed."""

    @pytest.mark.alpha

    def test_protocol_importable(self):
        from husks.design.transport import OracleBackend
        assert OracleBackend is not None

    @pytest.mark.alpha

    def test_protocol_is_runtime_checkable(self):
        from husks.design.transport import OracleBackend
        # A conforming callable should satisfy isinstance check
        def my_backend(recipe_form, inputs):
            return {}, {}
        assert isinstance(my_backend, OracleBackend)

    @pytest.mark.alpha

    def test_protocol_signature_is_content_keyed(self):
        """The protocol accepts recipe_form and inputs (content),
        not store, model, or other instrumentation."""
        from husks.design.transport import OracleBackend
        import inspect
        sig = inspect.signature(OracleBackend.__call__)
        params = list(sig.parameters.keys())
        # self, recipe_form, inputs -- no store, no model, no site
        assert "recipe_form" in params
        assert "inputs" in params
        for banned in ("store", "model", "site", "backend", "S"):
            assert banned not in params, (
                f"OracleBackend.__call__ has '{banned}' parameter -- "
                f"instrumentation must not cross the boundary"
            )

    @pytest.mark.alpha

    def test_stub_backend_conforms(self):
        """A minimal stub backend satisfies the protocol."""
        from husks.design.transport import OracleBackend

        def stub_backend(recipe_form, inputs):
            prompt = recipe_form[2].decode("utf-8") if len(recipe_form) > 2 else ""
            outputs = {"out.txt": f"stub response to: {prompt}".encode("utf-8")}
            provenance = {"model": "stub", "tokens_in": 0, "tokens_out": 0}
            return outputs, provenance

        assert isinstance(stub_backend, OracleBackend)
        recipe = [b"oracle", b"", b"Hello", [b"read-file"], b"3"]
        outputs, prov = stub_backend(recipe, {"in.txt": b"data"})
        assert isinstance(outputs, dict)
        assert isinstance(prov, dict)
        assert b"Hello" in outputs["out.txt"]


# -- Layer documentation -------------------------------------------------------

class TestLayerDocumentation:
    """Verify that modules document their layer membership."""

    @pytest.mark.alpha

    def test_core_docstring_mentions_dependency_free(self):
        import husks.core
        assert "dependency" in husks.core.__doc__.lower() or \
               "stdlib" in husks.core.__doc__.lower()

    @pytest.mark.alpha

    def test_transport_docstring_mentions_bijection(self):
        import husks.design.transport
        assert "bijection" in husks.design.transport.__doc__.lower() or \
               "bijective" in husks.design.transport.__doc__.lower()
