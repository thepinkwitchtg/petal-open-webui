"""
title: 🌸 petal · hush glass
author: lily & claude
description: total transparency for the pin — under every reply that answered a whisper, a source chip shows exactly the note Petal was given (the line you answered + its glow, lingers, device, presence), read from the private pin record and checked against her actual system prompt.
version: 0.2
required_open_webui_version: 0.12.0
"""

# install: Admin Panel → Functions → + → paste this file → save → turn it ON and set it Global
# (the ⋯ menu → Global), so every model gets the glass without touching each one.
#
# what it does, and doesn't:
#   · reads data/petal/hush-pins.jsonl (written by /petal_hush/pin, private, git-ignored)
#     for the record keyed to THIS reply's id — the exact note that was rendered
#   · checks that note really sits in the system message she's about to receive
#   · emits one source chip on the reply: click it → the note, word for word
#   · never changes the request — it only looks
#   · the chip is saved on the reply (like any source) and is never fed back to her
#     in later turns (0.12 replays only id/role/content/output/files/... — not sources)

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from open_webui.env import DATA_DIR

PINS = Path(DATA_DIR) / 'petal' / 'hush-pins.jsonl'
TAIL_BYTES = 256 * 1024  # the newest pins are at the end — never read the whole garden


def _find_pin(message_id: str) -> Optional[dict]:
    """the newest record whose message_ids hold this reply id (tail-read only)."""
    try:
        with open(PINS, 'rb') as f:
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


def _system_text(messages) -> str:
    if not messages or messages[0].get('role') != 'system':
        return ''
    content = messages[0].get('content')
    if isinstance(content, list):
        return '\n'.join(str(c.get('text', '')) for c in content if isinstance(c, dict))
    return content if isinstance(content, str) else ''


class Filter:
    class Valves(BaseModel):
        chip_name: str = Field(default='🌸 the whisper she answered', description='the source chip label')
        show_numbers: bool = Field(
            default=True, description='add a line under the note with the raw numbers sent with it'
        )

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, __metadata__: Optional[dict] = None, __event_emitter__=None) -> dict:
        try:
            message_id = (__metadata__ or {}).get('message_id')
            tag = f'…{str(message_id)[-6:]}' if message_id else '(no id)'
            if not message_id or not __event_emitter__:
                print(f'🌸 hush glass: reply {tag} · no reply id or no event emitter — nothing to show')
                return body
            rec = _find_pin(str(message_id))
            if not rec or not rec.get('note'):
                # no whisper answered on this send — no chip. (pins file present? that tells regen vs. not deployed)
                print(f'🌸 hush glass: reply {tag} · no pin recorded for it · pins file {"found" if PINS.exists() else "missing"} at {PINS}')
                return body

            note = rec['note']
            delivered = note in _system_text(body.get('messages') or [])
            where = (
                'at the bottom of her system message, under her persona, above your memories'
                if delivered
                else '⚠ recorded, but NOT found in the system message she is receiving'
            )
            doc = note
            if self.valves.show_numbers:
                doc += (
                    '\n\n── sent with ──\n'
                    f"kind {rec.get('kind')} · from {rec.get('origin')} · glowed {rec.get('waited_seconds')}s"
                    f" · wrote {rec.get('wrote_seconds')}s · {rec.get('linger_count')} rewrites"
                    f" · stillest {rec.get('stillest_seconds')}s · presence {rec.get('presence')}%"
                    f" · {rec.get('device')} · lens {rec.get('lens')}\n"
                    f'placed {where}'
                )
            print(f'🌸 hush glass: reply {tag} · chip shown · {len(note)} chars · ' + ('delivered' if delivered else 'NOT in her system message'))
            await __event_emitter__(
                {
                    'type': 'source',
                    'data': {
                        'source': {'name': self.valves.chip_name, 'id': f'petal-hush-pin-{message_id}'},
                        'document': [doc],
                        'metadata': [
                            {
                                # 0.12 groups chips by metadata.source and labels them with metadata.name
                                'source': f'petal-hush-pin-{message_id}',
                                'name': f"{self.valves.chip_name} · {rec.get('kind')}"
                                + ('' if delivered else ' · ⚠ not delivered'),
                            }
                        ],
                    },
                }
            )
        except Exception as e:  # the glass never breaks a message
            print(f'🌸 hush glass: {e!r}')
        return body
