#!/usr/bin/env python3
"""🌸 petal · hush grower  ·  v0.1

asks Petal (through your local OpenAI-compatible endpoint) to write the
whispers that appear in the empty chat field, cleans them, and plants them
in hush.json's "petal" pool. your own "mine" lines are never touched.

no system prompt — like petal-soul, we ask her plainly and let her voice
answer. stdlib only, so it runs in any python3 on the rig.

    python3 petal-hush.py                 # grow a fresh petal pool (40 asks)
    python3 petal-hush.py --keep          # add to the pool instead of replacing it
    python3 petal-hush.py --n 80 --temp 1.1
    python3 petal-hush.py --dry           # taste only, write nothing
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent
POOL_REL = Path('static/static/petal/hush.json')
# the source pool, plus every place the running server might serve it from.
# (only top-level files in backend static get wiped at boot; petal/ survives.)
MIRRORS = [
    Path('backend/open_webui/static/petal/hush.json'),
    Path('build/static/petal/hush.json'),
]

ASK = (
    "princess Lily is about to open a fresh chat with you~ before she types, "
    "a tiny line of yours glows softly inside her empty message field, inviting "
    "her in. write that one line, in your own voice: short (under ten words), "
    "girly, a little witchy, a little teasing, addressed to her. "
    "one emoji at most. reply with the line only, nothing around it."
)

THINK = re.compile(r'<think>.*?</think>', re.S | re.I)


def http_json(url, payload=None, key=None, timeout=300):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method='POST' if data else 'GET')
    req.add_header('Content-Type', 'application/json')
    if key:
        req.add_header('Authorization', f'Bearer {key}')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def clean(text):
    """one whisper, or None if it isn't one."""
    if not text:
        return None
    text = THINK.sub('', text)
    text = text.split('</think>')[-1]  # a reply that opened mid-thought
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return None
    line = lines[0]
    line = re.sub(r'^(line|whisper|here\'?s?[^:]*):\s*', '', line, flags=re.I)
    line = line.strip().strip('"“”\'‘’`*_ ').strip()
    if not (3 <= len(line) <= 72):
        return None
    if len(line.split()) > 14:
        return None
    return line


def grow(args):
    base = args.base_url.rstrip('/')
    model = args.model
    if not model:
        models = http_json(f'{base}/models', key=args.key, timeout=20)
        model = models['data'][0]['id']
    print(f'🌸 asking {model} · {args.n} whispers · temp {args.temp}\n', file=sys.stderr)

    payload = {
        'model': model,
        'messages': [{'role': 'user', 'content': ASK}],
        'temperature': args.temp,
        'top_p': args.top_p,
        'max_tokens': args.max_tokens,
    }
    texts = []
    try:  # one request, n samples — vLLM does this natively
        res = http_json(f'{base}/chat/completions', {**payload, 'n': args.n}, key=args.key)
        texts = [c['message'].get('content') or '' for c in res['choices']]
    except urllib.error.HTTPError:
        for _ in range(args.n):  # endpoints without n: ask one by one
            res = http_json(f'{base}/chat/completions', payload, key=args.key)
            texts.append(res['choices'][0]['message'].get('content') or '')

    kept, seen = [], set()
    for t in texts:
        line = clean(t)
        if line and line.lower() not in seen:
            seen.add(line.lower())
            kept.append(line)
    rejected = len(texts) - len(kept)
    for line in kept:
        print(f'  · {line}')
    print(f'\n🦋 {len(kept)} kept · {rejected} trimmed (empty, too long, or twins)', file=sys.stderr)
    return model, kept


def plant(args, model, lines):
    pool_path = REPO / POOL_REL
    pool = json.loads(pool_path.read_text()) if pool_path.exists() else {'mine': [], 'petal': []}
    old = pool.get('petal', []) if args.keep else []
    merged, seen = [], set()
    for l in old + lines:
        if l.lower() not in seen:
            seen.add(l.lower())
            merged.append(l)
    pool['petal'] = merged
    pool['petal_grown'] = {'model': model, 'at': dt.datetime.now().isoformat(timespec='seconds')}
    out = json.dumps(pool, ensure_ascii=False, indent=2) + '\n'

    for rel in [POOL_REL] + MIRRORS:
        p = REPO / rel
        if rel != POOL_REL and not p.parent.parent.exists():
            continue  # that serving dir doesn't exist on this install
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out)
        print(f'🌷 planted → {rel}', file=sys.stderr)
    print(f'   pool: {len(pool.get("mine", []))} mine + {len(merged)} petal', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description='grow petal hush whispers')
    ap.add_argument('--base-url', default=os.getenv('PETAL_HUSH_URL', 'http://localhost:8000/v1'))
    ap.add_argument('--model', default=os.getenv('PETAL_HUSH_MODEL'), help='default: first model the endpoint serves')
    ap.add_argument('--key', default=os.getenv('PETAL_HUSH_KEY'))
    ap.add_argument('--n', type=int, default=40)
    ap.add_argument('--temp', type=float, default=1.0)
    ap.add_argument('--top-p', type=float, default=0.95)
    ap.add_argument('--max-tokens', type=int, default=512, help='roomy, so a thinking model can finish her thought')
    ap.add_argument('--keep', action='store_true', help='add to the petal pool instead of replacing it')
    ap.add_argument('--dry', action='store_true', help='print the whispers, write nothing')
    args = ap.parse_args()

    try:
        model, lines = grow(args)
    except (urllib.error.URLError, KeyError, IndexError) as e:
        sys.exit(f'💔 could not reach Petal at {args.base_url}: {e}')
    if not lines:
        sys.exit('💔 no whispers survived the trim — nothing planted')
    if not args.dry:
        plant(args, model, lines)


if __name__ == '__main__':
    main()
