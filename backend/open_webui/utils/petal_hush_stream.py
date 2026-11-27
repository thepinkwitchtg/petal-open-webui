"""🌸 petal · hush stream (A47) · her whisper reaches the field as she writes it

hush's line used to arrive whole (`stream: False`) and the page replayed it at a typing pace, so a
finished line was animated instead of streamed. now the route streams her words as the model writes
them, and at every step it hands the page the part of the line that is already certain: the start of
exactly what `_petal_hush_clean` keeps from the whole answer. nothing she writes waits longer than it
takes to know it belongs to the line:

  · a <think> block holds until its </think> (her thinking is never shown)
  · blank lines and opening quotation marks before her words are dropped as they come
  · a possible label ('line:', 'whisper:', "here's …:") holds until it is known to be one (then
    dropped) or not; a line opening on "here" holds for its first 32 characters, where a label finds
    its colon (the rule can reach a later colon too: then the last word corrects the line, rarely)
  · closing quotes and stars hold until a letter follows them (a closing quote never flashes)
  · the end of the first line ends the whisper: the model is stopped there (a whisper is one line)
  · a line past max_chars / max_words is known to be too big the moment it passes: the route stops
    the model and asks once more, shorter, as it always did

this module only reads text: no network, no state between whispers.
"""

from __future__ import annotations

import json
import re
from typing import AsyncIterator

# the same rules as routers/tasks.py `_petal_hush_clean` (kept in step by the tests)
THINK = re.compile(r'<think>.*?</think>', re.S | re.I)
LABEL = re.compile(r"^(line|whisper|here'?s?[^:]*):\s*", re.I)
STRIP = '"“”\'‘’`*_ '
# str.splitlines() ends a line at any of these
NEWLINE = re.compile(r'[\n\r\v\f\x1c\x1d\x1e\x85  ]')
_TAGS = ('<think>', '</think>')
_LABEL_WORDS = ('line', 'whisper')


def _partial_tag_tail(text: str) -> int:
    """how many characters at the end of `text` could still grow into <think> or </think> (held)"""
    low = text[-9:].lower()
    for n in range(min(len(low), 8), 0, -1):
        tail = low[-n:]
        if any(t.startswith(tail) for t in _TAGS):
            return n
    return 0


HERE_HOLD = 32  # a label opening on "here" ("here's one:", "here is a line for you:") reaches its colon by then


def _maybe_label(line: str) -> bool:
    """could this unfinished first line still turn out to start with a label? (then it holds)"""
    low = line.lower()
    for word in _LABEL_WORDS:
        if word.startswith(low):  # 'wh', 'whisp', 'line' (its colon may be next)
            return True
    if 'here'.startswith(low):  # 'h', 'he', 'her'
        return True
    # "here's the line: …": held while a label could still reach its colon; past HERE_HOLD it shows (the rule can
    # still strip up to a later colon: the route's last word then carries the line as hush always cut it)
    return low.startswith('here') and len(low) <= HERE_HOLD


class LineCut:
    """feed it what the model writes, piece by piece; read `visible` after each piece

    visible: the part of the line already certain (a prefix of the final clean line, as a rule)
    done:    the first line has ended (a newline after her words): nothing more belongs to it
    over:    the line is already past max_chars or max_words: it can only be trimmed, never fit
    """

    def __init__(self, max_chars: int = 72, max_words: int = 14):
        self.max_chars = max_chars
        self.max_words = max_words
        self.text = ''
        self.visible = ''
        self.done = False
        self.over = False

    def feed(self, piece: str) -> str:
        if piece and not self.done:
            self.text += piece
            self._read()
        return self.visible

    def _read(self) -> None:
        t = THINK.sub('', self.text)
        if '<think>' in self.text and '</think>' not in self.text:
            return  # an open thought: nothing of it is shown, and nothing after it is known yet
        t = t.split('</think>')[-1]
        hold = _partial_tag_tail(t)
        if hold:
            t = t[:-hold]
        s = t.lstrip()
        if not s:
            return
        m = NEWLINE.search(s)
        done = m is not None
        line = (s[: m.start()] if done else s).strip()
        label = LABEL.match(line)
        if label:
            line = line[label.end():]
        elif not done and _maybe_label(line):
            return  # it may still be a label: held (a few letters, or a line opening on "here")
        line = line.lstrip(STRIP).lstrip()
        line = line.strip(STRIP).strip() if done else line.rstrip(STRIP).rstrip()
        self.visible = line
        self.done = done and bool(line)
        if len(line) > self.max_chars or len(line.split()) > self.max_words:
            self.over = True


async def deltas(body_iterator) -> AsyncIterator[str]:
    """the text pieces of an OpenAI-style SSE stream (chat chunks, or Responses' output_text deltas);
    her reasoning pieces are never yielded"""
    buf = b''
    async for chunk in body_iterator:
        if isinstance(chunk, str):
            chunk = chunk.encode('utf-8')
        buf += chunk
        while b'\n' in buf:
            raw, buf = buf.split(b'\n', 1)
            piece = _piece(raw)
            if piece is None:
                continue
            if piece is _END:
                return
            yield piece
    piece = _piece(buf)
    if piece and piece is not _END:
        yield piece


_END = object()


def _piece(raw: bytes):
    line = raw.strip()
    if not line.startswith(b'data:'):
        return None
    data = line[5:].strip()
    if data == b'[DONE]':
        return _END
    try:
        obj = json.loads(data)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get('type') == 'response.output_text.delta' and isinstance(obj.get('delta'), str):
        return obj['delta']
    try:
        delta = obj['choices'][0].get('delta') or {}
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
    text = delta.get('content') if isinstance(delta, dict) else None
    return text if isinstance(text, str) and text else None


def event(kind: str, **data) -> bytes:
    """one line of the page's stream (application/x-ndjson)"""
    return (json.dumps({'t': kind, **data}, ensure_ascii=False) + '\n').encode('utf-8')
