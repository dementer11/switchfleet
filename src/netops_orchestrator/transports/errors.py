from __future__ import annotations

import re


ERROR_PATTERNS = (
    r"^\s*% ?Error",
    r"^\s*% ?Invalid",
    r"^\s*% ?Incomplete",
    r"^\s*% ?Ambiguous",
    r"^\s*Invalid input",
    r"^\s*Invalid command",
    r"^\s*Invalid parameter",
    r"^\s*Error:",
    r"^\s*Wrong parameter found",
    r"^\s*Too many parameters",
    r"^\s*Ambiguous command",
    r"^\s*Incomplete command",
    r"^\s*Unrecognized command",
    r"^\s*Unrecognized command found",
    r"^\s*Bad command",
    r"^\s*Command not found",
    r"^\s*Unknown command",
    r"^\s*Syntax error",
    r"^\s*Command failed",
    r"^\s*Failed to",
)


def output_has_cli_error(output: str, extra_patterns: tuple[str, ...] = ()) -> bool:
    return any(re.search(pattern, output, re.IGNORECASE | re.MULTILINE) for pattern in ERROR_PATTERNS + extra_patterns)
