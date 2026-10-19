/* ═══════════════════════════════════════════════════════════
   🌸 petal · hush  ·  v0.11 · open + reply + linger + pin · she writes it in
   the empty chat field whispers — and Petal writes the words.

   open  · on a new chat: a line from her queue (written earlier,
           so it's instant), refilled live in the background.
   reply · inside a chat: after you send, the server waits for
           her reply to finish, then she whispers from that
           exchange — through your reply lens. opening an older
           chat gets one too (reply_on_open), tied to where you
           left off.
   pool  · your lines arrive from /petal_hush/pool, signed-in
           only — your lenses are no longer public files.

   no timers while idle; one request per mode at a time; the
   GPU only works after Petal's reply is done. the only motion
   is her line writing itself in (~1s), then everything rests.
   reduced-motion → it simply appears.

   v0.3 · a failed ask rests until you navigate; 3 misses → pool only.
   v0.5 · the console window (status · ask · roll · trail · reset · debug).
   v0.6 · reply whispers · pool from the server · and privacy by design:
          status, trail and debug are numbers only (safe to paste);
          petalHush.peek() is the one door to the words, for your eyes.
   v0.7 · inside a chat the field stays silent while she writes —
          no dry pool lines (your reply_lines still play if you add them).
          every line she gives writes itself in, letter by letter.
   v0.11 · fits the field: every ask says phone or computer, and the server
          holds her to that device's max (hush.json max_chars / max_chars_phone).
          on a phone, pool lines too long for the field are skipped.
   v0.10 · the pin: the whisper you answered goes with your message.
          the moment you begin writing over her line, hush holds it
          (how long it glowed, its lingers, your device, how present
          you seemed); on send the server renders it through
          petal-lenses/hush-pin.txt, keeps a private record keyed to
          her reply (data/petal/hush-pins.jsonl, for the ledger), and
          the note rides at the bottom of your system message — under
          her persona, above your memories. never in your bubble.
          regenerations and edits carry no pin. dial: "pin": false.
   v0.9 · presence: a 0–100% guess that you're really here — computer:
          focus + how recently the mouse/keys stirred (fades over ~1 min);
          phone: high whenever the screen is on, touches lift it. below
          ~55% she doesn't linger into an empty room: she waits, and
          whispers the moment you stir. she's told the score too.
   v0.8.2 · the new-chat page lingers too — after her line shows there,
          the same quiet clock runs (open-linger lens on the server).
   v0.8.1 · presence also wakes on any sign of you (click, key, wheel,
          mouse) — some window managers swallow the window 'focus'.
   v0.8 · linger: after her whisper, if you stay quiet ~20s with the
          window focused (unfocused time doesn't count; a phone in hand
          does), she writes a new one knowing how long the hush has been.
          up to 3 per quiet stretch, each waiting twice as long. typing
          or sending resets her. no polling — focus events only.
          queued open lines expire (15 min) so time-aware lines stay true.
   ═══════════════════════════════════════════════════════════ */
(() => {
	if (window.__petalHush) return;
	window.__petalHush = true;

	const POOL_URL = '/api/v1/tasks/petal_hush/pool';
	const LEGACY_POOL_URL = '/static/petal/hush.json'; // only if the server has no pool yet
	const LIVE_URL = '/api/v1/tasks/petal_hush/completions';
	const PIN_URL = '/api/v1/tasks/petal_hush/pin';
	const K = { queue: 'petal.hush.queue', recent: 'petal.hush.recent', debug: 'petal.hush.debug' };
	const rawFetch = window.fetch.bind(window); // hush's own requests never pass the send-watcher

	/* lines + dials — filled from the pool */
	let mine = [];
	let petal = [];
	let replyLines = [];
	let pool = []; // mine + petal, the open-mode fallback
	let sources = null;
	let poolInfo = { loaded: false, from: null };
	let live = true;
	let cap = 2;
	let replyLive = true;
	let replyOnOpen = true;
	let lingerOn = true;
	let lingerAfter = 20; // seconds of focused quiet before she notices
	let lingerMax = 3; // lingers per quiet stretch
	let lingerGrowth = 2; // each next one waits this many times longer
	let freshMs = 15 * 60 * 1000; // queued open lines older than this are let go
	let presenceMin = 0.55; // below this she waits for you instead of lingering
	let presenceFade = 60; // seconds for a mouse/key stir to fade by ~2/3 (computer)
	let pinOn = true; // the whisper you answered rides with your message
	let maxChars = matchMedia('(pointer: coarse)').matches ? 44 : 72; // filled from the pool's dials

	/* open mode */
	let inflight = false;
	let navs = 0;
	let restingAt = -1; // nav count at which open mode last failed
	/* reply mode */
	let replyCtrl = null; // the one reply ask in flight
	let replyFor = null; // { chatId, messageId }
	let openTimer = null;
	const replyCache = new Map(); // chatId → her last whisper there (this page session)
	const replyRecent = new Map(); // chatId → recent whispers there (for 'avoid')
	/* shared */
	let misses = 0;
	let shown = { line: null, from: null, mode: null, at: 0, lingered: 0 };
	let stillest = 0; // longest stillness (ms) while the shown line glowed
	let held = null; // the whisper you began answering — taken by the next send
	let lastPin = null; // { at, kind, chars, ms, status } — numbers only
	let lastAsk = null; // { at, mode, ms, status, body }
	let leaving = false; // a reload cuts requests off — that's not a miss
	addEventListener('pagehide', () => (leaving = true));

	const load = (k, d) => {
		try {
			return JSON.parse(localStorage.getItem(k)) ?? d;
		} catch (_) {
			return d;
		}
	};
	const save = (k, v) => {
		try {
			localStorage.setItem(k, JSON.stringify(v));
		} catch (_) {}
	};
	const chatIdOf = (path = location.pathname) => (path.match(/^\/c\/([^/?#]+)/) || [])[1] ?? null;
	const short = (id) => (id ? '…' + String(id).slice(-4) : null);

	/* ── the narrator — numbers only, safe to paste ───────── */
	let debug = load(K.debug, false) === true || /[?&]hushdebug\b/.test(location.search);
	const trail = [];
	const note = (event, data = {}) => {
		trail.push({ time: new Date().toLocaleTimeString(), event, ...data });
		if (trail.length > 30) trail.shift();
		if (debug) console.log('%c🌸 hush%c ' + event, 'color:#f2a7d6;font-weight:600', 'color:inherit', data);
	};
	const once = new Set();
	const tellOnce = (key, ...msg) => {
		if (once.has(key)) return;
		once.add(key);
		console.info('🌸 petal hush:', ...msg);
	};

	const toCss = (s) =>
		'"' +
		String(s)
			.replace(/[\u0000-\u001f\u007f]+/g, ' ')
			.replace(/\\/g, '\\\\')
			.replace(/"/g, '\\"')
			.trim() +
		'"';

	/* she writes it in: the final line goes on <html> at once (the truth),
	   while #chat-input gets a growing copy that wins for the field alone —
	   so each tick restyles one placeholder, not the whole page. */
	let typing = null;
	const graphemes = (s) =>
		typeof Intl !== 'undefined' && Intl.Segmenter
			? [...new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(s)].map((g) => g.segment)
			: [...s];
	const writeIn = (line) => {
		clearTimeout(typing);
		const field = document.querySelector('#chat-input');
		const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
		if (!field || still || !line) {
			field?.style.removeProperty('--p-hush');
			return;
		}
		const g = graphemes(line);
		let i = 0;
		const step = () => {
			i++;
			field.style.setProperty('--p-hush', toCss(g.slice(0, i).join('')));
			if (i < g.length) typing = setTimeout(step, 22 + Math.random() * 30);
			else field.style.removeProperty('--p-hush'); // done — the <html> line takes over, nothing left running
		};
		field.style.setProperty('--p-hush', '""');
		typing = setTimeout(step, 60);
	};

	const paint = (line, from, mode = 'open', lingered = 0) => {
		document.documentElement.style.setProperty('--p-hush', toCss(line));
		writeIn(line);
		shown = { line, from, mode, at: Date.now(), lingered };
		stillest = 0;
		if (mode === 'open' && line) {
			const recent = load(K.recent, []).filter((l) => l !== line);
			recent.unshift(line);
			save(K.recent, recent.slice(0, 8));
		}
		note('paint', { chars: line.length, from, mode });
	};

	/* the open queue holds { line, at } — a line written hours ago may name the wrong hour */
	const freshQueue = () => {
		const all = load(K.queue, []);
		const fresh = all.filter((i) => i && typeof i === 'object' && typeof i.line === 'string' && Date.now() - i.at < freshMs);
		if (fresh.length !== all.length) {
			save(K.queue, fresh);
			note('queue let go of stale lines', { dropped: all.length - fresh.length });
		}
		return fresh;
	};

	const pick = (list, last) => {
		if (!list.length) return null;
		const choices = list.length > 1 ? list.filter((l) => l !== last) : list;
		return choices[Math.floor(Math.random() * choices.length)];
	};

	const token = () => {
		try {
			return localStorage.getItem('token');
		} catch (_) {
			return null;
		}
	};
	const pageModel = () => {
		try {
			return JSON.parse(sessionStorage.getItem('selectedModels') ?? 'null')?.[0] ?? null;
		} catch (_) {
			return null;
		}
	};
	const fieldIsEmpty = () => !!document.querySelector('#chat-input p.is-editor-empty');

	/* one request, recorded as numbers — every mode shares it */
	const askPetal = async (why, extra = {}, signal = null, { withDebug = debug, peek = false } = {}) => {
		const t = token();
		if (!t) {
			note('no token — not signed in on this page');
			return { ok: false, status: -1, data: null };
		}
		const mode = extra.mode ?? 'open';
		const model = pageModel();
		note('ask', { why, mode, chat: short(extra.chat_id), model: model ?? '(server picks)' });
		const t0 = performance.now();
		let r = null;
		let data = null;
		try {
			r = await rawFetch(LIVE_URL, {
				method: 'POST',
				signal,
				headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` },
				body: JSON.stringify({
					model,
					device: phone ? 'phone' : 'computer', // the field is narrower on a phone
					avoid: load(K.recent, []).slice(0, 6),
					...extra,
					...(withDebug ? { debug: true } : {}),
					...(peek ? { peek: true } : {})
				})
			});
			data = await r.json().catch(() => null); // errors carry the why
		} catch (e) {
			if (e?.name === 'AbortError') {
				note('ask let go', { mode, why: 'a newer message or a new chat' });
				return { ok: false, status: -1, data: null, aborted: true };
			}
			if (leaving) return { ok: false, status: -1, data: null }; // page is closing, stay quiet
			const ms = Math.round(performance.now() - t0);
			lastAsk = { at: new Date().toLocaleTimeString(), mode, ms, status: 0, body: { detail: e?.message ?? 'offline' } };
			note('ask failed (network)', { ms, error: e?.message });
			return { ok: false, status: 0, data: null };
		}
		const ms = Math.round(performance.now() - t0);
		lastAsk = { at: new Date().toLocaleTimeString(), mode, ms, status: r.status, body: data };
		note(r.ok ? 'answer' : 'refused', {
			mode,
			status: r.status,
			ms,
			chars: data?.whisper ? data.whisper.length : 0,
			model: data?.model,
			picked_by: data?.picked_by,
			reason: data?.reason,
			detail: data?.detail
		});
		if (withDebug && data?.debug) {
			console.groupCollapsed('🌸 hush · what the server saw (numbers only)');
			console.log(data.debug);
			console.groupEnd();
		}
		return { ok: r.ok, status: r.status, data };
	};

	const miss = (why, tried) => {
		misses++;
		if (misses === 1) {
			console.info('🌸 petal hush: no whisper —', why);
			if (Array.isArray(tried)) for (const t of tried) console.info(`   ↳ ${t.model}: ${t.error}`);
		}
		if (misses >= 3) {
			live = false;
			replyLive = false;
			console.info('🌸 petal hush: resting until reload, the pool carries the room');
		}
	};

	/* ── open mode: a new chat ────────────────────────────── */
	const show = () => {
		const queue = freshQueue();
		const fromQueue = queue.shift()?.line;
		const line = fromQueue ?? pick(pool, load(K.recent, [])[0]);
		save(K.queue, queue);
		if (line) {
			paint(line, fromQueue ? 'queue (petal, written earlier)' : 'pool', 'open');
			lingerArm(null, 0);
		} else note('nothing to paint', { pool: pool.length, queue: queue.length });
		refill();
	};

	const refill = async () => {
		if (chatIdOf()) return; // the open queue is for new chats — inside a chat, reply mode speaks
		if (!live || inflight || restingAt === navs || freshQueue().length >= cap) return;
		inflight = true;
		const navAtAsk = navs;
		let ok = false;
		try {
			const { ok: httpOk, status, data } = await askPetal('refill');
			const line = data?.whisper;
			if (status > 0 && !httpOk) miss(`${status} ${data?.detail ?? ''}`.trim(), data?.tried);
			else if (status === 0) miss(lastAsk?.body?.detail ?? 'offline'); // -1 = not signed in, not a miss
			if (line) {
				ok = true;
				misses = 0;
				if (navAtAsk === navs && shown.from === 'pool' && fieldIsEmpty() && !chatIdOf()) {
					paint(line, 'live (petal, just now)', 'open'); // she answered while only a pool line showed
					lingerArm(null, 0);
				} else {
					const queue = freshQueue();
					queue.push({ line, at: Date.now() });
					save(K.queue, queue.slice(-cap));
					note('queued', { chars: line.length, queue: queue.length });
				}
			} else if (httpOk) {
				tellOnce('trimmed', 'Petal answered but the line was trimmed —', data?.reason ?? 'no reason given', '· petalHush.peek() shows her words, for your eyes');
			} else if (status === 404) {
				live = false;
				note('live off: endpoint missing (404)');
			}
		} finally {
			inflight = false;
		}
		if (!ok) {
			restingAt = navAtAsk;
			note('resting until next navigation');
			return;
		}
		if (freshQueue().length < cap && navAtAsk === navs) refill();
	};

	/* ── reply mode: inside a chat ────────────────────────── */
	const askReply = async (chatId, messageId, why) => {
		if (!replyLive) return;
		replyCtrl?.abort(); // one reply ask at a time — the newest message wins
		const ctrl = new AbortController();
		replyCtrl = ctrl;
		replyFor = { chatId, messageId };
		const res = await askPetal(
			why,
			{ mode: 'reply', chat_id: chatId, message_id: messageId, avoid: replyRecent.get(chatId) ?? [] },
			ctrl.signal
		);
		if (replyCtrl === ctrl) {
			replyCtrl = null;
			replyFor = null;
		}
		if (res.aborted) return;
		const { ok, status, data } = res;
		const line = data?.whisper;
		if (line) {
			misses = 0;
			replyCache.set(chatId, line);
			replyRecent.set(chatId, [line, ...(replyRecent.get(chatId) ?? []).filter((l) => l !== line)].slice(0, 6));
			if (chatIdOf() === chatId) {
				paint(line, 'reply (petal, just now)', 'reply');
				lingerArm(chatId, 0);
			} else note('reply kept for later', { chat: short(chatId), chars: line.length });
		} else if (status > 0 && !ok) {
			miss(`${status} ${data?.detail ?? ''}`.trim(), data?.tried);
		} else if (status === 0) {
			miss(lastAsk?.body?.detail ?? 'offline');
		} else if (ok && data?.reason && !/superseded|page left/.test(data.reason)) {
			tellOnce('reply-' + data.reason, 'no reply whisper —', data.reason);
		}
	};

	const enterChat = (chatId) => {
		const cached = replyCache.get(chatId);
		lingerStop('a different page');
		if (cached) {
			paint(cached, 'reply (petal, earlier in this chat)', 'reply');
			lingerArm(chatId, 0);
		}
		else if (replyLines.length) paint(pick(replyLines, shown.line), 'reply pool', 'reply');
		else paint('', 'silence (until she speaks here)', 'reply');
		clearTimeout(openTimer);
		if (!replyLive || !replyOnOpen) return;
		/* a brand-new chat arrives here right as its first message is sent —
		   give that send a moment to claim the whisper with the real reply id */
		openTimer = setTimeout(() => {
			if (chatIdOf() !== chatId) return;
			if (replyFor && replyFor.chatId === chatId) return;
			if (cached) return; // she already whispered here this session
			askReply(chatId, null, 'opened this chat');
		}, 700);
	};

	const onSend = (chatId, messageId) => {
		note('send seen', { chat: short(chatId) });
		clearTimeout(openTimer);
		lingerStop('you sent a message');
		if (replyLines.length) paint(pick(replyLines, shown.line), 'reply pool (while she writes)', 'reply');
		else paint('', 'silence (while she writes)', 'reply');
		askReply(chatId, messageId, 'after your message');
	};

	/* ── linger: you're quiet, she notices ───────────────────
	   the clock only runs while the page is visible AND focused —
	   a laptop window behind others doesn't count, a phone in your
	   hand does. no polling: focus / blur / visibility events move
	   the clock, one timeout waits for the moment. */
	let lw = null; // { chatId, count, shownAt, focusedMs, needMs, resumedAt, timer, ctrl, waiting }
	const present = () => document.visibilityState === 'visible' && document.hasFocus();

	/* ── presence: how sure is she that you're here? ─────── */
	const phone = matchMedia('(pointer: coarse)').matches;
	let lastStir = Date.now(); // page load counts as a stir
	const confidence = () => {
		if (document.visibilityState !== 'visible') return 0;
		return confidenceAt((Date.now() - lastStir) / 1000);
	};
	const confidenceAt = (age) => {
		if (phone) return Math.min(1, 0.75 + 0.25 * Math.exp(-age / 120)); // screen on ≈ in your hand
		return Math.min(1, (document.hasFocus() ? 0.35 : 0.1) + 0.65 * Math.exp(-age / presenceFade));
	};
	let lastStill = null; // { ms, at } — the most recent stillness a stir ended
	const presenceWord = (c) => (c >= 0.85 ? 'right here' : c >= 0.65 ? 'probably here' : c >= 0.45 ? 'maybe drifting' : 'likely away');

	const lingerStop = (why) => {
		if (!lw) return;
		clearTimeout(lw.timer);
		lw.ctrl?.abort();
		note('linger rests', { why });
		lw = null;
	};

	const lingerClock = () => {
		if (!lw || lw.ctrl) return; // already asking her
		clearTimeout(lw.timer);
		if (present()) {
			lw.resumedAt = lw.resumedAt ?? Date.now();
			const left = lw.needMs - lw.focusedMs - (Date.now() - lw.resumedAt);
			lw.timer = setTimeout(lingerFire, Math.max(0, left));
		} else if (lw.resumedAt) {
			lw.focusedMs += Date.now() - lw.resumedAt; // pause: bank what was focused
			lw.resumedAt = null;
		}
	};

	const lingerArm = (chatId, count) => {
		if (lw) {
			clearTimeout(lw.timer);
			lw.ctrl?.abort();
			lw = null;
		}
		if (!lingerOn || !replyLive || count >= lingerMax) return;
		lw = {
			chatId,
			count,
			shownAt: Date.now(),
			focusedMs: 0,
			needMs: lingerAfter * 1000 * Math.pow(lingerGrowth, count),
			resumedAt: null,
			timer: null,
			ctrl: null
		};
		note('linger waits', { page: chatId ? 'chat ' + short(chatId) : 'new chat', focused_seconds_needed: Math.round(lw.needMs / 1000), written: count });
		lingerClock();
	};

	const lingerFire = async () => {
		if (!lw || lw.ctrl) return;
		const { chatId } = lw;
		if (chatIdOf() !== chatId) return lingerStop('left the chat');
		if (replyFor) return lingerStop('a reply is already on its way');
		if (!present()) return lingerClock();
		const conf = confidence();
		if (conf < presenceMin) {
			// probably away — don't whisper into an empty room. bank the clock and
			// wait: the next stir (mouse, key, touch) brings her back at once.
			if (lw.resumedAt) {
				lw.focusedMs += Date.now() - lw.resumedAt;
				lw.resumedAt = null;
			}
			clearTimeout(lw.timer);
			lw.waiting = true;
			note('linger waits for you', { presence: Math.round(conf * 100) });
			return;
		}
		lw.waiting = false;
		if (!fieldIsEmpty()) {
			// you're composing — start the quiet over once the field is empty again
			lw.focusedMs = 0;
			lw.resumedAt = null;
			return lingerClock();
		}
		const quiet = Math.round((Date.now() - lw.shownAt) / 1000);
		const count = lw.count + 1;
		const ctrl = new AbortController();
		lw.ctrl = ctrl;
		const res = await askPetal(
			chatId ? 'you have been quiet' : 'you have not begun yet',
			{
				mode: 'linger',
				...(chatId ? { chat_id: chatId, avoid: replyRecent.get(chatId) ?? [] } : {}),
				quiet_seconds: quiet,
				linger_count: count,
				last_whisper: shown.line ?? '',
				presence: Math.round(confidence() * 100),
				last_active_seconds: Math.round((Date.now() - lastStir) / 1000),
				device: phone ? 'phone' : 'computer'
			},
			ctrl.signal
		);
		if (res.aborted || !lw || lw.ctrl !== ctrl) return;
		lw.ctrl = null;
		const line = res.data?.whisper;
		if (line) {
			misses = 0;
			if (chatId) {
				replyCache.set(chatId, line);
				replyRecent.set(chatId, [line, ...(replyRecent.get(chatId) ?? []).filter((l) => l !== line)].slice(0, 6));
			}
			if (chatIdOf() === chatId && fieldIsEmpty()) {
				paint(line, `linger ${count} (petal, after ${quiet}s of quiet)`, chatId ? 'reply' : 'open', count);
				lingerArm(chatId, count);
			} else lingerStop('you came back first');
		} else {
			if (res.status > 0 && !res.ok) miss(`${res.status} ${res.data?.detail ?? ''}`.trim(), res.data?.tried);
			lingerStop(res.data?.reason ?? 'no line this time');
		}
	};

	addEventListener('focus', lingerClock);
	addEventListener('blur', lingerClock);
	document.addEventListener('visibilitychange', lingerClock);
	/* some window managers swallow the window 'focus' when you come back from
	   another app — so any sign of you in the page also re-checks presence:
	   element focus, a click, a key, the wheel, or the mouse (at most every 2s). */
	addEventListener('focusin', lingerClock, true);
	addEventListener('focus', () => (lastStir = Date.now()));
	addEventListener('pageshow', lingerClock);
	let lastNudge = 0;
	const youreHere = () => {
		const now0 = Date.now();
		const gap = now0 - lastStir;
		if (gap > 1500) {
			lastStill = { ms: gap, at: now0 };
			if (shown.line) stillest = Math.max(stillest, now0 - Math.max(lastStir, shown.at));
		}
		lastStir = now0; // the presence signal
		if (!lw || lw.resumedAt || lw.ctrl) return; // already counting (or asking) — nothing to do
		const now = Date.now();
		if (now - lastNudge < 2000) return;
		lastNudge = now;
		lingerClock();
	};
	for (const ev of ['pointerdown', 'keydown', 'wheel', 'pointermove', 'touchstart'])
		addEventListener(ev, youreHere, { capture: true, passive: true });
	document.addEventListener(
		'input',
		(e) => {
			if (!lw || !e.target?.closest?.('#chat-input')) return;
			lw.focusedMs = 0; // you're typing — the quiet starts over
			lw.resumedAt = null;
			lingerClock();
		},
		true
	);
	addEventListener('pagehide', () => lingerStop('page closing'));

	/* ── the pin: hold the whisper the moment you begin answering it ──
	   beforeinput fires before the first letter lands, so the field is still
	   empty and her line is still the one glowing. typing into silence holds
	   nothing; clearing the field and beginning again re-holds. */
	const kindOf = (s) => (s.lingered ? 'linger' : s.mode === 'reply' ? 'reply' : 'open');
	const originOf = (from) => (/pool/.test(from ?? '') ? 'pool' : /queue/.test(from ?? '') ? 'queue' : 'petal');
	document.addEventListener(
		'beforeinput',
		(e) => {
			if (!e.target?.closest?.('#chat-input') || !fieldIsEmpty()) return;
			if (!shown.line) return void (held = null);
			const now = Date.now();
			// she came back to answer: the stillness that just ended, if it ended while her line glowed
			const back = lastStill && lastStill.at >= shown.at ? lastStill.ms : 0;
			held = {
				chatId: chatIdOf(),
				whisper: shown.line,
				kind: kindOf(shown),
				origin: originOf(shown.from),
				began: now,
				waited_seconds: Math.round((now - shown.at) / 1000),
				linger_count: shown.lingered,
				stillest_seconds: Math.round(Math.max(stillest, back ? Math.min(back, lastStill.at - shown.at) : 0) / 1000),
				presence: Math.round(confidenceAt(back / 1000) * 100),
				device: phone ? 'phone' : 'computer'
			};
			note('holding the whisper you answer', { kind: held.kind, waited: held.waited_seconds, lingered: held.linger_count });
		},
		true
	);

	/* the held whisper, rendered by the server through your pin lens and recorded
	   privately against her reply — so what she saw is what the ledger trains on */
	const pinNote = async (h, chatId, messageIds, model) => {
		const t = token();
		if (!t) return null;
		const ctrl = new AbortController();
		const cut = setTimeout(() => ctrl.abort(), 1500); // never hold your message hostage
		const t0 = performance.now();
		try {
			const r = await rawFetch(PIN_URL, {
				method: 'POST',
				signal: ctrl.signal,
				headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` },
				body: JSON.stringify({
					chat_id: chatId,
					message_ids: messageIds,
					model,
					whisper: h.whisper,
					kind: h.kind,
					origin: h.origin,
					waited_seconds: h.waited_seconds,
					wrote_seconds: Math.round((Date.now() - h.began) / 1000),
					linger_count: h.linger_count,
					stillest_seconds: h.stillest_seconds,
					presence: h.presence,
					device: h.device
				})
			});
			const data = await r.json().catch(() => null);
			const ms = Math.round(performance.now() - t0);
			lastPin = {
				at: new Date().toLocaleTimeString(),
				kind: h.kind,
				chars: data?.note?.length ?? 0,
				ms,
				status: r.status,
				recorded: !!data?.recorded,
				reason: data?.reason ?? data?.detail ?? null
			};
			note(data?.note ? 'pinned' : 'no pin', { kind: h.kind, chars: lastPin.chars, recorded: lastPin.recorded, ms, reason: lastPin.reason });
			return r.ok ? data?.note || null : null;
		} catch (e) {
			lastPin = {
				at: new Date().toLocaleTimeString(),
				kind: h.kind,
				chars: 0,
				ms: Math.round(performance.now() - t0),
				status: 0,
				recorded: false,
				reason: e?.name === 'AbortError' ? 'took too long — sent without it' : e?.message ?? 'offline'
			};
			note('no pin', { reason: lastPin.reason });
			return null;
		} finally {
			clearTimeout(cut);
		}
	};

	/* at the bottom of your system message: the server puts her persona above it
	   and your memories below it. a chat with no system prompt gets one, just this. */
	const withPin = (b, noteText) => {
		const msgs = Array.isArray(b.messages) ? b.messages : (b.messages = []);
		const sys = msgs[0]?.role === 'system' && typeof msgs[0].content === 'string' ? msgs[0] : null;
		if (sys) sys.content = sys.content.trim() ? sys.content + '\n\n' + noteText : noteText;
		else msgs.unshift({ role: 'system', content: noteText });
		return b;
	};

	/* the send-watcher — sees your message leave. it only ever ADDS the pin
	   (the whisper you answered) to the system message; your words are untouched,
	   and anything unexpected sends your message exactly as it was. */
	window.fetch = function (input, init) {
		let b = null;
		try {
			const url = typeof input === 'string' ? input : input?.url ?? input?.href ?? '';
			const method = String(init?.method ?? input?.method ?? 'GET').toUpperCase();
			if (method === 'POST' && /\/api\/(v1\/)?chat\/completions(\?|$)/.test(url) && typeof init?.body === 'string')
				b = JSON.parse(init.body);
		} catch (_) {
			b = null;
		}
		if (!b || typeof b !== 'object') return rawFetch(input, init);

		const chatId = b.chat_id ?? null;
		const ids = Array.isArray(b.message_ids)
			? b.message_ids.map((m) => m?.message_id).filter(Boolean)
			: b.message_ids && typeof b.message_ids === 'object'
				? Object.values(b.message_ids).filter(Boolean)
				: b.id
					? [b.id]
					: [];
		// a held whisper belongs to this send only if you began it in this chat (or on the new-chat page that became it)
		const h = held && (held.chatId === chatId || held.chatId === null) ? held : null;
		held = null;
		try {
			if (chatId && ids[0] && !String(chatId).startsWith('local')) onSend(chatId, ids[0]);
		} catch (_) {}
		if (!h || !pinOn) return rawFetch(input, init);

		return pinNote(h, chatId, ids, b.model ?? null).then(
			(noteText) => {
				if (!noteText) return rawFetch(input, init);
				let pinned = null;
				try {
					pinned = JSON.stringify(withPin(b, noteText));
				} catch (_) {}
				return pinned ? rawFetch(input, { ...init, body: pinned }) : rawFetch(input, init);
			},
			() => rawFetch(input, init)
		);
	};

	/* ── where are we? ────────────────────────────────────── */
	const enter = () => {
		const chatId = chatIdOf();
		if (chatId) enterChat(chatId);
		else {
			clearTimeout(openTimer);
			lingerStop('left the chat');
			show();
		}
	};

	let lastPath = location.pathname;
	const onNav = () => {
		if (location.pathname === lastPath) return;
		lastPath = location.pathname;
		navs++;
		note('navigation', { to: chatIdOf() ? 'a chat ' + short(chatIdOf()) : lastPath });
		enter();
	};
	for (const fn of ['pushState', 'replaceState']) {
		const orig = history[fn];
		history[fn] = function (...args) {
			const r = orig.apply(this, args);
			onNav();
			return r;
		};
	}
	window.addEventListener('popstate', onNav);

	/* ── the console window — numbers only, safe to paste ─── */
	const facts = () => {
		const root = document.documentElement;
		const field = document.querySelector('#chat-input');
		const empty = document.querySelector('#chat-input p.is-editor-empty');
		const drawn = empty ? getComputedStyle(empty, '::before').content : null;
		const dial = getComputedStyle(root).getPropertyValue('--p-hush').trim();
		const skinLoaded = getComputedStyle(root).getPropertyValue('--abyss').trim() !== '';
		let theme = null;
		try {
			theme = localStorage.getItem('theme');
		} catch (_) {}
		const chatId = chatIdOf();
		return {
			theme,
			'html.petal': root.classList.contains('petal'),
			'skin css loaded': skinLoaded,
			'chat field': !!field,
			'field empty': !!empty,
			'field draws the dial': !!dial && unquote(drawn) === unquote(dial),
			page: chatId ? `chat ${short(chatId)} (reply mode)` : 'new chat (open mode)',
			shown: shown.line ? `${shown.line.length} chars · ${shown.from}` : shown.from ?? '(nothing yet)',
			'pool from': poolInfo.from,
			'lines mine/petal/reply': `${mine.length}/${petal.length}/${replyLines.length}`,
			'fits the field': `${phone ? 'phone' : 'computer'} · ≤${maxChars} chars · pool lines that fit: ${pool.length}`,
			'open lens': sources?.open_lens ?? null,
			'reply lens': sources?.reply_lens ?? null,
			'still exposed': sources?.exposed?.length ? sources.exposed.join(', ') : 'none 🌸',
			'live open/reply': `${live}/${replyLive}`,
			'reply on open': replyOnOpen,
			'open queue': `${freshQueue().length}/${cap}`,
			'reply waiting': replyFor ? `for chat ${short(replyFor.chatId)}` : 'no',
			presence: `${Math.round(confidence() * 100)}% · ${presenceWord(confidence())} · stirred ${Math.round((Date.now() - lastStir) / 1000)}s ago · ${phone ? 'phone' : 'computer'}`,
			linger: !lingerOn
				? 'off'
				: lw
					? `${Math.round((lw.focusedMs + (lw.resumedAt ? Date.now() - lw.resumedAt : 0)) / 1000)}s / ${Math.round(lw.needMs / 1000)}s focused · ${lw.count}/${lingerMax} written · ${present() ? 'you are here' : 'away (clock paused)'}${lw.ctrl ? ' · asking her now' : ''}${lw.waiting ? ' · waiting for you to stir' : ''}`
					: 'resting',
			'linger lens': sources?.linger_lens ?? null,
			'open-linger lens': sources?.open_linger_lens ?? null,
			pin: !pinOn ? 'off' : held ? `holding a ${held.kind} whisper (${held.whisper.length} chars, glowed ${held.waited_seconds}s)` : 'ready — begin writing over her line',
			'pin lens': sources?.pin_lens ?? null,
			'last pin': lastPin ? `${lastPin.at} · ${lastPin.kind} · ${lastPin.status} · ${lastPin.chars} chars · ${lastPin.recorded ? 'recorded' : 'not recorded'} · ${lastPin.ms}ms${lastPin.reason ? ' · ' + lastPin.reason : ''}` : '(none yet)',
			'queue fresh for': `${Math.round(freshMs / 60000)} min`,
			misses,
			'signed in': !!token(),
			'last ask': lastAsk ? `${lastAsk.at} · ${lastAsk.mode} · ${lastAsk.status} · ${lastAsk.ms}ms` : '(none yet)',
			'last model': lastAsk?.body?.model ?? null,
			'picked by': lastAsk?.body?.picked_by ?? null,
			'last whisper': lastAsk?.body?.whisper ? `${lastAsk.body.whisper.length} chars` : null,
			'last reason':
				lastAsk?.body?.reason ??
				(lastAsk?.body?.tried?.[0] ? `${lastAsk.body.tried[0].model} → ${lastAsk.body.tried[0].error}` : null) ??
				lastAsk?.body?.detail ??
				null
		};
	};

	/* "a", 'a' and a are the same words — compare what's inside the quotes */
	function unquote(s) {
		return String(s ?? '')
			.trim()
			.replace(/^(['"])([\s\S]*)\1$/, '$2')
			.replace(/\\(.)/g, '$1');
	}

	const verdict = (f) => {
		if (!f['html.petal'])
			return `skin off — <html> has no "petal" class (theme is "${f.theme}"). pick 🌸 Petal in Settings → General → Theme`;
		if (!f['chat field']) return 'no chat field on this page — open a chat';
		if (!f['field empty']) return 'the field has text in it — the whisper only shows when it is empty';
		if (!f['skin css loaded'])
			return 'skin stylesheets not loaded — custom.css → petal/theme.css did not arrive (hard-refresh, or check /static/custom.css)';
		if (!f['field draws the dial'])
			return 'css not winning — the field draws something other than the dial (whisper rule in chat.css, or --p-hush in tokens.css)';
		if (!f['signed in']) return 'not signed in on this page — live cannot ask (the pool still whispers)';
		if (!poolInfo.loaded) return 'no pool — the server has no /petal_hush/pool yet (re-run petal-hush-apply.sh + restart)';
		const inChat = !!chatIdOf();
		if (inChat ? !replyLive : !live) return `live is off for ${inChat ? 'reply' : 'open'} mode (a dial in your hush.json, or 3 misses) — pool only`;
		if (lastAsk && lastAsk.status > 0 && lastAsk.status !== 200) return `live failing — ${f['last reason']}`;
		if (lastAsk && lastAsk.status === 200 && !lastAsk.body?.whisper)
			return `Petal answered but no line survived — ${f['last reason'] ?? 'see petalHush.peek()'}`;
		if (replyFor) return `waiting for Petal's reply in chat ${short(replyFor.chatId)} — her whisper follows it`;
		if (!lastAsk) return 'live has not asked yet — petalHush.ask() asks now';
		return `all well 🌸 — the field shows a line from ${shown.from}`;
	};

	window.petalHush = {
		status() {
			const f = facts();
			const v = verdict(f);
			console.log('%c🌸 hush verdict%c ' + v, 'color:#f2a7d6;font-weight:600', 'color:inherit');
			if (sources?.exposed?.length)
				console.warn('🌸 hush: lens files still sit in a public folder —', sources.exposed.join(', '));
			if (String(poolInfo.from ?? '').startsWith('served static') || poolInfo.from === 'legacy public file')
				console.warn('🌸 hush: your pool is still read from the public copy — move hush.json into petal-lenses/');
			console.table(f);
			return v;
		},
		async ask() {
			const chatId = chatIdOf();
			const res = chatId
				? await askPetal('asked from the console', { mode: 'reply', chat_id: chatId }, null, { withDebug: true })
				: await askPetal('asked from the console', {}, null, { withDebug: true });
			const line = res.data?.whisper;
			if (line) {
				if (chatId) replyCache.set(chatId, line);
				paint(line, 'live (petal, asked from console)', chatId ? 'reply' : 'open');
			}
			return {
				mode: chatId ? 'reply' : 'open',
				status: res.status,
				chars: line ? line.length : 0,
				model: res.data?.model,
				picked_by: res.data?.picked_by,
				reason: res.data?.reason ?? res.data?.detail ?? null
			};
		},
		async peek() {
			const chatId = chatIdOf();
			const res = await askPetal('peek from the console', chatId ? { mode: 'reply', chat_id: chatId } : {}, null, {
				withDebug: true,
				peek: true
			});
			console.groupCollapsed('🔒 hush · peek — for your eyes, not for pasting');
			console.log('prompt she was given:\n' + (res.data?.peek?.prompt ?? '(none)'));
			console.log('her raw answer:\n' + (res.data?.peek?.raw ?? '(none)'));
			console.log('whisper that survived:', res.data?.whisper ?? `(none — ${res.data?.reason ?? res.data?.detail ?? 'no answer'})`);
			console.groupEnd();
			if (res.data?.whisper) paint(res.data.whisper, 'live (petal, peeked)', chatId ? 'reply' : 'open');
			return 'peeked — open the 🔒 group above';
		},
		roll() {
			enter();
			return shown.line ? `${shown.line.length} chars · ${shown.from}` : shown.from ?? 'nothing to paint';
		},
		trail() {
			console.table(trail);
			return trail.length;
		},
		reset() {
			save(K.queue, []);
			replyCache.clear();
			replyRecent.clear();
			lingerStop('reset');
			held = null;
			misses = 0;
			restingAt = -1;
			live = true;
			replyLive = true;
			once.clear();
			note('reset — queue + reply cache cleared, live awake');
			enter();
			return 'reset';
		},
		debug(on = true) {
			debug = !!on;
			save(K.debug, debug);
			console.info('🌸 petal hush: debug', debug ? 'on — narrating in numbers, the server sends its numbers too' : 'off');
			return debug;
		}
	};

	/* ── the pool: from the server (signed in), else the old public file ── */
	const loadPool = async () => {
		const t = token();
		let data = null;
		if (t) {
			try {
				const r = await rawFetch(POOL_URL, { headers: { Authorization: `Bearer ${t}` }, cache: 'no-store' });
				if (r.ok) {
					data = await r.json();
					poolInfo = { loaded: true, from: data?.sources?.pool ?? 'server' };
				}
			} catch (_) {}
		}
		if (!data) {
			try {
				const r = await rawFetch(LEGACY_POOL_URL, { cache: 'no-cache' });
				if (r.ok) {
					data = await r.json();
					poolInfo = { loaded: true, from: 'legacy public file' };
				}
			} catch (_) {}
		}
		if (data) {
			const lines = (v) => [...new Set((v ?? []).filter((l) => typeof l === 'string' && l.trim()).map((l) => l.trim()))];
			live = data.live !== false;
			cap = Number.isInteger(data.queue) ? Math.max(0, Math.min(data.queue, 6)) : cap;
			replyLive = data.reply_live !== false;
			replyOnOpen = data.reply_on_open !== false;
			lingerOn = data.linger !== false;
			const num = (v, d, lo, hi) => (Number.isFinite(+v) ? Math.min(hi, Math.max(lo, +v)) : d);
			lingerAfter = num(data.linger_after, lingerAfter, 5, 3600);
			lingerMax = num(data.linger_max, lingerMax, 0, 10);
			lingerGrowth = num(data.linger_growth, lingerGrowth, 1, 10);
			freshMs = num(data.queue_fresh_minutes, freshMs / 60000, 1, 24 * 60) * 60000;
			presenceMin = num(data.presence_min, presenceMin, 0, 1);
			presenceFade = num(data.presence_fade, presenceFade, 10, 3600);
			pinOn = data.pin !== false;
			maxChars = num(phone ? data.max_chars_phone : data.max_chars, maxChars, 8, 200);
			mine = lines(data.mine);
			petal = lines(data.petal);
			replyLines = lines(data.reply_lines);
			const fits = (l) => graphemes(l).length <= maxChars; // a pool line that can't fit the field stays quiet
			pool = [...new Set([...mine, ...petal])].filter(fits);
			replyLines = replyLines.filter(fits);
			sources = data.sources ?? null;
		}
		note('pool', { from: poolInfo.from, mine: mine.length, petal: petal.length, reply: replyLines.length, live, cap });
		if (sources?.exposed?.length) tellOnce('exposed', 'lens files still sit in a public folder —', sources.exposed.join(', '), '· petalHush.status() for more');
		enter();
	};
	loadPool();

	console.info('🌸 petal hush alive — petalHush.status() for a look inside');
})();
