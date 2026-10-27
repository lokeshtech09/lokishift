"""Keep API keys out of everything that leaves the process: logs and responses.

``scrub_secrets`` redacts key-like text. ``install_log_redaction`` applies it
to every log record (message and traceback), whichever library logs it, so a
provider error such as "Incorrect API key provided: sk-proj-..." never reaches
a log file or the console intact.
"""

import logging
import re
import traceback

# Regex for provider-style API-key tokens that may appear in upstream error
# messages (OpenAI / Anthropic / OpenRouter / DeepSeek all use ``sk-...``;
# Google AI Studio uses ``AIza...``). The OpenAI client already partially
# masks keys in its error text but leaves the first ~8 and last ~4 chars
# visible, which is enough to identify the provider and correlate with the
# user's stored key. We redact any remaining key-like run before we surface
# the message to the client via ``error_detail``.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # sk-<anything-non-whitespace>, covering both plain and already-masked
    # tokens (e.g., ``sk-ant-a****...7QAA``). Minimum length of 12 avoids
    # matching harmless substrings like ``sk-foo``.
    re.compile(r"sk-[A-Za-z0-9_\-*.]{12,}"),
    # Google AI Studio.
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    # Generic Bearer tokens in an Authorization header line.
    re.compile(r"(?i)(Bearer\s+)[^\s\"']+"),
    # Azure sends its key in a bare ``api-key:`` header and the value is a plain
    # 32-84 char alphanumeric, so it matches none of the patterns above. M-08.
    re.compile(r"(?i)(api[-_]?key[\"'\s:=]+)[^\s\"',}]+"),
)


def scrub_secrets(text: str) -> str:
    """Redact API-key-like substrings."""
    if not text:
        return text
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda m: m.group(1) + "<redacted>", redacted)
        else:
            redacted = pattern.sub("<redacted>", redacted)
    return redacted


def _scrub_args(args: object) -> object:
    """Scrub each log argument; ``None`` when the arguments aren't a tuple/dict."""

    def one(value: object) -> object:
        text = value if isinstance(value, str) else str(value)
        cleaned = scrub_secrets(text)
        return cleaned if cleaned != text else value

    if isinstance(args, tuple):
        return tuple(one(a) for a in args)
    if isinstance(args, dict):
        return {k: one(v) for k, v in args.items()}
    return None


_installed = False


def install_log_redaction() -> None:
    """Scrub every log record at creation time (idempotent)."""
    global _installed
    if _installed:
        return
    _installed = True
    base_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = base_factory(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # malformed format args: leave the record alone
            return record
        clean = scrub_secrets(message)
        if clean != message:
            # Prefer scrubbing the arguments in place: some formatters (uvicorn's
            # access log) unpack ``args`` themselves. Otherwise flatten.
            scrubbed = _scrub_args(record.args)
            try:
                in_place = scrubbed is not None and scrub_secrets(record.msg % scrubbed) == clean
            except Exception:
                in_place = False
            if in_place and isinstance(record.msg, str) and scrub_secrets(record.msg) == record.msg:
                record.args = scrubbed
            else:
                record.msg, record.args = clean, ()
        if record.exc_info and record.exc_info[0] is not None:
            # Handlers print exc_text instead of re-formatting exc_info.
            record.exc_text = scrub_secrets("".join(traceback.format_exception(*record.exc_info)).rstrip())
        return record

    logging.setLogRecordFactory(factory)
