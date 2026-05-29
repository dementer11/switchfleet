from __future__ import annotations

import difflib


def unified_diff(before: str, after: str, fromfile: str = "before", tofile: str = "after") -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )

