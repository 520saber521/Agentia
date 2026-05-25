"""Shared helpers for protocol handling."""

import json


def normalize_to_list(to_value):
    """Normalize "to" field into a list of non-empty strings."""
    if isinstance(to_value, list):
        normalized = []
        for item in to_value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("to list must contain non-empty strings")
            normalized.append(item.strip())
        if not normalized:
            raise ValueError("to list must not be empty")
        return normalized
    if isinstance(to_value, str):
        parts = [part.strip() for part in to_value.split(",") if part.strip()]
        if not parts:
            raise ValueError("to string must contain at least one target")
        return parts
    raise TypeError("to must be a list of strings or a comma-separated string")


def encode_body(body):
    """Encode a dict body as a single-line JSON string or validate string input."""
    if body is None:
        return ""
    if isinstance(body, str):
        if "\n" in body or "\r" in body:
            raise ValueError("body must be single-line string")
        return body
    if isinstance(body, dict):
        encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        if "\n" in encoded or "\r" in encoded:
            raise ValueError("body must be single-line string")
        return encoded
    raise TypeError("body must be a dict or string")
