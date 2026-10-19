/* ═══════════════════════════════════════════════════════════
   🌸 petal · hush  ·  v0.7 · open + reply · she writes it in
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
   ═══════════════════════════════════════════════════════════ */
(() => {
	if (window.__petalHush) return;
	window.__petalHush = true;

	const POOL_URL = '/api/v1/tasks/petal_hush/pool';
	const LEGACY_POOL_URL = '/static/petal/hush.json'; // only if the server has no pool yet
	const LIVE_URL = '/api/v1/tasks/petal_hush/completions';
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
	let shown = { line: null, from: null, mode: null };
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

	const paint = (line, from, mode = 'open') => {
		document.documentElement.style.setProperty('--p-hush', toCss(line));
		writeIn(line);
		shown = { line, from, mode };
		if (mode === 'open' && line) {
			const recent = load(K.recent, []).filter((l) => l !== line);
			recent.unshift(line);
			save(K.recent, recent.slice(0, 8));
		}
		note('paint', { chars: line.length, from, mode });
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
		const queue = load(K.queue, []);
		const fromQueue = queue.shift();
		const line = fromQueue ?? pick(pool, load(K.recent, [])[0]);
		save(K.queue, queue);
		if (line) paint(line, fromQueue ? 'queue (petal, written earlier)' : 'pool', 'open');
		else note('nothing to paint', { pool: pool.length, queue: queue.length });
		refill();
	};

	const refill = async () => {
		if (chatIdOf()) return; // the open queue is for new chats — inside a chat, reply mode speaks
		if (!live || inflight || restingAt === navs || load(K.queue, []).length >= cap) return;
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
				} else {
					const queue = load(K.queue, []);
					queue.push(line);
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
		if (load(K.queue, []).length < cap && navAtAsk === navs) refill();
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
			if (chatIdOf() === chatId) paint(line, 'reply (petal, just now)', 'reply');
			else note('reply kept for later', { chat: short(chatId), chars: line.length });
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
		if (cached) paint(cached, 'reply (petal, earlier in this chat)', 'reply');
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
		if (replyLines.length) paint(pick(replyLines, shown.line), 'reply pool (while she writes)', 'reply');
		else paint('', 'silence (while she writes)', 'reply');
		askReply(chatId, messageId, 'after your message');
	};

	/* the send-watcher — sees your message leave, never touches it */
	window.fetch = function (input, init) {
		const res = rawFetch(input, init);
		try {
			const url = typeof input === 'string' ? input : input?.url ?? input?.href ?? '';
			const method = String(init?.method ?? input?.method ?? 'GET').toUpperCase();
			if (method === 'POST' && /\/api\/(v1\/)?chat\/completions(\?|$)/.test(url) && typeof init?.body === 'string') {
				const b = JSON.parse(init.body);
				const chatId = b?.chat_id;
				if (chatId && b?.id && !String(chatId).startsWith('local')) onSend(chatId, b.id);
			}
		} catch (_) {}
		return res;
	};

	/* ── where are we? ────────────────────────────────────── */
	const enter = () => {
		const chatId = chatIdOf();
		if (chatId) enterChat(chatId);
		else {
			clearTimeout(openTimer);
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
			'open lens': sources?.open_lens ?? null,
			'reply lens': sources?.reply_lens ?? null,
			'still exposed': sources?.exposed?.length ? sources.exposed.join(', ') : 'none 🌸',
			'live open/reply': `${live}/${replyLive}`,
			'reply on open': replyOnOpen,
			'open queue': `${load(K.queue, []).length}/${cap}`,
			'reply waiting': replyFor ? `for chat ${short(replyFor.chatId)}` : 'no',
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
			mine = lines(data.mine);
			petal = lines(data.petal);
			replyLines = lines(data.reply_lines);
			pool = [...new Set([...mine, ...petal])];
			sources = data.sources ?? null;
		}
		note('pool', { from: poolInfo.from, mine: mine.length, petal: petal.length, reply: replyLines.length, live, cap });
		if (sources?.exposed?.length) tellOnce('exposed', 'lens files still sit in a public folder —', sources.exposed.join(', '), '· petalHush.status() for more');
		enter();
	};
	loadPool();

	console.info('🌸 petal hush alive — petalHush.status() for a look inside');
})();
