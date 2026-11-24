"""Deterministic write keys for the shared memory service.

The service replays a stored response for a repeated key, so the key must
describe the run and the fact, never a choice the model makes. The namespace
and run identity are read from the token, which is the only authority.
"""

from __future__ import annotations

import base64
import hashlib
import json

TOKEN_VERSION = "v1"


class TokenError(ValueError):
    """The token cannot be read as a scoped claim set."""


def claims_from_token(token: str) -> dict[str, object]:
    """Read the signed claim set without the secret.

    The payload is base64url JSON. A malformed or incomplete token raises,
    because a write key built from missing claims would be identical across
    unrelated runs.
    """
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        raise TokenError("the memory token is not a scoped claim set")

    payload = parts[1]
    try:
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(decoded)
    except (ValueError, TypeError) as error:
        raise TokenError("the memory token payload is not readable") from error

    if not isinstance(claims, dict):
        raise TokenError("the memory token payload is not a claim set")
    for name in ("namespace", "automation_id", "run_id"):
        if not isinstance(claims.get(name), str) or not claims[name]:
            raise TokenError(f"the memory token is missing {name}")
    if not isinstance(claims.get("exp"), int):
        raise TokenError("the memory token is missing exp")
    return claims


def fact_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_key(claims: dict[str, object], content: str) -> str:
    """The idempotency key for one fact in one run."""
    material = f"{claims['automation_id']}:{claims['run_id']}:{fact_hash(content)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()