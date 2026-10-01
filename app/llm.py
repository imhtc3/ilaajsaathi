"""Optional LLM layer (stdlib only, no SDK needed).

Set ONE of:
  ANTHROPIC_API_KEY            -> uses Claude (LLM_MODEL, default claude-sonnet-4-6)
  OPENAI_API_KEY (+ OPENAI_BASE_URL) -> any OpenAI-compatible API (OpenAI, Groq, Gemini, etc.)

With no key the agent still works end to end using rule-based understanding,
so the demo never breaks because of an API outage.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

TIMEOUT = 40


def provider() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def _post(url: str, headers: dict, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def complete(system: str, user: str, image_b64: str | None = None, image_type: str = "image/jpeg",
             max_tokens: int = 1200) -> str | None:
    p = provider()
    if not p:
        return None
    try:
        if p == "anthropic":
            content = [{"type": "text", "text": user}]
            if image_b64:
                content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": image_type, "data": image_b64}})
            data = _post(
                "https://api.anthropic.com/v1/messages",
                {"content-type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01"},
                {"model": os.environ.get("LLM_MODEL", "claude-sonnet-4-6"), "max_tokens": max_tokens,
                 "system": system, "messages": [{"role": "user", "content": content}]},
            )
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        content = [{"type": "text", "text": user}]
        if image_b64:
            content.append({"type": "image_url", "image_url": {"url": f"data:{image_type};base64,{image_b64}"}})
        data = _post(
            f"{base}/chat/completions",
            {"content-type": "application/json", "authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            {"model": os.environ.get("LLM_MODEL", "gpt-4o-mini"), "max_tokens": max_tokens,
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]},
        )
        return data["choices"][0]["message"]["content"]
    except Exception as e:  # never let the LLM take the demo down
        print(f"[llm] {p} call failed: {e}")
        return None


def complete_json(system: str, user: str, **kw) -> dict | None:
    text = complete(system + "\nRespond with ONLY a JSON object. No markdown, no commentary.", user, **kw)
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
