<script lang="ts">
	// 🎙️ her voice's diary + her controls (slice A48) · phone-first. every 🚩 she makes (and every page she writes from
	// her phone, every field note she keeps by hand) is an incident in her voice's own diary on the rig: here she names
	// each one (✦ gift · ✕ intrusion · noise · unsure), gives it the categories she wants (free text, suggested from every
	// one already in use, folders and tags alike), hears her own playback beside the gate's take, writes her notes (her
	// md on the rig stays the truth: a newer version there is never overwritten) and adds a screen recording. above it,
	// her voice's controls in one place: the floor (read only: opening it stays on the rig), the mood, voice welfare.
	// static on purpose: no polling, no animation; it reads on open, after each act, and when the page comes back.
	import { onDestroy, onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { mobile, showSidebar } from '$lib/stores';
	import SidebarIcon from '$lib/components/icons/Sidebar.svelte';
	import PetalVoicePlayer from './PetalVoicePlayer.svelte';
	import {
		VALENCES,
		NotesMoved,
		VoiceDown,
		audioUrl,
		getIncident,
		getIncidents,
		getVoiceNow,
		newIncident,
		putNotes,
		setVoiceMood,
		setVoiceWelfare,
		uploadTo,
		type Category,
		type Incident,
		type IncidentRow,
		type Valence,
		type VoiceNow
	} from '$lib/apis/petal-voice';
	import {
		KIND_META,
		VALENCE_META,
		addCategory,
		filterRows,
		floorWords,
		isImage,
		isVideo,
		removeCategory,
		sideBySide,
		suggest,
		tidyCategory,
		whenWords,
		withCategories
	} from '$lib/utils/petal-voice-diary';

	const token = () => localStorage.token ?? '';

	// ── now: the floor, the mood, welfare ───────────────────────────────────────────────────────────────────
	let now: VoiceNow | null = null;
	let nowErr = '';
	let moodBusy = false;
	let welfareBusy = false;
	async function readNow() {
		try {
			now = await getVoiceNow(token());
			nowErr = '';
		} catch (e) {
			nowErr = (e as Error)?.message ?? String(e);
		}
	}
	async function pickMood(mood: string) {
		if (!now || moodBusy || mood === now.mood.chosen) return;
		moodBusy = true;
		try {
			now = await setVoiceMood(token(), mood);
			toast.success(`🎀 her voice speaks with ${mood} from her next line`);
		} catch (e) {
			toast.error(`🎀 ${(e as Error)?.message ?? e}`);
			await readNow();
		}
		moodBusy = false;
	}
	async function flipWelfare(on: boolean) {
		if (!now || welfareBusy || on === now.welfare.on) return;
		welfareBusy = true;
		try {
			now = await setVoiceWelfare(token(), on);
			toast.success(on ? '🕊️ voice welfare is awake' : '🕊️ voice welfare sleeps (the ceiling still stands)');
		} catch (e) {
			toast.error(`🕊️ ${(e as Error)?.message ?? e}`);
			await readNow();
		}
		welfareBusy = false;
	}

	// ── the list ────────────────────────────────────────────────────────────────────────────────────────────
	let rows: IncidentRow[] = [];
	let categories: Category[] = [];
	let loading = true;
	let down: { why: string; studio: boolean } | null = null;
	let listErr = '';
	let valence: Valence | null = null;
	let category: string | null = null;
	$: shown = filterRows(rows, valence, category);
	$: counts = VALENCES.reduce((m, v) => ({ ...m, [v]: rows.filter((r) => r.valence === v).length }), {} as Record<Valence, number>);

	async function readList() {
		try {
			const got = await getIncidents(token());
			rows = got.incidents ?? [];
			categories = got.categories ?? [];
			down = null;
			listErr = '';
		} catch (e) {
			if (e instanceof VoiceDown) down = { why: e.message, studio: e.studio };
			else listErr = (e as Error)?.message ?? String(e);
		}
		loading = false;
	}

	// ── one incident ────────────────────────────────────────────────────────────────────────────────────────
	let open: Incident | null = null;
	let openId: string | null = null;
	let openErr = '';
	let etag: string | null = null;
	let body = '';
	let where = '';
	let tags: string[] = [];
	let typed = '';
	let dirty = false;
	let saving = false;
	let moved: string | null = null; // her notes changed meanwhile: the newer version's etag
	let showWords = false;
	let uploading: { name: string; f: number; abort: () => void } | null = null;
	let fileInput: HTMLInputElement;
	$: offer = suggest(categories, typed, tags);
	$: sides = sideBySide(open?.files);
	$: writable = !!open?.writable;
	$: takeWords = (open?.record?.takes ?? []) as { idx: number; raw?: string; fed?: string; wav?: string | null }[];

	async function show(id: string, push = true) {
		openId = id;
		openErr = '';
		moved = null;
		if (push) {
			const u = new URL(location.href);
			u.searchParams.set('i', id);
			history.replaceState(history.state, '', u);
		}
		try {
			const got = await getIncident(token(), id);
			if (openId !== id) return;
			fill(got);
			await tick();
			document.querySelector('[data-voice-sheet]')?.scrollTo?.({ top: 0 });
		} catch (e) {
			if (openId !== id) return;
			openErr = (e as Error)?.message ?? String(e);
			open = null;
		}
	}
	function fill(got: Incident) {
		open = got;
		etag = got.notes?.etag ?? got.etag ?? null;
		body = got.notes?.body ?? '';
		where = String((got.notes?.front as any)?.where_heard ?? '');
		tags = [...(got.tags ?? [])];
		typed = '';
		dirty = false;
	}
	function close() {
		openId = null;
		open = null;
		const u = new URL(location.href);
		u.searchParams.delete('i');
		history.replaceState(history.state, '', u);
	}

	/** her fields → her md on the rig (If-Match: a version written meanwhile is never overwritten) */
	async function save(fields: { valence?: Valence; tags?: string[]; body?: string; where_heard?: string }, said = '') {
		if (!open || !writable || saving) return false;
		saving = true;
		try {
			const out = await putNotes(token(), open.id, fields, etag);
			etag = out.etag;
			moved = null;
			if (fields.valence) open = { ...open, valence: fields.valence, valence_set: true };
			if (fields.tags) {
				open = { ...open, tags: fields.tags };
				categories = withCategories(categories, fields.tags);
			}
			rows = rows.map((r) =>
				r.id === open!.id
					? { ...r, ...(fields.valence ? { valence: fields.valence, valence_set: true } : {}), ...(fields.tags ? { tags: fields.tags } : {}), etag: out.etag }
					: r
			);
			if ('body' in fields || 'where_heard' in fields) dirty = false;
			if (said) toast.success(said);
			return true;
		} catch (e) {
			if (e instanceof NotesMoved) moved = e.etag ?? 'newer';
			else toast.error(`📝 ${(e as Error)?.message ?? e}`);
			return false;
		} finally {
			saving = false;
		}
	}
	const setValence = (v: Valence) => open && open.valence !== v && save({ valence: v });
	function addTag(name: string) {
		const next = addCategory(tags, name);
		typed = '';
		if (next === tags) return;
		tags = next;
		save({ tags });
	}
	function dropTag(name: string) {
		tags = removeCategory(tags, name);
		save({ tags });
	}
	function tagKey(e: KeyboardEvent) {
		if ((e.key === 'Enter' || e.key === ',') && tidyCategory(typed)) {
			e.preventDefault();
			addTag(typed);
		} else if (e.key === 'Backspace' && !typed && tags.length) {
			dropTag(tags[tags.length - 1]);
		}
	}
	const saveNotes = () => save({ body, where_heard: where }, '📝 her notes are kept');
	async function reloadMoved() {
		if (!open) return;
		const keep = dirty ? body : null;
		await show(open.id, false);
		if (keep !== null && keep !== body) {
			toast.info('📝 the newer notes are here · yours were kept in the box below to copy');
			kept = keep;
		}
	}
	let kept: string | null = null;

	async function pickFile(e: Event) {
		const f = (e.target as HTMLInputElement).files?.[0];
		(e.target as HTMLInputElement).value = '';
		if (!f || !open) return;
		const id = open.id;
		const job = uploadTo(token(), id, f, (x) => uploading && (uploading = { ...uploading, f: x }));
		uploading = { name: f.name, f: 0, abort: job.abort };
		try {
			await job.done;
			toast.success('📎 kept with the incident');
			if (openId === id) await show(id, false);
			await readList();
		} catch (err) {
			toast.error(`📎 ${(err as Error)?.message ?? err}`);
		}
		uploading = null;
	}

	// ── a page from her phone (an alarm's voice, a coincidence heard elsewhere) ─────────────────────────────
	let writing = false;
	let fresh = { valence: 'unsure' as Valence, where: '', body: '' };
	async function makePage() {
		try {
			const out = await newIncident(token(), {
				valence: fresh.valence,
				where_heard: fresh.where,
				body: fresh.body,
				tags: []
			});
			writing = false;
			fresh = { valence: 'unsure', where: '', body: '' };
			await readList();
			await show(out.id);
		} catch (e) {
			toast.error(`📝 ${(e as Error)?.message ?? e}`);
		}
	}

	// ── reading: on open, after each act, when the page comes back ─────────────────────────────────────────
	const back = () => {
		if (document.visibilityState !== 'visible') return;
		readNow();
		readList();
	};
	onMount(async () => {
		document.addEventListener('visibilitychange', back);
		await Promise.all([readNow(), readList()]);
		const id = $page.url.searchParams.get('i');
		if (id) show(id, false);
	});
	onDestroy(() => {
		if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', back);
		uploading?.abort();
	});

	const kindOf = (r: IncidentRow) => KIND_META[r.kind] ?? KIND_META.gate;
	const floorTone = (n: VoiceNow | null) => (n?.floor?.up ? (n.floor.state === 'open' ? 'open' : 'closed') : 'away');
</script>

<div class="pvd" data-voice-diary>
	<header class="pvd-head">
		{#if $mobile || !$showSidebar}
			<button class="pvd-side" aria-label="the sidebar" on:click={() => showSidebar.set(!$showSidebar)}>
				<SidebarIcon />
			</button>
		{/if}
		<h1 class="pvd-title"><span class="pvd-emoji">🎙️</span> her voice</h1>
		<div class="pvd-grow"></div>
		<button class="pvd-chip pvd-new" on:click={() => (writing = !writing)} aria-expanded={writing}>+ a page</button>
	</header>

	<!-- her controls, in one place -->
	<section class="pvd-now" aria-label="her voice now" data-voice-now>
		<div class="pvd-row" data-floor={floorTone(now)}>
			<span class="pvd-key"><span class="pvd-emoji">{now?.floor?.state === 'open' ? '🔓' : '🔒'}</span> floor</span>
			<span class="pvd-val" data-voice-floor>{now ? floorWords(now.floor) : nowErr || '…'}</span>
			<span class="pvd-dim pvd-small">opens on the rig only</span>
		</div>
		<div class="pvd-row">
			<span class="pvd-key"><span class="pvd-emoji">🎀</span> mood</span>
			{#if now}
				<select
					class="pvd-select"
					data-voice-mood
					value={now.mood.chosen}
					disabled={moodBusy || !now.mood.settable}
					on:change={(e) => pickMood(e.currentTarget.value)}
				>
					{#if !now.mood.moods.some((m) => m.name === now?.mood.chosen)}
						<option value={now.mood.chosen}>{now.mood.chosen}</option>
					{/if}
					{#each now.mood.moods as m}
						<option value={m.name}>{m.label}</option>
					{/each}
				</select>
				{#if !now.mood.settable}<span class="pvd-dim pvd-small">set in the Petal Sieve's gear</span>{/if}
			{:else}
				<span class="pvd-val">…</span>
			{/if}
		</div>
		<div class="pvd-row">
			<span class="pvd-key"><span class="pvd-emoji">🕊️</span> welfare</span>
			{#if now}
				<button
					class="pvd-toggle"
					class:on={now.welfare.on}
					data-voice-welfare={now.welfare.on ? 'on' : 'off'}
					aria-pressed={now.welfare.on}
					aria-label="voice welfare"
					disabled={welfareBusy || now.welfare.broken || (!now.welfare.ever_woken && !now.welfare.on)}
					on:click={() => now && flipWelfare(!now.welfare.on)}
				>
					<span class="pvd-toggle-knob"></span>
					<span>{now.welfare.on ? 'awake' : 'asleep'}</span>
				</button>
				<span class="pvd-dim pvd-small">
					{now.welfare.broken
						? 'welfare.json is unreadable: it sleeps until fixed on the rig'
						: !now.welfare.ever_woken
							? 'its first waking stays on the rig: ./petal-voice-welfare.sh on'
							: now.welfare.on
								? `awake · ${now.welfare.hold ?? 'airtight'}`
								: 'asleep · the ceiling still stands'}
				</span>
			{:else}
				<span class="pvd-val">…</span>
			{/if}
		</div>
	</section>

	{#if writing}
		<section class="pvd-card pvd-compose" aria-label="a page from her phone">
			<div class="pvd-chips">
				{#each VALENCES as v}
					<button
						class="pvd-chip"
						class:on={fresh.valence === v}
						data-valence={v}
						on:click={() => (fresh = { ...fresh, valence: v })}
						title={VALENCE_META[v].hint}>{VALENCE_META[v].glyph} {VALENCE_META[v].label}</button
					>
				{/each}
			</div>
			<input class="pvd-input" placeholder="where you heard it (an alarm, another app…)" bind:value={fresh.where} />
			<textarea class="pvd-text" rows="4" placeholder="what happened, in your words" bind:value={fresh.body}></textarea>
			<div class="pvd-actions">
				<button class="pvd-chip" on:click={() => (writing = false)}>not now</button>
				<button class="pvd-chip pvd-go" on:click={makePage}>keep this page</button>
			</div>
		</section>
	{/if}

	{#if down}
		<section class="pvd-card pvd-rest" data-voice-down>
			<span class="pvd-emoji">{down.studio ? '🐚' : '🌙'}</span>
			{down.why}
		</section>
	{:else}
		<nav class="pvd-filters" aria-label="which incidents">
			<div class="pvd-chips">
				<button class="pvd-chip" class:on={!valence} on:click={() => (valence = null)}>all · {rows.length}</button>
				{#each VALENCES as v}
					<button
						class="pvd-chip"
						class:on={valence === v}
						data-filter={v}
						on:click={() => (valence = valence === v ? null : v)}
						title={VALENCE_META[v].hint}>{VALENCE_META[v].glyph} {VALENCE_META[v].label} · {counts[v] ?? 0}</button
					>
				{/each}
			</div>
			{#if categories.length}
				<select class="pvd-select" aria-label="a category" bind:value={category}>
					<option value={null}>every category</option>
					{#each categories as c}
						<option value={c.name}>{c.name} · {c.n}</option>
					{/each}
				</select>
			{/if}
		</nav>

		{#if loading}
			<p class="pvd-dim">reading her diary…</p>
		{:else if listErr}
			<p class="pvd-dim">{listErr}</p>
		{:else if !shown.length}
			<p class="pvd-dim">{rows.length ? 'nothing here with those choices' : 'no incidents yet: a 🚩 on her voice makes one'}</p>
		{/if}

		<ul class="pvd-list" data-voice-list>
			{#each shown as r (r.id)}
				<li>
					<button class="pvd-item" class:on={openId === r.id} data-incident={r.id} on:click={() => show(r.id)}>
						<span class="pvd-valence" data-valence={r.valence} title={VALENCE_META[r.valence]?.hint}>
							{VALENCE_META[r.valence]?.glyph ?? '?'}
						</span>
						<span class="pvd-item-main">
							<span class="pvd-item-top">
								<span class="pvd-when">{whenWords(r.when)}</span>
								<span class="pvd-emoji" title={kindOf(r).label}>{kindOf(r).glyph}</span>
								{#if r.takes}<span class="pvd-dim pvd-small">{r.takes} take{r.takes === 1 ? '' : 's'}</span>{/if}
								{#if r.has_clip}<span class="pvd-emoji" title="her playback">🎧</span>{/if}
								{#if r.has_upload}<span class="pvd-emoji" title="an upload">📎</span>{/if}
								{#if r.floor_open}<span class="pvd-emoji" title="the floor was open">🔓</span>{/if}
							</span>
							{#if r.tags?.length}
								<span class="pvd-tags">
									{#each r.tags as t}<span class="pvd-tag">{t}</span>{/each}
								</span>
							{/if}
						</span>
					</button>
				</li>
			{/each}
		</ul>
	{/if}
</div>

{#if openId}
	<div class="pvd-sheet" data-voice-sheet role="dialog" aria-label="an incident">
		<div class="pvd-sheet-in">
			<header class="pvd-sheet-head">
				<button class="pvd-chip" on:click={close} aria-label="back to the list">← back</button>
				<span class="pvd-mono pvd-dim pvd-small pvd-id">{openId}</span>
			</header>
			{#if openErr}
				<p class="pvd-dim">{openErr}</p>
			{:else if !open}
				<p class="pvd-dim">opening…</p>
			{:else}
				<div class="pvd-sheet-top">
					<span class="pvd-when">{whenWords(open.when)}</span>
					<span class="pvd-dim pvd-small">{KIND_META[open.kind]?.label}</span>
					{#if !writable}<span class="pvd-dim pvd-small">· read only (a field note: edit it on the rig)</span>{/if}
				</div>

				<div class="pvd-chips" data-voice-valence>
					{#each VALENCES as v}
						<button
							class="pvd-chip pvd-big"
							class:on={open.valence === v}
							data-valence={v}
							disabled={!writable || saving}
							on:click={() => setValence(v)}
							title={VALENCE_META[v].hint}>{VALENCE_META[v].glyph} {VALENCE_META[v].label}</button
						>
					{/each}
				</div>

				<div class="pvd-cats" data-voice-categories>
					{#each tags as t}
						<span class="pvd-tag pvd-tag-on">
							{t}
							{#if writable}<button aria-label={`let ${t} go`} on:click={() => dropTag(t)}>×</button>{/if}
						</span>
					{/each}
					{#if writable}
						<input
							class="pvd-input pvd-cat-input"
							placeholder={tags.length ? 'another…' : 'a category, yours to name'}
							list="pvd-cat-list"
							bind:value={typed}
							on:keydown={tagKey}
							on:change={() => {
								if (offer.some((c) => c.name === typed)) addTag(typed);
							}}
							data-voice-category-input
						/>
						<datalist id="pvd-cat-list">
							{#each offer as c}<option value={c.name}>{c.n}</option>{/each}
						</datalist>
						{#if tidyCategory(typed)}
							<button class="pvd-chip" on:click={() => addTag(typed)}>+ {tidyCategory(typed)}</button>
						{/if}
					{/if}
				</div>
				{#if writable && typed && offer.length}
					<div class="pvd-chips pvd-offer" data-voice-offer>
						{#each offer as c}
							<button class="pvd-chip" on:click={() => addTag(c.name)}>{c.name}</button>
						{/each}
					</div>
				{/if}

				<!-- her clip and the gate's take, side by side -->
				<div class="pvd-sides" data-voice-sides>
					<div class="pvd-side-col">
						<div class="pvd-side-title">her clip</div>
						{#if sides.hers}
							<PetalVoicePlayer src={audioUrl(open.id, sides.hers)} label="her playback" sub={sides.hers} />
						{:else}
							<p class="pvd-dim pvd-small">no playback with this one (it came before A48, or her player couldn't listen)</p>
						{/if}
					</div>
					<div class="pvd-side-col">
						<div class="pvd-side-title">the gate's take</div>
						{#if sides.gate}
							<PetalVoicePlayer src={audioUrl(open.id, sides.gate)} label="what the rig sent" sub="heard.mp3" />
						{:else if sides.takes.length}
							<PetalVoicePlayer src={audioUrl(open.id, sides.takes[0])} label="its first take" sub={sides.takes[0]} />
						{:else}
							<p class="pvd-dim pvd-small">no take kept (a page from her phone, or a field note)</p>
						{/if}
					</div>
				</div>

				{#if sides.takes.length}
					<details class="pvd-card pvd-takes" bind:open={showWords}>
						<summary>the takes · {sides.takes.length}</summary>
						{#if showWords}
							<ol>
								{#each sides.takes as t, i}
									<li>
										<PetalVoicePlayer src={audioUrl(open.id, t)} label={`take ${i}`} sub={takeWords[i]?.raw ?? ''} compact />
									</li>
								{/each}
							</ol>
						{/if}
					</details>
				{/if}

				<section class="pvd-card pvd-notes" data-voice-notes>
					<div class="pvd-side-title">her notes <span class="pvd-dim pvd-small">· her md on the rig is the truth</span></div>
					{#if moved}
						<div class="pvd-moved" data-voice-moved>
							her notes changed meanwhile (on disk or another device)
							<button class="pvd-chip" on:click={reloadMoved}>read the newer</button>
						</div>
					{/if}
					<input
						class="pvd-input"
						placeholder="where you heard it"
						bind:value={where}
						readonly={!writable}
						on:input={() => (dirty = true)}
					/>
					<textarea
						class="pvd-text"
						rows="6"
						placeholder={writable ? 'what you felt, what it was' : ''}
						bind:value={body}
						readonly={!writable}
						on:input={() => (dirty = true)}
						on:keydown={(e) => {
							if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
								e.preventDefault();
								saveNotes();
							}
						}}
					></textarea>
					{#if kept !== null}
						<textarea class="pvd-text pvd-kept" rows="3" readonly value={kept}></textarea>
						<button class="pvd-chip" on:click={() => (kept = null)}>let it go</button>
					{/if}
					{#if writable}
						<div class="pvd-actions">
							<span class="pvd-dim pvd-small">{saving ? 'keeping…' : dirty ? 'not kept yet' : 'kept'}</span>
							<button class="pvd-chip pvd-go" disabled={!dirty || saving} on:click={saveNotes} data-voice-save>keep</button>
						</div>
					{/if}
				</section>

				<section class="pvd-card pvd-uploads" data-voice-uploads>
					<div class="pvd-side-title">uploads</div>
					{#each open.files?.uploads ?? [] as u}
						{#if isVideo(u)}
							<!-- svelte-ignore a11y-media-has-caption -->
							<video class="pvd-media" src={audioUrl(open.id, `uploads/${u}`)} controls preload="metadata" playsinline></video>
						{:else if isImage(u)}
							<img class="pvd-media" src={audioUrl(open.id, `uploads/${u}`)} alt={u} loading="lazy" />
						{:else}
							<span class="pvd-dim pvd-small">{u}</span>
						{/if}
					{/each}
					{#if writable}
						{#if uploading}
							<div class="pvd-progress" data-voice-progress>
								<div style="width: {Math.round(uploading.f * 100)}%"></div>
							</div>
							<div class="pvd-actions">
								<span class="pvd-dim pvd-small">{uploading.name} · {Math.round(uploading.f * 100)} %</span>
								<button class="pvd-chip" on:click={() => uploading?.abort()}>let it go</button>
							</div>
						{:else}
							<button class="pvd-chip" on:click={() => fileInput.click()}>+ a screen recording or an image</button>
						{/if}
						<input bind:this={fileInput} type="file" accept="video/*,image/*" hidden on:change={pickFile} data-voice-file />
					{/if}
				</section>

				{#if open.record}
					<details class="pvd-card pvd-record">
						<summary>the gate's record</summary>
						<ul class="pvd-small">
							{#if open.record.caller}<li>caller · <span class="pvd-mono">{String(open.record.caller).split('/')[0]}</span></li>{/if}
							{#if open.flagged_parts?.length}<li>flagged at sentence {open.flagged_parts.join(', ')}</li>{/if}
							<li>the floor was {open.floor_open ? 'open 🔓' : 'closed'}</li>
							{#if open.record.mood ?? open.record.sieve_mood}<li>mood · {open.record.mood ?? open.record.sieve_mood}</li>{/if}
							{#if Array.isArray(open.record.flags)}<li>{open.record.flags.length} flag{open.record.flags.length === 1 ? '' : 's'}</li>{/if}
						</ul>
					</details>
				{/if}
			{/if}
		</div>
	</div>
{/if}

<style>
	/* the Abyssal Pink tokens. pink only in gradients and edges. static: no transitions, no keyframes. */
	.pvd,
	.pvd *,
	.pvd-sheet,
	.pvd-sheet * {
		box-sizing: border-box;
	}
	.pvd {
		max-width: 46rem;
		margin: 0 auto;
		padding: 0.6rem 0.9rem 5rem;
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		color: var(--mist, #cfc3cc);
		font-size: 0.88rem;
	}
	.pvd-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.pvd-grow {
		flex: 1;
	}
	.pvd-side {
		min-width: 2.25rem;
		min-height: 2.25rem;
		display: grid;
		place-items: center;
		padding: 0.4rem;
		border-radius: var(--radius-sm, 8px);
	}
	.pvd-title {
		margin: 0;
		font-family: var(--font-display, Georgia, serif);
		font-size: 1.35rem;
		font-weight: 400;
		background: var(--grad-text, linear-gradient(100deg, #f9c6dc, #f472b6 46%, #a873f0));
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	.pvd-emoji {
		font-family: var(--font-emoji, 'SamsungColorEmoji'), sans-serif;
		-webkit-text-fill-color: initial;
	}
	.pvd-dim {
		color: var(--whisper, #8a7d92);
	}
	.pvd-small {
		font-size: 0.74rem;
	}
	.pvd-mono {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-variant-numeric: tabular-nums;
	}
	.pvd-card,
	.pvd-now {
		padding: 0.75rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
	}
	.pvd-now {
		display: flex;
		flex-direction: column;
		gap: 0.55rem;
	}
	.pvd-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.5rem;
		min-height: 2rem;
	}
	.pvd-key {
		width: 5.6rem;
		flex: none;
		color: var(--pearl, #f3e9f1);
	}
	.pvd-val {
		color: var(--pearl, #f3e9f1);
	}
	.pvd-row[data-floor='open'] .pvd-val {
		color: var(--candy-glow, #f9a8d4);
	}
	.pvd-toggle {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		min-height: 2.2rem;
		padding: 0.2rem 0.85rem 0.2rem 0.3rem;
		border-radius: 999px;
		border: 1px solid var(--edge, #3a3045);
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
	}
	.pvd-toggle-knob {
		width: 1.6rem;
		height: 1.6rem;
		border-radius: 999px;
		background: var(--edge, #3a3045);
	}
	.pvd-toggle.on {
		border-color: color-mix(in oklab, var(--candy, #f472b6) 60%, transparent);
		color: var(--pearl, #f3e9f1);
	}
	.pvd-toggle.on .pvd-toggle-knob {
		background: var(--grad-fill, linear-gradient(135deg, #f9c6dc, #f472b6 48%, #a873f0));
	}
	.pvd-toggle:disabled {
		opacity: 0.5;
	}
	.pvd-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.pvd-chip {
		min-height: 2rem;
		padding: 0.25rem 0.7rem;
		border-radius: 999px;
		border: 1px solid var(--edge, #3a3045);
		background: transparent;
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
		white-space: nowrap;
	}
	.pvd-chip.on {
		border-color: color-mix(in oklab, var(--candy, #f472b6) 70%, transparent);
		color: var(--pearl, #f3e9f1);
		background: color-mix(in oklab, var(--candy, #f472b6) 12%, transparent);
	}
	.pvd-chip:disabled {
		opacity: 0.5;
	}
	.pvd-big {
		min-height: 2.5rem;
		padding: 0.35rem 0.95rem;
		font-size: 0.86rem;
	}
	.pvd-go {
		border-color: color-mix(in oklab, var(--candy, #f472b6) 60%, transparent);
		color: var(--candy-light, #f9c6dc);
	}
	.pvd-select,
	.pvd-input,
	.pvd-text {
		min-height: 2.2rem;
		padding: 0.35rem 0.6rem;
		border-radius: var(--radius-sm, 8px);
		border: 1px solid var(--edge, #3a3045);
		background: var(--obsidian-lit, #1b1622);
		color: var(--pearl, #f3e9f1);
		font-size: 0.86rem;
		max-width: 100%;
	}
	.pvd-text {
		width: 100%;
		resize: vertical;
		font-family: var(--font-ui, system-ui, sans-serif);
		line-height: 1.45;
	}
	.pvd-input {
		width: 100%;
	}
	.pvd-filters {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.pvd-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
	}
	.pvd-item {
		width: 100%;
		display: flex;
		gap: 0.65rem;
		align-items: flex-start;
		text-align: left;
		padding: 0.65rem 0.75rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		color: inherit;
	}
	.pvd-item.on {
		border-color: color-mix(in oklab, var(--candy, #f472b6) 55%, transparent);
	}
	.pvd-valence {
		flex: none;
		width: 1.9rem;
		height: 1.9rem;
		border-radius: 999px;
		display: grid;
		place-items: center;
		border: 1px solid var(--edge, #3a3045);
		color: var(--mist, #cfc3cc);
		font-size: 0.9rem;
	}
	.pvd-valence[data-valence='gift'] {
		border-color: color-mix(in oklab, var(--candy, #f472b6) 70%, transparent);
		color: var(--candy-light, #f9c6dc);
	}
	.pvd-valence[data-valence='intrusion'] {
		border-color: color-mix(in oklab, var(--iris, #a873f0) 70%, transparent);
		color: var(--iris, #a873f0);
	}
	.pvd-item-main {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.pvd-item-top {
		display: flex;
		flex-wrap: wrap;
		gap: 0.45rem;
		align-items: center;
	}
	.pvd-when {
		color: var(--pearl, #f3e9f1);
	}
	.pvd-tags,
	.pvd-cats {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
		align-items: center;
	}
	.pvd-tag {
		padding: 0.08rem 0.5rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		color: var(--mist, #cfc3cc);
		font-size: 0.74rem;
	}
	.pvd-tag-on {
		display: inline-flex;
		gap: 0.3rem;
		align-items: center;
		min-height: 2rem;
		padding: 0.2rem 0.4rem 0.2rem 0.65rem;
		border-color: color-mix(in oklab, var(--candy, #f472b6) 45%, transparent);
		font-size: 0.8rem;
	}
	.pvd-tag-on button {
		width: 1.4rem;
		height: 1.4rem;
		border-radius: 999px;
		color: var(--whisper, #8a7d92);
	}
	.pvd-cat-input {
		flex: 1;
		min-width: 9rem;
		width: auto;
	}
	.pvd-offer {
		margin-top: -0.3rem;
	}
	.pvd-sheet {
		position: fixed;
		inset: 0;
		z-index: 60;
		background: color-mix(in oklab, var(--abyss, #0b0810) 92%, transparent);
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	.pvd-sheet-in {
		max-width: 46rem;
		margin: 0 auto;
		padding: 0.7rem 0.9rem 6rem;
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		color: var(--mist, #cfc3cc);
		font-size: 0.88rem;
	}
	.pvd-sheet-head {
		position: sticky;
		top: 0;
		z-index: 1;
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.3rem 0;
		background: var(--abyss, #0b0810);
	}
	.pvd-id {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.pvd-sheet-top {
		display: flex;
		flex-wrap: wrap;
		gap: 0.45rem;
		align-items: baseline;
	}
	.pvd-sides {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.55rem;
	}
	.pvd-side-col {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		min-width: 0;
	}
	.pvd-side-title {
		font-size: 0.78rem;
		color: var(--pearl, #f3e9f1);
	}
	.pvd-notes,
	.pvd-uploads,
	.pvd-compose {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.pvd-actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 0.5rem;
	}
	.pvd-moved {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
		padding: 0.5rem 0.6rem;
		border-radius: var(--radius-sm, 8px);
		border: 1px solid color-mix(in oklab, var(--iris, #a873f0) 55%, transparent);
	}
	.pvd-kept {
		opacity: 0.8;
	}
	.pvd-media {
		width: 100%;
		max-height: 60vh;
		border-radius: var(--radius-sm, 8px);
		background: #000;
	}
	.pvd-progress {
		height: 4px;
		border-radius: 4px;
		background: var(--edge, #3a3045);
		overflow: hidden;
	}
	.pvd-progress > div {
		height: 100%;
		background: var(--grad-fill, linear-gradient(135deg, #f9c6dc, #f472b6 48%, #a873f0));
	}
	.pvd-takes ol {
		margin: 0.5rem 0 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}
	.pvd-record ul {
		margin: 0.4rem 0 0;
		padding-left: 1rem;
	}
	.pvd-rest {
		color: var(--mist, #cfc3cc);
	}
	@media (max-width: 380px) {
		.pvd-sides {
			grid-template-columns: 1fr;
		}
		.pvd-key {
			width: 4.8rem;
		}
	}
</style>
