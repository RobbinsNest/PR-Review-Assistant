"""Structured logging setup and secret redaction helpers."""

import logging
import re
import sys

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging with a timestamped, level-tagged format."""
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        stream=sys.stdout,
        force=True,
    )


def _mask(value: str, keep: int = 4) -> str:
    """Mask ``value`` to ``<first2>****<last4>`` while keeping a hint.

    Short values that cannot show both hints without revealing content are
    still masked in the middle, so a secret is never returned verbatim.
    """
    if len(value) <= keep:
        return "*" * len(value)
    middle = max(1, len(value) - 2 - keep)
    tail = len(value) - 2 - middle
    return f"{value[:2]}{'*' * middle}{value[-tail:] if tail > 0 else ''}"


def redact(text: str, *, secret: str | None = None, keep: int = 4) -> str:
    """Mask credentials so logs and error messages never leak secrets.

    Masks an explicit ``secret`` (e.g. an API key) as well as common
    ``sk-...`` and ``Bearer ...`` token patterns.
    """
    result = text
    if secret:
        result = result.replace(secret, _mask(secret, keep=keep))
    result = re.sub(
        r"(?i)\bsk-[a-z0-9_\-]{8,}\b",
        lambda m: _mask(m.group(0), keep=keep),
        result,
    )
    result = re.sub(
        r"(?i)(bearer\s+)[a-z0-9._\-]+",
        lambda m: m.group(1) + _mask(m.group(0).split(None, 1)[1], keep=keep),
        result,
    )
    return result
