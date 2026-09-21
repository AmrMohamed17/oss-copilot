"""Format the day's qualifying issues into a readable digest."""

from __future__ import annotations

from datetime import date


def rank(items: list[dict]) -> list[dict]:
    """Signalled issues (good-first-issue / help-wanted) first, then newest."""
    return sorted(items, key=lambda x: (-len(x["signals"]), x.get("created_at", "")),
                  reverse=False if False else True)  # newest + most-signalled first


def render(items: list[dict], stats: dict) -> str:
    d = date.today().isoformat()
    lines = [f"# OSS digest — {d}", ""]
    lines.append(f"Scanned {stats['scanned']} new issues · "
                 f"{stats['surfaced']} surfaced · "
                 f"{stats['filtered']} filtered.")
    lines.append("")
    if not items:
        lines.append("_Nothing new worth surfacing today._")
        return "\n".join(lines)

    for it in rank(items):
        tag = f"  [{', '.join(it['signals'])}]" if it["signals"] else ""
        lines.append(f"## {it['repo']}#{it['number']}{tag}")
        lines.append(f"{it['title']}")
        lines.append(f"→ {it['url']}")
        if it.get("reason"):
            lines.append(f"_readiness: {it['reason']}_")
        lines.append("")
    return "\n".join(lines)