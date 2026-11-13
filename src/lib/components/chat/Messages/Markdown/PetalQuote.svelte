<script lang="ts">
	// 🌸 the display quote (slice A17). in a reply, a blockquote is usually the heart of the message
	// (identity lines, vows, words to repeat), so it's set as display type: the theme's display face,
	// bigger and bolder, in the accent gradient, with room above and below so the line stands alone.
	// only replies ask for it (`display`); every other quote keeps the plain look. its text tokens read
	// the context below to dress their own quotation marks and keep emoji in colour (display only: the
	// words stay as written).
	// ✨ A18: the shimmer. it plays once when it first settles into view (a drifting light, a silk sweep,
	// an aura and a few stars), then rests in the static gradient; a hover or a tap replays it once. the
	// motion is CSS that ends on its own, so at rest nothing runs.
	// ✨ A18b: one door ($lib/utils/petal-quote-fx) decides when a quote moves and who paints it: the
	// shimmer, or the rig's quote effect (the candy) when one is awake and the setting asks for it. the
	// candy paints on the stage under the words; the words stay real (transparent while painted) for
	// selection, copy and voice. Settings → Interface → Quotes: still · shimmer · candy · candy hypnotic.
	import { onMount, setContext } from 'svelte';
	import { PLAY_MS, enroll, replay, touch } from '$lib/utils/petal-quote-fx';

	export let display = false;
	// the quote's words as written, and whether its reply is done streaming
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

	let el: HTMLElement;
	let playing = false;
	let sparks: Spark[] = [];
	let armed = true; // a hover replays once per visit
	let lastPointer = '';

	onMount(() => {
		if (!display) return;
		return enroll(el, {
			play: () => {
				sparks = scatter();
				playing = true;
			},
			stop: () => {
				playing = false;
				sparks = [];
			}
		});
	});

	$: if (display && el) touch(el, raw, done);

	// a few stars around the words (never on them): the brightest by the opening mark, one past the end
	// of the last line, small twinkles on the edges · placed in px from the quote's own box
	function scatter(): Spark[] {
		const box = el.getBoundingClientRect();
		const range = document.createRange();
		range.selectNodeContents(el);
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
		add(
			'big',
			L + rnd(-0.2, 0.1) * em,
			T + rnd(0.05, 0.3) * em,
			rnd(1.15, 1.45),
			rnd(250, 420),
			rnd(2300, 2800)
		);
		add(
			'four',
			last.right - box.left + rnd(0.45, 0.75) * em,
			(last.top + last.bottom) / 2 - box.top - rnd(0.1, 0.4) * em,
			rnd(0.75, 1),
			rnd(850, 1150),
			rnd(1900, 2400)
		);
		if (W >= 420)
			add(
				'four',
				L + (R - L) * rnd(0.45, 0.8),
				T - rnd(0.1, 0.35) * em,
				rnd(0.65, 0.9),
				rnd(1500, 1900),
				rnd(1700, 2200)
			);
		add(
			'small',
			L + (R - L) * rnd(0.15, 0.45),
			T - rnd(0.05, 0.3) * em,
			rnd(0.38, 0.52),
			rnd(600, 800),
			rnd(1500, 1900)
		);
		add(
			'small',
			L + (R - L) * rnd(0.55, 0.95),
			B + rnd(0.05, 0.3) * em,
			rnd(0.38, 0.52),
			rnd(1900, 2300),
			rnd(1500, 1900)
		);
		return out;
	}

	// a hover (mouse, pen) replays it once per visit; a tap replays it unless words are being selected ·
	// only a display quote listens (an action, so a plain quote carries no handlers at all)
	function replays(node: HTMLElement) {
		if (!display) return;
		const down = (e: PointerEvent) => (lastPointer = e.pointerType);
		const enter = (e: PointerEvent) => {
			if (e.pointerType === 'touch' || !armed) return;
			armed = false;
			replay(node);
		};
		const leave = () => (armed = true);
		const tap = (e: MouseEvent) => {
			if (((e as PointerEvent).pointerType || lastPointer) !== 'touch') return;
			const sel = window.getSelection();
			if (sel && !sel.isCollapsed && sel.anchorNode && node.contains(sel.anchorNode)) return;
			replay(node);
		};
		node.addEventListener('pointerdown', down);
		node.addEventListener('pointerenter', enter);
		node.addEventListener('pointerleave', leave);
		node.addEventListener('click', tap);
		return {
			destroy() {
				node.removeEventListener('pointerdown', down);
				node.removeEventListener('pointerenter', enter);
				node.removeEventListener('pointerleave', leave);
				node.removeEventListener('click', tap);
			}
		};
	}
</script>

<blockquote
	bind:this={el}
	dir="auto"
	class:petal-quote={display}
	class:pq-shimmer={playing}
	style:--pq-play={display ? `${PLAY_MS}ms` : undefined}
	use:replays
>
	{#if display}<div class="pq-stage" aria-hidden="true"></div>{/if}
	{#if playing && sparks.length}
		<span class="pq-sparks" aria-hidden="true"
			>{#each sparks as s}<i
					class="pq-spark pq-{s.kind}"
					style="left: {s.x}px; top: {s.y}px; --sz: {s.size}px; --at: {s.at}ms; --life: {s.life}ms; --rot: {s.rot}deg"
				></i>{/each}</span
		>
	{/if}
	<slot />
</blockquote>

<style>
	/* light first (no .dark): deep candy into deep iris keeps its contrast on white. gradients lean
	   purple-up, pink-down (80deg: the top lines a breath more iris), and pink never stands flat.
	   the ink is mirrored and twice as wide as the words: its first half is the resting gradient, the
	   whole is the road the shimmer drifts along and back */
	.petal-quote {
		--pq-ink: linear-gradient(
			80deg,
			#c2337f 0%,
			#ad3a96 23%,
			#7b4fc4 50%,
			#ad3a96 77%,
			#c2337f 100%
		);
		--pq-mark: linear-gradient(175deg, #7b4fc4 0%, #d4408f 100%);
		--pq-edge: linear-gradient(180deg, #8f5bd1 0%, #d4408f 55%, #f0a8cf 100%);
		--pq-select: #3b0f2e;
		--pq-select-bg: rgb(212 64 143 / 0.18);
		--pq-sheen: rgb(255 255 255 / 0.42);
		--pq-aura: rgb(212 64 143 / 0.34);
		--pq-glow: rgb(143 91 209 / 0.22);
		--pq-star: 212 64 143;
		position: relative;
		isolation: isolate; /* the stars and the stage sit behind the words, in front of the page */
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
		--pq-mark: linear-gradient(175deg, var(--iris, #c07de0) 0%, var(--candy, #ff5bb0) 100%);
		--pq-edge: linear-gradient(
			180deg,
			var(--iris, #c07fdd) 0%,
			var(--candy, #ff5bb0) 55%,
			var(--candy-light, #ffcce9) 100%
		);
		--pq-select: var(--pearl, #fff4f9);
		--pq-select-bg: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.28);
		--pq-sheen: rgb(
			255 255 255 / 0.55
		); /* the sheen, a touch brighter on the night */
		--pq-aura: rgb(255 77 190 / 0.72); /* the aura's candy */
		--pq-glow: rgb(255 122 206 / 0.42); /* the glow around it */
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

	/* the accent hairline where the grey bar stood (over the stage) */
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

	/* every paragraph wears the gradient (its box hugs the words, so short lines walk all of it);
	   the first is the display line, the rest step down a little so longer quotes stay readable */
	.petal-quote > :global(p) {
		width: fit-content;
		max-width: 100%;
		margin: 0 0 0.55em;
		font-size: 1.15em;
		font-weight: 560;
		line-height: 1.42;
		text-wrap: pretty;
		background-image: var(--pq-ink);
		background-size: 200% 100%;
		background-position: 0% 0;
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	.petal-quote > :global(p:first-of-type) {
		font-size: 1.35em;
		font-weight: 600;
		line-height: 1.34;
		text-wrap: balance;
	}
	.petal-quote > :global(:last-child) {
		margin-bottom: 0;
	}
	/* each line between breaks wraps on its own, evenly (a lone word never hangs on the phone) */
	.petal-quote :global(.pq-line) {
		display: block;
		text-wrap: balance;
	}

	/* the quote's own marks, kept: curly, a little larger, in the accent (their size never spreads the lines) */
	.petal-quote :global(.pq-mark) {
		font-size: 1.22em;
		line-height: 0;
		font-weight: 500;
		background: var(--pq-mark);
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}

	/* emoji keep their colours, code stays code, bold stays bolder than the line */
	.petal-quote :global(.pq-emoji),
	.petal-quote :global(.emoji),
	.petal-quote :global(code) {
		-webkit-text-fill-color: initial;
	}
	.petal-quote :global(code) {
		font-size: 0.8em;
		font-weight: 500;
	}
	.petal-quote :global(strong) {
		font-weight: 760;
	}
	/* selected words read in one solid ink over a candy wash (gradient ink can't show a selection) */
	.petal-quote :global(::selection) {
		-webkit-text-fill-color: var(--pq-select);
		color: var(--pq-select);
		background: var(--pq-select-bg);
	}

	/* ── ✨ the shimmer (A18): a candy light, for one play ─────────────────────────────────────────
	   drift · the light's sway, as the ink gliding through the letters and back to rest
	   silk  · the sweep: a soft white band crossing at 20°
	   aura  · a blurred-glyph glow, candy over a softer pink (about 0.17 of the letter size)
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
	.petal-quote.pq-shimmer > :global(p) {
		background-image:
			linear-gradient(
				110deg,
				transparent 46.5%,
				color-mix(in srgb, var(--pq-sheen) 55%, transparent) 48.8%,
				var(--pq-sheen) 50%,
				color-mix(in srgb, var(--pq-sheen) 55%, transparent) 51.2%,
				transparent 53.5%
			),
			var(--pq-ink);
		background-size:
			300% 100%,
			200% 100%;
		background-position:
			var(--pq-sweep) 0,
			var(--pq-drift) 0;
		animation:
			pq-drift calc(var(--pq-play) / 2) ease-in-out 0s 2 alternate both,
			pq-silk calc(var(--pq-play) * 0.7) cubic-bezier(0.45, 0.05, 0.55, 0.95)
				calc(var(--pq-play) * 0.1) 1 both,
			pq-aura var(--pq-play) ease-out 0s 1 both;
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
			filter: drop-shadow(0 0 0 transparent) drop-shadow(0 0 0 transparent);
		}
		24%,
		62% {
			filter: drop-shadow(0 0 0.14em var(--pq-aura)) drop-shadow(0 0 0.42em var(--pq-glow));
		}
	}

	.pq-sparks {
		position: absolute;
		inset: 0;
		z-index: -1;
		pointer-events: none;
		user-select: none;
	}
	.pq-spark {
		--ray: max(1.5px, calc(var(--sz) * 0.05));
		position: absolute;
		width: var(--sz);
		height: var(--sz);
		margin: calc(var(--sz) / -2) 0 0 calc(var(--sz) / -2);
		opacity: 0;
		background:
			radial-gradient(
				circle,
				rgb(255 255 255 / var(--hot, 0.8)) 0,
				rgb(255 255 255 / 0) calc(var(--sz) * 0.09)
			),
			radial-gradient(
				circle,
				rgb(var(--pq-star) / 0.95) 0,
				rgb(var(--pq-star) / 0) calc(var(--sz) * 0.17)
			),
			radial-gradient(
				circle,
				rgb(var(--pq-star) / var(--halo, 0.36)) 0,
				rgb(var(--pq-star) / 0) calc(var(--sz) * 0.36)
			),
			linear-gradient(
					90deg,
					rgb(var(--pq-star) / 0),
					rgb(var(--pq-star) / 0.92) 50%,
					rgb(var(--pq-star) / 0)
				)
				center / 100% var(--ray) no-repeat,
			linear-gradient(
					0deg,
					rgb(var(--pq-star) / 0),
					rgb(var(--pq-star) / 0.92) 50%,
					rgb(var(--pq-star) / 0)
				)
				center / var(--ray) 100% no-repeat;
		will-change: transform, opacity;
		animation: pq-twinkle var(--life) cubic-bezier(0.33, 0.7, 0.4, 1) var(--at) 1 both;
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
			linear-gradient(
					90deg,
					rgb(var(--pq-star) / 0),
					rgb(var(--pq-star) / 0.5) 50%,
					rgb(var(--pq-star) / 0)
				)
				center / 100% var(--ray) no-repeat,
			linear-gradient(
					0deg,
					rgb(var(--pq-star) / 0),
					rgb(var(--pq-star) / 0.5) 50%,
					rgb(var(--pq-star) / 0)
				)
				center / var(--ray) 100% no-repeat;
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

	/* ── ✨ the stage (A18b): an empty layer under the words, a little taller than the quote (into its
	   own margins, never past them), where an awake quote effect paints. the words sit above it ───── */
	.pq-stage {
		position: absolute;
		z-index: 0;
		inset: -1em 0;
		pointer-events: none;
	}
	.petal-quote > :global(:not(.pq-stage, .pq-sparks)) {
		position: relative;
		z-index: 1;
	}
	/* the effect names its face on the page (--pq-face) and gives it to the quotes it paints
	   (data-pq-face, before it measures them): one weight, upright, natural spacing, so the words
	   underneath keep the painted letters' exact places */
	.petal-quote:global([data-pq-face]),
	.petal-quote:global([data-pq-face])
		:global(*:not(code, pre, kbd, samp, code *, pre *, .katex, .katex *, .pq-emoji)) {
		font-family:
			var(--pq-face),
			var(--font-emoji, 'SamsungColorEmoji', 'Noto Color Emoji'), serif !important;
		font-weight: 400 !important;
		font-style: normal !important;
		font-synthesis: none;
		font-variation-settings: normal;
		letter-spacing: 0;
	}
	/* faces run small or large (a script's x-height isn't the display face's): the effect says how much
	   (--pq-face-scale), so its words stand as tall as the display line they replace */
	.petal-quote:global([data-pq-face]) > :global(p) {
		font-size: calc(1.15em * var(--pq-face-scale, 1));
	}
	.petal-quote:global([data-pq-face]) > :global(p:first-of-type) {
		font-size: calc(1.35em * var(--pq-face-scale, 1));
	}
	/* painted: the words' ink steps aside (they're still there to select, copy and voice; a selection
	   shows in its solid ink above the paint). code stays code */
	.petal-quote:global([data-pq-fx='drawn']) > :global(p),
	.petal-quote:global([data-pq-fx='drawn']) :global(.pq-mark),
	.petal-quote:global([data-pq-fx='drawn']) :global(.pq-emoji),
	.petal-quote:global([data-pq-fx='drawn']) :global(.emoji) {
		background: none;
		-webkit-text-fill-color: transparent;
	}

	/* reduced motion: the resting look, always (the door won't start a play either) */
	@media (prefers-reduced-motion: reduce) {
		.petal-quote.pq-shimmer > :global(p) {
			animation: none;
			background-image: var(--pq-ink);
			background-size: 200% 100%;
			background-position: 0% 0;
		}
		.pq-sparks {
			display: none;
		}
	}
</style>
