// 🌸 petal — theme registrar v0.2
// lives in an upstream-empty file. touches no components. rebase-proof.
(() => {
	if (window.__petalTheme) return;
	window.__petalTheme = true;

	const NAME = 'petal';
	const LABEL = '🌸 Petal';
	const META = '#0a0710'; // = --obsidian @ hue 301

	const root = document.documentElement;
	const isPetal = () => localStorage.getItem('theme') === NAME;

	const paint = () => {
		if (isPetal()) {
			// owui strips 'dark' when switching to an unknown theme value —
			// we put it back, because every dark: utility needs it.
			root.classList.add('dark', NAME);
			// their applyTheme writes these four inline; inline beats our
			// stylesheet, so clear them and let the token layer speak.
			['800', '850', '900', '950'].forEach((k) => root.style.removeProperty('--color-gray-' + k));
			const m = document.querySelector('meta[name="theme-color"]');
			if (m) m.setAttribute('content', META);
		} else {
			root.classList.remove(NAME); // owui won't clean up after us
		}
	};

	window.applyTheme = paint; // their hook, our hands

	const graft = (sel) => {
		// identified by its options, not its label — survives i18n and renames
		if (!sel.querySelector('option[value="oled-dark"]')) return;
		if (sel.querySelector('option[value="' + NAME + '"]')) return;
		const opt = document.createElement('option');
		opt.value = NAME;
		opt.textContent = LABEL;
		sel.appendChild(opt);
		if (isPetal()) sel.value = NAME;
		console.log('🌸 petal: grafted into theme select');
	};

	const sweep = () => document.querySelectorAll('select').forEach(graft);

	// three nets, because one silent failure is enough
	new MutationObserver((muts) => {
		for (const m of muts)
			for (const n of m.addedNodes) {
				if (n.nodeType !== 1) continue; // skip streaming text nodes
				if (n.tagName === 'SELECT') graft(n);
				else if (n.querySelectorAll) n.querySelectorAll('select').forEach(graft);
			}
	}).observe(root, { childList: true, subtree: true });

	document.addEventListener('click', () => setTimeout(sweep, 120), true);
	document.addEventListener('DOMContentLoaded', () => {
		paint();
		sweep();
	});

	paint();
	console.log('🌸 petal registrar alive — theme is', localStorage.getItem('theme'));
})();

// 🌸 petal — script garden v0.1 · layered under the registrar, never over it.
// each entry wakes one petal script; they load after the registrar, in order.
(() => {
	if (window.__petalGarden) return;
	window.__petalGarden = true;

	for (const src of ['/static/petal/hush.js', '/static/petal/probe.js']) {
		const s = document.createElement('script');
		s.src = src;
		s.async = false; // keep garden order
		s.onerror = () => console.warn('🌸 petal garden: could not load', src);
		document.head.appendChild(s);
	}
})();

// ✨ petal — the fx door v0.1 (slice A18b) · a quote effect, if the rig offers one.
// asks /api/v1/petal/fx/look (OWUI forwards it to the rig's effects service); the look names the
// scripts to wake, served through the same door, and they register window.petalQuoteFx. quiet when
// the door is closed (no service, signed out, offline): quotes keep their static face, nothing waits.
// display quotes knock again as they arrive (window.petalFxOpen), at most once a minute.
(() => {
	if (window.petalFxOpen) return;
	const BASE = '/api/v1/petal/fx/';
	const SAFE = /^[a-z0-9][a-z0-9._-]*(\/[a-z0-9][a-z0-9._-]*)*$/i; // a plain relative path, nothing else
	const COOLDOWN_MS = 60000;
	const woken = new Set(); // a script wakes once per page
	let opening = null;
	let lastTry = 0;

	const wake = (src) =>
		new Promise((resolve, reject) => {
			if (woken.has(src)) return resolve();
			woken.add(src);
			const s = document.createElement('script');
			s.src = BASE + src;
			s.async = false;
			s.onload = resolve;
			s.onerror = () => {
				woken.delete(src); // it may wake next time
				s.remove();
				reject(new Error(src));
			};
			document.head.appendChild(s);
		});

	window.petalFxOpen = () => {
		if (window.petalQuoteFx) return Promise.resolve(true);
		if (window.petalFxDeclined) return Promise.resolve(false); // the effect said this device can't (no webgl2…)
		if (opening) return opening;
		if (Date.now() - lastTry < COOLDOWN_MS) return Promise.resolve(false);
		lastTry = Date.now();
		opening = (async () => {
			const ctl = new AbortController();
			const timer = setTimeout(() => ctl.abort(), 3000);
			try {
				const token = localStorage.getItem('token');
				const r = await fetch(BASE + 'look', {
					credentials: 'same-origin',
					cache: 'no-store',
					signal: ctl.signal,
					headers: token ? { Authorization: `Bearer ${token}` } : {}
				});
				if (!r.ok) return false;
				const look = await r.json();
				const scripts = (Array.isArray(look?.load) ? look.load : []).filter(
					(p) => typeof p === 'string' && SAFE.test(p) && !p.includes('..')
				);
				if (!scripts.length) return false;
				window.petalFxLook = Object.freeze({ ...look, base: BASE });
				for (const src of scripts) await wake(src);
				return !!window.petalQuoteFx;
			} catch {
				return false; // asleep, unreachable or signed out: quiet
			} finally {
				clearTimeout(timer);
				opening = null;
			}
		})();
		return opening;
	};

	window.petalFxOpen();
})();
