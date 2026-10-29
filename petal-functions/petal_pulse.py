"""
title: 🌸 petal · pulse
author: lily & claude
description: how she wrote, riding with every message — when she began, how long she wrote, typed / pasted / erased / sent, pauses, emptied fields, time looked away. numbers measured by hush.js, rendered through petal-lenses/hush-pulse.txt, set at the bottom of Petal's system message, with a source chip showing the note word for word.
version: 0.1
required_open_webui_version: 0.12.0
"""

# install: Admin Panel → Functions → + → paste this file → save → turn it ON and set it Global
# (the ⋯ menu → Global), so every model gets the pulse without touching each one.
#
# what it does, and doesn't:
#   · reads data/petal/hush-pulse.jsonl (written by /petal_hush/pulse, private, git-ignored)
#     for the record keyed to THIS reply's id — the exact note that was rendered
#   · sets that note at the bottom of the system message she's about to receive
#     (below the pin when you answered a whisper; her persona lands above both)
#   · emits one source chip on the reply: click it → the note, word for word
#   · a regenerate or an edit carries no pulse (you didn't write anything new)
#   · the chip is saved on the reply like any source, and never fed back to her later
#   · filters run in order of their priority valve — lower runs first; raise this one's
#     priority if you want the pulse set after another filter's injection

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from open_webui.env import DATA_DIR

PULSE = Path(DATA_DIR) / 'petal' / 'hush-pulse.jsonl'
TAIL_BYTES = 256 * 1024  # the newest pulses are at the end — never read the whole garden


def _find_pulse(message_id: str) -> Optional[dict]:
    """the newest record whose message_ids hold this reply id (tail-read only)."""
    try:
        with open(PULSE, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode('utf-8', errors='ignore')
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        if message_id not in line:  # cheap check before parsing
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if isinstance(rec, dict) and message_id in (rec.get('message_ids') or []):
            return rec
    return None


def _set_in_system(messages: list, note: str) -> bool:
    """the note at the bottom of the system message; a chat with none gets one, just this.
    returns False if it was already there (never doubled)."""
    if messages and messages[0].get('role') == 'system':
        content = messages[0].get('content')
        if isinstance(content, list):
            if any(isinstance(c, dict) and note in str(c.get('text', '')) for c in content):
                return False
            content.append({'type': 'text', 'text': note})
            return True
        text = content if isinstance(content, str) else ''
        if note in text:
            return False
        messages[0]['content'] = f'{text}\n\n{note}' if text.strip() else note
        return True
    messages.insert(0, {'role': 'system', 'content': note})
    return True


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description='filter order — lower runs first')
        inject: bool = Field(default=True, description='set the pulse in her system message')
        chip: bool = Field(default=True, description='show the source chip under her reply')
        chip_name: str = Field(default='🌸 how she wrote', description='the source chip label')
        show_numbers: bool = Field(
            default=True, description='add a line under the note with the raw numbers recorded with it'
        )

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, __metadata__: Optional[dict] = None, __event_emitter__=None) -> dict:
        try:
            message_id = (__metadata__ or {}).get('message_id')
            tag = f'…{str(message_id)[-6:]}' if message_id else '(no id)'
            if not message_id:
                print(f'🌸 pulse: reply {tag} · no reply id — nothing to set')
                return body
            rec = _find_pulse(str(message_id))
            if not rec or not rec.get('note'):
                # regenerate / edit / nothing typed — or hush hasn't recorded (pulse file present?)
                print(f'🌸 pulse: reply {tag} · no pulse recorded for it · pulse file {"found" if PULSE.exists() else "missing"} at {PULSE}')
                return body

            note = rec['note']
            placed = 'not set (inject is off)'
            if self.valves.inject:
                messages = body.get('messages')
                if not isinstance(messages, list):
                    messages = body['messages'] = []
                placed = (
                    'at the bottom of her system message (below the pin, if one rode)'
                    if _set_in_system(messages, note)
                    else 'already in her system message — not doubled'
                )
            print(f'🌸 pulse: reply {tag} · {len(note)} chars · {placed}')

            if self.valves.chip and __event_emitter__:
                doc = note
                if self.valves.show_numbers:
                    doc += (
                        '\n\n── recorded with ──\n'
                        f"from {rec.get('anchor')} · began {rec.get('began_seconds')}s · wrote {rec.get('wrote_seconds')}s"
                        f" · typed {rec.get('typed_chars')} · pasted {rec.get('pasted_chars')}"
                        f" · erased {rec.get('deleted_chars')} · sent {rec.get('sent_chars')} ({rec.get('kept_percent')}% kept)"
                        f" · {rec.get('pauses')} pauses ≥{rec.get('pause_min_seconds')}s · longest {rec.get('longest_pause_seconds')}s"
                        f" · emptied {rec.get('emptied')}× · away {rec.get('away_seconds')}s"
                        f" · {rec.get('device')} · lens {rec.get('lens')}\n"
                        f'placed {placed}'
                    )
                await __event_emitter__(
                    {
                        'type': 'source',
                        'data': {
                            'source': {'name': self.valves.chip_name, 'id': f'petal-pulse-{message_id}'},
                            'document': [doc],
                            'metadata': [
                                {
                                    # 0.12 groups chips by metadata.source and labels them with metadata.name
                                    'source': f'petal-pulse-{message_id}',
                                    'name': self.valves.chip_name,
                                }
                            ],
                        },
                    }
                )
        except Exception as e:  # the pulse never breaks a message
            print(f'🌸 pulse: {e!r}')
        return body
