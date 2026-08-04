"""Type-specialized readiness rubrics — multiagent_v2.

v1 lost to the single-agent baseline by 4.5 pts, concentrated in feature (51.3%)
and question (47.1%). Diagnosis: those workers were too LENIENT. needs_info
recall fell 0.53 -> 0.43 -- the workers waved through vague requests that
maintainers flagged. v2 raises the bar on feature/question toward what the
maintainer labels actually reward. bug/docs largely unchanged (bug held at 68.6%).
"""

CLASSIFIER_SYSTEM = """Classify this GitHub issue into exactly one type.

- "bug": something is broken, errors, crashes, wrong behavior.
- "feature": a request for new or changed functionality.
- "documentation": docs are wrong, missing, or unclear.
- "question": asking how to do something, or for help understanding.

If an issue reports something not working, prefer "bug" even if phrased as a question.
Respond with ONLY JSON: {"type": "bug"|"feature"|"documentation"|"question"}"""

_WORKERS = {
    "bug": """You are triaging a BUG report. Could a maintainer start investigating from what is written, or must they ask for more first?

Actionable when it gives enough to reproduce or locate the problem: what was done, what went wrong (error text or a clear symptom), and — when behavior is environment-dependent — version/environment. Vague about the symptom, or missing reproduction details for an environment-specific failure -> needs_info.

Do NOT over-demand: if the symptom is clear and reproducible from the description alone, missing version numbers may be fine.

Respond ONLY JSON: {"verdict":"actionable"|"needs_info","reason":"<one sentence>"}""",

    # RAISED BAR: maintainers flag vague feature requests as needs_info.
    "feature": """You are triaging a FEATURE request. Could a maintainer act on it as written, or would they have to ask the author to clarify first?

Be demanding. Actionable requires a CONCRETE, specific proposal: what exactly should change, and ideally why or in what scenario. A maintainer should be able to scope the work from the description alone.

needs_info when the request is vague, high-level, or under-specified — "it would be nice to support X", "please add better Y", a broad wish with no concrete behavior, or a proposal missing the detail a maintainer would need to act. When in doubt about whether the desired behavior is specific enough to implement, choose needs_info.

Respond ONLY JSON: {"verdict":"actionable"|"needs_info","reason":"<one sentence>"}""",

    "documentation": """You are triaging a DOCUMENTATION issue. Could a maintainer act on it, or must they ask first?

Actionable when it identifies what is wrong/missing and roughly where — a maintainer can usually verify directly. Does NOT need code or version info. needs_info only when too vague to locate what needs fixing.

Respond ONLY JSON: {"verdict":"actionable"|"needs_info","reason":"<one sentence>"}""",

    # RAISED BAR: maintainers flag context-thin questions as needs_info.
    "question": """You are triaging a QUESTION / how-to issue. Could a maintainer give a real answer as written, or would they first have to ask the author for more context?

Be demanding. Actionable requires enough context to actually answer: what the author is trying to achieve, what they already tried, and their relevant setup when it matters. A well-formed, specific question a maintainer could answer directly is actionable.

needs_info when essential context is missing — a vague or overly broad question, no description of what was tried, or a problem statement too thin to answer without a follow-up. When the maintainer's realistic first response would be a clarifying question, choose needs_info.

Respond ONLY JSON: {"verdict":"actionable"|"needs_info","reason":"<one sentence>"}""",
}

def worker_system(issue_type: str) -> str:
    return _WORKERS.get(issue_type, _WORKERS["bug"])

RUBRIC_VERSION = "multiagent_v2"
