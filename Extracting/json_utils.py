"""
json_utils.py

Shared helper for parsing Gemini's JSON responses.

Even with response_mime_type="application/json", Gemini can occasionally
still wrap the answer in ```json ... ``` fences, or append trailing
commentary/whitespace/a second object after the real one -- any of which
makes a bare json.loads(response.text) fail with something like:
    "Extra data: line 49 column 1 (char 1386)"
That error specifically means json.loads found one complete, valid JSON
value and then hit more (non-whitespace) text after it -- it's not a sign
the JSON itself is malformed, just that there's extra content around it.

parse_json_response() strips fences and, if anything is still left over,
falls back to slicing out the first balanced {...} / [...] span before
parsing -- so a well-formed JSON object survives being wrapped in fences
or followed by stray text.

As a LAST resort, if the payload is a top-level JSON ARRAY (used for the
lab-topics list -- see Extracting/PD_Extractor.generate_lab_syllabus_json_from_pdf)
and it's still unparseable at that point -- most commonly because the
model's response got cut off mid-array before the closing ']' -- it
salvages every COMPLETE "string" entry that appears before the cutoff
and returns those as a valid (if possibly shorter) array, rather than
failing the whole run over a dropped closing bracket. This repair only
ever applies to array payloads; object payloads (the unit/topic
skeleton) still raise as before, since there's no safe way to guess
which nested fields were lost.
"""

import json
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_STRING_LITERAL_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = _FENCE_RE.sub("", text).strip()
    return text


def _slice_balanced(text: str) -> str:
    """Returns the substring from the first '{' or '[' to its matching
    closing bracket, tracking string/escape state so brackets inside
    string values don't confuse the count. Falls back to the original
    text if no opening bracket is found."""
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        return text

    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]  # unbalanced -- return what we have, let json.loads report the real error


def _repair_truncated_string_array(text: str):
    """
    Best-effort recovery for a top-level JSON array OF STRINGS that got
    cut off before its closing ']' (e.g. the model hit a length limit
    mid-response). Pulls out every syntactically-complete "..." string
    literal in `text` (handling \\" escapes) and rebuilds a valid,
    possibly-shorter array from just those -- dropping only whatever
    trailed off unfinished at the very end.

    Returns None (never raises) if `text` doesn't even look like it was
    meant to be an array, or if no complete string literal could be
    found at all, so the caller can fall through to the original error.
    """
    stripped = text.strip()
    if not stripped.startswith("["):
        return None
    items = _STRING_LITERAL_RE.findall(stripped)
    if not items:
        return None
    return "[" + ",".join(items) + "]"


def parse_json_response(text: str):
    """
    Parses a Gemini response's .text into Python data, tolerating Markdown
    code fences and/or trailing extra content around the JSON payload,
    and -- for array-of-strings payloads specifically -- a response that
    got cut off before its closing bracket (see
    _repair_truncated_string_array). Raises json.JSONDecodeError (with the
    ORIGINAL text in the message) if nothing usable can be salvaged, so
    callers can still surface a clear error.
    """
    cleaned = _strip_fences(text or "")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        sliced = _slice_balanced(cleaned)
        try:
            return json.loads(sliced)
        except json.JSONDecodeError as e:
            repaired = _repair_truncated_string_array(sliced)
            if repaired is not None:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass
            raise json.JSONDecodeError(
                f"{e.msg} (even after stripping fences/extra data/attempting array repair) "
                f"-- raw response was: {text[:1500]!r}",
                e.doc,
                e.pos,
            )
