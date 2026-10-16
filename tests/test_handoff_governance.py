"""Phase 0 Governance & Handoff Audit Verification Suite.

Enforces that:
1. Required handoff audit files exist and are populated.
2. Every completed phase in AGENT_EXECUTION_LOG.md contains the exact mandatory
   self-documentation headers and non-empty engineering content.
3. Hardware and SDK constraints in backend/requirements.txt are respected.
4. Code modularity limit (<= 300 lines per file) from .cursorrules is respected.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HANDOFF_DIR = REPO_ROOT / "handoff_audit"
AGENT_LOG_PATH = HANDOFF_DIR / "AGENT_EXECUTION_LOG.md"
PROMPT_LEDGER_PATH = HANDOFF_DIR / "PROMPT_LEDGER.md"
VERIFICATION_GATES_PATH = HANDOFF_DIR / "VERIFICATION_GATES.md"
REQUIREMENTS_PATH = REPO_ROOT / "backend" / "requirements.txt"

REQUIRED_PHASE_HEADERS = [
    "Spec Comprehension Check",
    "Architectural Decisions & Ambiguity Log",
    "Failure & Self-Correction Ledger",
    "Verification Evidence",
]

FORBIDDEN_PACKAGES = {
    "langchain-google-genai",
    "google-generativeai",
    "torch",
    "pytorch",
    "tensorflow",
    "transformers",
    "sentence-transformers",
}


def test_core_governance_files_exist() -> None:
    """Verify repository structure, config files, and handoff_audit files exist."""
    expected_paths = [
        REPO_ROOT / ".cursorrules",
        REPO_ROOT / "document.md",
        REPO_ROOT / ".env.example",
        REPO_ROOT / "pytest.ini",
        REPO_ROOT / "backend" / "pytest.ini",
        REQUIREMENTS_PATH,
        AGENT_LOG_PATH,
        PROMPT_LEDGER_PATH,
        VERIFICATION_GATES_PATH,
        REPO_ROOT / "backend" / "app",
        REPO_ROOT / "backend" / "app" / "models",
        REPO_ROOT / "backend" / "app" / "schemas",
        REPO_ROOT / "backend" / "app" / "services",
        REPO_ROOT / "backend" / "app" / "symbolic",
        REPO_ROOT / "backend" / "app" / "graph",
        REPO_ROOT / "backend" / "app" / "routers",
    ]
    for path in expected_paths:
        assert path.exists(), f"Missing required governance path: {path}"


def test_requirements_respect_hardware_and_sdk_constraints() -> None:
    """Verify requirements.txt locks official SDKs and excludes forbidden packages."""
    content = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    active_lines = [
        line.strip().lower()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    active_pkg_names = {
        re.split(r"[<>=!\[\s]", line)[0] for line in active_lines
    }

    for forbidden in FORBIDDEN_PACKAGES:
        assert forbidden not in active_pkg_names, (
            f"Forbidden dependency '{forbidden}' found in backend/requirements.txt"
        )

    required_pkgs = {
        "fastapi",
        "sqlmodel",
        "langgraph",
        "google-genai",
        "sympy",
        "pymupdf",
        "pytest",
    }
    for req in required_pkgs:
        assert req in active_pkg_names, (
            f"Required dependency '{req}' missing from backend/requirements.txt"
        )


def test_agent_execution_log_contains_required_headers_per_phase() -> None:
    """Verify every completed phase section in AGENT_EXECUTION_LOG.md has all required headers."""
    text = AGENT_LOG_PATH.read_text(encoding="utf-8")
    assert text.strip(), "AGENT_EXECUTION_LOG.md must not be empty."

    phase_pattern = re.compile(
        r"^### Phase (\d+):\s*(.+?)\s*-\s*(.+)$", re.MULTILINE
    )
    matches = list(phase_pattern.finditer(text))
    assert len(matches) >= 1, (
        "AGENT_EXECUTION_LOG.md must document at least Phase 0."
    )

    logged_phases = [int(m.group(1)) for m in matches]
    expected_sequence = list(range(len(logged_phases)))
    assert logged_phases == expected_sequence, (
        f"Phases in AGENT_EXECUTION_LOG.md must be sequential starting at 0, got {logged_phases}"
    )

    for idx, match in enumerate(matches):
        phase_num = match.group(1)
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        section_body = text[start:end]

        for required_header in REQUIRED_PHASE_HEADERS:
            header_regex = re.compile(
                rf"^####\s+\d+\.\s+{re.escape(required_header)}.*$",
                re.MULTILINE,
            )
            header_match = header_regex.search(section_body)
            assert header_match is not None, (
                f"Phase {phase_num} in AGENT_EXECUTION_LOG.md is missing required header: "
                f"'{required_header}'"
            )

            after_header = section_body[header_match.end() :]
            next_sub = re.search(r"^####\s+", after_header, re.MULTILINE)
            subsection_content = (
                after_header[: next_sub.start()] if next_sub else after_header
            ).strip()
            assert len(subsection_content) >= 20, (
                f"Phase {phase_num} header '{required_header}' must contain substantive content."
            )


def test_source_files_respect_300_line_modularity_limit() -> None:
    """Enforce .cursorrules Section 4: No code file may exceed 300 lines."""
    scan_roots = [REPO_ROOT / "backend", REPO_ROOT / "tests", REPO_ROOT / "frontend" / "src"]
    for root in scan_roots:
        if not root.exists():
            continue
        for ext in ("*.py", "*.ts", "*.tsx"):
            for src_file in root.rglob(ext):
                line_count = len(src_file.read_text(encoding="utf-8").splitlines())
                assert line_count <= 300, (
                    f"Modularity violation: {src_file.relative_to(REPO_ROOT)} has "
                    f"{line_count} lines (max 300 allowed)."
                )
