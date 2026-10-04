"""Layer boundaries (see .importlinter) and the no-writer rule, as part of the test suite."""

import ast
import re
import subprocess
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "mcatlas"


def test_import_contracts_hold():
    lint = Path(sys.executable).with_name("lint-imports")
    if not lint.exists():
        pytest.skip("import-linter not installed")
    result = subprocess.run([str(lint)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_nbt_or_region_writer_in_package():
    """mcatlas must not even contain code capable of encoding world data."""
    for path in (SRC / "core").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.ClassDef):
                lowered = node.name.lower()
                assert not any(w in lowered for w in ("encode", "write", "save", "dump")), (
                    f"{path.relative_to(ROOT)}: {node.name}"
                )


def _calls(path: Path) -> list[ast.Call]:
    return [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Call)]


def _mode(call: ast.Call, position: int) -> str | None:
    node = call.args[position] if len(call.args) > position else None
    for kw in call.keywords:
        if kw.arg == "mode":
            node = kw.value
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


@pytest.mark.parametrize("name", ["readonly.py", "source_folder.py", "source_zip.py"])
def test_source_adapters_only_open_read_only(name):
    """Every open() in the source adapters is provably read-only."""
    for call in _calls(SRC / "adapters" / name):
        func = ast.unparse(call.func)
        if func == "os.open":
            assert "READ_FLAGS" in ast.unparse(call.args[1]), f"{name}: {ast.unparse(call)}"
        elif func == "os.fdopen":
            assert _mode(call, 1) == "rb", f"{name}: {ast.unparse(call)}"
        elif func == "zipfile.ZipFile":
            assert _mode(call, 1) == "r", f"{name}: {ast.unparse(call)}"
        elif func == "open" or func.endswith((".write_bytes", ".write_text", ".touch", ".mkdir")):
            pytest.fail(f"{name}: unexpected file operation {ast.unparse(call)}")


def _requirement_name(spec: str) -> str:
    return re.split(r"[<>=!~;\[ ]", spec, maxsplit=1)[0].strip().lower().replace("_", "-")


def test_every_imported_package_is_a_runtime_dependency():
    """An install without the dev dependencies (a server, a container) must still start: a
    package that only arrives through a dev tool would crash it at import time."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    declared = {_requirement_name(spec) for spec in project["dependencies"]}
    distributions = packages_distributions()
    stdlib = sys.stdlib_module_names
    missing: set[str] = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top = module.split(".", 1)[0]
                if top in stdlib or top == "mcatlas":
                    continue
                dists = {d.lower().replace("_", "-") for d in distributions.get(top, [top])}
                if not dists & declared:
                    missing.add(f"{top} ({path.relative_to(ROOT)})")
    assert not missing, f"imported but not in [project] dependencies: {sorted(missing)}"
