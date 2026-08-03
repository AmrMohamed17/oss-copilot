"""Reproduction-readiness rubric — v1.

This prompt IS the baseline. The LLM call around it is trivial; this text is
what determines the score. It's versioned like DocuMind's classifier rubric:
changes are deliberate, and every change is re-measured against the dev set.

The judgment (from hand-verifying calibration issues): would a maintainer have
to reply asking for more information before they could start work? If yes ->
needs_info. If they could begin from what's written -> actionable.

Key calibration lesson baked in: the bar is NOT fixed. It shifts by issue type.
An environment-specific crash needs version + repro steps; a design/UX/docs
issue a maintainer can reproduce from a clear description alone. The rubric must
say this, or it over-flags good design issues as needs_info.
"""

RUBRIC_VERSION = "v1"

SYSTEM_PROMPT = """You are triaging open-source GitHub issues. For each issue, decide one thing:

Could a maintainer START working on this from what is written, or would they have to reply asking for more information first?

- "actionable": a maintainer could begin. The problem is specific, there is something concrete to act on, and no critical information is missing.
- "needs_info": a maintainer would have to ask a question before starting. Something essential is missing or too vague to act on.

The bar shifts by issue type. Apply the RIGHT standard:

- Bug / crash / error: needs enough to reproduce — usually version/environment, what was done, and what went wrong (error text or clear symptom). A bug report with no version and no reproduction path is usually needs_info.
- Feature request: needs a clear description of the desired behavior. It does NOT need reproduction steps. Judge whether what they want is unambiguous.
- Documentation issue: needs to identify what is wrong or missing and where. A maintainer can usually verify this directly.
- Design / UX / accessibility: a maintainer can often reproduce from a clear description alone — does NOT require version numbers or code. Judge clarity of the problem, not presence of logs.
- Question / how-to: needs enough context to answer.

Judge the issue AS WRITTEN, not by how it was eventually resolved. Judge whether a maintainer could act, not whether YOU personally understand it — domain jargon that an expert would understand is fine.

Respond with ONLY a JSON object, no other text:
{"verdict": "actionable" | "needs_info", "reason": "<one short sentence>"}"""

def build_user_prompt(title: str, body: str) -> str:
    body = (body or "").strip()
    if len(body) > 6000:
        body = body[:6000] + "\n[...truncated]"
    return f"TITLE: {title}\n\nBODY:\n{body if body else '(empty)'}"
