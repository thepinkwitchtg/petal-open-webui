<script lang="ts">
	// 🌙 petal states · the panel (W4) — the forge, rendered from whatever it declares. this fork ships empty:
	// no gems, no words, no names live in this file. the schema and its words stay on the rig (Petal-App-Data),
	// petal-witch-forge shapes them, and this panel reads them through /api/v1/petal/forge (admin-only).
	// here, and on the phone: rewrite a gem's words, retire or restore one, turn a knob, touch the readout.
	// every keep is a whole version in the forge's history, merged field by field if the rig saved meanwhile.
	// it asks when it opens, after a pause in an edit, and when ↻ is tapped: no polling, no animation.
	import { getContext, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { user } from '$lib/stores';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import ModelSettingsLabel from './ModelSettingsLabel.svelte';

	const i18n: any = getContext('i18n');

	export let meta: Record<string, any> = {}; // the card's meta stays as it is: the forge lives outside it
	export let system = '';
	export let disabled = false;
	export let modelId: string | null = null; // the editor may pass its id; otherwise the edit page's ?id=

	type Doc = Record<string, any>;
	type Seg = { text: string; kind: string; gem?: string };

	const STATES = '{{states}}';
	const READOUT = '{{readout}}';
	const FOOTNOTE = 'footnote'; // rides under her latest message, never in a prompt
	const tokenOf = (slot: string) =>
		slot === 'states' ? STATES : slot === 'readout' ? READOUT : slot === FOOTNOTE ? '🪶 footnote' : `{{slot:${slot}}}`;
	const slotRank = (s: string) => (s === 'states' ? 0 : s === FOOTNOTE ? 2 : 1);
	const clone = (x: any) => (x == null ? x : JSON.parse(JSON.stringify(x)));
	const same = (a: any, b: any) => JSON.stringify(a) === JSON.stringify(b);
	const ord = (x: any) => (typeof x?.order === 'number' ? x.order : 100);
	const slotOf = (g: any) => g.slot || 'states';

	let open = false;
	let installed: boolean | null = null;
	let why = '';
	let loading = false;
	let saved: Doc | null = null; // the forge as it was read: the base every keep carries
	let draft: Doc | null = null;
	let versions: any[] = [];
	let preview: any = null;
	let previewDoc: Doc | null = null;
	let previewError = '';
	let showRetired = false;
	let note = '';
	let keeping = false;
	let message = '';
	let clash: any[] | null = null;
	let letGo: { name: string; text: string }[] = [];
	let timer: ReturnType<typeof setTimeout> | null = null;
	let seq = 0;

	$: model = modelId ?? $page?.url?.searchParams?.get('id') ?? null;
	$: admin = $user?.role === 'admin';
	$: if (admin && installed === null && !loading) load();
	$: gems = [...(draft?.gems ?? [])].sort(
		(a, b) => slotRank(slotOf(a)) - slotRank(slotOf(b)) || slotOf(a).localeCompare(slotOf(b)) || ord(a) - ord(b)
	);
	$: worn = (g: any) => {
		const w = Array.isArray(g.wearers) && g.wearers.length ? g.wearers : ['*'];
		return w.includes('*') || (!!model && w.includes(model));
	};
	$: here = gems.filter((g) => worn(g) && (showRetired || !g.retired));
	$: retiredCount = gems.filter((g) => worn(g) && g.retired).length;
	$: knobs = (draft?.knobs ?? []).filter((k: any) => showRetired || !k.retired);
	$: allLines = [...(draft?.readout?.lines ?? [])]
		.sort((a, b) => ord(a) - ord(b))
		.filter((l) => showRetired || !l.retired);
	$: lines = allLines.filter((l) => l.slot !== FOOTNOTE);
	$: noteLines = allLines.filter((l) => l.slot === FOOTNOTE);
	$: empty = !!draft && !draft.gems?.length && !draft.knobs?.length && !draft.readout?.lines?.length;
	$: dirty = !!saved && !same(saved, draft);
	$: live = preview?.gems_live ?? [];
	$: liveHere = here.filter((g) => live.includes(g.id)).length;
	// a fresh look when an edit pauses, the prompt above changes, or it opens · one look while folded, for the
	// count above · the answer itself never asks again (kick reads preview without depending on it)
	$: kick(draft, system, model, open, installed);
	function kick(..._: unknown[]) {
		if (!installed || empty) return;
		if (open) previewSoon(preview ? 450 : 0);
		else if (!preview) previewSoon(0);
	}

	onDestroy(() => timer && clearTimeout(timer));

	// defaults, not `?` params: older and newer svelte printers both read these plainly
	const call = async (path: string, body: any = undefined) => {
		const res = await fetch(`${WEBUI_API_BASE_URL}/petal/forge${path}`, {
			method: body === undefined ? 'GET' : 'POST',
			headers: {
				Accept: 'application/json',
				...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
				authorization: `Bearer ${localStorage.token}`
			},
			...(body !== undefined ? { body: JSON.stringify(body) } : {})
		});
		const json = await res.json().catch(() => ({}));
		if (!res.ok) {
			const d = json?.detail;
			throw { status: res.status, ...(d && typeof d === 'object' ? d : { error: d ?? `the forge answered ${res.status}` }) };
		}
		return json;
	};

	async function load() {
		loading = true;
		try {
			const r = await call('');
			installed = !!r.installed;
			why = r.why ?? '';
			if (r.installed) {
				saved = r.doc;
				draft = clone(r.doc);
				versions = r.versions ?? [];
			}
		} catch (e: any) {
			installed = false;
			why = e?.status === 404 ? 'the forge door isn’t in this OWUI yet' : (e?.error ?? 'the forge didn’t answer');
		}
		loading = false;
	}

	function previewSoon(ms: number) {
		if (timer) clearTimeout(timer);
		timer = setTimeout(askPreview, ms);
	}

	async function askPreview() {
		timer = null;
		if (!draft) return;
		const mine = ++seq;
		const doc = clone(draft);
		try {
			const r = await call('/preview', { model, template: system ?? '', doc });
			if (mine !== seq) return;
			preview = r;
			previewDoc = doc;
			previewError = '';
		} catch (e: any) {
			if (mine === seq) previewError = e?.error ?? 'the preview didn’t come back';
		}
	}

	async function refresh() {
		message = '';
		if (dirty) return previewSoon(0);
		installed = null; // the reactive line above reads it all again
	}

	// her edits, on this device · every one a copy, so the draft never moves underfoot
	const setGem = (id: string, patch: Doc) => {
		draft = { ...draft, gems: draft!.gems.map((g: any) => (g.id === id ? { ...g, ...patch } : g)) };
	};
	const setKnob = (id: string, value: any) => {
		draft = { ...draft, knobs: draft!.knobs.map((k: any) => (k.id === id ? { ...k, value } : k)) };
	};
	const setLine = (id: string, patch: Doc) => {
		draft = {
			...draft,
			readout: { ...draft!.readout, lines: draft!.readout.lines.map((l: any) => (l.id === id ? { ...l, ...patch } : l)) }
		};
	};
	const setWrap = (key: 'head' | 'foot', text: string) => {
		const ro = { ...(draft!.readout ?? {}) };
		if (text.trim()) ro[key] = text;
		else delete ro[key];
		draft = { ...draft, readout: ro };
	};
	const onWords = (id: string) => (e: Event) => setGem(id, { words: (e.target as HTMLTextAreaElement).value });
	// a readout line wraps on a narrow screen but stays one line: Enter is refused, a pasted break becomes a space
	const oneLine = (e: KeyboardEvent) => e.key === 'Enter' && e.preventDefault();
	const mend = (t: string) => t.replace(/\s*\n\s*/g, ' ');
	const onLineWords = (id: string) => (e: Event) => {
		const el = e.target as HTMLTextAreaElement;
		const words = mend(el.value);
		if (words !== el.value) {
			const at = mend(el.value.slice(0, el.selectionStart ?? el.value.length)).length;
			el.value = words;
			el.setSelectionRange(at, at);
			el.dispatchEvent(new Event('input', { bubbles: true })); // the textarea's own copy hears the mended line too
			return;
		}
		setLine(id, { words });
	};
	const nudge = (k: any, dir: number) => {
		const step = Number.isInteger(k.value) ? 1 : 0.5;
		setKnob(k.id, Math.round(((Number(k.value) || 0) + dir * step) * 100) / 100);
	};

	function changes(a: Doc | null, b: Doc | null): string[] {
		if (!a || !b) return [];
		const out: string[] = [];
		const kinds: [(d: Doc) => any[], string][] = [
			[(d) => d.gems ?? [], 'gem'],
			[(d) => d.knobs ?? [], 'knob'],
			[(d) => d.readout?.lines ?? [], 'line']
		];
		for (const [pick] of kinds) {
			const before = new Map(pick(a).map((x: any) => [x.id, x]));
			for (const x of pick(b)) {
				const y: any = before.get(x.id);
				const name = x.name ?? x.id;
				if (!y) out.push(`${name} (new)`);
				else for (const k of new Set([...Object.keys(x), ...Object.keys(y)])) if (!same(x[k], y[k])) out.push(`${name} · ${k}`);
			}
		}
		for (const k of ['head', 'foot']) if ((a.readout?.[k] ?? '') !== (b.readout?.[k] ?? '')) out.push(`readout ${k}`);
		return out;
	}

	async function keep(prefer: 'mine' | 'theirs' | null = null) {
		if (!draft || !saved) return;
		keeping = true;
		message = '';
		const held = draft;
		try {
			const r = await call('/save', {
				doc: draft,
				note: note.trim() || `📱 ${changes(saved, draft).join(', ')}`,
				base: saved,
				...(prefer ? { prefer } : {})
			});
			letGo = prefer === 'theirs' && clash
				? clash.filter((c) => c.kind !== 'forge').map((c) => ({ name: clashName(c), text: textOf(held, c) }))
				: [];
			const settled = prefer && clash?.length
				? ` · ${prefer === 'mine' ? 'this device’s' : 'the rig’s'} kept for ${clash.map(clashName).join(', ')}`
				: '';
			saved = r.doc;
			draft = clone(r.doc);
			versions = r.versions ?? versions;
			clash = null;
			note = '';
			message = `kept · ${r.version}${r.merged ? ' · merged over what the rig saved' : ''}${settled}`;
		} catch (e: any) {
			if (e?.status === 409) {
				clash = (e.conflict ?? []).filter((c: any) => !c.settled);
				message = e.error ?? 'the rig saved the same words meanwhile';
			} else message = `not kept · ${e?.error ?? e}`;
		}
		keeping = false;
		previewSoon(0);
	}

	const clashName = (c: any) => (c.key === '*' ? c.name : `${c.name} · ${c.key}`);

	function textOf(d: Doc, c: any): string {
		const list = c.kind === 'gem' ? d.gems : c.kind === 'knob' ? d.knobs : c.kind === 'line' ? d.readout?.lines : null;
		if (c.kind === 'readout') return String(d.readout?.[c.key] ?? '');
		const item = (list ?? []).find((x: any) => x.id === c.id);
		const v = c.key === '*' ? item : item?.[c.key];
		return typeof v === 'string' ? v : JSON.stringify(v);
	}

	const letDraftGo = () => {
		draft = clone(saved);
		clash = null;
		message = 'these edits are let go · the forge is as the rig keeps it';
	};

	// the legend · a tap puts the token at the cursor in the System Prompt (or at its end when it's folded)
	const insert = (token: string) => {
		const el = document.querySelector(`textarea[aria-label="${$i18n.t('System Prompt')}"]`) as HTMLTextAreaElement | null;
		if (el) {
			const a = el.selectionStart ?? el.value.length;
			const b = el.selectionEnd ?? a;
			el.value = el.value.slice(0, a) + token + el.value.slice(b);
			el.dispatchEvent(new Event('input', { bubbles: true }));
			el.focus();
			el.setSelectionRange(a + token.length, a + token.length);
		} else {
			system = `${system.trimEnd()}\n${token}`;
		}
	};
	$: tokens = [
		...new Set([...gems.filter((g) => !g.retired && slotOf(g) !== FOOTNOTE).map(slotOf), ...(lines.length ? ['readout'] : [])])
	].sort((a, b) => (a === 'states' ? -1 : b === 'states' ? 1 : a === 'readout' ? 1 : b === 'readout' ? -1 : a.localeCompare(b)));

	// what Petal reads · the forge's own string, with each live gem and the readout tinted
	function pieces(slot: string, text: string, liveGems: any[]): Seg[] {
		if (slot === 'readout') return [{ kind: 'readout', text }];
		const out: Seg[] = [];
		let i = 0;
		for (const g of liveGems.filter((x) => slotOf(x) === slot)) {
			const w = String(g.words ?? '').trim();
			const at = w ? text.indexOf(w, i) : -1;
			if (at < 0) continue;
			if (at > i) out.push({ kind: 'plain', text: text.slice(i, at) });
			out.push({ kind: 'gem', gem: g.id, text: w });
			i = at + w.length;
		}
		if (i < text.length) out.push({ kind: 'plain', text: text.slice(i) });
		return out.length ? out : [{ kind: 'slot', text }];
	}
	function segmentsOf(p: any, doc: Doc | null): Seg[] {
		if (!p) return [];
		const byId = new Map((doc?.gems ?? []).map((g: any) => [g.id, g]));
		const liveGems = (p.gems_live ?? []).map((id: string) => byId.get(id)).filter(Boolean);
		const tbs: Record<string, string> = p.text_by_slot ?? {};
		if (typeof p.prompt !== 'string') {
			return Object.entries(tbs).flatMap(([slot, text]) => [{ kind: 'label', text: `${tokenOf(slot)}\n` }, ...pieces(slot, text, liveGems), { kind: 'plain', text: '\n\n' }]);
		}
		const ranges: { at: number; end: number; slot: string; text: string }[] = [];
		for (const [slot, text] of Object.entries(tbs)) {
			if (!text) continue;
			for (let from = 0, at = p.prompt.indexOf(text); at >= 0; from = at + text.length, at = p.prompt.indexOf(text, from))
				ranges.push({ at, end: at + text.length, slot, text });
		}
		ranges.sort((a, b) => a.at - b.at || b.end - a.end);
		const out: Seg[] = [];
		let i = 0;
		for (const r of ranges) {
			if (r.at < i) continue;
			if (r.at > i) out.push({ kind: 'plain', text: p.prompt.slice(i, r.at) });
			out.push(...pieces(r.slot, r.text, liveGems));
			i = r.end;
		}
		if (i < p.prompt.length) out.push({ kind: 'plain', text: p.prompt.slice(i) });
		return out;
	}
	$: segs = segmentsOf(preview, previewDoc);
	// the note under her latest message · head, her lines (the state), the gems' words (the steer), foot
	function notePieces(fn: any): Seg[] {
		const text: string = fn?.text ?? '';
		if (!text) return [];
		const out: Seg[] = [];
		let i = 0;
		for (const it of fn.items ?? []) {
			const w = String(it.text ?? '');
			const at = w ? text.indexOf(w, i) : -1;
			if (at < 0) continue;
			if (at > i) out.push({ kind: 'plain', text: text.slice(i, at) });
			out.push({ kind: it.kind === 'gem' ? 'gem' : 'note', gem: it.id, text: w });
			i = at + w.length;
		}
		if (i < text.length) out.push({ kind: 'plain', text: text.slice(i) });
		return out;
	}
	$: under = notePieces(preview?.footnote);
	$: names = new Map((draft?.gems ?? []).map((g: any) => [g.id, g]));

	const left = (s: number | null | undefined) => {
		if (s == null) return '';
		const m = Math.round(s / 60);
		const h = Math.floor(m / 60);
		return h ? `${h}h ${String(m % 60).padStart(2, '0')}m left` : `${m}m left`;
	};
	const stateWords = (w: any) => {
		if (!w) return '…';
		if (w.state === 'iced') return `iced by ${(w.replaced_by ?? []).map((id: string) => names.get(id)?.name ?? id).join(', ')}`;
		if (w.state === 'asleep' && w.absent?.length) return `asleep · ${w.absent.join(', ')} missing`;
		if (w.state === 'live' && !w.chars) return 'live · no words yet';
		if (w.state === 'waiting') return 'waiting for her key';
		if (w.state === 'set aside') return 'set aside · she leads';
		return w.state;
	};
	const whereWords = (g: any, w: any) =>
		g.key != null
			? `;${g.key} at the start of her message picks it · 🪶 under her message`
			: `when ${w?.words ?? (g.when ? '…' : 'always')} · ${slotOf(g) === FOOTNOTE ? '🪶 under her message' : tokenOf(slotOf(g))}`;
	const jewel = (state: string | undefined, retired: boolean) =>
		retired
			? 'border border-dashed border-gray-400 dark:border-gray-600'
			: state === 'live'
				? 'bg-linear-to-br from-pink-300 to-fuchsia-500 shadow-[0_0_6px_rgba(236,72,153,0.55)]'
				: state === 'iced' || state === 'set aside'
					? 'bg-linear-to-br from-violet-300 to-violet-600'
					: 'border border-gray-400 dark:border-gray-600';
	const when = (ts: number | null | undefined) => {
		if (!ts) return '';
		const d = new Date(ts * 1000);
		return `${['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'][d.getDay()]} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
	};
	const DESCRIPTION = 'petal-witch-forge decides which gems join this model’s system prompt, by live state. Here you can read what the model reads, rewrite a gem’s words, turn knobs, and keep a version.';
</script>

{#if admin}
	<section class="mt-3 px-1">
		<button
			type="button"
			class="flex w-full items-center justify-between gap-2 text-xs font-normal text-gray-600 dark:text-gray-400"
			aria-expanded={open}
			on:click={() => (open = !open)}
		>
			<ModelSettingsLabel label="🌙 States" description={DESCRIPTION} />
			<span class="truncate text-gray-400 dark:text-gray-600">
				{#if installed === null}…{:else if !installed}quiet{:else if empty}the forge is empty{:else}
					{liveHere} live of {here.length} here
					· {system.includes(STATES) ? `${STATES} placed` : `no ${STATES} · states go at the end`}{/if}
				{#if dirty}· <span class="text-pink-500 dark:text-pink-400">unkept edits</span>{/if}
				· {open ? '▾' : '▸'}
			</span>
		</button>

		{#if open}
			<div class="mt-2 min-w-0 space-y-3 text-xs">
				{#if installed === false}
					<p class="text-[0.6875rem] text-gray-500">the forge isn’t reachable from here · {why}</p>
				{:else if installed && empty}
					<p class="text-[0.6875rem] text-gray-500">no gems, knobs or readout lines yet · the forge on the rig shapes them</p>
				{:else if installed}
					<div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.6875rem] text-gray-500">
						<span>
							{#if versions[0]}kept {when(versions[0].at)}{versions[0].note ? ` · ${versions[0].note}` : ''}{:else}nothing kept yet{/if}
						</span>
						{#if preview?.note}<span>· {preview.note}</span>{/if}
						{#if !model}<span>· this card’s id is unknown here: gems worn by every Petal</span>{/if}
						<button type="button" class="ml-auto rounded-md px-2.5 py-1 text-sm hover:bg-gray-50 hover:text-gray-900 dark:hover:bg-gray-850 dark:hover:text-gray-100" on:click={refresh} title="read the forge and her senses again">↻</button>
					</div>
					{#if previewError}<p class="text-[0.6875rem] text-pink-600 dark:text-pink-400">{previewError}</p>{/if}

					<fieldset {disabled} class="min-w-0 space-y-3">
						{#each here as g (g.id)}
							{@const w = preview?.why?.[g.id]}
							<div class={g.retired ? 'opacity-60' : ''}>
								<div class="flex items-center gap-2">
									<span class="inline-block size-2.5 shrink-0 rounded-full {jewel(w?.state, !!g.retired)}" title={w?.state ?? ''}></span>
									<span class="font-medium text-gray-900 dark:text-gray-100">{g.emoji || '✧'} {g.name || g.id}</span>
									<span class="truncate text-[0.6875rem] text-gray-400 dark:text-gray-600">
										{g.retired ? 'retired · kept' : stateWords(w)}{w?.state === 'live' && w?.flip_in_s != null ? ` · ${left(w.flip_in_s)}` : ''}
									</span>
									<button
										type="button"
										class="ml-auto shrink-0 rounded-md px-2.5 py-1.5 text-[0.6875rem] text-gray-500 hover:bg-gray-50 hover:text-gray-900 dark:hover:bg-gray-850 dark:hover:text-gray-100"
										on:click={() => setGem(g.id, { retired: !g.retired })}>{g.retired ? 'restore' : 'retire'}</button
									>
								</div>
								<div class="mt-0.5 text-[0.6875rem] text-gray-400 dark:text-gray-600">
									{whereWords(g, w)}
								</div>
								<Textarea
									ariaLabel={`🌙 ${g.name || g.id}`}
									className="mt-1 min-h-10 w-full resize-none overflow-y-hidden rounded-md bg-gray-50 px-2 py-1 text-[0.8125rem] outline-hidden dark:bg-gray-850 text-gray-900 dark:text-gray-100"
									placeholder="empty: Petal reads nothing from it"
									rows={2}
									minSize={40}
									value={g.words ?? ''}
									disabled={disabled || !!g.retired}
									onInput={onWords(g.id)}
								/>
							</div>
						{/each}
						{#if retiredCount}
							<button type="button" class="text-[0.6875rem] text-gray-500 hover:text-gray-900 dark:hover:text-gray-100" on:click={() => (showRetired = !showRetired)}>
								{showRetired ? 'hide the retired' : `show the retired (${retiredCount})`}
							</button>
						{/if}

						{#if knobs.length}
							<div class="border-t border-gray-100/60 pt-2 dark:border-gray-850/60">
								<div class="mb-1 text-[0.6875rem] text-gray-600 dark:text-gray-400">knobs · the rules lean on them</div>
								{#each knobs as k (k.id)}
									<div class="flex items-center gap-2 py-0.5 {k.retired ? 'opacity-60' : ''}">
										<span class="font-mono text-gray-800 dark:text-gray-200">{k.id}</span>
										<span class="truncate text-[0.6875rem] text-gray-400 dark:text-gray-600">{k.about ?? ''}</span>
										<span class="ml-auto flex shrink-0 items-center gap-1">
											{#if k.type === 'number'}
												<button type="button" class="rounded-md bg-gray-50 px-2.5 py-1 dark:bg-gray-850" on:click={() => nudge(k, -1)} aria-label={`${k.id} down`}>−</button>
												<input
													type="number"
													step="any"
													class="w-16 rounded-md bg-gray-50 px-1.5 py-1 text-center outline-hidden dark:bg-gray-850"
													value={k.value}
													on:change={(e) => {
														const v = Number(e.currentTarget.value);
														if (Number.isFinite(v)) setKnob(k.id, v);
													}}
												/>
												<button type="button" class="rounded-md bg-gray-50 px-2.5 py-1 dark:bg-gray-850" on:click={() => nudge(k, 1)} aria-label={`${k.id} up`}>+</button>
											{:else if k.type === 'bool'}
												<button type="button" class="rounded-md bg-gray-50 px-2.5 py-1 dark:bg-gray-850" on:click={() => setKnob(k.id, !k.value)}>{k.value ? 'yes' : 'no'}</button>
											{:else if k.type === 'enum'}
												<select class="rounded-md bg-gray-50 px-1.5 py-1 outline-hidden dark:bg-gray-850" value={k.value} on:change={(e) => setKnob(k.id, e.currentTarget.value)}>
													{#each k.options ?? [] as o}<option value={o}>{o}</option>{/each}
												</select>
											{:else}
												<input class="w-32 rounded-md bg-gray-50 px-1.5 py-1 outline-hidden dark:bg-gray-850" value={k.value ?? ''} on:input={(e) => setKnob(k.id, e.currentTarget.value)} />
											{/if}
										</span>
									</div>
								{/each}
							</div>
						{/if}

						{#if lines.length}
							<div class="space-y-1.5 border-t border-gray-100/60 pt-2 dark:border-gray-850/60">
								<div class="text-[0.6875rem] text-gray-600 dark:text-gray-400">readout · {READOUT} · the live state, laid open</div>
								<input
									class="w-full rounded-md bg-gray-50 px-2 py-1 font-mono text-[0.75rem] outline-hidden dark:bg-gray-850"
									placeholder="opens with… (shown only around a line that speaks)"
									value={draft.readout.head ?? ''}
									on:input={(e) => setWrap('head', e.currentTarget.value)}
								/>
								{#each lines as l (l.id)}
									{@const r = (preview?.readout ?? []).find((x) => x.id === l.id)}
									<div class={l.retired ? 'opacity-60' : ''}>
										<div class="flex items-center gap-2 text-[0.75rem]">
											<span class="truncate {r?.shown ? 'text-gray-900 dark:text-gray-100' : 'text-gray-400 dark:text-gray-600'}">{r?.shown ? r.text : `resting · ${r?.why ?? '…'}`}</span>
											<button
												type="button"
												class="ml-auto shrink-0 rounded-md px-2.5 py-1.5 text-[0.6875rem] text-gray-500 hover:bg-gray-50 hover:text-gray-900 dark:hover:bg-gray-850 dark:hover:text-gray-100"
												on:click={() => setLine(l.id, { retired: !l.retired })}>{l.retired ? 'restore' : 'retire'}</button
											>
										</div>
										<Textarea
											ariaLabel={`readout · ${l.id}`}
											className="mt-0.5 w-full resize-none overflow-y-hidden rounded-md bg-gray-50 px-2 py-1 font-mono text-[0.75rem] outline-hidden dark:bg-gray-850"
											rows={1}
											value={l.words ?? ''}
											disabled={disabled || !!l.retired}
											onKeydown={oneLine}
											onInput={onLineWords(l.id)}
										/>
										{#if l.when}<div class="text-[0.6875rem] text-gray-400 dark:text-gray-600">speaks only while {r?.words ?? '…'}</div>{/if}
									</div>
								{/each}
								<input
									class="w-full rounded-md bg-gray-50 px-2 py-1 font-mono text-[0.75rem] outline-hidden dark:bg-gray-850"
									placeholder="closes with…"
									value={draft.readout.foot ?? ''}
									on:input={(e) => setWrap('foot', e.currentTarget.value)}
								/>
							</div>
						{/if}

							{#if noteLines.length}
								<div class="space-y-1.5 border-t border-gray-100/60 pt-2 dark:border-gray-850/60">
									<div class="text-[0.6875rem] text-gray-600 dark:text-gray-400">🪶 under her latest message · lines of the footnote</div>
									{#each noteLines as l (l.id)}
										{@const r = (preview?.readout ?? []).find((x) => x.id === l.id)}
										<div class={l.retired ? 'opacity-60' : ''}>
											<div class="flex items-center gap-2 text-[0.75rem]">
												<span class="truncate {r?.shown ? 'text-gray-900 dark:text-gray-100' : 'text-gray-400 dark:text-gray-600'}">{r?.shown ? r.text : `resting · ${r?.why ?? '…'}`}</span>
												<button
													type="button"
													class="ml-auto shrink-0 rounded-md px-2.5 py-1.5 text-[0.6875rem] text-gray-500 hover:bg-gray-50 hover:text-gray-900 dark:hover:bg-gray-850 dark:hover:text-gray-100"
													on:click={() => setLine(l.id, { retired: !l.retired })}>{l.retired ? 'restore' : 'retire'}</button
												>
											</div>
											<Textarea
												ariaLabel={`footnote · ${l.id}`}
												className="mt-0.5 w-full resize-none overflow-y-hidden rounded-md bg-gray-50 px-2 py-1 font-mono text-[0.75rem] outline-hidden dark:bg-gray-850"
												rows={1}
												value={l.words ?? ''}
												disabled={disabled || !!l.retired}
												onKeydown={oneLine}
												onInput={onLineWords(l.id)}
											/>
										</div>
									{/each}
								</div>
							{/if}
					</fieldset>

					<div class="border-t border-gray-100/60 pt-2 dark:border-gray-850/60">
						<div class="mb-1 flex flex-wrap items-center gap-x-2 text-[0.6875rem] text-gray-600 dark:text-gray-400">
							what the model reads ·
							{#each tokens as t}
								<button type="button" class="font-mono text-pink-500 hover:underline dark:text-pink-400" title="put it at the cursor in the System Prompt" on:click={() => insert(tokenOf(t))}>{tokenOf(t)}</button>
								<span class="text-gray-400 dark:text-gray-600">{preview?.placed?.[t] === 'token' ? 'placed' : preview?.placed?.[t] === 'appended' ? 'at the end' : preview?.placed?.[t] === 'unplaced' ? 'not placed' : 'quiet now'}</span>
							{/each}
						</div>
						<pre class="max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-gray-50 p-2 text-[0.75rem] text-gray-700 dark:bg-gray-850 dark:text-gray-300">{#each segs as s}{#if s.kind === 'gem'}<mark class="rounded-sm bg-pink-500/10 text-gray-900 shadow-[inset_2px_0_0_rgba(236,72,153,0.7)] dark:text-gray-100" title={names.get(s.gem)?.name ?? s.gem}>{s.text}</mark>{:else if s.kind === 'readout'}<mark class="rounded-sm bg-violet-500/10 text-gray-900 shadow-[inset_2px_0_0_rgba(139,92,246,0.7)] dark:text-gray-100">{s.text}</mark>{:else if s.kind === 'label'}<span class="text-pink-500 dark:text-pink-400">{s.text}</span>{:else if s.kind === 'slot'}<mark class="rounded-sm bg-pink-500/10 text-gray-900 dark:text-gray-100">{s.text}</mark>{:else}{s.text}{/if}{:else}{preview ? 'nothing from the forge right now' : '…'}{/each}</pre>
						{#if under.length}
							<div class="mt-2 mb-1 text-[0.6875rem] text-gray-600 dark:text-gray-400">🪶 under her latest message · never in the prompt</div>
							<pre class="max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-gray-50 p-2 text-[0.75rem] text-gray-700 dark:bg-gray-850 dark:text-gray-300"><span class="italic text-gray-400 dark:text-gray-500">⟨her latest message⟩</span>{'\n\n'}{#each under as s}{#if s.kind === 'gem'}<mark class="rounded-sm bg-pink-500/10 text-gray-900 shadow-[inset_2px_0_0_rgba(236,72,153,0.7)] dark:text-gray-100" title={names.get(s.gem)?.name ?? s.gem}>{s.text}</mark>{:else if s.kind === 'note'}<mark class="rounded-sm bg-violet-500/10 text-gray-900 shadow-[inset_2px_0_0_rgba(196,181,253,0.8)] dark:text-gray-100">{s.text}</mark>{:else}<span class="text-gray-400 dark:text-gray-500">{s.text}</span>{/if}{/each}</pre>
						{/if}
					</div>

					{#if meta?.petal_states}
						<p class="text-[0.6875rem] text-gray-400 dark:text-gray-600">this card still holds its old 🌙 blocks · kept as they were, no longer read (the forge carries them now)</p>
					{/if}

					{#if dirty || clash || message}
						<div class="space-y-1.5 border-t border-gray-100/60 pt-2 dark:border-gray-850/60">
							{#if message}<p class="text-[0.6875rem] {clash ? 'text-pink-600 dark:text-pink-400' : 'text-gray-500'}">{message}</p>{/if}
							{#if clash}
								<div class="flex flex-wrap gap-1.5">
									<button type="button" class="rounded-lg bg-gray-100 px-3 py-1.5 text-gray-900 dark:bg-gray-800 dark:text-gray-100" disabled={keeping} on:click={() => keep('mine')}>keep mine for these</button>
									<button type="button" class="rounded-lg px-3 py-1.5 text-gray-600 dark:text-gray-400" disabled={keeping} on:click={() => keep('theirs')}>take the rig’s for these</button>
								</div>
							{:else if dirty}
								<input
									class="w-full rounded-md bg-gray-50 px-2 py-1 outline-hidden dark:bg-gray-850"
									placeholder={`📱 ${changes(saved, draft).join(', ')}`}
									bind:value={note}
								/>
								<div class="flex flex-wrap gap-1.5">
									<button type="button" class="rounded-lg bg-gray-100 px-3 py-1.5 font-medium text-gray-900 dark:bg-gray-800 dark:text-gray-100" disabled={keeping || disabled} on:click={() => keep()}>{keeping ? 'keeping…' : 'keep this version'}</button>
									<button type="button" class="rounded-lg px-3 py-1.5 text-gray-600 dark:text-gray-400" disabled={keeping} on:click={letDraftGo}>let these edits go</button>
								</div>
							{/if}
							{#if letGo.length}
								<details class="text-[0.6875rem] text-gray-500">
									<summary>what this device held there (not kept)</summary>
									{#each letGo as x}<div class="mt-1"><span class="text-gray-400">{x.name}</span><pre class="whitespace-pre-wrap break-words">{x.text}</pre></div>{/each}
								</details>
							{/if}
						</div>
					{/if}
				{:else}
					<p class="text-[0.6875rem] text-gray-500">…</p>
				{/if}
			</div>
		{/if}
	</section>
{/if}
