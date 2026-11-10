<script lang="ts">
	// 👁 her eyes (slice A10) — a full-screen raw view of exactly what Petal received for one
	// reply: the parts in the order Petal reads them (each unfolds to its full text + extras, A13),
	// her system context tinted by source, the history as sent (with whatever rides on past
	// answers), the params + the Heartstrings pull, and petal-wellspring's side of the join (the
	// source tap: every raw character she wrote, before OWUI prettified it).
	// 🧵 the rendered tab (A13): the same request through vLLM's own chat template, asked live:
	// every special token, the thinking switch, the tool block the template writes.
	// static on purpose: no animation, no timers, nothing redraws while it sits open.
	import { createEventDispatcher, onDestroy, onMount, tick } from 'svelte';
	import {
		getEyes,
		getRendered,
		getWellspring,
		type EyesRecord,
		type Rendered,
		type WellFound
	} from '$lib/apis/petal-eyes';
	import {
		TINTS,
		changed,
		cut,
		diffWords,
		foldSame,
		historyOf,
		paramsOf,
		partKind,
		placesOf,
		renderedSegs,
		sourcesOf,
		stripDetails,
		systemOf,
		thinkingOf,
		tint,
		turnLabels,
		visible,
		type RSeg,
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
	type TRide = [string, string, Seg[]];
	$: rec = rounds[ri] ?? null;
	$: parts = rec?.parts ?? [];
	$: sources = sourcesOf(parts);
	$: view = rec ? build(rec) : null;

	function build(r: EyesRecord) {
		const found = new Set<number>();
		const src = sourcesOf(r.parts);
		const sys = systemOf(r.payload).map((s) => ({ ...s, segs: tint(s.text, r.parts, src, found) }));
		const above = new Set(sys.map((s) => s.at));
		// her turns are searched too (pulse rides inside them), and whatever rides along on a turn
		const history = historyOf(r.payload).map((m) => ({
			...m,
			above: above.has(m.i),
			pieces: m.pieces.map(
				(p): TPiece => ({
					...p,
					segs: p.kind === 'text' && !above.has(m.i) ? tint(p.text, r.parts, src, found) : null
				})
			),
			rides: m.extra.map(([k, v]): TRide => [k, v, tint(cut(v, 1200), r.parts, src, found)])
		}));
		const labels = turnLabels(historyOf(r.payload));
		const chars = new Map<number, number>();
		for (const segs of [
			...sys.map((s) => s.segs),
			...history.flatMap((m) => [...m.pieces.map((p) => p.segs ?? []), ...m.rides.map((x) => x[2])])
		])
			for (const s of segs) if (s.src !== null) chars.set(s.src, (chars.get(s.src) ?? 0) + s.text.length);
		return {
			sys,
			history,
			labels,
			...placesOf(r.payload, r.parts), // A13 · places + the order Petal reads them in
			params: paramsOf(r.payload),
			found,
			chars,
			sysChars: sys.reduce((n, s) => n + s.text.length, 0)
		};
	}

	$: pulls = parts.filter((p) => /heartstring|💗|strings/i.test(p.source));
	// steering and soft tokens are never text: they're named, never counted as missing
	$: missing = view ? parts.filter((p, i) => !view.found.has(i) && p.text && partKind(p.source) === 'text') : [];
	const NOT_TEXT: Record<string, string> = { steering: 'steering · not text', soft: 'soft tokens · not text' };
	const extras = (p: Record<string, unknown>) =>
		Object.entries(p).filter(([k]) => k !== 'source' && k !== 'text');
	const asJson = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v, null, 1));
	const plural = (n: number, one: string) => `${n.toLocaleString()} ${one}${n === 1 ? '' : 's'}`;

	let openParam: Record<string, boolean> = {};
	let openX: Record<string, boolean> = {}; // a part's long extra, unfolded
	let tab: 'sent' | 'rendered' = 'sent';

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

	// ── 🫗 petal-wellspring: the source tap's side of the join ──
	let well: WellFound | null = null;
	let wellErr = '';
	let wellFor = '';
	let showRecord = false;
	let showRaw = false;
	$: if (rec && rec.req_sha !== wellFor) loadWell(rec);
	async function loadWell(r: EyesRecord) {
		wellFor = r.req_sha;
		well = null;
		wellErr = '';
		showRecord = false;
		showRaw = false;
		try {
			const w = await getWellspring(localStorage.token, r.req_sha, r.at);
			if (wellFor === r.req_sha) well = w;
		} catch (e) {
			if (wellFor === r.req_sha) wellErr = String(e);
		}
	}
	// ── 🧵 the rendered tab: asked of the live vLLM once per round, when she opens it ──
	let rendered: Rendered | null = null;
	let renderedErr = '';
	let renderedFor = '';
	let copiedR = false;
	$: if (tab === 'rendered' && rec && `${rec.req_sha}:${rec.round}` !== renderedFor) loadRendered(rec);
	async function loadRendered(r: EyesRecord) {
		const key = `${r.req_sha}:${r.round}`;
		renderedFor = key;
		rendered = null;
		renderedErr = '';
		try {
			const out = await getRendered(localStorage.token, chatId, messageId, r.round);
			if (renderedFor === key) rendered = out;
		} catch (e) {
			if (renderedFor === key) renderedErr = String(e);
		}
	}
	const renderAgain = () => rec && loadRendered(rec);
	const copyRendered = async () => {
		if (!rendered) return;
		try {
			await navigator.clipboard.writeText(rendered.text);
			copiedR = true;
			setTimeout(() => (copiedR = false), 1400);
		} catch {
			/* no clipboard rights: the text is selectable */
		}
	};
	$: rview = rendered && rec ? renderedSegs(rendered.text, rec.payload, parts, sources) : null;
	$: tailSegs = rview ? after(rview.segs, rview.lastEnd) : [];
	$: think = rview ? thinkingOf(rview.tail) : null;
	$: settingChips = rendered ? chipsOf(rendered.settings) : [];
	$: fill = rendered?.max_model_len ? Math.round((rendered.count / rendered.max_model_len) * 1000) / 10 : null;
	function after(segs: RSeg[], from: number): RSeg[] {
		let pos = 0;
		const out: RSeg[] = [];
		for (const g of segs) {
			if (pos >= from) out.push(g);
			pos += g.text.length * g.n;
		}
		return out;
	}
	function chipsOf(st: Record<string, unknown>): string[] {
		const out: string[] = [];
		if (st.continue_final_message) out.push('continues her last message');
		else out.push(st.add_generation_prompt === false ? 'no generation prompt' : 'generation prompt');
		if (st.add_special_tokens) out.push('special tokens added');
		const kw = st.chat_template_kwargs;
		if (kw && typeof kw === 'object')
			for (const [k, v] of Object.entries(kw as Record<string, unknown>)) out.push(`${k}: ${JSON.stringify(v)}`);
		if (typeof st.tools === 'number') out.push(plural(st.tools, 'tool'));
		if (st.tool_choice !== undefined) out.push(`tool_choice: ${JSON.stringify(st.tool_choice)}`);
		if (typeof st.chat_template === 'string') out.push(`template: ${st.chat_template}`);
		if (st.mm_processor_kwargs) out.push('mm_processor_kwargs');
		return out;
	}
	const ws = (t: string) => t.replace(/\n/g, '↵\n');

	$: savedSide = stripDetails(saved);
	$: wrote = well?.view?.content ?? null;
	$: ops = wrote !== null ? diffWords(wrote, savedSide.text) : null;
	$: nChanged = ops ? changed(ops) : 0;
	$: meta = well?.view?.meta ?? {};
	$: metaLine = [
		meta.route,
		meta.caller,
		meta.model,
		meta.status !== undefined ? `status ${meta.status}` : '',
		meta.ms !== undefined ? `${(meta.ms / 1000).toFixed(1)} s` : '',
		meta.finish ? `finish: ${meta.finish}` : '',
		meta.streamed === undefined ? '' : meta.streamed ? 'streamed' : 'not streamed',
		meta.cut ? 'cut' : ''
	].filter(Boolean);
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
			<div class="pe-tabs" role="tablist" aria-label="how to see it">
				<button role="tab" aria-selected={tab === 'sent'} class="pe-tab" class:on={tab === 'sent'} on:click={() => (tab = 'sent')}
					><span class="pe-emoji">👁</span> as sent</button
				>
				<button
					role="tab"
					aria-selected={tab === 'rendered'}
					class="pe-tab"
					class:on={tab === 'rendered'}
					on:click={() => (tab = 'rendered')}><span class="pe-emoji">🧵</span> rendered</button
				>
			</div>

			<div class="pe-legend">
				<span class="pe-key"><span class="pe-sw pe-plain"></span>{tab === 'rendered' ? 'her messages' : 'unmarked'}</span>
				{#if tab === 'rendered'}
					<span class="pe-key"><span class="pe-sw pe-tplsw"></span>the template's own words</span>
					<span class="pe-key"><span class="pe-tok">&lt;|special|&gt;</span>special token</span>
				{/if}
				{#each sources as s, i (s)}
					<span class="pe-key"
						><span class="pe-sw pe-c{i % TINTS}"></span>{s}{#if tab === 'sent' && view.chars.get(i)}<span class="pe-dim"
								>{' '}{view.chars.get(i)?.toLocaleString()}</span
							>{/if}</span
					>
				{/each}
			</div>

			{#if tab === 'rendered'}
				{#if renderedErr}
					<p class="pe-note">{renderedErr}</p>
					<button class="pe-more" on:click={renderAgain}>ask again</button>
				{:else if !rendered || !rview}
					<p class="pe-dim">asking vLLM to render it through her chat template…</p>
				{:else}
					<div class="pe-rmeta">
						<span class="pe-mono">{rendered.count.toLocaleString()}</span> tokens{#if rendered.max_model_len}{' '}of
							<span class="pe-mono">{rendered.max_model_len.toLocaleString()}</span> · {fill}%{/if}
						<span class="pe-dot">·</span> rendered now by <span class="pe-mono">{rendered.asked}</span>
						<span class="pe-dim">({rendered.how}) · asked live, kept nowhere</span>
					</div>
					{#if settingChips.length}
						<div class="pe-marks">{#each settingChips as c (c)}<span class="pe-mark">{c}</span>{/each}</div>
					{/if}
					<div class="pe-sub">
						where she starts writing{#if think === 'closed'}{' '}· thinking closed by the template{:else if think === 'open'}{' '}·
							she starts inside &lt;think&gt;{/if}
					</div>
					<pre class="pe-text pe-raw">{#each tailSegs as g}{#if g.tok}<span class="pe-tok">{g.text}{#if g.n > 1}<b>{' '}×{g.n}</b>{/if}</span>{:else}<span class="pe-tpl">{ws(g.text)}</span>{/if}{/each}</pre>
					<details class="pe-sec" open>
						<summary
							><span class="pe-caret"></span>the whole prompt, as the template wrote it
							<span class="pe-dim"
								>· {rendered.text.length.toLocaleString()} chars{#if rview.missed}{' '}· {plural(rview.missed, 'message text')} reshaped by
									the template (shown as its words){/if}</span
							></summary
						>
						<pre class="pe-text">{#each rview.segs as g}{#if g.tok}<span class="pe-tok" class:pe-tok-in={!g.tpl}>{g.text}{#if g.n > 1}<b>{' '}×{g.n}</b>{/if}</span>{:else if g.src !== null}<mark class="pe-tint pe-c{g.src % TINTS}" title={sources[g.src]}>{g.text}</mark>{:else if g.tpl}<span class="pe-tpl">{g.text}</span>{:else}{g.text}{/if}{/each}</pre>
					</details>
					<div class="pe-meta">
						<button class="pe-more" on:click={copyRendered}>{copiedR ? '✓ copied' : '⧉ copy every character'}</button>
						<button class="pe-more" on:click={renderAgain}>render again</button>
					</div>
				{/if}
			{:else}
				<details class="pe-sec" open>
					<summary
						><span class="pe-caret"></span>parts
						<span class="pe-dim"
							>· {parts.length} · in the order Petal reads them{#if missing.length}{' '}· {missing.length} not found in what was sent{/if}</span
						></summary
					>
					{#each view.order as i (i)}
						{@const p = parts[i]}
						{@const pl = view.places[i]}
						{@const kind = partKind(p.source)}
						{@const xs = extras(p)}
						<details class="pe-part">
							<summary>
								<span class="pe-caret"></span>
								<span class="pe-sw pe-c{sources.indexOf(p.source) % TINTS}"></span>
								<span class="pe-psrc">{p.source}</span>
								{#if pl}
									<span class="pe-where">{pl.where}</span>{#if pl.role && /^turn \d+$/.test(pl.where)}<span class="pe-dim">· {pl.role}</span>{/if}
								{:else if kind !== 'text'}
									<span class="pe-where">{NOT_TEXT[kind]}</span>
								{:else if !p.text}
									<span class="pe-dim">· nothing to tint</span>
								{:else}
									<span class="pe-warn">· not in what was sent</span>
								{/if}
								<span class="pe-dim pe-mono"
									>{plural(p.text.length, 'char')}{#if xs.length}{' '}· {plural(xs.length, 'extra')}{/if}</span
								>
							</summary>
							<div class="pe-part-body">
								{#if p.text}
									<pre class="pe-text pe-raw">{p.text}</pre>
								{:else}
									<p class="pe-dim">no text{kind !== 'text' ? ` · ${NOT_TEXT[kind]}` : ''}</p>
								{/if}
								{#each xs as [k, v] (k)}
									{@const full = asJson(v)}
									{@const key = `${i}:${k}`}
									<div class="pe-param">
										<span class="pe-pk">{k}</span>
										<pre class="pe-text pe-pv">{openX[key] ? full : cut(full, 1200)}</pre>
										{#if full.length > 1200}
											<button class="pe-more" on:click={() => (openX = { ...openX, [key]: !openX[key] })}
												>{openX[key] ? 'fold' : 'show all'}</button
											>
										{/if}
									</div>
								{/each}
							</div>
						</details>
					{:else}
						<p class="pe-dim">no injector named its part for this request</p>
					{/each}
				</details>

				<details class="pe-sec" open>
					<summary
						><span class="pe-caret"></span>her system context
						<span class="pe-dim">· {view.sysChars.toLocaleString()} chars</span></summary
					>
					{#each view.sys as s, i (i)}
						{#if view.sys.length > 1}<div class="pe-sub">
								{s.at === null ? 'instructions' : view.labels[s.at]}
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
								<span class="pe-mono pe-dim">{view.labels[m.i]}</span>
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
							{#each m.rides as [k, , segs] (k)}
								<div class="pe-ride">
									<span class="pe-dim">rides along ·</span> <b>{k}</b>
									<pre class="pe-text">{#each segs as g}{#if g.src === null}{g.text}{:else}<mark class="pe-tint pe-c{g.src % TINTS}" title={sources[g.src]}>{g.text}</mark>{/if}{/each}</pre>
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

				<details class="pe-sec" open>
					<summary><span class="pe-caret"></span><span class="pe-emoji">🫗</span> petal-wellspring · raw at the source</summary>
					{#if marks.length}
						<div class="pe-marks">{#each marks as mk (mk)}<span class="pe-mark">{mk}</span>{/each}</div>
					{/if}
					{#if wellErr}
						<p class="pe-dim">{wellErr}{#if rec.to}{' '}· these bytes went to {rec.to}{/if}</p>
					{:else if !well}
						<p class="pe-dim">looking for the wellspring record…</p>
					{:else}
						<div class="pe-sub pe-mono">{well.path}</div>
						{#if metaLine.length}<div class="pe-sub">{metaLine.join(' · ')}</div>{/if}
						{#if well.view.flags?.length}
							<div class="pe-marks">{#each well.view.flags as f, fi (fi)}<span class="pe-mark">{f}</span>{/each}</div>
						{/if}
						{#if well.view.reasoning}
							<div class="pe-sub">her reasoning, raw</div>
							<pre class="pe-text pe-raw">{well.view.reasoning}</pre>
						{/if}
						{#if wrote !== null}
							<div class="pe-sub">what she wrote, raw</div>
							<pre class="pe-text pe-raw">{wrote}</pre>
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
								no content in this record (keys: {well.view.keys.join(', ')}) · the whole record is below
							</p>
						{/if}
						{#if well.view.raw}
							<button class="pe-more" on:click={() => (showRaw = !showRaw)}
								>{showRaw ? 'fold every raw character' : `every raw character · ${well.view.raw.length.toLocaleString()}`}</button
							>
							{#if showRaw}<pre class="pe-text pe-raw">{well.view.raw}</pre>{/if}
						{/if}
						<button class="pe-more" on:click={() => (showRecord = !showRecord)}
							>{showRecord ? 'fold the record' : 'the whole record'}</button
						>
						{#if showRecord}
							<pre class="pe-text pe-dim">{cut(JSON.stringify(well.record, null, 1), 200000)}</pre>
						{/if}
					{/if}
				</details>
			{/if}
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
	/* A13 · each part is a row that unfolds to its full text + extras, in the order Petal reads them */
	.pe-part {
		border-top: 1px solid var(--edge-soft, #2a2433);
		font-size: 0.78rem;
	}
	.pe-part:first-of-type {
		border-top: none;
	}
	.pe-part > summary {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.45rem;
		padding: 0.35rem 0;
		cursor: pointer;
		list-style: none;
		user-select: none;
	}
	.pe-part > summary::-webkit-details-marker {
		display: none;
	}
	.pe-part[open] > summary .pe-caret::before {
		content: '▾';
	}
	.pe-part > summary .pe-caret::before {
		width: 0.8rem;
	}
	.pe-part-body {
		padding: 0 0 0.6rem 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.pe-psrc {
		color: var(--pearl, #f6eef3);
	}
	.pe-where {
		color: var(--pearl, #f6eef3);
		font-size: 0.75rem;
		padding: 0 0.45rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian-lit, #1d1724);
	}
	/* 🧵 the rendered tab */
	.pe-tabs {
		display: flex;
		gap: 0.35rem;
	}
	.pe-tab {
		padding: 0.3rem 0.85rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
	}
	.pe-tab.on {
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian-lit, #1d1724), var(--obsidian-lit, #1d1724)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
		color: var(--pearl, #f6eef3);
	}
	.pe-rmeta {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.3rem;
		font-size: 0.78rem;
	}
	.pe-tpl {
		color: oklch(0.84 0.09 75);
		background: oklch(0.78 0.11 75 / 0.08);
		border-radius: 2px;
	}
	.pe-sw.pe-tplsw {
		background: oklch(0.78 0.11 75 / 0.45);
	}
	.pe-tok {
		display: inline;
		padding: 0 0.2em;
		border-radius: 4px;
		border: 1px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.45);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.12);
		color: var(--pearl, #f6eef3);
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.74rem;
		-webkit-box-decoration-break: clone;
		box-decoration-break: clone;
	}
	.pe-tok b {
		font-weight: 600;
		color: var(--whisper, #8a7d92);
	}
	.pe-tok.pe-tok-in {
		border-color: oklch(0.8 0.12 75 / 0.7);
		background: oklch(0.8 0.12 75 / 0.14);
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
