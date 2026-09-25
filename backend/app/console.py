from __future__ import annotations

import sys


def configure_console() -> None:
    """Prevent CLI reports from crashing on Windows code pages with missing glyphs."""
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # Some wrappers (such as test capture streams) cannot be reconfigured.
            pass
