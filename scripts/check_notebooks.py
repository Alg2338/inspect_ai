"""Static checks

Usage (from the repo root):

    .venv/bin/python scripts/check_notebooks.py [notebook.ipynb ...]

Exits non-zero on any failure.
"""
from __future__ import annotations

import ast
import importlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import nbformat


def _ruff_path() -> str:
    """Find the ruff binary, preferring one next to our Python interpreter."""
    import shutil

    candidate = Path(sys.executable).parent / "ruff"
    if candidate.is_file():
        return str(candidate)
    found = shutil.which("ruff")
    if found:
        return found
    raise RuntimeError("ruff not found — install with `uv pip install ruff`")


PLACEHOLDER_MARKER = "# YOUR CODE HERE"

# Jupyter line-magic / shell-escape prefixes — stripped before compiling.
NOTEBOOK_MAGIC_PREFIXES = ("!", "%")

# Numbered headings like "### 7.3 Title" — group 2 is the number.
HEADING_NUM_RE = re.compile(r"^(#{1,6})\s+(\d+(?:\.\d+)*)\.?\s*(.*?)$", re.MULTILINE)

# Only inspect_ai imports are verified; third-party imports aren't our concern.
RESOLVABLE_PREFIXES = ("inspect_ai",)


@dataclass
class Finding:
    notebook: Path
    where: str  # human-readable cell reference
    msg: str
    severity: str = "error"  # "error" or "warning"

    def render(self) -> str:
        return f"  [{self.severity:7}] {self.notebook}  {self.where}: {self.msg}"


@dataclass
class Result:
    findings: list[Finding] = field(default_factory=list)

    def add(self, *args, **kwargs) -> None:
        self.findings.append(Finding(*args, **kwargs))


def cell_label(idx: int, last_heading: str | None) -> str:
    h = f" ({last_heading})" if last_heading else ""
    return f"cell {idx}{h}"


def iter_cells(nb) -> Iterable[tuple[int, dict, str | None]]:
    """Yield (idx, cell, last_heading), where last_heading is the closest
    markdown heading above the cell."""
    last_heading: str | None = None
    h_only_re = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
    for i, cell in enumerate(nb.cells):
        if cell.cell_type == "markdown":
            matches = h_only_re.findall(cell.source)
            if matches:
                last_heading = matches[-1].strip()
        yield i, cell, last_heading


# ---------------------------------------------------------------------------
# Source preparation
# ---------------------------------------------------------------------------

def strip_notebook_magics(source: str) -> str:
    """Replace Jupyter magic / shell-escape lines with `pass` so the cell
    compiles as plain Python."""
    out_lines = []
    for line in source.splitlines():
        if line.lstrip().startswith(NOTEBOOK_MAGIC_PREFIXES):
            out_lines.append("pass  # stripped notebook magic")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def fill_placeholders(source: str) -> str:
    """Replace `# YOUR CODE HERE` markers with stubs so the cell compiles.

    Two forms:
      - `lhs = # YOUR CODE HERE` → `lhs = ...,`  (trailing comma keeps a call
        with one kwarg per line valid)
      - standalone `# YOUR CODE HERE` → `...`     (fills an empty body)

    A bare marker used as a positional arg inside a call has no valid stub, so it
    stays a SyntaxError — by design, the compile check flags it.
    """
    src = re.sub(rf"(?m)^(\s*.+?=)[ \t]*{PLACEHOLDER_MARKER}.*$", r"\1 ...,", source)
    src = re.sub(rf"(?m)^(\s*){PLACEHOLDER_MARKER}.*$", r"\1...", src)
    return src


def prepare(source: str) -> str:
    """Strip magics + fill placeholders so a cell can be parsed/compiled."""
    return fill_placeholders(strip_notebook_magics(source))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_jsonformat(nb_path: Path, result: Result):
    try:
        nb = nbformat.read(str(nb_path), as_version=4)
        nbformat.validate(nb)
        return nb
    except Exception as e:
        result.add(nb_path, "(file)", f"nbformat invalid: {e}")
        return None


def check_cells_compile(nb_path: Path, nb, result: Result) -> None:
    for i, cell, heading in iter_cells(nb):
        if cell.cell_type != "code":
            continue
        # `prepare` stubs out placeholders; a real SyntaxError still surfaces.
        try:
            compile(prepare(cell.source), f"{nb_path}:cell-{i}", "exec")
        except SyntaxError as e:
            result.add(nb_path, cell_label(i, heading),
                       f"SyntaxError at line {e.lineno}: {e.msg}")


def check_imports_resolve(nb_path: Path, nb, result: Result) -> None:
    """For each `from inspect_ai... import Y`, check that Y exists on the module.
    Guards against API drift when inspect_ai is upgraded."""
    cache: dict[str, object] = {}

    def get_module(name: str):
        if name not in cache:
            try:
                cache[name] = importlib.import_module(name)
            except Exception as e:
                cache[name] = e
        return cache[name]

    for i, cell, heading in iter_cells(nb):
        if cell.cell_type != "code":
            continue
        try:
            tree = ast.parse(prepare(cell.source))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            mod_name = node.module or ""
            if not mod_name.startswith(RESOLVABLE_PREFIXES):
                continue
            mod = get_module(mod_name)
            if isinstance(mod, Exception):
                result.add(nb_path, cell_label(i, heading),
                           f"cannot import module {mod_name!r}: {mod}")
                continue
            for alias in node.names:
                if alias.name != "*" and not hasattr(mod, alias.name):
                    result.add(nb_path, cell_label(i, heading),
                               f"`from {mod_name} import {alias.name}` — attribute does not exist")


def check_numbering(nb_path: Path, nb, result: Result) -> None:
    """Flag holes in section numbering — under each parent, the sub-numbers
    must run 1, 2, 3, … with no gaps."""
    sub_seen: dict[str, list[int]] = {}
    for cell in nb.cells:
        if cell.cell_type != "markdown":
            continue
        for _hashes, num, _title in HEADING_NUM_RE.findall(cell.source):
            parts = num.split(".")
            if len(parts) >= 2:
                sub_seen.setdefault(".".join(parts[:-1]), []).append(int(parts[-1]))

    for parent, nums in sub_seen.items():
        if len(nums) <= 1:
            continue
        missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
        if missing:
            result.add(nb_path, "section numbering",
                       f"under '{parent}.x': saw {sorted(nums)}, missing {missing}")


def check_no_outputs(nb_path: Path, nb, result: Result) -> None:
    bloat = sum(1 for c in nb.cells if c.cell_type == "code" and c.get("outputs"))
    if bloat:
        result.add(nb_path, "(file)",
                   f"{bloat} code cell(s) have committed outputs — run nbstripout",
                   severity="warning")


# Real-bug rules only (bad %-format, syntax, mutable defaults). F401 is dropped
# too: imports provided for `# YOUR CODE HERE` cells look unused (false positives).
RUFF_RULE_SELECT = "F501,F502,F503,F504,F505,F506,F507,F901,E9,B006,B008"

# These are errors; everything else is a warning.
RUFF_ERROR_RULES = {"E9"}

RUFF_LINE_RE = re.compile(
    r":(?P<line>\d+):\d+:\s+(?P<code>[A-Z]+\d+)\s+(?:\[\*\]\s+)?(?P<msg>.+)$"
)


def check_ruff_lint(nb_path: Path, nb, result: Result) -> None:
    """Run ruff on all code cells concatenated (so an import in one cell used in
    another isn't flagged unused). `# --- cell N ---` markers map findings back."""
    tmp = Path(f"/tmp/_nbcheck_{nb_path.stem}_concat.py")
    parts = []
    for i, cell, _h in iter_cells(nb):
        if cell.cell_type != "code":
            continue
        parts.append(f"# --- cell {i} ---\n{prepare(cell.source)}\n")
    tmp.write_text("\n".join(parts))
    try:
        proc = subprocess.run(
            [_ruff_path(), "check", f"--select={RUFF_RULE_SELECT}",
             "--output-format=concise", "--no-cache", str(tmp)],
            capture_output=True, text=True, timeout=20,
        )
        body = tmp.read_text().splitlines()
        for line in proc.stdout.splitlines():
            m = RUFF_LINE_RE.search(line)
            if not m:
                continue
            ln, code, msg = int(m.group("line")), m.group("code"), m.group("msg")
            cell_hint = ""
            for j in range(ln - 1, -1, -1):
                mm = re.match(r"# --- cell (\d+) ---", body[j])
                if mm:
                    cell_hint = f"cell {mm.group(1)}: "
                    break
            severity = "error" if code in RUFF_ERROR_RULES else "warning"
            result.add(nb_path, "(ruff)", f"{cell_hint}{code} {msg}", severity=severity)
    except subprocess.TimeoutExpired:
        pass
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def check_notebook(nb_path: Path) -> Result:
    result = Result()
    nb = check_jsonformat(nb_path, result)
    if nb is None:
        return result
    check_cells_compile(nb_path, nb, result)
    check_imports_resolve(nb_path, nb, result)
    check_numbering(nb_path, nb, result)
    check_no_outputs(nb_path, nb, result)
    check_ruff_lint(nb_path, nb, result)
    return result


def main(argv: list[str]) -> int:
    if argv:
        paths = [Path(p) for p in argv]
    else:
        paths = sorted(p for p in Path(".").rglob("*.ipynb") if ".ipynb_checkpoints" not in p.parts)
    if not paths:
        print("no .ipynb files found")
        return 0

    all_findings: list[Finding] = []
    for nb in paths:
        print(f"== {nb} ==")
        result = check_notebook(nb)
        if not result.findings:
            print("  ✅ clean")
        else:
            for f in result.findings:
                print(f.render())
        all_findings.extend(result.findings)

    errors = [f for f in all_findings if f.severity == "error"]
    warnings = [f for f in all_findings if f.severity == "warning"]
    print()
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s) across {len(paths)} notebook(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
