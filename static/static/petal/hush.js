/* ═══════════════════════════════════════════════════════════
   🌸 petal · hush  ·  v0.5 · live + debug
   the empty chat field whispers — and Petal writes the words.

   live  · asks /api/v1/tasks/petal_hush/completions (the task
           grafted beside title generation) for a fresh line,
           keeps a tiny queue of her newest words so every new
           chat opens on one instantly — no waiting on the GPU.
   pool  · hush.json { mine, petal } is the fallback: first load,
           server offline, or "live": false.

   re-rolls on page load and on every in-app navigation. no
   timers, no animation; at most one request in flight, and
   only while the queue is short. idle room = silent room.

   v0.3 · a failed ask makes her rest until you navigate —
          never an instant retry. three misses in a row and
          live sleeps until the page reloads (pool carries on).
   v0.5 · a console window into all of it:
            petalHush.status()   one verdict + every fact, as a table
            petalHush.ask()      ask Petal right now, show her raw answer
            petalHush.roll()     re-roll the whisper on screen
            petalHush.trail()    the last 30 things hush did
            petalHush.reset()    clear queue + misses, wake live
            petalHush.debug()    narrate everything (off: debug(false))
          a trimmed answer (Petal spoke, the line didn't survive
          cleaning) is no longer silent — it says why, once.
   ═══════════════════════════════════════════════════════════ */
(() => {
	if (window.__petalHush) return;
	window.__petalHush = true;

	const POOL_URL = '/static/petal/hush.json';
	const LIVE_URL = '/api/v1/tasks/petal_hush/completions';
	const K = { queue: 'petal.hush.queue', recent: 'petal.hush.recent', debug: 'petal.hush.debug' };

	let pool = [];
	let poolInfo = { loaded: false, mine: 0, petal: 0 };
	let live = true;
	let cap = 2;
	let inflight = false;
	let navs = 0;
	let restingAt = -1; // nav count at which she last failed
	let misses = 0;
	let shown = { line: null, from: null };
	let lastAsk = null; // { at, model, ms, status, body }
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

	/* ── the narrator ─────────────────────────────────────── */
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

	const paint = (line, from) => {
		document.documentElement.style.setProperty('--p-hush', toCss(line));
		shown = { line, from };
		const recent = load(K.recent, []).filter((l) => l !== line);
		recent.unshift(line);
		save(K.recent, recent.slice(0, 8));
		note('paint', { line, from });
	};

	const fromPool = () => {
		if (!pool.length) return null;
		const last = load(K.recent, [])[0];
		const choices = pool.length > 1 ? pool.filter((l) => l !== last) : pool;
		return choices[Math.floor(Math.random() * choices.length)];
	};

	/* her freshest words first, the pool when she hasn't spoken yet */
	const show = () => {
		const queue = load(K.queue, []);
		const fromQueue = queue.shift();
		const line = fromQueue ?? fromPool();
		save(K.queue, queue);
		if (line) paint(line, fromQueue ? 'queue (petal, written earlier)' : 'pool');
		else note('nothing to paint', { pool: pool.length, queue: queue.length });
		refill();
	};

	const fieldIsEmpty = () => !!document.querySelector('#chat-input p.is-editor-empty');
	const pageModel = () => {
		try {
			return JSON.parse(sessionStorage.getItem('selectedModels') ?? 'null')?.[0] ?? null;
		} catch (_) {
			return null;
		}
	};
	const token = () => {
		try {
			return localStorage.getItem('token');
		} catch (_) {
			return null;
		}
	};

	/* one request, fully recorded — refill and petalHush.ask() share it */
	const askPetal = async (why, withDebug = debug) => {
		const t = token();
		if (!t) {
			note('no token — not signed in on this page');
			return { ok: false, status: -1, data: null };
		}
		const model = pageModel();
		note('ask', { why, model: model ?? '(none from tab → server picks your default)' });
		const t0 = performance.now();
		let r = null;
		let data = null;
		try {
			r = await fetch(LIVE_URL, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` },
				body: JSON.stringify({
					model,
					avoid: load(K.recent, []).slice(0, 6),
					...(withDebug ? { debug: true } : {})
				})
			});
			data = await r.json().catch(() => null); // errors carry the why
		} catch (e) {
			if (leaving) return { ok: false, status: -1, data: null }; // page is closing, stay quiet
			const ms = Math.round(performance.now() - t0);
			lastAsk = { at: new Date().toLocaleTimeString(), model, ms, status: 0, body: { detail: e?.message ?? 'offline' } };
			note('ask failed (network)', { ms, error: e?.message });
			return { ok: false, status: 0, data: null };
		}
		const ms = Math.round(performance.now() - t0);
		lastAsk = { at: new Date().toLocaleTimeString(), model, ms, status: r.status, body: data };
		note(r.ok ? 'answer' : 'refused', {
			status: r.status,
			ms,
			whisper: data?.whisper ?? null,
			model: data?.model,
			picked_by: data?.picked_by,
			reason: data?.reason,
			detail: data?.detail
		});
		if (withDebug && data?.debug) {
			console.groupCollapsed('🌸 hush · what the server saw');
			console.log(data.debug);
			console.groupEnd();
		}
		return { ok: r.ok, status: r.status, data };
	};

	const refill = async () => {
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
				const shownFromPool = !pool.length || shown.from === 'pool';
				if (navAtAsk === navs && shownFromPool && fieldIsEmpty()) {
					/* she answered while you're still on the same page and
					   the field shows only a pool line — let her speak now */
					paint(line, 'live (petal, just now)');
				} else {
					const queue = load(K.queue, []);
					queue.push(line);
					save(K.queue, queue.slice(-cap));
					note('queued', { line, queue: queue.length });
				}
			} else if (httpOk) {
				/* she spoke, but nothing survived the trim — say why, once */
				tellOnce('trimmed', 'Petal answered but the line was trimmed —', data?.reason ?? 'no reason given', '· petalHush.ask() shows her raw words');
			} else if (status === 404) {
				live = false; // graft not applied on this server — pool only
				note('live off: endpoint missing (404)');
			}
		} finally {
			inflight = false;
		}
		if (!ok) {
			restingAt = navAtAsk; // rest until the next navigation
			note('resting until next navigation');
			return;
		}
		if (load(K.queue, []).length < cap && navAtAsk === navs) refill();
	};

	const miss = (why, tried) => {
		misses++;
		if (misses === 1) {
			console.info('🌸 petal hush: no whisper —', why);
			if (Array.isArray(tried)) for (const t of tried) console.info(`   ↳ ${t.model}: ${t.error}`);
		}
		if (misses >= 3) {
			live = false;
			console.info('🌸 petal hush: resting until reload, the pool carries the room');
		}
	};

	let lastPath = location.pathname;
	const onNav = () => {
		if (location.pathname === lastPath) return;
		lastPath = location.pathname;
		navs++;
		note('navigation', { to: lastPath });
		show();
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

	/* ── the console window ───────────────────────────────── */
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
		return {
			theme,
			'html.petal': root.classList.contains('petal'),
			'html.dark': root.classList.contains('dark'),
			registrar: !!window.__petalTheme,
			'skin css loaded': skinLoaded,
			'chat field': !!field,
			'field empty': !!empty,
			'drawn in field': drawn,
			'--p-hush dial': dial || null,
			'shown line': shown.line,
			'shown from': shown.from,
			'pool loaded': poolInfo.loaded,
			'pool mine/petal': `${poolInfo.mine}/${poolInfo.petal}`,
			live,
			'queue cap': cap,
			queue: load(K.queue, []).join(' · ') || '(empty)',
			'asking now': inflight,
			misses,
			resting: restingAt === navs,
			'signed in': !!token(),
			'tab model': pageModel(),
			'last ask': lastAsk ? `${lastAsk.at} · ${lastAsk.status} · ${lastAsk.ms}ms` : '(none yet)',
			'last model': lastAsk?.body?.model ?? null,
			'picked by': lastAsk?.body?.picked_by ?? null,
			'last whisper': lastAsk?.body?.whisper ?? null,
			'last reason':
				lastAsk?.body?.reason ??
				(lastAsk?.body?.tried?.[0] ? `${lastAsk.body.tried[0].model} → ${lastAsk.body.tried[0].error}` : null) ??
				lastAsk?.body?.detail ??
				null
		};
	};

	/* "a", 'a' and a are the same words — compare what's inside the quotes */
	const unquote = (s) =>
		String(s ?? '')
			.trim()
			.replace(/^(['"])([\s\S]*)\1$/, '$2')
			.replace(/\\(.)/g, '$1');

	const verdict = (f) => {
		if (!f['html.petal'])
			return `skin off — <html> has no "petal" class (theme is "${f.theme}"). pick 🌸 Petal in Settings → General → Theme`;
		if (!f['chat field']) return 'no chat field on this page — open a new chat';
		if (!f['field empty']) return 'the field has text in it — the whisper only shows when it is empty';
		if (!f['skin css loaded'])
			return 'skin stylesheets not loaded — custom.css → petal/theme.css did not arrive (hard-refresh, or check /static/custom.css)';
		if (!f['--p-hush dial']) return 'no --p-hush dial at all — tokens.css is missing the hush line';
		if (unquote(f['drawn in field']) !== unquote(f['--p-hush dial']))
			return 'css not winning — the field draws something other than the dial (the whisper rule in chat.css is missing or overridden)';
		if (!f.live) return 'live is off (hush.json "live": false, endpoint missing, or 3 misses) — pool only';
		if (!f['signed in']) return 'not signed in on this page — live cannot ask (the pool still whispers)';
		if (lastAsk && lastAsk.status !== 200) return `live failing — ${f['last reason']}`;
		if (lastAsk && !f['last whisper']) return `Petal answered but her line was trimmed — ${f['last reason'] ?? 'see petalHush.ask()'}`;
		if (!lastAsk) return 'live has not asked yet — petalHush.ask() asks now';
		return `all well 🌸 — the field shows a line from ${f['shown from']}`;
	};

	window.petalHush = {
		status() {
			const f = facts();
			const v = verdict(f);
			console.log('%c🌸 hush verdict%c ' + v, 'color:#f2a7d6;font-weight:600', 'color:inherit');
			console.table(f);
			return v;
		},
		async ask() {
			const res = await askPetal('asked from the console', true);
			const line = res.data?.whisper;
			if (line) paint(line, 'live (petal, asked from console)');
			return res.data;
		},
		roll() {
			show();
			return shown.line;
		},
		trail() {
			console.table(trail);
			return trail.length;
		},
		reset() {
			save(K.queue, []);
			misses = 0;
			restingAt = -1;
			live = true;
			once.clear();
			note('reset — queue cleared, live awake');
			refill();
			return 'reset';
		},
		debug(on = true) {
			debug = !!on;
			save(K.debug, debug);
			console.info('🌸 petal hush: debug', debug ? 'on — narrating, and the server sends what it saw' : 'off');
			return debug;
		}
	};

	fetch(POOL_URL, { cache: 'no-cache' })
		.then((r) => (r.ok ? r.json() : null))
		.catch(() => null)
		.then((data) => {
			if (data) {
				live = data.live !== false;
				cap = Number.isInteger(data.queue) ? Math.max(0, Math.min(data.queue, 6)) : cap;
				const mine = (data.mine ?? []).filter((l) => typeof l === 'string' && l.trim());
				const petal = (data.petal ?? []).filter((l) => typeof l === 'string' && l.trim());
				pool = [...new Set([...mine, ...petal].map((l) => l.trim()))];
				poolInfo = { loaded: true, mine: mine.length, petal: petal.length };
			}
			note('pool', { ...poolInfo, live, cap });
			show();
		});

	console.info('🌸 petal hush alive — petalHush.status() for a look inside');
})();
