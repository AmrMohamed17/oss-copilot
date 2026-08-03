"""The baseline judge: one LLM call, no orchestration. This is the reference
Phase 3's multi-agent version must beat."""

from __future__ import annotations

import json
import os

from openai import OpenAI   # DeepSeek is OpenAI-API-compatible

from .rubric import SYSTEM_PROMPT, build_user_prompt, RUBRIC_VERSION

MODEL = "deepseek-chat"


def _client() -> OpenAI:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set.")
    return OpenAI(api_key=key, base_url="https://api.deepseek.com")


def judge_issue(title: str, body: str) -> dict:
    """Return {'verdict','reason','rubric_version'} or {'error': ...}.

    Deterministic-leaning: temperature 0. JSON parsed defensively — a judge that
    returns malformed output is a measurable failure, not a crash."""
    try:
        resp = _client().chat.completions.create(
            model=MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(title, body)},
            ],
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        verdict = data.get("verdict", "").strip()
        if verdict not in ("actionable", "needs_info"):
            return {"error": f"invalid verdict: {verdict!r}", "raw": raw}
        return {
            "verdict": verdict,
            "reason": data.get("reason", "").strip(),
            "rubric_version": RUBRIC_VERSION,
        }
    except json.JSONDecodeError as e:
        return {"error": f"json parse failed: {e}"}
    except Exception as e:
        return {"error": f"api error: {e}"}
