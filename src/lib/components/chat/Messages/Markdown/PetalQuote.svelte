<script lang="ts">
	// 🌸 the display quote (slice A17). in a reply, a blockquote is usually the heart of the message
	// (identity lines, vows, words to repeat), so it's set as display type: the theme's display face,
	// bigger and bolder, in the accent gradient, with room above and below so the line stands alone.
	// only display contexts ask for it (`display`); every other quote keeps the plain look. its text
	// tokens read the context below to dress their own quotation marks and keep emoji in colour.
	// ✨ A18: the shimmer, a reveal that plays once when the quote first settles into view (a drifting
	// light, a silk sweep, an aura and a few stars); a hover replays it.
	// 🌸 A19: the words are always painted first. the real words (selectable, copied, voiced) wear a
	// solid ink of their own; every effect is a layer that only ever sits on top or behind them:
	//   glow  · a copy behind the letters, its own soft halo (the glyphs are never blurred)
	//   ink   · a copy on top in the accent gradient, with a soft gloss on every line
	//   sheen · a band of light crossing a copy now and then (moved by the compositor, never repainted)
	// if a layer ever fails to paint, the words beneath still show. the door ($lib/utils/petal-quote-fx)
	// decides when anything moves; a click reveals it and lets her voice say just that line.
	import { onDestroy, setContext } from 'svelte';
	import { PLAY_MS, enroll, replay, touch } from '$lib/utils/petal-quote-fx';
	import { speakQuote } from '$lib/utils/petal-voice';

	export let display = false;
	// the quote's words as written, and whether its message is done streaming
	export let raw = '';
	export let done = true;

	setContext('petal-quote', display);

	type Spark = {
		kind: 'big' | 'four' | 'small';
		x: number;
		y: number;
		size: number;
		at: number;
		life: number;
		rot: number;
	};

	let el: HTMLElement | null = null;
	let baseEl: HTMLElement | null = null;
	let glowEl: HTMLElement | null = null;
	let inkEl: HTMLElement | null = null;
	let sheenEl: HTMLElement | null = null;
	let glintsEl: HTMLElement | null = null;
	let revealing = false;
	let selecting = false;
	let sparks: Spark[] = [];
	let armed = true; // a hover reveals once per visit
	let mo: MutationObserver | null = null;
	let syncFrame = 0;
	let off: (() => void) | null = null;

	const reduced = () => !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

	// ── the layers are copies of the real words, kept in step with them (streaming included) ──────
	function copyInto(target: HTMLElement | null) {
		if (!target || !baseEl) return;
		const frag = document.createDocumentFragment();
		for (const n of baseEl.childNodes) {
			const c = n.cloneNode(true);
			if (c instanceof Element) {
				c.removeAttribute('id');
				c.querySelectorAll('[id]').forEach((x) => x.removeAttribute('id'));
			}
			frag.appendChild(c);
		}
		target.replaceChildren(frag);
	}
	const sync = () => {
		syncFrame = 0;
		copyInto(glowEl);
		copyInto(inkEl);
	};
	const syncSoon = () => {
		if (!syncFrame) syncFrame = requestAnimationFrame(sync);
	};

	// ── a band of light across the words: a window slides over a copy that slides back the other
	// way, so the copy stays on its letters (two transforms, run by the compositor) ───────────────
	function shine() {
		if (!sheenEl || reduced()) return;
		const W = sheenEl.clientWidth;
		if (W < 40) return;
		const win = sheenEl.firstElementChild as HTMLElement | null;
		const words = win?.firstElementChild as HTMLElement | null;
		if (!win || !words || words.childNodes.length) return; // one shine at a time
		const w = Math.max(90, W * 0.38);
		copyInto(words);
		words.style.width = `${W}px`;
		win.style.width = `${w}px`;
		const timing: KeyframeAnimationOptions = {
			duration: 2000 + Math.min(800, W), // slow: a gloss, not a flash (and done within its beat)
			easing: 'cubic-bezier(0.45, 0.05, 0.55, 0.95)'
		};
		win.animate(
			[
				{ transform: `translateX(${-w}px)`, opacity: 1 },
				{ transform: `translateX(${W}px)`, opacity: 1 }
			],
			timing
		);
		const a = words.animate(
			[{ transform: `translateX(${w}px)` }, { transform: `translateX(${-W}px)` }],
			timing
		);
		a.onfinish = a.oncancel = () => words.replaceChildren();
	}

	// ── one faint star near the words, once (its own little element, gone when it's done) ──────────
	function star() {
		if (!glintsEl || reduced()) return;
		const s = scatter(true)[0];
		if (!s) return;
		const i = document.createElement('i');
		i.className = `pq-spark pq-${s.kind} pq-glint`;
		i.style.cssText = `left:${s.x}px;top:${s.y}px;--sz:${s.size}px;--at:0ms;--life:${s.life}ms;--rot:${s.rot}deg`;
		glintsEl.appendChild(i);
		setTimeout(() => i.remove(), s.life + 100);
	}

	// ── a display quote joins the door once its layers exist (and leaves it if it stops being one) ──
	function arm() {
		if (!el || !baseEl) return;
		sync();
		mo = new MutationObserver(syncSoon);
		mo.observe(baseEl, {
			subtree: true,
			childList: true,
			characterData: true,
			attributes: true,
			attributeFilter: ['class', 'style']
		});
		off = enroll(el, {
			reveal: () => {
				sparks = reduced() ? [] : scatter(false);
				revealing = true;
			},
			stop: () => {
				revealing = false;
				sparks = [];
			},
			shine,
			star,
			selecting: (on) => (selecting = on)
		});
		touch(el, raw, done);
	}
	function disarm() {
		mo?.disconnect();
		mo = null;
		if (syncFrame) cancelAnimationFrame(syncFrame);
		syncFrame = 0;
		off?.();
		off = null;
		revealing = false;
		sparks = [];
	}

	$: if (display && el && baseEl && !off) arm();
	$: if ((!display || !el) && off) disarm();
	$: if (off && el) touch(el, raw, done);

	onDestroy(disarm);

	// stars around the words (never on them): for the reveal, the brightest by the opening mark, one
	// past the end of the last line, small twinkles on the edges; for a glint, one small star · placed
	// in px from the quote's own box
	function scatter(one: boolean): Spark[] {
		if (!el) return [];
		const box = el.getBoundingClientRect();
		const range = document.createRange();
		range.selectNodeContents(baseEl ?? el);
		const lines = [...range.getClientRects()].filter((r) => r.width > 1 && r.height > 1);
		if (!lines.length || box.width < 60) return [];
		const words = lines.reduce(
			(u, r) => ({
				l: Math.min(u.l, r.left),
				t: Math.min(u.t, r.top),
				r: Math.max(u.r, r.right),
				b: Math.max(u.b, r.bottom)
			}),
			{ l: Infinity, t: Infinity, r: -Infinity, b: -Infinity }
		);
		const last = lines.reduce((a, r) =>
			r.bottom > a.bottom + 1 || (Math.abs(r.bottom - a.bottom) <= 1 && r.right > a.right) ? r : a
		);
		const em = parseFloat(getComputedStyle(el.querySelector('p') ?? el).fontSize) || 20;
		const W = box.width;
		const L = words.l - box.left;
		const T = words.t - box.top;
		const R = words.r - box.left;
		const B = words.b - box.top;
		const rnd = (a: number, b: number) => a + Math.random() * (b - a);
		const out: Spark[] = [];
		const add = (
			kind: Spark['kind'],
			x: number,
			y: number,
			size: number,
			at: number,
			life: number
		) => {
			const px = size * em;
			out.push({
				kind,
				x: Math.min(Math.max(x, px / 2), W - px / 2), // never past the quote's sides (no sideways scroll)
				y,
				size: px,
				at,
				life,
				rot: rnd(-12, 12)
			});
		};
		if (one) {
			// a glint: one small star on an edge of the words, somewhere new each time
			const side = Math.floor(rnd(0, 4));
			const x = side === 0 ? L - rnd(0.1, 0.4) * em : side === 1 ? R + rnd(0.1, 0.4) * em : L + (R - L) * rnd(0.1, 0.9);
			const y = side === 2 ? T - rnd(0.05, 0.3) * em : side === 3 ? B + rnd(0.05, 0.3) * em : T + (B - T) * rnd(0.2, 0.8);
			add(Math.random() < 0.3 ? 'four' : 'small', x, y, rnd(0.4, 0.62), 0, rnd(1300, 1800));
			return out;
		}
		add('big', L + rnd(-0.2, 0.1) * em, T + rnd(0.05, 0.3) * em, rnd(1.15, 1.45), rnd(250, 420), rnd(2300, 2800));
		add(
			'four',
			last.right - box.left + rnd(0.45, 0.75) * em,
			(last.top + last.bottom) / 2 - box.top - rnd(0.1, 0.4) * em,
			rnd(0.75, 1),
			rnd(850, 1150),
			rnd(1900, 2400)
		);
		if (W >= 420)
			add('four', L + (R - L) * rnd(0.45, 0.8), T - rnd(0.1, 0.35) * em, rnd(0.65, 0.9), rnd(1500, 1900), rnd(1700, 2200));
		add('small', L + (R - L) * rnd(0.15, 0.45), T - rnd(0.05, 0.3) * em, rnd(0.38, 0.52), rnd(600, 800), rnd(1500, 1900));
		add('small', L + (R - L) * rnd(0.55, 0.95), B + rnd(0.05, 0.3) * em, rnd(0.38, 0.52), rnd(1900, 2300), rnd(1500, 1900));
		return out;
	}

	// a hover (mouse, pen) reveals it once per visit; a click or a tap reveals it and lets her voice say
	// just that line (unless she's already speaking, or words are being selected) · only a display
	// quote listens (an action, so a plain quote carries no handlers at all)
	function gestures(node: HTMLElement) {
		const enter = (e: PointerEvent) => {
			if (e.pointerType === 'touch' || !armed) return;
			armed = false;
			replay(node);
		};
		const leave = () => (armed = true);
		// a click waits a breath: a second one means words are being picked (a double click selects)
		let pending: ReturnType<typeof setTimeout> | null = null;
		const selecting = () => {
			const sel = window.getSelection();
			return !!(sel && !sel.isCollapsed && sel.anchorNode && node.contains(sel.anchorNode));
		};
		const click = (e: MouseEvent) => {
			if ((e.target as Element)?.closest?.('a, button, code, pre, input, textarea')) return;
			if (pending) clearTimeout(pending);
			pending = null;
			if (e.detail > 1 || selecting()) return;
			pending = setTimeout(() => {
				pending = null;
				if (selecting()) return;
				replay(node, true);
				speakQuote(node);
			}, 260);
		};
		node.addEventListener('pointerenter', enter);
		node.addEventListener('pointerleave', leave);
		node.addEventListener('click', click);
		return {
			destroy() {
				if (pending) clearTimeout(pending);
				node.removeEventListener('pointerenter', enter);
				node.removeEventListener('pointerleave', leave);
				node.removeEventListener('click', click);
			}
		};
	}
</script>

{#if display}
	<blockquote
		bind:this={el}
		dir="auto"
		class="petal-quote"
		class:pq-reveal={revealing}
		class:pq-selecting={selecting}
		style:--pq-play={`${PLAY_MS}ms`}
		use:gestures
	>
		<div class="pq-words pq-glow pq-copy" aria-hidden="true" inert translate="no" bind:this={glowEl}></div>
		<div class="pq-words pq-base" bind:this={baseEl}><slot /></div>
		<div class="pq-words pq-ink pq-copy" aria-hidden="true" inert translate="no" bind:this={inkEl}></div>
		<div class="pq-sheen pq-copy" aria-hidden="true" inert translate="no" bind:this={sheenEl}>
			<div class="pq-sheen-win"><div class="pq-words pq-sheen-words"></div></div>
		</div>
		<span class="pq-sparks pq-glints pq-copy" aria-hidden="true" inert bind:this={glintsEl}></span>
		{#if revealing && sparks.length}
			<span class="pq-sparks pq-copy" aria-hidden="true" inert
				>{#each sparks as s}<i
						class="pq-spark pq-{s.kind}"
						style="left: {s.x}px; top: {s.y}px; --sz: {s.size}px; --at: {s.at}ms; --life: {s.life}ms; --rot: {s.rot}deg"
					></i>{/each}</span
			>
		{/if}
	</blockquote>
{:else}
	<blockquote dir="auto"><slot /></blockquote>
{/if}

<style>
	/* light first (no .dark): deep candy into deep iris keeps its contrast on white. gradients lean
	   purple-up, pink-down (80deg: the top lines a breath more iris), and pink never stands flat.
	   the ink is mirrored and twice as wide as the words: its first half is the resting gradient, the
	   whole is the road the reveal drifts along and back. --pq-solid is the words' own ink, the one
	   that shows wherever no layer paints (and at the antialiased edges under the gradient) */
	.petal-quote {
		--pq-ink: linear-gradient(80deg, #c2337f 0%, #ad3a96 23%, #7b4fc4 50%, #ad3a96 77%, #c2337f 100%);
		--pq-solid: #ad3a96;
		--pq-mark: linear-gradient(175deg, #7b4fc4 0%, #d4408f 100%);
		--pq-mark-solid: #a8479f;
		--pq-edge: linear-gradient(180deg, #8f5bd1 0%, #d4408f 55%, #f0a8cf 100%);
		--pq-select: #3b0f2e;
		--pq-select-bg: rgb(212 64 143 / 0.18);
		--pq-gloss: rgb(255 255 255 / 0.26);
		--pq-sheen: rgb(255 255 255 / 0.42);
		--pq-sheen-ink: rgb(255 255 255 / 0.78);
		--pq-aura: rgb(212 64 143 / 0.34);
		--pq-glow: rgb(143 91 209 / 0.22);
		--pq-rest-glow: 0.5;
		--pq-star: 212 64 143;
		position: relative;
		isolation: isolate; /* every layer stays inside the quote, in front of the page */
		display: grid; /* the layers share one cell: same width, same lines, same letters */
		margin: 1.2em 0;
		padding-block: 0.1em;
		padding-inline: 1em 0;
		border-inline-start: 0;
		color: inherit;
		font-size: inherit; /* upstream sets quotes smaller and muted, like footnotes */
		font-style: normal;
		font-weight: 600;
		font-variation-settings: 'SOFT' 60;
		letter-spacing: -0.01em;
		line-height: 1.4;
		overflow-wrap: break-word;
	}
	:global(.dark) .petal-quote {
		--pq-ink: linear-gradient(
			80deg,
			var(--candy-light, #ffe1f2) 0%,
			var(--candy, #ff90cf) 23%,
			var(--iris, #c07de0) 50%,
			var(--candy, #ff90cf) 77%,
			var(--candy-light, #ffe1f2) 100%
		);
		--pq-solid: var(--candy, #ff90cf);
		--pq-mark: linear-gradient(175deg, var(--iris, #c07de0) 0%, var(--candy, #ff5bb0) 100%);
		--pq-mark-solid: var(--iris, #d391e8);
		--pq-edge: linear-gradient(180deg, var(--iris, #c07fdd) 0%, var(--candy, #ff5bb0) 55%, var(--candy-light, #ffcce9) 100%);
		--pq-select: var(--pearl, #fff4f9);
		--pq-select-bg: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.28);
		--pq-gloss: rgb(255 255 255 / 0.3);
		--pq-sheen: rgb(255 255 255 / 0.55);
		--pq-sheen-ink: rgb(255 246 252 / 0.92);
		--pq-aura: rgb(255 77 190 / 0.72); /* the aura's candy */
		--pq-glow: rgb(255 122 206 / 0.42); /* the glow around it */
		--pq-rest-glow: 0.55;
		--pq-star: 255 158 219; /* the stars' blush */
	}

	/* the app sets every element's face with !important (the sovereign emoji fallback in app.css, and
	   the skin's own): inside the quote its display face wins, code keeps its mono, math its own */
	.petal-quote,
	.petal-quote :global(*:not(code, pre, kbd, samp, code *, pre *, .katex, .katex *)) {
		font-family:
			var(--font-display, 'Fraunces', ui-serif, Georgia, serif),
			var(--font-emoji, 'SamsungColorEmoji', 'Noto Color Emoji'), serif !important;
	}
	.petal-quote :global(.pq-emoji) {
		font-family: var(--font-emoji, 'SamsungColorEmoji', 'Noto Color Emoji'), sans-serif !important;
	}

	/* the accent hairline where the grey bar stood (over every layer) */
	.petal-quote::before {
		content: '';
		position: absolute;
		z-index: 2;
		inset-block: 0.3em;
		inset-inline-start: 0;
		width: 2px;
		border-radius: 2px;
		background: var(--pq-edge);
		opacity: 0.9;
	}

	/* ── the words, in every layer alike: the same lines in the same places ───────────────────────
	   the first paragraph is the display line, the rest step down a little so longer quotes read */
	.petal-quote > .pq-words,
	.petal-quote > .pq-sheen {
		grid-area: 1 / 1;
		min-width: 0;
	}
	.petal-quote .pq-words > :global(p) {
		width: fit-content;
		max-width: 100%;
		margin: 0 0 0.55em;
		font-size: 1.15em;
		font-weight: 560;
		line-height: 1.42;
		text-wrap: pretty;
	}
	.petal-quote .pq-words > :global(p:first-of-type) {
		font-size: 1.35em;
		font-weight: 600;
		line-height: 1.34;
		text-wrap: balance;
	}
	.petal-quote .pq-words > :global(:last-child) {
		margin-bottom: 0;
	}
	/* each line between breaks wraps on its own, evenly (a lone word never hangs on the phone) */
	.petal-quote .pq-words :global(.pq-line) {
		display: block;
		text-wrap: balance;
	}
	/* the quote's own marks, kept: curly, a little larger (their size never spreads the lines) */
	.petal-quote .pq-words :global(.pq-mark) {
		font-size: 1.22em;
		line-height: 0;
		font-weight: 500;
	}
	.petal-quote .pq-words :global(code) {
		font-size: 0.8em;
		font-weight: 500;
	}
	.petal-quote .pq-words :global(strong) {
		font-weight: 760;
	}

	/* ── base · the real words, always painted, in their own solid ink ─────────────────────────── */
	.petal-quote .pq-base {
		color: var(--pq-solid);
		-webkit-text-fill-color: var(--pq-solid);
	}
	.petal-quote .pq-base :global(.pq-mark) {
		color: var(--pq-mark-solid);
		-webkit-text-fill-color: var(--pq-mark-solid);
	}
	/* emoji keep their colours, code stays code */
	.petal-quote .pq-base :global(.pq-emoji),
	.petal-quote .pq-base :global(.emoji),
	.petal-quote .pq-base :global(code) {
		-webkit-text-fill-color: initial;
	}
	/* selected words read in one solid ink over a candy wash, and the layers above step aside */
	.petal-quote .pq-base :global(::selection) {
		-webkit-text-fill-color: var(--pq-select);
		color: var(--pq-select);
		background: var(--pq-select-bg);
	}
	.petal-quote.pq-selecting > .pq-ink,
	.petal-quote.pq-selecting > .pq-sheen {
		opacity: 0;
	}

	/* ── the copies only echo the words: never touched, never selected, never copied; what isn't a
	   letter (emoji, code, pictures, buttons, math) shows once, from the words themselves ────────── */
	.pq-copy {
		pointer-events: none;
		user-select: none;
	}
	.pq-copy :global(:is(img, svg, video, canvas, iframe, input, button, select, textarea, .katex)) {
		visibility: hidden;
	}

	/* ── glow · behind the letters: a copy whose letters are clear and whose halo is soft ──────── */
	.pq-glow {
		position: relative;
		z-index: -1; /* under the words, whatever paints first (its opacity would lift it otherwise) */
		opacity: var(--pq-rest-glow);
	}
	.pq-glow,
	.pq-glow :global(*) {
		color: transparent !important;
		-webkit-text-fill-color: transparent !important;
		background: none !important;
		text-shadow:
			0 0 0.18em var(--pq-aura),
			0 0 0.55em var(--pq-glow);
	}

	/* ── ink · on top: the accent gradient, with a soft gloss across the top of every line ─────── */
	.pq-ink {
		color: transparent; /* its underlines and its own fill stay out: only the gradient shows */
	}
	/* (a browser that can't cut a background to letters paints no ink at all: the words below show) */
	@supports (background-clip: text) or (-webkit-background-clip: text) {
		.pq-ink > :global(p) {
			background-image:
				linear-gradient(180deg, var(--pq-gloss) 0%, transparent 46%),
				var(--pq-ink);
			background-size:
				100% 1lh,
				200% 100%;
			background-repeat: repeat-y, no-repeat;
			background-position:
				0 0,
				0% 0;
			-webkit-background-clip: text;
			background-clip: text;
			-webkit-text-fill-color: transparent;
		}
		.pq-ink :global(.pq-mark) {
			background: var(--pq-mark);
			-webkit-background-clip: text;
			background-clip: text;
			-webkit-text-fill-color: transparent;
		}
	}
	.pq-ink :global(.pq-emoji),
	.pq-ink :global(.emoji),
	.pq-ink :global(code) {
		visibility: hidden;
	}

	/* ── sheen · a band of light that crosses now and then (the window and its copy slide) ─────── */
	.pq-sheen {
		position: relative;
		overflow: hidden;
	}
	.pq-sheen-win {
		position: absolute;
		inset-block: 0;
		left: 0;
		overflow: hidden;
		opacity: 0;
		-webkit-mask-image: linear-gradient(105deg, transparent 12%, #000 50%, transparent 88%);
		mask-image: linear-gradient(105deg, transparent 12%, #000 50%, transparent 88%);
	}
	.pq-sheen-words {
		position: absolute;
		top: 0;
		left: 0;
		color: var(--pq-sheen-ink);
		-webkit-text-fill-color: var(--pq-sheen-ink);
	}
	.pq-sheen-words :global(.pq-emoji),
	.pq-sheen-words :global(.emoji),
	.pq-sheen-words :global(code) {
		visibility: hidden;
	}

	/* ── ✨ the reveal (A18's shimmer, on the layers): a candy light, for one play ─────────────────
	   drift · the light's sway, as the ink gliding through the letters and back to rest
	   silk  · a soft white band crossing at 20°
	   aura  · the glow layer swells and settles back to its resting halo
	   stars · a big four-ray star, smaller four-rays and twinkles: hot core, colour core, halo, rays */
	@property --pq-drift {
		syntax: '<percentage>';
		inherits: false;
		initial-value: 0%;
	}
	@property --pq-sweep {
		syntax: '<percentage>';
		inherits: false;
		initial-value: 100%;
	}
	@supports (background-clip: text) or (-webkit-background-clip: text) {
		.petal-quote.pq-reveal > .pq-ink > :global(p) {
			background-image:
				linear-gradient(
					110deg,
					transparent 46.5%,
					color-mix(in srgb, var(--pq-sheen) 55%, transparent) 48.8%,
					var(--pq-sheen) 50%,
					color-mix(in srgb, var(--pq-sheen) 55%, transparent) 51.2%,
					transparent 53.5%
				),
				linear-gradient(180deg, var(--pq-gloss) 0%, transparent 46%),
				var(--pq-ink);
			background-size:
				300% 100%,
				100% 1lh,
				200% 100%;
			background-repeat: no-repeat, repeat-y, no-repeat;
			background-position:
				var(--pq-sweep) 0,
				0 0,
				var(--pq-drift) 0;
			animation:
				pq-drift calc(var(--pq-play) / 2) ease-in-out 0s 2 alternate both,
				pq-silk calc(var(--pq-play) * 0.7) cubic-bezier(0.45, 0.05, 0.55, 0.95) calc(var(--pq-play) * 0.1) 1 both;
		}
	}
	.petal-quote.pq-reveal > .pq-glow {
		animation: pq-aura var(--pq-play) ease-out 0s 1 both;
	}
	@keyframes pq-drift {
		from {
			--pq-drift: 0%;
		}
		to {
			--pq-drift: 100%;
		}
	}
	@keyframes pq-silk {
		from {
			--pq-sweep: 100%;
		}
		to {
			--pq-sweep: 0%;
		}
	}
	@keyframes pq-aura {
		0%,
		100% {
			opacity: var(--pq-rest-glow);
		}
		24%,
		62% {
			opacity: 1;
		}
	}

	.pq-sparks {
		position: absolute;
		inset: 0;
		z-index: -1;
	}
	.pq-spark,
	.pq-glints :global(.pq-spark) {
		--ray: max(1.5px, calc(var(--sz) * 0.05));
		position: absolute;
		width: var(--sz);
		height: var(--sz);
		margin: calc(var(--sz) / -2) 0 0 calc(var(--sz) / -2);
		opacity: 0;
		background:
			radial-gradient(circle, rgb(255 255 255 / var(--hot, 0.8)) 0, rgb(255 255 255 / 0) calc(var(--sz) * 0.09)),
			radial-gradient(circle, rgb(var(--pq-star) / 0.95) 0, rgb(var(--pq-star) / 0) calc(var(--sz) * 0.17)),
			radial-gradient(circle, rgb(var(--pq-star) / var(--halo, 0.36)) 0, rgb(var(--pq-star) / 0) calc(var(--sz) * 0.36)),
			linear-gradient(90deg, rgb(var(--pq-star) / 0), rgb(var(--pq-star) / 0.92) 50%, rgb(var(--pq-star) / 0)) center /
				100% var(--ray) no-repeat,
			linear-gradient(0deg, rgb(var(--pq-star) / 0), rgb(var(--pq-star) / 0.92) 50%, rgb(var(--pq-star) / 0)) center /
				var(--ray) 100% no-repeat;
		animation: pq-twinkle var(--life) cubic-bezier(0.33, 0.7, 0.4, 1) var(--at) 1 both;
	}
	/* a resting glint is fainter than a reveal's star */
	.pq-glints :global(.pq-glint) {
		--hot: 0.45;
		--halo: 0.18;
		animation-name: pq-glint;
	}
	.pq-spark:global(.pq-big) {
		--hot: 1;
		--halo: 0.45;
	}
	/* the big star's short diagonals (45° and 135°) */
	.pq-spark:global(.pq-big)::before {
		content: '';
		position: absolute;
		inset: 22%;
		rotate: 45deg;
		background:
			linear-gradient(90deg, rgb(var(--pq-star) / 0), rgb(var(--pq-star) / 0.5) 50%, rgb(var(--pq-star) / 0)) center /
				100% var(--ray) no-repeat,
			linear-gradient(0deg, rgb(var(--pq-star) / 0), rgb(var(--pq-star) / 0.5) 50%, rgb(var(--pq-star) / 0)) center /
				var(--ray) 100% no-repeat;
	}
	.pq-spark:global(.pq-four) {
		--hot: 0.7;
		--halo: 0.34;
	}
	.pq-spark:global(.pq-small) {
		--hot: 0.5;
		--halo: 0.22;
	}
	/* the twinkle, drawn once: up from nothing, a dip, a second wink, gone before the rest */
	@keyframes pq-twinkle {
		0% {
			opacity: 0;
			transform: scale(0.15) rotate(var(--rot));
		}
		20% {
			opacity: 1;
			transform: scale(1) rotate(calc(var(--rot) + 10deg));
		}
		42% {
			opacity: 0.6;
			transform: scale(0.7) rotate(calc(var(--rot) + 16deg));
		}
		64% {
			opacity: 1;
			transform: scale(1.06) rotate(calc(var(--rot) + 22deg));
		}
		100% {
			opacity: 0;
			transform: scale(0.2) rotate(calc(var(--rot) + 32deg));
		}
	}
	@keyframes pq-glint {
		0% {
			opacity: 0;
			transform: scale(0.2) rotate(var(--rot));
		}
		45% {
			opacity: 0.75;
			transform: scale(1) rotate(calc(var(--rot) + 14deg));
		}
		100% {
			opacity: 0;
			transform: scale(0.3) rotate(calc(var(--rot) + 28deg));
		}
	}

	/* reduced motion: the resting look, always (the door won't start a reveal or a gloss either) */
	@media (prefers-reduced-motion: reduce) {
		.petal-quote.pq-reveal > .pq-ink > :global(p),
		.petal-quote.pq-reveal > .pq-glow {
			animation: none;
		}
		.pq-sparks {
			display: none;
		}
	}
</style>
