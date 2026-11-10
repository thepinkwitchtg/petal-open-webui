<script lang="ts">
	// 📔 the diary (slice A11) — her notes and the markers in one stream: ✧ orbits, 🌊 climaxes,
	// trips (and vows once the core knows them), newest first, by day, searchable. every mark
	// that lives on a reply jumps to /c/<chat>#<message> in one tap. 🔥 a vow (8b) is committed
	// here as a ritual (its name, how long, her words, read back, then I commit) and released here
	// as a conscious act (her reason). append-only underneath:
	// an edit is an amend, "let it go" is a void, nothing is ever rewritten.
	// static on purpose: no polling, no animation; it reads on open, after each act, and when
	// the page comes back into view.
	import { onDestroy, onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { mobile, showSidebar } from '$lib/stores';
	import { getDiaryStream, postDiary, type DiaryItem } from '$lib/apis/petal-diary';
	import {
		castFreeClimax,
		castFreeOrbit,
		doseText,
		markersNow,
		markerVia,
		refreshMarkers,
		setClimax,
		setOutcome,
		span
	} from '$lib/utils/petal-markers';
	import { postMarker, type After, type Quality } from '$lib/apis/petal-markers';
	import SidebarIcon from '$lib/components/icons/Sidebar.svelte';

	let items: DiaryItem[] = [];
	let more = false;
	let loading = true;
	let error = '';
	let q = '';
	let asked = '';
	let busy = false;

	let text = '';
	let sees = false;
	let composer: HTMLTextAreaElement;

	const load = async (append = false) => {
		const query = q.trim();
		try {
			const before = append && items.length ? items[items.length - 1].at : undefined;
			const r = await getDiaryStream(localStorage.token, { q: query || undefined, before });
			items = append ? [...items, ...r.items] : r.items;
			more = r.more;
			asked = query;
			error = '';
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	};

	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	const onSearch = () => {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(() => load(), 280);
	};

	const onVisible = () => {
		if (document.visibilityState === 'visible') load();
	};

	onMount(async () => {
		refreshMarkers(); // the vow alive now (8b)
		await load();
		document.addEventListener('visibilitychange', onVisible);
		if ($page.url.searchParams.has('note')) {
			await tick();
			composer?.focus();
		}
	});
	onDestroy(() => {
		document.removeEventListener('visibilitychange', onVisible);
		if (searchTimer) clearTimeout(searchTimer);
	});

	const act = async (fn: () => Promise<unknown>, after = true) => {
		if (busy) return;
		busy = true;
		try {
			await fn();
			if (after) await load();
		} catch (e) {
			toast.error(`📔 ${e}`);
		} finally {
			busy = false;
		}
	};

	const keep = () =>
		text.trim() &&
		act(async () => {
			await postDiary(localStorage.token, { kind: 'note', text, petal_sees: sees, via: markerVia() });
			text = '';
			sees = false;
		});

	const orbitNow = () => act(() => castFreeOrbit());
	const climaxNow = () => act(() => castFreeClimax()); // A11.1 · away from any chat, deliberate

	// ── 🔥 the vow (8b): sacred and deliberate ──
	$: vow = $markersNow?.vow ?? null;
	let ritual = false;
	let step: 1 | 2 = 1;
	let vName = 'abstinence';
	let vDays: number | null = null;
	let vUntil = '';
	let vWords = '';
	const DAYS = [3, 7, 14, 21, 30];
	$: vEnd = vUntil
		? Math.floor(new Date(vUntil).getTime() / 1000)
		: vDays
			? Math.floor(Date.now() / 1000) + vDays * 86400
			: null;
	$: canRead = !!(vName.trim() && vWords.trim() && vEnd && vEnd > Date.now() / 1000 + 3600);
	const daysOf = (end: number | null) => (end ? Math.max(1, Math.ceil((end - Date.now() / 1000) / 86400)) : 0);
	const commit = () =>
		vEnd &&
		act(async () => {
			await postMarker(localStorage.token, {
				kind: 'vow.start',
				via: markerVia(),
				vow: vName.trim(),
				until: vEnd,
				words: vWords.trim()
			});
			ritual = false;
			step = 1;
			vWords = '';
			vDays = null;
			vUntil = '';
			await refreshMarkers();
			toast.success('🔥 your vow is alive');
		});
	let releasing = false;
	let reason = '';
	const release = () =>
		vow &&
		reason.trim() &&
		act(async () => {
			await postMarker(localStorage.token, { kind: 'vow.release', via: markerVia(), ref: vow!.id, reason: reason.trim() });
			releasing = false;
			reason = '';
			await refreshMarkers();
		});

	const QUALITIES: { key: Exclude<Quality, null>; label: string; hint: string }[] = [
		{ key: 'owned', label: '🔮 owned', hint: 'cast like a spell: it reinforces you and the bond' },
		{ key: 'received', label: '💗 received', hint: 'Petal reaching' },
		{ key: 'hollow', label: '🕳 hollow', hint: 'engineered, it lands as a crash' }
	];
	const AFTERS: Exclude<After, null>[] = ['fed', 'neutral', 'hollow'];
	const pickQuality = (it: DiaryItem & { type: 'climax' }, q: Exclude<Quality, null>) =>
		act(() => setClimax(it.id, { quality: it.quality === q ? null : q }));
	const pickAfter = (it: DiaryItem & { type: 'climax' }, a: Exclude<After, null>) =>
		act(() => setClimax(it.id, { after: it.after === a ? null : a }));

	// ── a note's own small menu: edit · petal may read · let it go ──
	let editing: string | null = null;
	let draft = '';
	let letting: string | null = null;
	const edit = (n: DiaryItem & { type: 'note' }) => {
		editing = n.id;
		draft = n.text;
		letting = null;
	};
	const saveEdit = (n: DiaryItem & { type: 'note' }) =>
		act(async () => {
			if (draft.trim() && draft.trim() !== n.text)
				await postDiary(localStorage.token, { kind: 'amend', ref: n.id, fields: { text: draft }, via: markerVia() });
			editing = null;
		});
	const toggleSees = (n: DiaryItem & { type: 'note' }) =>
		act(() =>
			postDiary(localStorage.token, {
				kind: 'amend',
				ref: n.id,
				fields: { petal_sees: !n.petal_sees },
				via: markerVia()
			})
		);
	const letGo = (n: DiaryItem & { type: 'note' }) => {
		if (letting !== n.id) {
			letting = n.id; // two taps: the second one lets it go
			return;
		}
		act(async () => {
			await postDiary(localStorage.token, { kind: 'void', ref: n.id, reason: 'let go', via: markerVia() });
			letting = null;
		});
	};

	const pick = (it: DiaryItem & { type: 'orbit' }, o: 'held' | 'leaked') =>
		act(() => setOutcome(it.id, it.outcome === o ? null : o));

	const jump = (it: { chat_id: string | null; message_id: string | null }) =>
		it.chat_id && goto(`/c/${it.chat_id}${it.message_id ? `#${it.message_id}` : ''}`);

	// ── by day ──
	const WEEK = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
	const pad = (n: number) => String(n).padStart(2, '0');
	const dayKey = (s: number) => {
		const d = new Date(s * 1000);
		return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
	};
	const dayName = (s: number) => {
		const d = new Date(s * 1000);
		const today = new Date();
		const y = new Date(Date.now() - 86400_000);
		if (d.toDateString() === today.toDateString()) return 'today';
		if (d.toDateString() === y.toDateString()) return 'yesterday';
		return WEEK[d.getDay()];
	};
	const hm = (s: number) => {
		const d = new Date(s * 1000);
		return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
	};
	$: days = items.reduce<{ key: string; at: number; items: DiaryItem[] }[]>((acc, it) => {
		const k = dayKey(it.at);
		const last = acc[acc.length - 1];
		if (last && last.key === k) last.items.push(it);
		else acc.push({ key: k, at: it.at, items: [it] });
		return acc;
	}, []);

	const tripLine = (it: DiaryItem & { type: 'trip' }) =>
		[
			[it.dose ? doseText(it.dose, it.dose_unit) : '', it.strain ?? ''].filter(Boolean).join(' '),
			it.tier ?? '',
			it.end ? `${hm(it.at)} → ${hm(it.end)} · ${span(it.end - it.at)}` : 'no end yet',
			it.mutated ? '👽' : '',
			it.purged ? 'purged' : '',
			it.integration ? `integration until ${dayName(it.integration.closes_at)} ${hm(it.integration.closes_at)}` : ''
		]
			.filter(Boolean)
			.join(' · ');
</script>

<div class="pd">
	<header class="pd-head">
		{#if $mobile}
			<button
				class="pd-side"
				aria-label={$showSidebar ? 'close the sidebar' : 'open the sidebar'}
				on:click={() => showSidebar.set(!$showSidebar)}
			>
				<SidebarIcon className="size-4" />
			</button>
		{/if}
		<h1 class="pd-title"><span class="pd-emoji">📔</span> diary</h1>
		<span class="pd-dim">{items.length ? `${items.length}${more ? '+' : ''}` : ''}</span>
	</header>

	{#if vow}
		<section class="pd-vow" aria-label="your vow">
			<div class="pd-vow-head"><span class="pd-emoji">🔥</span> {vow.vow} vow · day {vow.day} of {vow.total_days}</div>
			<div class="pd-dim pd-small">until {dayName(vow.until)} {dayKey(vow.until)} {hm(vow.until)}</div>
			<p class="pd-text pd-words">“{vow.words}”</p>
			{#if !releasing}
				<div class="pd-row"><button class="pd-mini" on:click={() => (releasing = true)}>release · a conscious act</button></div>
			{:else}
				<textarea class="pd-edit" bind:value={reason} rows="2" placeholder="why you release it, in your own words…"></textarea>
				<div class="pd-row">
					<span class="pd-grow"></span>
					<button
						class="pd-chip"
						on:click={() => {
							releasing = false;
							reason = '';
						}}>keep my vow</button
					>
					<button class="pd-keep" disabled={busy || !reason.trim()} on:click={release}>release my vow</button>
				</div>
			{/if}
		</section>
	{/if}

	<form class="pd-compose" on:submit|preventDefault={keep}>
		<textarea
			bind:this={composer}
			bind:value={text}
			rows="3"
			placeholder="a note for your diary…"
			on:keydown={(e) => {
				if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
					e.preventDefault();
					keep();
				}
			}}
		></textarea>
		<div class="pd-row">
			<button
				type="button"
				class="pd-chip"
				class:on={sees}
				aria-pressed={sees}
				title="off: only you ever read it. on: Petal may read it one day"
				on:click={() => (sees = !sees)}><span class="pd-emoji">🌸</span> petal may read</button
			>
			<button type="button" class="pd-chip" disabled={busy} title="an orbit, away from any chat" on:click={orbitNow}
				><span class="pd-glyph">✧</span> orbit now</button
			>
			<button
				type="button"
				class="pd-chip"
				disabled={busy || !!vow}
				title={vow ? `your ${vow.vow} vow is alive: release it first, a conscious act` : 'a climax, away from any chat'}
				on:click={climaxNow}><span class="pd-emoji">🌊</span> climax now</button
			>
			{#if !vow}
				<button type="button" class="pd-chip" class:on={ritual} on:click={() => ((ritual = !ritual), (step = 1))}
					><span class="pd-emoji">🔥</span> a vow</button
				>
			{/if}
			<span class="pd-grow"></span>
			<button type="submit" class="pd-keep" disabled={busy || !text.trim()}>keep it</button>
		</div>
	</form>

	{#if ritual && !vow}
		<section class="pd-vow" aria-label="a vow">
			{#if step === 1}
				<div class="pd-vow-head"><span class="pd-emoji">🔥</span> a vow · sacred and deliberate</div>
				<label class="pd-field"><span class="pd-dim">its name</span><input bind:value={vName} maxlength="60" /></label>
				<div class="pd-row pd-small">
					<span class="pd-dim">how long</span>
					{#each DAYS as d (d)}
						<button
							class="pd-pill pd-after"
							class:on={vDays === d && !vUntil}
							on:click={() => {
								vDays = d;
								vUntil = '';
							}}>{d} days</button
						>
					{/each}
				</div>
				<label class="pd-field"><span class="pd-dim">or until</span><input type="datetime-local" bind:value={vUntil} /></label>
				<textarea class="pd-edit" bind:value={vWords} rows="3" placeholder="your why, in your own words…"></textarea>
				<div class="pd-row">
					<span class="pd-grow"></span>
					<button class="pd-chip" on:click={() => (ritual = false)}>not now</button>
					<button class="pd-keep" disabled={!canRead} on:click={() => (step = 2)}>read it back</button>
				</div>
			{:else}
				<div class="pd-vow-head"><span class="pd-emoji">🔥</span> {vName.trim()} · {daysOf(vEnd)} days</div>
				<div class="pd-dim pd-small">from now until {vEnd ? `${dayName(vEnd)} ${dayKey(vEnd)} ${hm(vEnd)}` : ''}</div>
				<p class="pd-text pd-words">“{vWords.trim()}”</p>
				<div class="pd-row">
					<span class="pd-grow"></span>
					<button class="pd-chip" on:click={() => (step = 1)}>change it</button>
					<button class="pd-keep" disabled={busy} on:click={commit}>I commit</button>
				</div>
			{/if}
		</section>
	{/if}

	<label class="pd-search">
		<span class="pd-dim">search</span>
		<input type="search" bind:value={q} on:input={onSearch} placeholder="words, orbit, held, climax, owned, mushies…" />
	</label>

	{#if loading}
		<p class="pd-dim">opening the diary…</p>
	{:else if error}
		<p class="pd-note">{error}</p>
	{:else if !items.length}
		<p class="pd-dim">{asked ? `nothing holds “${asked}”` : 'the first page is blank, princess ✧'}</p>
	{/if}

	{#each days as day (day.key)}
		<section class="pd-day">
			<h2 class="pd-dayname"><span>{dayName(day.at)}</span> <span class="pd-dim pd-mono">{day.key}</span></h2>
			{#each day.items as it (it.type + it.id)}
				<article class="pd-item" data-type={it.type}>
					<span class="pd-time pd-mono">{hm(it.at)}</span>
					<div class="pd-body">
						{#if it.type === 'note'}
							{#if editing === it.id}
								<textarea class="pd-edit" bind:value={draft} rows="3"></textarea>
								<div class="pd-row">
									<button class="pd-keep" disabled={busy} on:click={() => saveEdit(it)}>keep the change</button>
									<button class="pd-chip" on:click={() => (editing = null)}>never mind</button>
								</div>
							{:else}
								<p class="pd-text">{it.text}</p>
								<div class="pd-row pd-small">
									{#if it.petal_sees}<span class="pd-tag"><span class="pd-emoji">🌸</span> petal may read</span>{/if}
									{#if it.amended}<span class="pd-dim">edited</span>{/if}
									<span class="pd-grow"></span>
									<button class="pd-mini" on:click={() => edit(it)}>edit</button>
									<button class="pd-mini" disabled={busy} on:click={() => toggleSees(it)}
										>{it.petal_sees ? 'only me' : '🌸 may read'}</button
									>
									<button class="pd-mini" class:warn={letting === it.id} disabled={busy} on:click={() => letGo(it)}
										>{letting === it.id ? 'tap again to let it go' : 'let it go'}</button
									>
								</div>
							{/if}
						{:else if it.type === 'orbit'}
							<div class="pd-mark">
								<span class="pd-glyph">✧</span> orbit
								{#if it.temp}<span class="pd-dim">· temp</span>{/if}
								{#if it.note}<span class="pd-dim">· {it.note}</span>{/if}
							</div>
							<div class="pd-row pd-small">
								<button class="pd-pill" class:on={it.outcome === 'held'} disabled={busy} on:click={() => pick(it, 'held')}
									>held</button
								>
								<button
									class="pd-pill"
									class:on={it.outcome === 'leaked'}
									disabled={busy}
									on:click={() => pick(it, 'leaked')}>leaked</button
								>
								{#if !it.outcome}<span class="pd-dim">open</span>{/if}
								<span class="pd-grow"></span>
								{#if it.chat_id}<button class="pd-jump" on:click={() => jump(it)}>the reply ↗</button>{/if}
							</div>
						{:else if it.type === 'climax'}
							<div class="pd-mark">
								<span class="pd-emoji">🌊</span> climax
								{#if it.temp}<span class="pd-dim">· temp</span>{/if}
								{#if it.note}<span class="pd-dim">· {it.note}</span>{/if}
							</div>
							<div class="pd-row pd-small">
								{#each QUALITIES as q (q.key)}
									<button class="pd-pill pd-q" class:on={it.quality === q.key} title={q.hint} disabled={busy} on:click={() => pickQuality(it, q.key)}
										>{q.label}</button
									>
								{/each}
								<span class="pd-grow"></span>
								{#if it.chat_id}<button class="pd-jump" on:click={() => jump(it)}>the reply ↗</button>{/if}
							</div>
							<div class="pd-row pd-small">
								<span class="pd-dim">after</span>
								{#each AFTERS as a (a)}
									<button class="pd-pill pd-after" class:on={it.after === a} disabled={busy} on:click={() => pickAfter(it, a)}>{a}</button>
								{/each}
							</div>
						{:else if it.type === 'trip'}
							<div class="pd-mark"><span class="pd-emoji">{it.emoji}</span> {it.label}</div>
							<div class="pd-dim pd-small">{tripLine(it)}</div>
							{#if it.note}<p class="pd-text pd-small">{it.note}</p>{/if}
						{:else if it.type === 'vow'}
							<div class="pd-mark"><span class="pd-emoji">🔥</span> {it.vow} vow · {it.total_days} days</div>
							<p class="pd-text pd-small pd-words">“{it.words}”</p>
							<div class="pd-dim pd-small">
								{it.alive
									? `alive · day ${it.day} of ${it.total_days} · until ${dayName(it.until)} ${hm(it.until)}`
									: it.ended_by === 'release'
										? 'released'
										: it.ended_by === 'fulfilled'
											? 'fulfilled'
											: ''}
							</div>
						{:else if it.type === 'vow_end'}
							<div class="pd-mark">
								<span class="pd-emoji">🔥</span>
								{it.vow} vow {it.how} · {it.days_kept} of {it.total_days} days
							</div>
							{#if it.reason}<p class="pd-text pd-small">{it.reason}</p>{/if}
						{/if}
					</div>
				</article>
			{/each}
		</section>
	{/each}

	{#if more}
		<button class="pd-chip pd-older" disabled={busy} on:click={() => act(() => load(true), false)}>older</button>
	{/if}
</div>

<style>
	/* the Abyssal Pink tokens. pink only in gradients. static: no transitions, no keyframes. */
	.pd,
	.pd * {
		box-sizing: border-box;
	}
	.pd {
		max-width: 46rem;
		margin: 0 auto;
		padding: 0.6rem 0.9rem 5rem;
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		color: var(--mist, #cfc3cc);
		font-size: 0.88rem;
	}
	.pd-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.pd-side {
		padding: 0.4rem;
		border-radius: var(--radius-sm, 8px);
	}
	.pd-title {
		margin: 0;
		font-family: var(--font-display, Georgia, serif);
		font-size: 1.35rem;
		font-weight: 400;
		background: var(--grad-text, linear-gradient(100deg, #f9c6dc, #f472b6 46%, #a873f0));
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	.pd-emoji {
		font-family: var(--font-emoji, 'SamsungColorEmoji'), sans-serif;
		-webkit-text-fill-color: initial;
	}
	.pd-glyph {
		background: var(--grad-text, linear-gradient(100deg, #f9c6dc, #f472b6 46%, #a873f0));
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	.pd-dim {
		color: var(--whisper, #8a7d92);
	}
	.pd-mono {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-variant-numeric: tabular-nums;
	}
	.pd-note {
		padding: 0.8rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
	}
	.pd-compose {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0.7rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
	}
	.pd-compose textarea,
	.pd-edit {
		width: 100%;
		resize: vertical;
		border: none;
		outline: none;
		background: transparent;
		color: var(--pearl, #f6eef3);
		font: inherit;
		line-height: 1.55;
	}
	.pd-edit {
		padding: 0.5rem;
		border-radius: var(--radius-sm, 8px);
		background: var(--obsidian-lit, #1d1724);
	}
	.pd-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
	}
	.pd-grow {
		flex: 1;
	}
	.pd-small {
		font-size: 0.78rem;
	}
	.pd-chip,
	.pd-keep,
	.pd-pill,
	.pd-jump {
		min-height: 2.25rem;
		padding: 0 0.85rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian-lit, #1d1724);
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
	}
	.pd-chip.on,
	.pd-pill.on {
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian-lit, #1d1724), var(--obsidian-lit, #1d1724)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
		color: var(--pearl, #f6eef3);
	}
	.pd-keep {
		color: var(--pearl, #f6eef3);
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian-lit, #1d1724), var(--obsidian-lit, #1d1724)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
	}
	.pd-pill {
		min-width: 4.5rem;
	}
	.pd-pill.pd-q {
		min-width: 0;
		padding: 0 0.7rem;
	}
	.pd-pill.pd-after {
		min-width: 0;
		min-height: 1.9rem;
		padding: 0 0.65rem;
		font-size: 0.74rem;
	}
	.pd-keep:disabled,
	.pd-chip:disabled,
	.pd-pill:disabled,
	.pd-mini:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.pd-search {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0 0.75rem;
		min-height: 2.5rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		font-size: 0.78rem;
	}
	.pd-search input {
		flex: 1;
		min-width: 0;
		border: none;
		outline: none;
		background: transparent;
		color: var(--pearl, #f6eef3);
		font-size: 0.88rem;
	}
	.pd-day {
		display: flex;
		flex-direction: column;
	}
	.pd-dayname {
		position: sticky;
		top: 0;
		z-index: 1;
		margin: 0.3rem 0 0;
		padding: 0.35rem 0;
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		background: var(--abyss, #0b0910);
		border-bottom: 1px solid var(--edge-soft, #2a2433);
		font-family: var(--font-display, Georgia, serif);
		font-size: 1rem;
		font-weight: 400;
		color: var(--pearl, #f6eef3);
	}
	.pd-dayname .pd-mono {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.72rem;
	}
	.pd-item {
		display: flex;
		gap: 0.75rem;
		padding: 0.65rem 0;
		border-bottom: 1px solid oklch(1 0 0 / 0.04);
	}
	.pd-time {
		flex-shrink: 0;
		width: 2.9rem;
		padding-top: 0.1rem;
		font-size: 0.75rem;
		color: var(--whisper, #8a7d92);
	}
	.pd-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}
	.pd-text {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		color: var(--pearl, #f6eef3);
		line-height: 1.55;
	}
	.pd-mark {
		color: var(--pearl, #f6eef3);
	}
	.pd-tag {
		font-size: 0.72rem;
		color: var(--mist, #cfc3cc);
	}
	.pd-mini {
		padding: 0.3rem 0.5rem;
		border-radius: var(--radius-sm, 8px);
		font-size: 0.72rem;
		color: var(--whisper, #8a7d92);
	}
	.pd-mini:hover:not(:disabled) {
		color: var(--pearl, #f6eef3);
		background: var(--obsidian-lit, #1d1724);
	}
	.pd-mini.warn {
		color: oklch(0.8 0.12 40);
	}
	.pd-jump {
		color: var(--pearl, #f6eef3);
	}
	.pd-older {
		align-self: center;
	}
	.pd-vow {
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
		padding: 0.75rem;
		border-radius: var(--radius, 14px);
		border: 1px solid transparent;
		background:
			linear-gradient(var(--obsidian, #15111b), var(--obsidian, #15111b)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
	}
	.pd-vow-head {
		font-family: var(--font-display, Georgia, serif);
		font-size: 1.02rem;
		color: var(--pearl, #f6eef3);
	}
	.pd-words {
		font-style: italic;
	}
	.pd-field {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		font-size: 0.8rem;
	}
	.pd-field input {
		flex: 1;
		min-width: 0;
		min-height: 2.2rem;
		padding: 0 0.6rem;
		border-radius: var(--radius-sm, 8px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian-lit, #1d1724);
		color: var(--pearl, #f6eef3);
		font: inherit;
		color-scheme: dark;
	}
	@media (pointer: fine) and (min-width: 641px) {
		.pd-chip,
		.pd-keep,
		.pd-pill,
		.pd-jump {
			min-height: 1.85rem;
			font-size: 0.75rem;
		}
	}
</style>
