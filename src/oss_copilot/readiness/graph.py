"""LangGraph multi-agent readiness pipeline (Phase 3).

Topology:  START -> classify -> [deterministic route by type] -> {bug|feature|
           documentation|question} worker -> END

Design rules from the spec:
- Routing is DETERMINISTIC Python (route_by_type), not an LLM deciding edges.
- State is lean (only what nodes need).
- Iteration is capped by recursion_limit in Python, not by a prompt.
- Checkpointer is wired for durability; defaults to in-memory for batch scoring,
  swappable for Postgres in the Phase 4 watcher.
"""

from __future__ import annotations

import json
import os
from typing import TypedDict

from openai import OpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .type_rubrics import CLASSIFIER_SYSTEM, worker_system, RUBRIC_VERSION

MODEL = "deepseek-chat"


class State(TypedDict, total=False):
    title: str
    body: str
    issue_type: str          # set by classify
    verdict: str             # set by a worker
    reason: str
    error: str


def _client() -> OpenAI:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set.")
    return OpenAI(api_key=key, base_url="https://api.deepseek.com")


def _llm_json(system: str, user: str) -> dict:
    resp = _client().chat.completions.create(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


def _user_prompt(state: State) -> str:
    body = (state.get("body") or "").strip()
    if len(body) > 6000:
        body = body[:6000] + "\n[...truncated]"
    return f"TITLE: {state['title']}\n\nBODY:\n{body or '(empty)'}"


# ---- nodes ----
def classify_node(state: State) -> State:
    try:
        data = _llm_json(CLASSIFIER_SYSTEM, _user_prompt(state))
        t = data.get("type", "").strip().lower()
        if t not in ("bug", "feature", "documentation", "question"):
            t = "bug"          # safe default; bug has the strictest bar
        return {"issue_type": t}
    except Exception as e:
        return {"error": f"classify: {e}", "issue_type": "bug"}


def _worker(state: State) -> State:
    try:
        data = _llm_json(worker_system(state["issue_type"]), _user_prompt(state))
        v = data.get("verdict", "").strip()
        if v not in ("actionable", "needs_info"):
            return {"error": f"invalid verdict: {v!r}"}
        return {"verdict": v, "reason": data.get("reason", "").strip()}
    except Exception as e:
        return {"error": f"worker: {e}"}


def route_by_type(state: State) -> str:
    """Deterministic routing — pure Python, no LLM. The 'supervisor'."""
    return state.get("issue_type", "bug")


def build_graph():
    g = StateGraph(State)
    g.add_node("classify", classify_node)
    for t in ("bug", "feature", "documentation", "question"):
        g.add_node(t, _worker)
    g.add_edge(START, "classify")
    g.add_conditional_edges("classify", route_by_type,
                            {t: t for t in ("bug", "feature", "documentation", "question")})
    for t in ("bug", "feature", "documentation", "question"):
        g.add_edge(t, END)
    return g.compile(checkpointer=MemorySaver())


def judge_issue_multiagent(title: str, body: str) -> dict:
    """Run one issue through the graph. Mirrors the baseline's return shape so
    the two are scored identically."""
    graph = build_graph()
    try:
        out = graph.invoke(
            {"title": title, "body": body},
            config={"configurable": {"thread_id": "batch"}, "recursion_limit": 10},
        )
    except Exception as e:
        return {"error": f"graph: {e}"}
    if out.get("error") and not out.get("verdict"):
        return {"error": out["error"]}
    return {
        "verdict": out.get("verdict"),
        "reason": out.get("reason"),
        "issue_type": out.get("issue_type"),
        "rubric_version": RUBRIC_VERSION,
    }
