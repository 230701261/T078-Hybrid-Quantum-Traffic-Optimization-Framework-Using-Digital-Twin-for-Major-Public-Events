"""Request validation helpers shared by API handlers and tests."""

import re


MESSAGE_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def validate_message_id(value):
    if not isinstance(value, str) or MESSAGE_ID_RE.fullmatch(value) is None:
        raise ValueError("message_id is required and must be 1-128 safe ASCII characters")
    return value
