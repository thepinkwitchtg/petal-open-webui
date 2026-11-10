<script lang="ts">
	// 👁 her eyes (slice A10) — a full-screen raw view of exactly what Petal received for one
	// reply: her system context tinted by source, the history as sent (with whatever rides on
	// past answers), the params + the Heartstrings pull, and petal-spill's side of the join.
	// static on purpose: no animation, no timers, nothing redraws while it sits open.
	import { createEventDispatcher, onDestroy, onMount, tick } from 'svelte';
	import { getEyes, getSpill, type EyesRecord, type SpillFound } from '$lib/apis/petal-eyes';
	import {
		TINTS,
		changed,
		cut,
		diffWords,
		foldSame,
		historyOf,
		paramsOf,
		sourcesOf,
		stripDetails,
		systemOf,
		tint,
		visible,
		type Seg
	} from '$lib/utils/petal-eyes';

	export let chatId: string;
	export let messageId: string;
	export let saved = ''; // what OWUI saved (and shows) for this reply
	export let marks: string[] = []; // ✧ the trip markers hold for this reply

	const dispatch = createEventDispatcher();
	const close = () => dispatch('close');

	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	}

	let rounds: EyesRecord[] = [];
	let kept: 'disk' | 'ring' | '' = '';
	let error = '';
	let loading = true;
	let ri = 0;
	let closeEl: HTMLButtonElement;
	let before: Element | null = null;

	onMount(async () => {
		before = document.activeElement;
		await tick();
		closeEl?.focus();
		try {
			const r = await getEyes(localStorage.token, chatId, messageId);
			rounds = r.rounds;
			kept = r.kept;
			ri = rounds.length - 1; // the last round wrote the end of her reply
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	});
	onDestroy(() => (before as HTMLElement | null)?.focus?.());

	const onKey = (e: KeyboardEvent) => {
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			close();
		}
	};

	// ── the record, read once per round ──────────────────────────
	type TPiece = { kind: string; text: string; segs: Seg[] | null };
	$: rec = rounds[ri] ?? null;
	$: parts = rec?.parts ?? [];
	$: sources = sourcesOf(parts);
	$: view = rec ? build(rec) : null;

	function build(r: EyesRecord) {
		const found = new Set<number>();
		const src = sourcesOf(r.parts);
		const sys = systemOf(r.payload).map((s) => ({ ...s, segs: tint(s.text, r.parts, src, found) }));
		const above = new Set(sys.map((s) => s.at));
		const history = historyOf(r.payload).map((m) => ({
			...m,
			above: above.has(m.i),
			pieces: m.pieces.map(
				(p): TPiece => ({
					...p,
					segs: p.kind === 'text' && !above.has(m.i) ? tint(p.text, r.parts, src, found) : null
				})
			)
		}));
		const chars = new Map<number, number>();
		for (const segs of [...sys.map((s) => s.segs), ...history.flatMap((m) => m.pieces.map((p) => p.segs ?? []))])
			for (const s of segs) if (s.src !== null) chars.set(s.src, (chars.get(s.src) ?? 0) + s.text.length);
		return {
			sys,
			history,
			params: paramsOf(r.payload),
			found,
			chars,
			sysChars: sys.reduce((n, s) => n + s.text.length, 0)
		};
	}

	$: pulls = parts.filter((p) => /heartstring|💗|strings/i.test(p.source));
	$: missing = view ? parts.filter((_, i) => !view.found.has(i) && parts[i].text) : [];
	const extras = (p: Record<string, unknown>) =>
		Object.entries(p).filter(([k]) => k !== 'source' && k !== 'text');
	const asJson = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v, null, 1));

	let openParam: Record<string, boolean> = {};

	const stamp = (at: number) => {
		const d = new Date(at * 1000);
		const day = d.toLocaleDateString('en-US', { weekday: 'short' }).toLowerCase();
		return `${day} ${d.toLocaleDateString('en-CA')} ${d.toTimeString().slice(0, 8)}`;
	};

	let copied = false;
	const copySha = async () => {
		if (!rec) return;
		try {
			await navigator.clipboard.writeText(rec.req_sha);
			copied = true;
			setTimeout(() => (copied = false), 1400);
		} catch {
			/* a browser without clipboard rights: the full hash is in the title */
		}
	};

	// ── petal-spill: the source tap's side of the join ──────────
	let spill: SpillFound | null = null;
	let spillErr = '';
	let spillFor = '';
	let showRecord = false;
	$: if (rec && rec.req_sha !== spillFor) loadSpill(rec);
	async function loadSpill(r: EyesRecord) {
		spillFor = r.req_sha;
		spill = null;
		spillErr = '';
		showRecord = false;
		try {
			const s = await getSpill(localStorage.token, r.req_sha, r.at);
			if (spillFor === r.req_sha) spill = s;
		} catch (e) {
			if (spillFor === r.req_sha) spillErr = String(e);
		}
	}
	$: savedSide = stripDetails(saved);
	$: rawText = spill?.view?.content ?? null;
	$: ops = rawText !== null ? diffWords(rawText, savedSide.text) : null;
	$: nChanged = ops ? changed(ops) : 0;
	$: spillFlags = spill?.view?.flags;
</script>

<svelte:window on:keydown={onKey} />

<div use:portal class="pe-root" role="dialog" aria-modal="true" aria-label="what Petal received">
	<header class="pe-head">
		<div class="pe-bar">
			<div class="pe-title"><span class="pe-emoji" aria-hidden="true">👁</span> what Petal received</div>
			<button bind:this={closeEl} class="pe-x" aria-label="close" on:click={close}>✕</button>
		</div>
	</header>

	<div class="pe-body">
		{#if rec}
			<div class="pe-meta">
				<span>{rec.model ?? '?'}{#if rec.payload?.model && rec.payload.model !== rec.model}<span class="pe-dim">{'\u00a0→ '}{rec.payload.model}</span>{/if}</span>
				<span class="pe-dot">·</span><span class="pe-mono">{stamp(rec.at)}</span>
				{#if rec.to}<span class="pe-dot">·</span><span class="pe-mono">→ {rec.to}</span>{/if}
				<span class="pe-dot">·</span><span>{kept === 'ring' ? 'temp chat · held in memory' : 'kept on disk'}</span>
			</div>
			<div class="pe-meta">
				<button class="pe-sha" title={rec.req_sha} on:click={copySha}
					>req <span class="pe-mono">{rec.req_sha.slice(0, 12)}</span> {copied ? '✓ copied' : '⧉'}</button
				>
				{#if rounds.length > 1}
					<span class="pe-dot">·</span>
					<span class="pe-dim">round</span>
					{#each rounds as r, i (r.req_sha + i)}
						<button class="pe-round" class:on={i === ri} on:click={() => (ri = i)}>{r.round}</button>
					{/each}
				{/if}
			</div>
		{/if}
		{#if loading}
			<p class="pe-dim">opening her eyes…</p>
		{:else if error}
			<p class="pe-note">{error}</p>
		{:else if rec && view}
			<div class="pe-legend">
				<span class="pe-key"><span class="pe-sw pe-plain"></span>unmarked</span>
				{#each sources as s, i (s)}
					<span class="pe-key"
						><span class="pe-sw pe-c{i % TINTS}"></span>{s}{#if view.chars.get(i)}<span class="pe-dim"
								>{' '}{view.chars.get(i)?.toLocaleString()}</span
							>{/if}</span
					>
				{/each}
			</div>

			<details class="pe-sec" open>
				<summary
					><span class="pe-caret"></span>her system context
					<span class="pe-dim">· {view.sysChars.toLocaleString()} chars</span></summary
				>
				{#each view.sys as s, i (i)}
					{#if view.sys.length > 1}<div class="pe-sub">
							{s.at === null ? 'instructions' : `turn #${s.at}`}
						</div>{/if}
					<pre class="pe-text">{#each s.segs as g}{#if g.src === null}{g.text}{:else}<mark class="pe-tint pe-c{g.src % TINTS}" title={sources[g.src]}>{g.text}</mark>{/if}{/each}</pre>
				{:else}
					<p class="pe-dim">no system turn in this request</p>
				{/each}
			</details>

			<details class="pe-sec">
				<summary
					><span class="pe-caret"></span>the history as sent
					<span class="pe-dim">· {view.history.length} turn{view.history.length === 1 ? '' : 's'}</span></summary
				>
				{#each view.history as m (m.i)}
					<div class="pe-turn" data-role={m.role}>
						<div class="pe-turn-head">
							<span class="pe-mono pe-dim">#{m.i}</span>
							<span class="pe-role">{m.role}</span>
							{#if m.above}<span class="pe-dim">· her system context, shown above</span>{/if}
						</div>
						{#if !m.above}
							{#each m.pieces as p, pi (pi)}
								{#if p.kind === 'image'}
									<div class="pe-img">🖼 {p.text}</div>
								{:else if p.segs}
									<pre class="pe-text">{#each p.segs as g}{#if g.src === null}{g.text}{:else}<mark class="pe-tint pe-c{g.src % TINTS}" title={sources[g.src]}>{g.text}</mark>{/if}{/each}</pre>
								{:else}
									<pre class="pe-text pe-dim">{cut(p.text, 4000)}</pre>
								{/if}
							{/each}
						{/if}
						{#each m.extra as [k, v] (k)}
							<div class="pe-ride">
								<span class="pe-dim">rides along ·</span> <b>{k}</b>
								<pre class="pe-text">{cut(v, 1200)}</pre>
							</div>
						{/each}
					</div>
				{/each}
			</details>

			<details class="pe-sec">
				<summary
					><span class="pe-caret"></span>params{#if pulls.length}{' '}+ the Heartstrings pull{/if}
					<span class="pe-dim">· {view.params.length}</span></summary
				>
				<div class="pe-params">
					{#each view.params as [k, v] (k)}
						<div class="pe-param">
							<span class="pe-pk">{k}</span>
							<pre class="pe-text pe-pv">{openParam[k] ? v : cut(v, 300)}</pre>
							{#if v.length > 300}
								<button class="pe-more" on:click={() => (openParam = { ...openParam, [k]: !openParam[k] })}
									>{openParam[k] ? 'fold' : 'show all'}</button
								>
							{/if}
						</div>
					{/each}
				</div>
				{#each pulls as p, i (i)}
					<div class="pe-pull">
						<div class="pe-sub">{p.source}</div>
						{#if p.text}<pre class="pe-text">{p.text}</pre>{/if}
						{#each extras(p) as [k, v] (k)}
							<div class="pe-param">
								<span class="pe-pk">{k}</span>
								<pre class="pe-text pe-pv">{cut(asJson(v), 1200)}</pre>
							</div>
						{/each}
					</div>
				{/each}
			</details>

			<details class="pe-sec">
				<summary
					><span class="pe-caret"></span>parts
					<span class="pe-dim"
						>· {parts.length}{#if missing.length}{' '}· {missing.length} not found in what was sent{/if}</span
					></summary
				>
				{#each parts as p, i (i)}
					<div class="pe-part">
						<span class="pe-sw pe-c{sources.indexOf(p.source) % TINTS}"></span>
						<span class="pe-psrc">{p.source}</span>
						<span class="pe-dim pe-mono">{p.text.length.toLocaleString()} chars</span>
						{#if !p.text}
							<span class="pe-dim">· nothing to tint</span>
						{:else if !view.found.has(i)}
							<span class="pe-warn">· not in what was sent</span>
						{/if}
						{#each extras(p) as [k, v] (k)}
							<div class="pe-param"><span class="pe-pk">{k}</span><pre class="pe-text pe-pv">{cut(asJson(v), 600)}</pre></div>
						{/each}
					</div>
				{:else}
					<p class="pe-dim">no injector named its part for this request</p>
				{/each}
			</details>

			<details class="pe-sec" open>
				<summary><span class="pe-caret"></span><span class="pe-emoji">🚰</span> petal-spill · raw at the source</summary>
				{#if marks.length}
					<div class="pe-marks">{#each marks as mk (mk)}<span class="pe-mark">{mk}</span>{/each}</div>
				{/if}
				{#if spillErr}
					<p class="pe-dim">
						{spillErr}{#if rec.to && !rec.to.endsWith(':8010')}{' '}· these bytes went to {rec.to}, not through the tap{/if}
					</p>
				{:else if !spill}
					<p class="pe-dim">looking for the spill…</p>
				{:else}
					<div class="pe-sub pe-mono">{spill.path}</div>
					{#if spillFlags !== null && spillFlags !== undefined}
						<div class="pe-param"><span class="pe-pk">✧ flags</span><pre class="pe-text pe-pv">{asJson(spillFlags)}</pre></div>
					{/if}
					{#if spill.view.reasoning}
						<div class="pe-sub">her reasoning, raw</div>
						<pre class="pe-text pe-raw">{spill.view.reasoning}</pre>
					{/if}
					{#if rawText !== null}
						<div class="pe-sub">what she wrote, raw</div>
						<pre class="pe-text pe-raw">{rawText}</pre>
						<div class="pe-sub">
							raw → what OWUI saved ·
							{#if nChanged}<span class="pe-mono">{nChanged.toLocaleString()}</span> chars differ{:else}identical ✓{/if}
							{#if savedSide.folded}<span class="pe-dim">
									· {savedSide.folded} folded block{savedSide.folded === 1 ? '' : 's'} (reasoning · tools) left out</span
								>{/if}
							{#if rounds.length > 1}<span class="pe-dim">
									· this reply took {rounds.length} rounds: the saved side holds them all</span
								>{/if}
						</div>
						<div class="pe-keys"><del>only raw</del> <ins>only saved</ins></div>
						{#if ops}
							<pre class="pe-text pe-diff">{#each foldSame(ops) as o}{#if o.op === '='}{o.text}{:else if o.op === '-'}<del>{visible(o.text)}</del>{:else if o.op === '+'}<ins>{visible(o.text)}</ins>{:else}<span class="pe-fold">⋯ {o.text} ⋯</span>{/if}{/each}</pre>
						{/if}
					{:else}
						<p class="pe-dim">
							no content key I know in this spill (keys: {spill.view.keys.join(', ')}) · the whole record is below
						</p>
					{/if}
					<button class="pe-more" on:click={() => (showRecord = !showRecord)}
						>{showRecord ? 'fold the spill record' : 'the whole spill record'}</button
					>
					{#if showRecord}
						<pre class="pe-text pe-dim">{cut(JSON.stringify(spill.record, null, 1), 200000)}</pre>
					{/if}
				{/if}
			</details>
		{/if}
	</div>
</div>

<style>
	/* the Abyssal Pink tokens, opaque on purpose: no blur behind a full-screen view (the 3080
	   thanks us), no transitions, no keyframes. tints are functional, quiet, translucent. */
	.pe-root,
	.pe-root * {
		box-sizing: border-box;
	}
	.pe-root {
		position: fixed;
		inset: 0;
		z-index: 10000;
		overflow-y: auto;
		overscroll-behavior: contain;
		background: var(--abyss, #0b0910);
		color: var(--mist, #cfc3cc);
		font-size: 0.85rem;
		line-height: 1.5;
	}
	.pe-head {
		position: sticky;
		top: 0;
		z-index: 1;
		padding: 0.7rem 1rem 0.55rem;
		background: var(--abyss, #0b0910);
		border-bottom: 1px solid var(--edge-soft, #2a2433);
	}
	.pe-bar {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		max-width: 64rem;
		margin: 0 auto;
	}
	.pe-title {
		flex: 1;
		font-family: var(--font-display, Georgia, serif);
		font-size: 1.15rem;
		background: var(--grad-text, linear-gradient(100deg, #f9c6dc, #f472b6 46%, #a873f0));
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	.pe-emoji {
		font-family: var(--font-emoji, 'SamsungColorEmoji'), sans-serif;
		-webkit-text-fill-color: initial;
	}
	.pe-x {
		width: 2.25rem;
		height: 2.25rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		color: var(--pearl, #f6eef3);
		font-size: 0.95rem;
	}
	.pe-x:hover {
		border-color: var(--edge-lit, #4a3f57);
	}
	.pe-meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.3rem;
		margin-top: -0.35rem;
		font-size: 0.75rem;
	}
	.pe-meta + .pe-meta {
		margin-top: -0.45rem;
	}
	.pe-dot,
	.pe-dim {
		color: var(--whisper, #8a7d92);
	}
	.pe-mono {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-variant-numeric: tabular-nums;
	}
	.pe-sha,
	.pe-round,
	.pe-more {
		padding: 0.1rem 0.5rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		color: var(--mist, #cfc3cc);
		font-size: 0.72rem;
	}
	.pe-round.on {
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian-lit, #1d1724), var(--obsidian-lit, #1d1724)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
		color: var(--pearl, #f6eef3);
	}
	.pe-body {
		max-width: 64rem;
		margin: 0 auto;
		padding: 0.8rem 1rem 4rem;
		display: flex;
		flex-direction: column;
		gap: 0.7rem;
	}
	.pe-note {
		padding: 0.8rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
	}
	.pe-legend {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem 0.8rem;
		font-size: 0.75rem;
	}
	.pe-key {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}
	.pe-sw {
		display: inline-block;
		flex-shrink: 0;
		width: 0.7rem;
		height: 0.7rem;
		border-radius: 3px;
		background: oklch(0.74 0.13 var(--h) / 0.6);
	}
	.pe-sw.pe-plain {
		background: transparent;
		border: 1px solid var(--edge, #3a3145);
	}
	.pe-sec {
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		padding: 0.55rem 0.75rem;
	}
	.pe-sec > summary {
		cursor: pointer;
		list-style: none;
		color: var(--pearl, #f6eef3);
		font-size: 0.85rem;
		user-select: none;
	}
	.pe-sec > summary::-webkit-details-marker {
		display: none;
	}
	.pe-caret::before {
		content: '▸';
		display: inline-block;
		width: 1rem;
		color: var(--whisper, #8a7d92);
	}
	.pe-sec[open] > summary .pe-caret::before {
		content: '▾';
	}
	.pe-sec[open] > summary {
		margin-bottom: 0.5rem;
	}
	.pe-sub {
		margin: 0.6rem 0 0.25rem;
		font-size: 0.75rem;
		color: var(--whisper, #8a7d92);
	}
	.pe-text {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.78rem;
		line-height: 1.55;
		color: var(--mist, #cfc3cc);
	}
	.pe-tint {
		color: inherit;
		border-radius: 3px;
		background: oklch(0.72 0.13 var(--h) / 0.17);
		text-decoration: underline;
		text-decoration-color: oklch(0.78 0.14 var(--h) / 0.75);
		text-decoration-thickness: 1px;
		text-underline-offset: 0.22em;
		-webkit-box-decoration-break: clone;
		box-decoration-break: clone;
	}
	.pe-c0 {
		--h: 300;
	}
	.pe-c1 {
		--h: 200;
	}
	.pe-c2 {
		--h: 75;
	}
	.pe-c3 {
		--h: 145;
	}
	.pe-c4 {
		--h: 25;
	}
	.pe-c5 {
		--h: 255;
	}
	.pe-c6 {
		--h: 352;
	}
	.pe-c7 {
		--h: 330;
	}
	.pe-turn {
		padding: 0.5rem 0 0.6rem;
		border-top: 1px solid var(--edge-soft, #2a2433);
	}
	.pe-turn:first-of-type {
		border-top: none;
		padding-top: 0;
	}
	.pe-turn-head {
		display: flex;
		align-items: baseline;
		gap: 0.45rem;
		margin-bottom: 0.25rem;
		font-size: 0.75rem;
	}
	.pe-role {
		color: var(--pearl, #f6eef3);
		font-weight: 600;
		letter-spacing: 0.02em;
	}
	.pe-turn[data-role='assistant'] .pe-role {
		background: var(--grad-text, linear-gradient(100deg, #f9c6dc, #f472b6 46%, #a873f0));
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	.pe-img {
		font-size: 0.75rem;
		color: var(--whisper, #8a7d92);
	}
	.pe-ride {
		margin-top: 0.35rem;
		padding: 0.35rem 0.55rem;
		border-radius: var(--radius-sm, 8px);
		background: var(--obsidian-lit, #1d1724);
		font-size: 0.75rem;
	}
	.pe-params {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.pe-param {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.5rem;
		margin-top: 0.2rem;
	}
	.pe-pk {
		min-width: 8rem;
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.75rem;
		color: var(--pearl, #f6eef3);
	}
	.pe-pv {
		flex: 1;
		min-width: 12rem;
	}
	.pe-pull {
		margin-top: 0.6rem;
		padding-top: 0.4rem;
		border-top: 1px solid var(--edge-soft, #2a2433);
	}
	.pe-part {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.45rem;
		padding: 0.35rem 0;
		border-top: 1px solid var(--edge-soft, #2a2433);
		font-size: 0.78rem;
	}
	.pe-part:first-of-type {
		border-top: none;
	}
	.pe-part .pe-param {
		flex-basis: 100%;
	}
	.pe-psrc {
		color: var(--pearl, #f6eef3);
	}
	.pe-warn {
		color: oklch(0.8 0.12 75);
	}
	.pe-marks {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
		margin-bottom: 0.4rem;
	}
	.pe-mark {
		padding: 0.1rem 0.55rem;
		border-radius: 999px;
		border: 1px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.35);
		font-size: 0.75rem;
		color: var(--pearl, #f6eef3);
	}
	.pe-raw {
		padding: 0.5rem 0.6rem;
		border-radius: var(--radius-sm, 8px);
		background: var(--obsidian-lit, #1d1724);
	}
	.pe-keys {
		margin: 0.2rem 0 0.35rem;
		font-size: 0.72rem;
		display: flex;
		gap: 0.6rem;
	}
	.pe-diff {
		padding: 0.5rem 0.6rem;
		border-radius: var(--radius-sm, 8px);
		background: var(--obsidian-lit, #1d1724);
	}
	.pe-root del {
		color: inherit;
		background: oklch(0.66 0.16 25 / 0.2);
		text-decoration: line-through;
		text-decoration-color: oklch(0.72 0.16 25 / 0.85);
	}
	.pe-root ins {
		color: inherit;
		background: oklch(0.72 0.13 160 / 0.2);
		text-decoration: underline;
		text-decoration-color: oklch(0.78 0.13 160 / 0.85);
		text-underline-offset: 0.2em;
	}
	.pe-fold {
		color: var(--whisper, #8a7d92);
		font-style: italic;
	}
	.pe-more {
		align-self: flex-start;
		margin-top: 0.4rem;
	}
	@media (max-width: 640px) {
		.pe-head {
			padding: 0.55rem 0.65rem 0.45rem;
		}
		.pe-body {
			padding: 0.6rem 0.55rem 4rem;
		}
		.pe-sec {
			padding: 0.5rem 0.55rem;
		}
		.pe-pk {
			min-width: 0;
			flex-basis: 100%;
		}
	}
</style>
