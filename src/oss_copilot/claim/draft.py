"""Draft a claim comment. Conservative by default: offer to help and ask to be
pointed at the code — asserting NO specific fix, so there's nothing to verify
before posting. Pass name_fix=True only for an issue you've actually looked at.
"""

from __future__ import annotations

import json
import os

from openai import OpenAI

MODEL = "deepseek-chat"

_CONSERVATIVE = """You write a brief, sincere comment for a newcomer offering to work on an open-source GitHub issue.

Rules:
- 2-3 sentences, plain and natural. No emoji, no hype, no timeline promises.
- Show you read it: reference the specific symptom/request in one concrete phrase.
- Offer to work on it and ask to be pointed at the relevant code or conventions.
- Do NOT propose a specific code-level fix or name files/functions you haven't verified.

Respond ONLY as JSON: {"comment": "<text>"}"""

_WITH_FIX = """You write a brief, sincere comment for a contributor offering to work on an open-source GitHub issue, who HAS looked at the code.

Rules:
- 2-4 sentences, plain and natural. No emoji, no hype, no timeline promises.
- Show understanding: reference the specific mechanism/cause.
- You MAY state a concrete intended fix, but frame it as a proposal ("I'd add..."), not a certainty.
- End by asking about tests or conventions so the PR matches the project.

Respond ONLY as JSON: {"comment": "<text>"}"""


def _client() -> OpenAI:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set.")
    return OpenAI(api_key=key, base_url="https://api.deepseek.com")


def draft_comment(title: str, body: str, name_fix: bool = False) -> dict:
    body = (body or "")[:4000]
    system = _WITH_FIX if name_fix else _CONSERVATIVE
    try:
        resp = _client().chat.completions.create(
            model=MODEL, temperature=0.4,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": f"TITLE: {title}\n\nBODY:\n{body}"}],
            response_format={"type": "json_object"},
        )
        c = json.loads(resp.choices[0].message.content).get("comment", "").strip()
        return {"comment": c} if c else {"error": "empty draft"}
    except Exception as e:
        return {"error": str(e)}