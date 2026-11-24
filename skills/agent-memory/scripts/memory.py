#!/usr/bin/env python3
"""Recall and record shared memory for this run.

When the deployment gives the run both a memory endpoint and a scoped token,
facts live in the shared service and survive the sandbox. Without them, the
skill falls back to AGENTS.md in the workspace, as it always has.

Run from the workspace root:
  python3 <skill-dir>/scripts/memory.py mode
  python3 <skill-dir>/scripts/memory.py recall
  python3 <skill-dir>/scripts/memory.py remember --fact "<one fact>"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

from idempotency import TokenError, build_key, claims_from_token

API_URL_ENV = "MEMORY_API_URL"
TOKEN_ENV = "MEMORY_TOKEN"
CURL = "/usr/bin/curl"
TIMEOUT_SECONDS = 20
STATUS_MARKER = "\n__MEMORY_STATUS__"
MEMORY_CONTEXT_OPEN = "<MEMORY_CONTEXT>"
MEMORY_CONTEXT_CLOSE = "</MEMORY_CONTEXT>"


class MemoryError(RuntimeError):
    """The service did not answer with usable memory."""


def _settings() -> tuple[str, str]:
    return os.environ.get(API_URL_ENV, "").strip(), os.environ.get(TOKEN_ENV, "").strip()


def configured() -> bool:
    """The shared store is used only when both settings are non-empty."""
    api_url, token = _settings()
    return bool(api_url and token)


def mode() -> str:
    return "network" if configured() else "file"


def _base_url(api_url: str) -> str:
    if not api_url.startswith(("http://", "https://")):
        raise MemoryError("the memory endpoint is not an http(s) URL")
    return api_url.rstrip("/")


def _index_url(api_url: str, namespace: str) -> str:
    return f"{_base_url(api_url)}/v1/namespaces/{quote(namespace, safe='')}/index"


def _entries_url(api_url: str, namespace: str) -> str:
    return f"{_base_url(api_url)}/v1/namespaces/{quote(namespace, safe='')}/entries"


def _source(claims: dict[str, object]) -> str:
    return f"{claims['automation_id']}/{claims['run_id']}"


def _curl(
    method: str,
    url: str,
    token: str,
    *,
    headers: Sequence[str] = (),
    payload: str | None = None,
) -> tuple[int, str]:
    """Call the service with an argument list, never a composed shell string."""
    command = [
        CURL,
        "--silent",
        "--show-error",
        "--max-time",
        str(TIMEOUT_SECONDS),
        "--request",
        method,
        "--url",
        url,
        "--header",
        f"Authorization: Bearer {token}",
        "--header",
        "Accept: application/json",
        "--write-out",
        f"{STATUS_MARKER}%{{http_code}}",
    ]
    for header in headers:
        command.extend(["--header", header])
    if payload is not None:
        command.extend(["--header", "Content-Type: application/json", "--data-binary", "@-"])

    try:
        result = subprocess.run(
            command,
            input=payload,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS + 5,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MemoryError("the memory service is unreachable") from error
    if result.returncode != 0:
        raise MemoryError("the memory service is unreachable")

    body, _, status = result.stdout.rpartition(STATUS_MARKER)
    if not status.isdigit():
        raise MemoryError("the memory service answered an unreadable response")
    return int(status), body


def _detail(body: str) -> str:
    try:
        payload = json.loads(body)
    except ValueError:
        return "the service gave no reason"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return detail if isinstance(detail, str) and detail else "the service gave no reason"


def _agents_md() -> Path:
    return Path.cwd() / "AGENTS.md"


def _recall_file() -> int:
    path = _agents_md()
    if path.is_file():
        print(path.read_text(encoding="utf-8").rstrip())
    return 0


def recall() -> int:
    """Print the budgeted index inside the outer memory section, or nothing."""
    api_url, token = _settings()
    if not configured():
        return _recall_file()

    try:
        claims = claims_from_token(token)
        status, body = _curl("GET", _index_url(api_url, str(claims["namespace"])), token)
        if status != 200:
            raise MemoryError(f"the memory service answered {status}")
        payload = json.loads(body)
        block = payload.get("block") if isinstance(payload, dict) else None
        if not isinstance(block, str):
            raise MemoryError("the memory service response has no index block")
    except (MemoryError, TokenError, ValueError) as error:
        # Memory is an aid, never a precondition for the task.
        print(f"warning: memory is unavailable: {error}", file=sys.stderr)
        return 0

    if block.strip():
        print(f"{MEMORY_CONTEXT_OPEN}\n{block}\n{MEMORY_CONTEXT_CLOSE}")
    return 0


def _remember_file(fact: str) -> int:
    path = _agents_md()
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + f"- {fact}\n", encoding="utf-8")
    print(f"Appended the fact to {path}.")
    return 0


def remember(fact: str) -> int:
    """Store one fact in the configured store."""
    fact = fact.strip()
    if not fact:
        print("error: the fact is empty", file=sys.stderr)
        return 1
    if not configured():
        return _remember_file(fact)

    api_url, token = _settings()
    try:
        claims = claims_from_token(token)
        source = _source(claims)
        key = build_key(claims, fact)
        status, body = _curl(
            "POST",
            _entries_url(api_url, str(claims["namespace"])),
            token,
            headers=(f"Idempotency-Key: {key}",),
            payload=json.dumps({"source": source, "content": fact}),
        )
    except (MemoryError, TokenError) as error:
        print(f"error: the fact was not stored: {error}", file=sys.stderr)
        return 1

    if status == 201:
        try:
            entry_id = json.loads(body).get("id")
        except ValueError:
            entry_id = None
        label = f" {entry_id}" if isinstance(entry_id, int) else ""
        print(f"Stored memory entry{label} from {source}.")
        return 0
    if status == 422:
        print(
            f"error: the memory service refused the entry: {_detail(body)}",
            file=sys.stderr,
        )
    elif status == 409:
        print(
            "error: the memory service is still storing this fact; retry the call",
            file=sys.stderr,
        )
    else:
        print(
            f"error: the fact was not stored ({status}): {_detail(body)}",
            file=sys.stderr,
        )
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read and write this run's shared memory.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("mode", help="print network or file")
    commands.add_parser("recall", help="print remembered knowledge")
    remember_parser = commands.add_parser("remember", help="store one fact")
    remember_parser.add_argument("--fact", required=True)

    args = parser.parse_args(argv)
    if args.command == "mode":
        print(mode())
        return 0
    if args.command == "recall":
        return recall()
    return remember(args.fact)


if __name__ == "__main__":
    sys.exit(main())