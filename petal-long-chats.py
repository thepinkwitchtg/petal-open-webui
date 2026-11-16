#!/usr/bin/env python3
"""
🌸📏 petal long chats — what opening her longest chats costs, numbers only (slice A24)

opens her N largest chats one by one in a headless browser, through OWUI's own pages and routes, as a reader
only, and reports per chat:
  payload    the chat as the page parsed it (page KB), what crossed the wire (wire KB, compressed), and × how
             many times the page fetched it
  backend    OWUI's memory (RSS + swap, MB) before the open → once the page is interactive → 10 s after closing
  paint      ms from navigation to the first of her messages painted on screen
  ready      ms to interactive: the last long task (≥ 50 ms) after that paint, once the page has been quiet 2 s
  busy       ms of long tasks on the page's main thread during the open
  switch     the same chat opened again from inside the app (home → chat, the way a sidebar click does):
             × fetches, paint and ready, counted from the click

a reader only: every request that isn't a GET is refused in that browser (no "viewed" stamps, no device
readings for petal-live, no whispers), and the socket never sends a "read" mark (her unread dots stay as they
are): it only joins, leaves and says it's alive. a title or a word is never read or printed: chats are picked
by size from the database, opened read-only, and named by a hash of their id. (OWUI's chat route itself may file
an old chat's messages into its message table the first time it's read, upstream's self-heal, as when she
opens that chat herself.) the report (numbers only) is also kept in Petal-App-Data/petal-probes/.

usage (through petal-long-chats.sh, which brings its own browser):
  ./petal-long-chats.sh            the 12 largest chats
  ./petal-long-chats.sh 20         the 20 largest
  ./petal-long-chats.sh 8 --phone  as her phone would (360×780 @3x, CPU ×4)
env: OWUI_URL (default http://127.0.0.1:3000) · OWUI_DB (else found) · OWUI_TOKEN (else asked: email + password)
"""

import argparse
import getpass
import hashlib
import json
import os
import re
import sqlite3
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB_GUESSES = [
    '/gardens/petal-open-webui/backend/open_webui/data/webui.db',
    '~/Gardens/petal-open-webui/backend/open_webui/data/webui.db',
    '~/Gardens/petal-open-webui/backend/data/webui.db',
]
QUIET_MS = 2000
SETTLE_S = 10

WATCH = r"""
(() => {
  // a reader only: the socket never carries a "read" mark (the polling transport is filtered in python)
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) {
    if (typeof data === 'string' && data.includes('"last_read_at"')) return;
    return send.call(this, data);
  };
  const W = (window.__lc = { firstMsg: 0, longTasks: [], fcp: 0 });
  new PerformanceObserver((l) => { for (const e of l.getEntries()) W.longTasks.push([e.startTime, e.duration]); })
    .observe({ type: 'longtask', buffered: true });
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) if (e.name === 'first-contentful-paint') W.fcp = e.startTime;
  }).observe({ type: 'paint', buffered: true });
  // one look per frame: the frame where her first message (an id-named reply, not the composer) is on screen
  const isMessage = (el) => /^message-[0-9a-f]{8}-[0-9a-f]{4}-/.test(el.id);
  const messages = () => [...document.querySelectorAll('[id^="message-"]')].filter(isMessage);
  const look = () => {
    if (messages().length) W.firstMsg = performance.now();
    else requestAnimationFrame(look);
  };
  requestAnimationFrame(look);
  // inside the app: a link click, which the app's router turns into its own navigation (no page load)
  window.__lcGo = (href) => {
    const a = document.createElement('a');
    a.href = href;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };
  window.__lcEmpty = () => messages().length === 0;
  // the in-app switch: the first frame with a message that wasn't on screen before the click
  window.__lcSwitch = (href) => {
    const seen = new Set(messages().map((el) => el.id));
    const S = (W.switch = { t0: performance.now(), firstMsg: 0 });
    const peek = () => {
      if (messages().some((el) => !seen.has(el.id))) S.firstMsg = performance.now();
      else requestAnimationFrame(peek);
    };
    requestAnimationFrame(peek);
    window.__lcGo(href);
  };
})();
"""


def tag(chat_id: str) -> str:
    return hashlib.sha256(chat_id.encode()).hexdigest()[:8]


def find_db() -> str:
    if os.environ.get('OWUI_DB'):
        return os.environ['OWUI_DB']
    for guess in DB_GUESSES:
        p = Path(guess).expanduser()
        if p.exists():
            return str(p)
    sys.exit('💔 webui.db not found: set OWUI_DB=/path/to/webui.db')


def listening_pid(port: int) -> int | None:
    """the process listening on OWUI's port (only her own processes are visible, and OWUI is one of them)"""
    inodes = set()
    for table in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            for line in open(table).read().splitlines()[1:]:
                f = line.split()
                if f[3] == '0A' and int(f[1].rsplit(':', 1)[1], 16) == port:
                    inodes.add(f[9])
        except (OSError, ValueError, IndexError):
            continue
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            for fd in os.listdir(f'/proc/{pid}/fd'):
                link = os.readlink(f'/proc/{pid}/fd/{fd}')
                if link.startswith('socket:[') and link[8:-1] in inodes:
                    return int(pid)
        except OSError:
            continue
    return None


def owui_pids(port: int) -> list[int]:
    """OWUI's backend: the process on its port, else whatever runs `open-webui serve` / open_webui.main"""
    pid = listening_pid(port)
    if pid:
        return [pid]
    found = []
    for p in filter(str.isdigit, os.listdir('/proc')):
        try:
            cmd = open(f'/proc/{p}/cmdline', 'rb').read().replace(b'\0', b' ').decode(errors='ignore')
        except OSError:
            continue
        if ('open-webui serve' in cmd or 'open_webui.main' in cmd) and int(p) != os.getpid():
            found.append(int(p))
    return found


def backend_mb(pids: list[int]) -> float | None:
    """RSS + swap of OWUI's backend, MB"""
    if not pids:
        return None
    total = 0.0
    for pid in pids:
        try:
            status = open(f'/proc/{pid}/status').read()
        except OSError:
            return None
        fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
        total += sum(int(fields.get(key, '0 kB').split()[0]) for key in ('VmRSS', 'VmSwap')) / 1024
    return round(total, 1)


def sign_in(base: str) -> tuple[str, str]:
    token = os.environ.get('OWUI_TOKEN')
    if token:
        req = urllib.request.Request(f'{base}/api/v1/auths/', headers={'Authorization': f'Bearer {token}'})
        me = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return token, me['id']
    email = input('OWUI email: ').strip()
    password = getpass.getpass('OWUI password (kept in memory only): ')
    req = urllib.request.Request(
        f'{base}/api/v1/auths/signin',
        method='POST',
        data=json.dumps({'email': email, 'password': password}).encode(),
        headers={'Content-Type': 'application/json'},
    )
    me = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return me['token'], me['id']


def largest_chats(db: str, user_id: str, n: int) -> list[tuple[str, int]]:
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(
            "SELECT id, length(chat) FROM chat WHERE user_id = ? AND id NOT LIKE 'local:%' "
            "AND id NOT LIKE 'temporary:%' ORDER BY length(chat) DESC LIMIT ?",
            (user_id, n),
        ).fetchall()
    finally:
        con.close()
    return [(r[0], int(r[1] or 0)) for r in rows]


def socket_polling(route):
    """the socket's polling transport: drop a "read" mark from what the page sends, keep everything else"""
    req = route.request
    body = req.post_data if req.method == 'POST' else None
    if not body or '"last_read_at"' not in body:
        return route.continue_()
    kept = [packet for packet in body.split('\x1e') if '"last_read_at"' not in packet]
    route.continue_(post_data='\x1e'.join(kept) if kept else '6')  # 6: engine.io's no-op


def quiet_after(page, since: float) -> float:
    """page-clock ms of the last long task ending after `since`, once the page has been quiet QUIET_MS"""
    while True:
        lc = page.evaluate('window.__lc')
        now = page.evaluate('performance.now()')
        last = max([s + d for s, d in lc['longTasks'] if s + d >= since - 1] + [since])
        if now - last >= QUIET_MS:
            return last
        page.wait_for_timeout(250)


def open_one(pw, base: str, token: str, chat_id: str, phone: bool, pids: list[int]) -> dict:
    browser = pw.chromium.launch()
    ctx = browser.new_context(
        viewport={'width': 360, 'height': 780} if phone else {'width': 1440, 'height': 900},
        device_scale_factor=3 if phone else 1,
        is_mobile=phone,
        has_touch=phone,
    )
    page = ctx.new_page()
    # a reader only: every API call that isn't a GET is refused (every write lives under /api; the page's own
    # files pass untouched, so the load isn't slowed by the watching), and the socket's "read" marks are dropped
    page.route(
        '**/api/**',
        lambda route: route.continue_() if route.request.method in ('GET', 'HEAD', 'OPTIONS') else route.abort(),
    )
    page.route(re.compile(r'/ws/socket\.io/'), socket_polling)
    gets, wire = [], []

    def done(req):
        if req.method == 'GET' and req.url.split('?')[0].endswith(f'/api/v1/chats/{chat_id}'):
            try:
                gets.append(len(req.response().body()))
                wire.append(req.sizes()['responseBodySize'])
            except Exception:
                gets.append(0)
                wire.append(0)

    page.on('requestfinished', done)
    page.goto(f'{base}/static/favicon.png')
    page.evaluate('(t) => { localStorage.token = t; }', token)
    page.add_init_script(WATCH)
    if phone:
        ctx.new_cdp_session(page).send('Emulation.setCPUThrottlingRate', {'rate': 4})

    # 1 · the open: a fresh tab straight onto the chat (the whole app boots with it)
    before = backend_mb(pids)
    page.goto(f'{base}/c/{chat_id}', wait_until='commit', timeout=120000)
    page.wait_for_function('() => window.__lc && window.__lc.firstMsg > 0', timeout=180000)
    first = page.evaluate('window.__lc.firstMsg')
    ready = quiet_after(page, first)
    after = backend_mb(pids)
    lc = page.evaluate('window.__lc')
    opened = {'fetches': len(gets), 'payload': gets[0] if gets else 0, 'wire': wire[0] if wire else 0}

    # 2 · the switch: home, then this chat again from inside the app (the way a sidebar click opens it)
    page.evaluate('(h) => window.__lcGo(h)', '/')
    page.wait_for_function("() => location.pathname === '/' && window.__lcEmpty()", timeout=60000)
    quiet_after(page, page.evaluate('performance.now()'))
    fetched = len(gets)
    page.evaluate('(h) => window.__lcSwitch(h)', f'/c/{chat_id}')
    page.wait_for_function('() => window.__lc.switch.firstMsg > 0', timeout=180000)
    sw = page.evaluate('window.__lc.switch')
    sw_ready = quiet_after(page, sw['firstMsg'])
    switched = len(gets) - fetched
    browser.close()
    time.sleep(SETTLE_S)
    return {
        'chat': tag(chat_id),
        'payload_kb': round(opened['payload'] / 1024),
        'fetches': opened['fetches'],
        'wire_kb': round(opened['wire'] / 1024),
        'paint_ms': round(first),
        'ready_ms': round(ready),
        'busy_ms': round(sum(d for s, d in lc['longTasks'] if s <= ready)),
        'shell_fcp_ms': round(lc['fcp']),
        'backend_mb': [before, after, backend_mb(pids)],
        'switch': {
            'fetches': switched,
            'paint_ms': round(sw['firstMsg'] - sw['t0']),
            'ready_ms': round(sw_ready - sw['t0']),
        },
    }


def main():
    ap = argparse.ArgumentParser(description='what opening her longest chats costs (numbers only)')
    ap.add_argument('n', nargs='?', type=int, default=12)
    ap.add_argument('--phone', action='store_true', help='as her phone would: 360×780 @3x, CPU ×4')
    ap.add_argument('--url', default=os.environ.get('OWUI_URL', 'http://127.0.0.1:3000'))
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    base = args.url.rstrip('/')
    db = find_db()
    token, user_id = sign_in(base)
    chats = largest_chats(db, user_id, args.n)
    if not chats:
        sys.exit('💔 no saved chats found for this account')
    url = urllib.parse.urlparse(base)
    pids = owui_pids(url.port or (443 if url.scheme == 'https' else 80))
    if not pids:
        print("⚠️  OWUI's backend process isn't visible from here: the backend MB columns stay empty")
    print(f'🌸 opening her {len(chats)} largest chats ({"phone" if args.phone else "desktop"}) · numbers only\n')
    print(
        f'{"chat":8}  {"db KB":>7}  {"page KB":>7}  {"wire KB":>7}  {"×":>2}  {"paint":>8}  {"ready":>8}  {"busy":>7}'
        f'   {"backend MB before → ready → settled":<36}  switch: ×   paint     ready'
    )
    rows = []
    with sync_playwright() as pw:
        for chat_id, db_bytes in chats:
            r = open_one(pw, base, token, chat_id, args.phone, pids)
            r['db_kb'] = round(db_bytes / 1024)
            rows.append(r)
            b, sw = r['backend_mb'], r['switch']
            mem = f'{b[0]} → {b[1]} → {b[2]}'
            print(
                f'{r["chat"]:8}  {r["db_kb"]:>7}  {r["payload_kb"]:>7}  {r["wire_kb"]:>7}  {r["fetches"]:>2}'
                f'  {r["paint_ms"]:>5} ms  {r["ready_ms"]:>5} ms  {r["busy_ms"]:>4} ms   {mem:<36}'
                f'          {sw["fetches"]:>1}  {sw["paint_ms"]:>5} ms  {sw["ready_ms"]:>5} ms',
                flush=True,
            )

    def med(get):
        return round(statistics.median(get(r) for r in rows))

    print(
        f'\nmedians · open: page {med(lambda r: r["payload_kb"])} KB · wire {med(lambda r: r["wire_kb"])} KB · '
        f'fetched ×{med(lambda r: r["fetches"])} · '
        f'paint {med(lambda r: r["paint_ms"])} ms · ready {med(lambda r: r["ready_ms"])} ms · '
        f'busy {med(lambda r: r["busy_ms"])} ms'
    )
    print(
        f'        switch: fetched ×{med(lambda r: r["switch"]["fetches"])} · '
        f'paint {med(lambda r: r["switch"]["paint_ms"])} ms · ready {med(lambda r: r["switch"]["ready_ms"])} ms'
    )
    growth = [r['backend_mb'][2] - r['backend_mb'][0] for r in rows if None not in r['backend_mb']]
    if growth:
        print(
            f'backend kept after each chat (settled − before): median {statistics.median(growth):+.0f} MB · '
            f'total {sum(growth):+.0f} MB over {len(growth)} chats'
        )
    out = Path(os.environ.get('PETAL_APP_DATA', '~/Gardens/Documents/Petal-App-Data')).expanduser() / 'petal-probes'
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    f = out / f'long-chats-{time.strftime("%Y-%m-%d-%H%M")}{"-phone" if args.phone else ""}.json'
    f.write_text(json.dumps({'at': int(time.time()), 'phone': args.phone, 'chats': rows}, indent=1))
    os.chmod(f, 0o600)
    print(f'\nkept: {f}')


if __name__ == '__main__':
    main()
