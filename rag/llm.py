"""LLM backend: headless Claude Code on a Claude subscription.

Calls `claude -p` as a subprocess so generation runs on the signed-in plan
instead of per-token API billing. `--bare` is deliberately not used because it
skips the plan sign-in. Tools are disabled: the model only sees the context we
pass it, which is the point of a grounded RAG system.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time

CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
DEFAULT_MODEL = os.environ.get("COPILOT_MODEL", "sonnet")
USAGE_LIMIT_MARKERS = ("usage limit", "rate limit", "limit reached", "session limit", "hit your", "overloaded")


class LLMError(RuntimeError):
    pass


class UsageLimitError(LLMError):
    """The plan's usage window is exhausted; callers can park and resume later."""


def complete(prompt: str, system: str | None = None, model: str | None = None,
             retries: int = 2, timeout: int = 300) -> str:
    """Return the model's text reply to a single prompt."""
    cmd = [CLAUDE_BIN, "-p", "--output-format", "json", "--no-session-persistence", "--model", model or DEFAULT_MODEL,
           "--disallowedTools", "Bash,Edit,Write,Read,WebFetch,WebSearch,Glob,Grep,Task,NotebookEdit"]
    if system:
        cmd += ["--append-system-prompt", system]

    last_err = ""
    for attempt in range(retries + 1):
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
        out = proc.stdout.strip()
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            payload = None

        if proc.returncode == 0 and payload and not payload.get("is_error"):
            return payload.get("result", "")

        last_err = (payload or {}).get("result") or proc.stderr or out
        if any(m in last_err.lower() for m in USAGE_LIMIT_MARKERS):
            raise UsageLimitError(last_err.strip()[:300])
        time.sleep(2 * (attempt + 1))
    raise LLMError(f"claude -p failed: {last_err.strip()[:300]}")


def complete_json(prompt: str, system: str | None = None, **kw) -> dict:
    """Ask for a JSON object and parse it, tolerating ```json fences."""
    text = complete(prompt, system=system, **kw)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise LLMError(f"no JSON object in reply: {text[:200]}")
    return json.loads(match.group(0))
