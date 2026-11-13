<script lang="ts">
	// 🌸 the display quote (slice A17). in a reply, a blockquote is usually the heart of the message
	// (identity lines, vows, words to repeat), so it's set as display type: the theme's display face,
	// bigger and bolder, in the accent gradient, with room above and below so the line stands alone.
	// only replies ask for it (`display`); every other quote keeps the plain look. static: no motion,
	// nothing for the GPU to redraw while it rests. its text tokens read the context below to dress
	// their own quotation marks and keep emoji in colour (display only: the words stay as written).
	import { setContext } from 'svelte';

	export let display = false;

	setContext('petal-quote', display);
</script>

<blockquote dir="auto" class:petal-quote={display}><slot /></blockquote>

<style>
	/* light first (no .dark): deep candy into deep iris keeps its contrast on white. gradients lean
	   purple-up, pink-down (80deg: the top lines a breath more iris), and pink never stands flat */
	.petal-quote {
		--pq-ink: linear-gradient(80deg, #c2337f 0%, #ad3a96 46%, #7b4fc4 100%);
		--pq-mark: linear-gradient(175deg, #7b4fc4 0%, #d4408f 100%);
		--pq-edge: linear-gradient(180deg, #8f5bd1 0%, #d4408f 55%, #f0a8cf 100%);
		--pq-select: #3b0f2e;
		--pq-select-bg: rgb(212 64 143 / 0.18);
		position: relative;
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
			var(--candy, #ff90cf) 46%,
			var(--iris, #c07de0) 100%
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

	/* the accent hairline where the grey bar stood */
	.petal-quote::before {
		content: '';
		position: absolute;
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
		background: var(--pq-ink);
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	.petal-quote > :global(p:first-child) {
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
</style>
