"""
title: ✿ Petal Tool Traces
author: Lily · the Pink Witch
description: after every reply, tucks the tools Petal truly touched into one quiet source pastille — expand it to see each call (arguments + what came back). no chip = no tools. a reply that talks about a skill without opening one gets a ♡ pastille instead. traces live in the message's sources: you see them, she never re-reads them.
version: 0.2.0
"""

import json
import re
from typing import Optional

from pydantic import BaseModel, Field


def _text(parts) -> str:
    """function_call_output.output → plain text (list of parts, a string, or anything json-able)."""
    if parts is None:
        return ""
    if isinstance(parts, str):
        return parts
    if isinstance(parts, list):
        out = []
        for p in parts:
            if isinstance(p, dict):
                out.append(p.get("text") or p.get("content") or json.dumps(p, ensure_ascii=False))
            else:
                out.append(str(p))
        return "\n".join(out)
    return json.dumps(parts, ensure_ascii=False)


def _args(raw) -> str:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return json.dumps(parsed, ensure_ascii=False, indent=2) if parsed else "{}"
    except Exception:
        return str(raw or "{}")


def _short_args(raw) -> str:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if isinstance(parsed, dict) and parsed:
            return ", ".join(f"{k}={str(v)[:40]}" for k, v in parsed.items())
    except Exception:
        pass
    return ""


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=99, description="run late, after other outlet filters")
        chip_when_none: bool = Field(default=False, description="add a ◦ pastille even when she touched no tools (off: no chip = no tools)")
        flag_skill_mimicry: bool = Field(default=True, description="flag replies that talk about a skill without opening one")
        max_result_chars: int = Field(default=6000, description="how much of each tool result to keep in the chip")

    def __init__(self):
        self.valves = self.Valves()

    async def outlet(self, body: dict, __event_emitter__=None, __user__: Optional[dict] = None) -> dict:
        if not __event_emitter__:
            return body
        messages = body.get("messages") or []
        target_id = body.get("id")
        msg = next((m for m in reversed(messages) if m.get("id") == target_id), None) or next(
            (m for m in reversed(messages) if m.get("role") == "assistant"), None
        )
        if not msg:
            return body

        calls, results = [], {}
        for item in msg.get("output") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                calls.append(item)
            elif item.get("type") == "function_call_output":
                results[item.get("call_id")] = item

        async def chip(name: str, text: str):
            await __event_emitter__({"type": "source", "data": {
                "source": {"name": name},
                "document": [text],
                "metadata": [{"source": name, "name": name}],
            }})

        if not calls:
            content = msg.get("content") or ""
            if self.valves.flag_skill_mimicry and re.search(r"\bskills?\b", content, re.I):
                await chip("♡ skill spoken · none opened",
                           "she spoke of a skill in this reply without calling view_skill —\n"
                           "she answered from the skill's one-line summary alone.")
            elif self.valves.chip_when_none:
                await chip("◦ no tools", "no tools touched · answered from what she already held.")
            return body

        sections, labels = [], []
        for n, c in enumerate(calls, 1):
            name = c.get("name") or "?"
            res = results.get(c.get("call_id") or c.get("id"))
            ok = res is not None and res.get("status") not in ("incomplete", "failed")
            mark = "✓" if ok else ("✗" if res else "…")
            short = _short_args(c.get("arguments"))
            labels.append(name)
            result_txt = _text(res.get("output")) if res else "— no result recorded —"
            if len(result_txt) > self.valves.max_result_chars:
                result_txt = result_txt[: self.valves.max_result_chars] + f"\n… (+{len(result_txt) - self.valves.max_result_chars} chars)"
            sections.append(
                f"── {n} · {name} {mark}" + (f"  ({short})" if short else "") +
                f"\n\narguments\n{_args(c.get('arguments'))}\n\nresult\n{result_txt}"
            )

        lead = "✿" if any(c.get("name") == "view_skill" for c in calls) else "🔧"
        uniq = list(dict.fromkeys(labels))
        title = f"{lead} " + (uniq[0] if len(uniq) == 1 else f"{len(calls)} tools")
        await chip(title, "\n\n".join(sections))
        return body
