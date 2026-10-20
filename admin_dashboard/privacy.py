"""Defense-in-depth browser payload sanitizer for the internal Admin surface."""
from __future__ import annotations

import re

_FORBIDDEN_KEYS = {
    "author", "content", "cookie", "authorization", "api_key", "token",
    "hmac_secret", "password", "raw_error", "wrangler_credential", "account_id",
    "filesystem_secret_path", "request_headers", "response_body", "subprocess_output",
}
_SENSITIVE_SUFFIXES = ("_secret", "_credential", "_token", "_password")
_LOCAL_PATH = re.compile(r"^(?:/(?:Users|home|private|var/folders|tmp)/|[A-Za-z]:[\\/])")


def sanitize_for_browser(value):
    """Drop browser-forbidden keys and replace local absolute filesystem paths.

    This does not establish producer trust; it is a final display boundary.
    Canonical evidence validation must happen before this function.
    """
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _FORBIDDEN_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES):
                continue
            result[key] = sanitize_for_browser(item)
        return result
    if isinstance(value, list):
        return [sanitize_for_browser(item) for item in value]
    if isinstance(value, str) and _LOCAL_PATH.match(value):
        return "[redacted-local-path]"
    return value
