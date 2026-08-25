"""
gemini_retry.py

Small shared retry wrapper for calls to client.models.generate_content().

The Gemini API occasionally returns a transient server-side error --
503 UNAVAILABLE / "Deadline expired before operation could complete",
429 RESOURCE_EXHAUSTED (rate limiting), or a plain socket timeout -- that
has nothing to do with the request itself and clears up if you just try
again a moment later. Without a retry, any one of those turns into a
"couldn't parse the syllabus" failure the user has to notice and manually
re-trigger.

call_with_retry() retries ONLY on that class of transient error, with a
short exponential backoff, and lets everything else (bad prompt, invalid
response, auth failure, etc.) raise immediately as before.
"""
import time
from typing import Callable, TypeVar

T = TypeVar("T")

# Substrings that identify a TRANSIENT, worth-retrying failure. Matched
# case-insensitively against str(exception) since the google-genai SDK
# raises plain exceptions carrying the HTTP status/message as text rather
# than a small set of typed exception classes we could catch by type alone.
_TRANSIENT_MARKERS = (
    "503",
    "UNAVAILABLE",
    "DEADLINE",
    "429",
    "RESOURCE_EXHAUSTED",
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
)


def _is_transient(exc: Exception) -> bool:
    text = str(exc).upper()
    return any(marker.upper() in text for marker in _TRANSIENT_MARKERS)


def call_with_retry(
    fn: Callable[[], T],
    attempts: int = 3,
    initial_delay: float = 2.0,
    backoff: float = 2.0,
) -> T:
    """
    Calls `fn()` (a zero-arg callable, typically a small lambda wrapping
    client.models.generate_content(...)) and retries it on a transient
    error, waiting `initial_delay` seconds before the first retry and
    multiplying the wait by `backoff` each time after that. Re-raises the
    last exception once `attempts` is exhausted, or immediately for any
    error that doesn't look transient (see _is_transient).
    """
    delay = initial_delay
    last_exc: Exception = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            is_last = attempt == attempts
            if is_last or not _is_transient(e):
                raise
            print(
                f"\u26a0\ufe0f Gemini call hit a transient error "
                f"(attempt {attempt}/{attempts}): {e} -- retrying in {delay:g}s\u2026"
            )
            time.sleep(delay)
            delay *= backoff
    raise last_exc  # pragma: no cover -- loop always returns or raises above
