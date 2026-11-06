"""
petal_temp_chats 🧪 — contract 0's one numbers-only exception: when a temp chat was opened.

for the saturation shape (bursts of temp chats: sys-prompt testing, "hii" probes). the first
message of a temporary: / local: chat in this process's life appends one line

    $PETAL_APP_DATA/temp-chats/opened.jsonl   →   { "at": <unix s> }

and nothing else: no id, no hash, no model, no title, no content. the de-duplication lives in
memory only (a bounded set of the chats already counted) and never touches disk, so a restart
simply forgets it. channel: chats are not temp chats and are never counted.
"""

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from open_webui.utils.chat_id import is_temporary_chat_id

log = logging.getLogger(__name__)

_CAP = 4096  # chats remembered as "already counted" — oldest forgotten first
_seen: 'OrderedDict[str, None]' = OrderedDict()
_lock = threading.Lock()


def _opened_path() -> Path:
    root = Path(os.environ.get('PETAL_APP_DATA') or '~/Gardens/Documents/Petal-App-Data').expanduser()
    return root / 'temp-chats' / 'opened.jsonl'


def note_opened(chat_id: Optional[str], now: Optional[int] = None) -> bool:
    """count a temp chat's first message once per process · → True if a line was written."""
    if not is_temporary_chat_id(chat_id):
        return False
    with _lock:
        if chat_id in _seen:
            _seen.move_to_end(chat_id)
            return False
        _seen[chat_id] = None
        while len(_seen) > _CAP:
            _seen.popitem(last=False)
    path = _opened_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'at': int(now if now is not None else time.time())}) + '\n')
        return True
    except OSError as e:
        log.warning(f'🧪 temp-chat counter: could not append ({e.strerror or e})')
        return False
