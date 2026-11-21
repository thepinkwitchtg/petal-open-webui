/* ═══════════════════════════════════════════════════════════
   🌸 petal · type  ·  v0.2 (A35) · nothing of hers appears pre-written
   one small engine for every Petal text the page shows that was written before it showed: hush's
   whispers and her thank-you, the notes and little words in toasts, a note the page leaves her.
   live streams keep streaming as they are; only what arrives whole types itself in.

   · paced to its length: a short line takes its time, a long one quickens (and never runs past a few
     seconds), with the small unevenness of a hand and a short pause after , ; : and . ! ? … ~
   · her speed: Settings → 🌸 Petal → Typing (natural · slow · quick · at once), kept on this device in
     localStorage 'petal.type.speed' (the app mirrors her setting there). typing is text arriving, not
     movement, so it types even with reduced motion: 'at once' is the switch for that
   · event-driven: a job starts when a text arrives and steps on requestAnimationFrame, writing on every
     frame a letter changes (A35: full beauty, no ~32 ms gate), stops the moment it's done, and holds while
     the page is hidden (no letter and no frame there, even where a browser keeps frames coming; the hidden
     time never counts), carrying on from where it was when she's back. slow frames still type in real time
     (a few letters a frame). nothing runs at rest.
   · A35 · a job can hold where it is while its place is off her screen (hold(true)), and carries on from
     there (hold(false)); the time it held never counts either.

   window.petalType:
     run({ text, write(partial, done), speed? }) → { cancel(), finish(), hold(on), done }   (write('') at once)
     ms(text, speed?)   how long it takes to type     ·     speed() / speed('quick')     ·     active
   ═══════════════════════════════════════════════════════════ */
(() => {
	if (window.petalType) return;

	const KEY = 'petal.type.speed';
	const PACE = { natural: 1, slow: 1.6, quick: 0.55, instant: 0 };
	const CAP = { natural: 3600, slow: 5200, quick: 2200 }; // the longest a text takes, whatever its length
	const BASE = 34; // ms a grapheme, at natural, for a line of about forty
	const FROZEN = 1000; // a gap between frames this long, with the page never hidden, was a freeze: it doesn't count

	let jobs = 0;
	// how long the page has been hidden in all (no frames come then): a job's time never counts it
	let hiddenMs = 0;
	let hiddenSince = null;
	const asleep = new Set(); // jobs holding while the page is hidden: each wakes the moment she's back
	const onVisibility = () => {
		const t = performance.now();
		if (document.visibilityState === 'hidden') hiddenSince ??= t;
		else {
			if (hiddenSince !== null) {
				hiddenMs += t - hiddenSince;
				hiddenSince = null;
			}
			for (const wake of [...asleep]) wake();
		}
	};
	document.addEventListener('visibilitychange', onVisibility);
	onVisibility();
	const hiddenNow = () => hiddenMs + (hiddenSince !== null ? performance.now() - hiddenSince : 0);
	const graphemes = (s) =>
		typeof Intl !== 'undefined' && Intl.Segmenter
			? [...new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(s)].map((g) => g.segment)
			: [...s];

	const speed = (set) => {
		try {
			if (set !== undefined) {
				if (PACE[set] === undefined) return speed();
				localStorage.setItem(KEY, set);
			}
			const v = localStorage.getItem(KEY);
			return PACE[v] !== undefined ? v : 'natural';
		} catch (_) {
			return 'natural';
		}
	};

	/* when each grapheme shows: at[i] ms after the start (a beat before the first), and the total */
	const plan = (text, sp = speed()) => {
		const g = graphemes(String(text ?? ''));
		const k = PACE[sp] ?? 1;
		const n = g.length;
		if (!k || !n) return { g, at: g.map(() => 0), total: 0 };
		const per = BASE * k * Math.pow(40 / Math.max(40, n), 0.35); // the longer the text, the quicker each
		const at = [];
		let [t, even] = [per, per]; // with a hand's unevenness, and without it (the length it should take)
		for (let i = 0; i < n; i++) {
			at.push(t);
			let [d, e] = [per * (0.65 + Math.random() * 0.7), per];
			const ch = g[i];
			if (i < n - 1) {
				const pause = /[.!?…~]/u.test(ch) && g[i + 1] === ' ' ? 150 * k : /[,;:]/u.test(ch) ? 80 * k : 0;
				const space = ch === ' ' ? 0.8 : 1;
				[d, e] = [d * space + pause, e * space + pause];
			}
			[t, even] = [t + d, even + e];
		}
		// the unevenness moves letters, never the length: the whole takes exactly what ms() says (a toast's time
		// and the words that follow it are counted from that)
		const total = Math.min(CAP[sp] ?? CAP.natural, even - per); // its last letter shows here, never past the cap
		const s = total / at[n - 1];
		for (let i = 0; i < n; i++) at[i] *= s;
		return { g, at, total };
	};

	const ms = (text, sp) => Math.round(plan(text, sp).total);

	const run = ({ text, write, speed: sp } = {}) => {
		const p = plan(text, sp ?? speed());
		const full = p.g.join('');
		const job = { shown: -1, done: false, cancelled: false };
		let raf = 0;
		let e = 0; // how long it has been typing: frame gaps, minus any time the page was hidden
		let last = null;
		let lastHidden = 0;
		let held = false; // its place is off her screen (A35): no letter, no frame, the time doesn't count
		const put = (n) => {
			if (n === job.shown) return;
			job.shown = n;
			const done = n >= p.g.length;
			try {
				write(done ? full : p.g.slice(0, n).join(''), done);
			} catch (_) {}
			if (done) end();
		};
		const end = () => {
			if (job.done) return;
			job.done = true;
			if (raf) cancelAnimationFrame(raf);
			raf = 0;
			asleep.delete(wake);
			jobs = Math.max(0, jobs - 1);
		};
		// hidden: no letter and no frame (whatever a browser does with frames there); back: from where it was
		function wake() {
			asleep.delete(wake);
			if (!job.done && !raf && !held) raf = requestAnimationFrame(step);
		}
		function step(now) {
			raf = 0;
			if (job.done || held) return;
			if (document.visibilityState === 'hidden') return void asleep.add(wake);
			const hid = hiddenNow();
			if (last !== null) {
				let gap = now - last - (hid - lastHidden); // hidden time never counts
				if (gap > FROZEN) gap = 16; // a page frozen without a word (no frames, no hidden event): carry on
				e += Math.max(0, gap);
			}
			last = now;
			lastHidden = hid;
			let n = Math.max(0, job.shown);
			while (n < p.g.length && p.at[n] <= e) n++;
			if (n >= p.g.length) return put(n);
			if (n !== job.shown) put(n); // every frame a letter changes (A35)
			raf = requestAnimationFrame(step);
		}
		const handle = {
			cancel() {
				if (job.done) return;
				job.cancelled = true;
				end();
			},
			finish() {
				if (!job.done) put(p.g.length);
			},
			/** A35 · its place left her screen (true): it holds where it is · back (false): it carries on from there */
			hold(on) {
				if (job.done || held === !!on) return;
				held = !!on;
				if (held) {
					if (raf) cancelAnimationFrame(raf);
					raf = 0;
					last = null; // the time it holds never counts: the next frame starts the count again
				} else wake();
			},
			get done() {
				return job.done;
			},
			total: p.total
		};
		jobs += 1;
		if (!p.total) {
			put(p.g.length);
			return handle;
		}
		put(0); // the place starts empty this instant: never a flash of the whole line
		raf = requestAnimationFrame(step);
		return handle;
	};

	window.petalType = {
		run,
		ms,
		speed,
		/** jobs typing right now (numbers only, for her console and the tests) */
		get active() {
			return jobs;
		},
		/** numbers only: jobs, and how long the page has been hidden while a job could have typed */
		get facts() {
			return { jobs, hidden: hiddenSince !== null, hiddenMs: Math.round(hiddenNow()) };
		},
		v: '0.2'
	};
})();
