"""Documentation integrity checks.

Offline by construction: these tests read repository files and introspect the already-installed
package. They make no network calls, require no provider credentials, and never import
``kgmd.embed`` or ``kgmd.mcp_server`` (whose import graph reaches ``fastembed`` and could trigger a
model download). MCP tool names are therefore derived with ``ast``.

See specs/001-project-documentation/contracts/page-conventions.md for the page contracts these
tests enforce, and .../contracts/documented-surface.md for the surface inventory.
"""

from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path

import click

import kgmd
from kgmd.cli import main
from kgmd.config import DEFAULT_CONFIG

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
INDEX = DOCS / "README.md"
FIXTURES = REPO_ROOT / "tests" / "fixtures"

CLI_REF = DOCS / "reference" / "cli.md"
CONFIG_REF = DOCS / "reference" / "configuration.md"
EXPORT_REF = DOCS / "reference" / "export.md"
MCP_GUIDE = DOCS / "guides" / "mcp.md"
CONCEPTS = DOCS / "concepts.md"
TROUBLESHOOTING = DOCS / "guides" / "troubleshooting.md"
EXAMPLES = DOCS / "examples"

EXPECTED_PAGES = [
    "README.md",
    "install.md",
    "quickstart.md",
    "concepts.md",
    "guides/mcp.md",
    "guides/maintenance.md",
    "guides/troubleshooting.md",
    "reference/cli.md",
    "reference/configuration.md",
    "reference/export.md",
    "examples/personal-notes.md",
    "examples/mcp-assistant.md",
    "examples/graph-export.md",
    "contributing/development.md",
    "contributing/architecture.md",
    "contributing/release.md",
]

INERT_CONFIG_KEYS = {
    "extraction.max_entities_per_chunk",
    "extraction.max_relations_per_chunk",
    "induction.include_attribute_summary",
}
INERT_MARKER = "Accepted but currently has no effect"

CONCEPT_TERMS = ["document", "chunk", "entity", "mention", "relation", "induced schema"]

WALKTHROUGH_SECTIONS = [
    "Goal",
    "Prerequisites",
    "Corpus",
    "Steps",
    "Expected output",
    "Limitations",
]

STAMP_RE = re.compile(r"^> Applies to kgmd (\d+)\.(\d+)\.x$")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
DOTTED_RE = re.compile(r"^[a-z_]+(?:\.[a-z_]+)+$")
INVOCATION_RE = re.compile(r"kgmd ([a-z][a-z-]*)")
CREDENTIAL_RE = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
ABSOLUTE_PATH_RE = re.compile(r"/Users/[A-Za-z0-9._-]+|[A-Z]:\\\\?Users\\\\?")

# Words that follow "kgmd " in prose without naming a subcommand.
NON_COMMAND_TOKENS = {"and", "or", "is", "the", "in", "on", "with", "corpus", "commands", "command"}


# --------------------------------------------------------------------------------------
# Helpers: pages
# --------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def docs_pages() -> tuple[Path, ...]:
    """Every markdown page under docs/, discovered (never hard-coded)."""
    return tuple(sorted(DOCS.rglob("*.md")))


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


@lru_cache(maxsize=64)
def page_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def page_lines(path: Path) -> list[str]:
    return page_text(path).splitlines()


def prose_lines(path: Path) -> list[str]:
    """Page lines that sit outside fenced code blocks.

    Markdown inside a fence is sample text, not page structure: a ``# comment`` in a bash block is
    not a second H1, and a fence's backticks must never be paired as an inline code span.
    """
    out = []
    in_fence = False
    for line in page_lines(path):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return out


def fenced_blocks(path: Path) -> list[str]:
    """Bodies of fenced code blocks, without their delimiters."""
    blocks: list[list[str]] = []
    in_fence = False
    for line in page_lines(path):
        if line.lstrip().startswith("```"):
            if not in_fence:
                blocks.append([])
            in_fence = not in_fence
            continue
        if in_fence:
            blocks[-1].append(line)
    return ["\n".join(block) for block in blocks]


def strip_fences(text: str) -> str:
    return FENCE_RE.sub("", text)


def sections(path: Path, level: int = 3) -> dict[str, str]:
    """Split a page into ``### heading`` -> body, ignoring headings inside code fences."""
    prefix = "#" * level + " "
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in prose_lines(path):
        if line.startswith(prefix):
            current = line[len(prefix) :].strip()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def code_spans(text: str) -> set[str]:
    """Inline code spans only. Fences are stripped first so backtick pairing stays correct."""
    return set(CODE_SPAN_RE.findall(strip_fences(text)))


def internal_links(path: Path) -> list[str]:
    """Link targets that point at the filesystem, with any fragment stripped."""
    targets = []
    for raw in LINK_RE.findall(page_text(path)):
        target = raw.split("#", 1)[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        targets.append(target)
    return targets


# --------------------------------------------------------------------------------------
# Helpers: surface introspection
# --------------------------------------------------------------------------------------


def click_commands() -> dict[str, click.Command]:
    return dict(main.commands)


def command_identifiers(command: click.Command) -> list[set[str]]:
    """One set of acceptable spellings per parameter of ``command``."""
    acceptable = []
    for param in command.params:
        if isinstance(param, click.Argument):
            acceptable.append({param.name, param.name.upper()})
        else:
            acceptable.append(set(param.opts))
    return acceptable


def global_options() -> set[str]:
    return {opt for param in main.params for opt in param.opts}


def config_keys(node: dict | None = None, prefix: str = "") -> set[str]:
    node = DEFAULT_CONFIG if node is None else node
    keys: set[str] = set()
    for key, value in node.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            keys |= config_keys(value, f"{dotted}.")
        else:
            keys.add(dotted)
    return keys


def config_sections() -> set[str]:
    return set(DEFAULT_CONFIG)


@lru_cache(maxsize=1)
def mcp_tool_names() -> tuple[str, ...]:
    """Registered MCP tool names, via AST so no runtime import is needed."""
    tree = ast.parse((REPO_ROOT / "kgmd" / "mcp_server.py").read_text(encoding="utf-8"))
    names = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            func = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(func, ast.Attribute) and func.attr == "tool":
                names.append(node.name)
    return tuple(names)


def export_formats() -> set[str]:
    param = next(p for p in main.commands["export"].params if p.name == "fmt")
    return set(param.type.choices)


def structured_output_commands() -> set[str]:
    return {
        name
        for name, command in click_commands().items()
        if any(p.name == "as_json" for p in command.params)
    }


@lru_cache(maxsize=1)
def package_source_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((REPO_ROOT / "kgmd").rglob("*.py"))
    )


# --------------------------------------------------------------------------------------
# Page structure (convention C-1)
# --------------------------------------------------------------------------------------


def test_expected_pages_exist():
    missing = [name for name in EXPECTED_PAGES if not (DOCS / name).is_file()]
    assert not missing, f"missing documentation pages: {missing}"


def test_page_skeleton():
    problems = []
    for path in docs_pages():
        lines = page_lines(path)
        if len(lines) < 4:
            problems.append(f"{rel(path)}: fewer than 4 lines")
            continue
        if not lines[0].startswith("# "):
            problems.append(f"{rel(path)}: line 1 is not an H1")
        if lines[2].strip():
            problems.append(f"{rel(path)}: line 3 must be blank")
        if not lines[3].strip():
            problems.append(f"{rel(path)}: line 4 must begin the audience paragraph")
        extra_h1 = [line for line in prose_lines(path)[1:] if line.startswith("# ")]
        if extra_h1:
            problems.append(f"{rel(path)}: extra H1 outside code fences: {extra_h1}")
    assert not problems, "page skeleton violations:\n" + "\n".join(problems)


def test_version_stamps():
    major, minor = kgmd.__version__.split(".")[:2]
    problems = []
    for path in docs_pages():
        lines = page_lines(path)
        stamp = STAMP_RE.match(lines[1]) if len(lines) > 1 else None
        if stamp is None:
            problems.append(f"{rel(path)}: line 2 must be '> Applies to kgmd {major}.{minor}.x'")
        elif (stamp.group(1), stamp.group(2)) != (major, minor):
            problems.append(
                f"{rel(path)}: stamp {stamp.group(1)}.{stamp.group(2)}.x "
                f"does not match kgmd {kgmd.__version__}"
            )
    assert not problems, "version stamp violations:\n" + "\n".join(problems)


# --------------------------------------------------------------------------------------
# Links and navigation (convention C-7)
# --------------------------------------------------------------------------------------


def test_internal_links_resolve():
    problems = []
    for path in docs_pages():
        for target in internal_links(path):
            if not (path.parent / target).resolve().exists():
                problems.append(f"{rel(path)} -> {target}")
    assert not problems, "unresolved internal links:\n" + "\n".join(problems)


def test_readme_links_resolve():
    readme = REPO_ROOT / "README.md"
    problems = [
        f"README.md -> {target}"
        for target in internal_links(readme)
        if not (readme.parent / target).resolve().exists()
    ]
    assert not problems, "unresolved links in README.md:\n" + "\n".join(problems)


def test_two_link_reachability():
    depth = {INDEX.resolve(): 0}
    frontier = [INDEX.resolve()]
    while frontier:
        current = frontier.pop()
        for target in internal_links(current):
            resolved = (current.parent / target).resolve()
            if resolved.suffix != ".md" or not resolved.is_file():
                continue
            if resolved not in depth or depth[resolved] > depth[current] + 1:
                depth[resolved] = depth[current] + 1
                frontier.append(resolved)
    unreachable = [
        f"{rel(path)} (depth {depth.get(path.resolve(), 'unreachable')})"
        for path in docs_pages()
        if depth.get(path.resolve(), 99) > 2
    ]
    assert not unreachable, "pages more than two links from the index:\n" + "\n".join(unreachable)


# --------------------------------------------------------------------------------------
# Prohibited content (convention C-9)
# --------------------------------------------------------------------------------------


def test_no_credential_shaped_strings():
    problems = [rel(path) for path in docs_pages() if CREDENTIAL_RE.search(page_text(path))]
    assert not problems, f"credential-shaped strings found in: {problems}"


def test_no_absolute_paths():
    problems = [rel(path) for path in docs_pages() if ABSOLUTE_PATH_RE.search(page_text(path))]
    assert not problems, f"developer-machine absolute paths found in: {problems}"


def test_no_unwritten_placeholders():
    banned = ("TODO", "TBD", "coming soon", "Coming soon")
    problems = [
        f"{rel(path)}: {token}"
        for path in docs_pages()
        for token in banned
        if token in page_text(path)
    ]
    assert not problems, "unwritten placeholders:\n" + "\n".join(problems)


def test_fixture_references_exist():
    pattern = re.compile(r"tests/fixtures/([A-Za-z0-9_.-]+\.md)")
    problems = []
    for path in docs_pages():
        for name in pattern.findall(page_text(path)):
            if not (FIXTURES / name).is_file():
                problems.append(f"{rel(path)} references missing fixture {name}")
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------------------
# CLI reference coverage (convention C-2)
# --------------------------------------------------------------------------------------


def test_all_commands_documented():
    documented = set(sections(CLI_REF))
    actual = set(click_commands())
    assert documented == actual, (
        f"undocumented commands: {sorted(actual - documented)}; "
        f"documented but nonexistent: {sorted(documented - actual)}"
    )


def test_all_parameters_documented():
    documented = sections(CLI_REF)
    problems = []
    for name, command in click_commands().items():
        body = documented.get(name, "")
        spans = code_spans(body)
        for acceptable in command_identifiers(command):
            if not acceptable & spans:
                problems.append(f"{name}: none of {sorted(acceptable)} documented")
    assert not problems, "undocumented parameters:\n" + "\n".join(problems)


def test_global_option_documented():
    text = page_text(CLI_REF)
    missing = [opt for opt in global_options() if f"`{opt}`" not in text]
    assert not missing, f"undocumented global options: {missing}"


def test_structured_output_parity():
    documented = {
        name for name, body in sections(CLI_REF).items() if "**Structured output**:" in body
    }
    actual = structured_output_commands()
    assert documented == actual, (
        f"commands with --json but no structured-output block: {sorted(actual - documented)}; "
        f"documented structured output for commands without --json: {sorted(documented - actual)}"
    )


# --------------------------------------------------------------------------------------
# Configuration reference coverage (convention C-3)
# --------------------------------------------------------------------------------------


def documented_config_keys() -> set[str]:
    known_sections = config_sections()
    return {
        span
        for span in code_spans(page_text(CONFIG_REF))
        if DOTTED_RE.match(span) and span.split(".")[0] in known_sections
    }


def test_all_config_keys_documented():
    documented = documented_config_keys()
    actual = config_keys()
    assert documented == actual, (
        f"undocumented config keys: {sorted(actual - documented)}; "
        f"documented but nonexistent: {sorted(documented - actual)}"
    )


def test_inert_keys_marked():
    rows = {
        line.split("|")[1].strip().strip("`"): line
        for line in page_lines(CONFIG_REF)
        if line.startswith("|") and line.count("|") >= 4
    }
    problems = [key for key in INERT_CONFIG_KEYS if INERT_MARKER not in rows.get(key, "")]
    assert not problems, f"inert keys missing the '{INERT_MARKER}' marker: {sorted(problems)}"


# --------------------------------------------------------------------------------------
# MCP and export coverage (conventions C-4, C-3)
# --------------------------------------------------------------------------------------


def test_all_mcp_tools_documented():
    documented = set(sections(MCP_GUIDE))
    actual = set(mcp_tool_names())
    assert documented == actual, (
        f"undocumented MCP tools: {sorted(actual - documented)}; "
        f"documented but not registered: {sorted(documented - actual)}"
    )


def test_all_export_formats_documented():
    documented = set(sections(EXPORT_REF))
    actual = export_formats()
    assert documented == actual, (
        f"undocumented export formats: {sorted(actual - documented)}; "
        f"documented but unsupported: {sorted(documented - actual)}"
    )


def test_no_phantom_entries():
    """No page may show a `kgmd <subcommand>` invocation that does not exist.

    Checks inline code spans and command lines inside fenced blocks -- the two places a reader
    copy-pastes from. A wrong name here is exactly the class of defect that shipped in the old
    README's MCP tool table.
    """
    actual = set(click_commands())
    problems = []
    for path in docs_pages():
        candidates = [span for span in code_spans(page_text(path)) if span.startswith("kgmd ")]
        for block in fenced_blocks(path):
            candidates += [
                line.strip() for line in block.splitlines() if line.strip().startswith("kgmd ")
            ]
        for candidate in candidates:
            token = INVOCATION_RE.match(candidate)
            if token is None:
                continue
            word = token.group(1)
            if word not in actual and word not in NON_COMMAND_TOKENS:
                problems.append(f"{rel(path)}: `{candidate}` names no such command")
    assert not problems, "phantom command invocations:\n" + "\n".join(problems)


# --------------------------------------------------------------------------------------
# Concepts, troubleshooting, walkthroughs (conventions C-8, C-5, C-6)
# --------------------------------------------------------------------------------------


def test_concept_terms_defined():
    headings = {heading.lower() for heading in sections(CONCEPTS)}
    missing = [term for term in CONCEPT_TERMS if term not in headings]
    assert not missing, f"vocabulary terms without a definition heading: {missing}"


def test_quoted_errors_exist_in_source():
    source = package_source_text()
    symptoms = [line for line in prose_lines(TROUBLESHOOTING) if line.startswith("**Symptom**:")]
    assert symptoms, "troubleshooting page has no **Symptom**: entries"
    problems = []
    for line in symptoms:
        spans = CODE_SPAN_RE.findall(line)
        if len(spans) != 1:
            problems.append(f"{line!r}: expected exactly one code span, found {len(spans)}")
            continue
        if spans[0] not in source:
            problems.append(f"{spans[0]!r} appears in no kgmd/**/*.py source file")
    assert not problems, "troubleshooting quote violations:\n" + "\n".join(problems)


def test_walkthrough_sections():
    problems = []
    for path in sorted(EXAMPLES.glob("*.md")):
        headings = [line[3:].strip() for line in prose_lines(path) if line.startswith("## ")]
        for section in WALKTHROUGH_SECTIONS:
            if section not in headings:
                problems.append(f"{rel(path)}: missing '## {section}'")
        present = [h for h in headings if h in WALKTHROUGH_SECTIONS]
        expected_order = [s for s in WALKTHROUGH_SECTIONS if s in present]
        if present != expected_order:
            problems.append(f"{rel(path)}: sections out of order: {present}")
    assert not problems, "walkthrough structure violations:\n" + "\n".join(problems)
