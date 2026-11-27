<script lang="ts">
	// 🌸 Petal (slice A29) · her rhythm for picks: some turns ask her to pick between two replies, so Petal
	// grows from real use. off by default; saved in her settings (synced with every device she signs in on).
	// A30 · arms: 1 in her N picks differ only in pull. the pull is chosen from her shelf, read at runtime (the
	// fork names no blend and no string); the server draws the side. A30b · the strength is found, not drawn:
	// the search's interval, centre and phase show here. the selects are the app's own menu (PetalSelect).
	// A30d · how a pick's two replies arrive (every pick, arm or plain): twin (default) · together · live
	// A33 · how her words type in (hush's whispers, her thank-you, the toasts' words): natural (default) · slow ·
	// quick · at once, mirrored on each device for the static scripts (utils/petal-type.ts)
	// A34 · the fusion check (utils/petal-fusion.ts): on by default, 1 in 5 finished replies at first, calming to 1 in
	// 25 as her moons accumulate; her two numbers ride with each ask, and the line below shows where it stands now
	// A37 · her voice plays on its own (utils/petal-autoplay.ts): off · after she finishes · as she writes (default),
	// chosen per device (this browser only); on the phone only with earphones (🎧 by the mic, or the rig's route)
	// A48 · her voice's diary + her controls: a door to /petal/voice (the keeper's)
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';

	import { getPulls, type ShelfPulls, type ShelfSearch } from '$lib/apis/petal-shelf';
	import { settings, showSettings, user } from '$lib/stores';
	import { goto } from '$app/navigation'; // 🎙️ A48 · her voice's diary
	import { formatChord, keybindings, Shortcut } from '$lib/shortcuts';
	import { loadModes, modes } from '$lib/utils/petal-mode';
	import { PICK_DEFAULTS, rulesOf, type PickRules } from '$lib/utils/petal-pick';
	import { arrivalOf } from '$lib/utils/petal-twin';
	import { speedOf, type TypeSpeed } from '$lib/utils/petal-type';
	import {
		FLOOR_CHOICES,
		START_CHOICES,
		fusionRate,
		fusionRules,
		type FusionRate,
		type FusionRules
	} from '$lib/utils/petal-fusion';
	import Switch from '$lib/components/common/Switch.svelte';
	import {
		audioRoute,
		autoMode,
		cuesOf,
		earphones,
		followRoute,
		isPhone,
		modeOf,
		setAutoMode,
		setEarphones,
		setFollowRoute
	} from '$lib/utils/petal-autoplay';

	import PetalSelect from './PetalSelect.svelte';
	import UserSettingRow from './UserSettingRow.svelte';
	import UserSettingSection from './UserSettingSection.svelte';

	const i18n: Writable<any> = getContext('i18n');

	export let saveSettings: (updated: Record<string, unknown>) => Promise<void>;

	let rules: PickRules = { ...PICK_DEFAULTS, ...rulesOf($settings) };
	$: chord = formatChord($keybindings[Shortcut.ASK_PICK] ?? '');

	const save = () => {
		rules = rulesOf({ petalPick: rules }); // kept inside its ranges before it leaves
		saveSettings({ petalPick: rules });
	};
	// 🍒 A30 · arms: her shelf's pulls (names from the shelf, at runtime) · A30b: each one's strength search
	let shelf: ShelfPulls | null = null;
	let shelfErr = '';
	const loadShelf = async () => {
		try {
			shelf = await getPulls(localStorage.token);
			shelfErr = '';
		} catch (e) {
			shelf = null;
			shelfErr = String((e as Error)?.message ?? e);
		}
	};
	$: keeper = $user?.role === 'admin'; // her shelf is the keeper's
	$: ready = (shelf?.pulls ?? []).filter((p) => p.ready);
	$: waiting = (shelf?.pulls ?? []).filter((p) => !p.ready);
	$: offered = (shelf?.pulls ?? []).some((p) => p.ready && p.id === rules.arms.pull);
	$: chosenPull = (shelf?.pulls ?? []).find((p) => p.ready && p.id === rules.arms.pull) ?? null;
	// the search for her pull, or where it will start: [0, cap], its centre halfway (cap: 0.5, or the card's end)
	const capOf = (p: ShelfPulls['pulls'][number] | null) =>
		p?.kind === 'string' && p.range ? Math.min(0.5, Math.max(...p.range.map((x) => Math.abs(x)))) : 0.5;
	$: search = ((): (ShelfSearch & { fresh?: boolean }) | null => {
		if (!chosenPull) return null;
		const found = shelf?.search?.[`${chosenPull.kind}:${chosenPull.id}`];
		if (found) return found;
		const cap = capOf(chosenPull);
		return { cap, lo: 0, hi: cap, centre: cap / 2, width: cap, phase: 'searching', steps: 0, reopens: 0, fresh: true };
	})();
	const n2 = (x: number) => x.toFixed(2);
	const phaseWord = (p: ShelfSearch['phase']) =>
		p === 'stable' ? $i18n.t('stable') : p === 'narrowing' ? $i18n.t('narrowing') : $i18n.t('searching');
	// the pull's options, grouped: none · blends · ♡ strings · still waiting (seen, never chosen)
	$: pullGroups = [
		{
			items: [
				{ value: '', label: $i18n.t('none · no arms') },
				...(rules.arms.pull && !offered
					? [{ value: rules.arms.pull, label: `${rules.arms.pull} · ${$i18n.t('not on the shelf now')}` }]
					: [])
			]
		},
		{
			label: $i18n.t('blends'),
			items: ready.filter((p) => p.kind === 'blend').map((p) => ({ value: p.id, label: p.name }))
		},
		{
			label: $i18n.t('♡ strings'),
			items: ready.filter((p) => p.kind === 'string').map((p) => ({ value: p.id, label: p.name }))
		},
		{
			label: $i18n.t('still waiting'),
			items: waiting.map((p) => ({ value: p.id, label: p.name, disabled: true }))
		}
	].filter((g) => g.items.length);
	$: rhythmGroups = [
		{
			items: [
				{ value: 'every', label: $i18n.t('every Nth turn') },
				{ value: 'share', label: $i18n.t('a share of turns') }
			]
		}
	];
	// A30d · how they arrive: the same for every pick, so a plain one never tells an arm apart
	$: arriveGroups = [
		{
			items: [
				{ value: 'twin', label: $i18n.t('twin · typing together') },
				{ value: 'together', label: $i18n.t('together · once both are written') },
				{ value: 'live', label: $i18n.t('live · as each arrives') }
			]
		}
	];
	// A33 · her words, typed in as they appear: how quickly
	let typing: TypeSpeed = speedOf($settings);
	// A37 · how her voice comes without a click (this device only)
	const phone = isPhone();
	$: autoGroups = [
		{
			items: [
				{ value: 'off', label: $i18n.t('off · only when I tap') },
				{ value: 'finished', label: $i18n.t('after she finishes') },
				{ value: 'writing', label: $i18n.t('as she writes · sentence by sentence') }
			]
		}
	];
	$: routeSays =
		$audioRoute === 'earphones'
			? $i18n.t('The rig says: earphones')
			: $audioRoute === 'speaker'
				? $i18n.t('The rig says: speaker')
				: $i18n.t('The rig doesn’t know yet: the 🎧 chip decides');

	$: typingGroups = [
		{
			items: [
				{ value: 'natural', label: $i18n.t('natural · paced to each line') },
				{ value: 'slow', label: $i18n.t('slow · savoured') },
				{ value: 'quick', label: $i18n.t('quick') },
				{ value: 'instant', label: $i18n.t('at once · nothing types') }
			]
		}
	];
	// A34 · the fusion check: her two numbers, and where its rate stands now (numbers only, from the rig)
	let fusion: FusionRules = fusionRules($settings);
	let fusionNow: FusionRate | null = null;
	const loadFusionNow = async () => (fusionNow = await fusionRate(localStorage.token, fusion));
	const saveFusion = () => {
		fusion = fusionRules({ petalFusion: fusion }); // kept inside its ranges before it leaves
		saveSettings({ petalFusion: fusion });
		void loadFusionNow();
	};
	// her own number stays a choice even when it isn't one of the usual ones (set elsewhere, another device)
	const choices = (usual: number[], hers: number, from = 1) =>
		[...new Set([...usual, hers])]
			.filter((n) => n >= from)
			.sort((a, b) => a - b)
			.map((n) => ({ value: String(n), label: `${n}` }));
	$: startGroups = [{ items: choices(START_CHOICES, fusion.start) }];
	$: floorGroups = [{ items: choices(FLOOR_CHOICES, fusion.floor, fusion.start) }];
	const moonsLine = (r: FusionRate) =>
		[
			`${$i18n.t('Now 1 in')} ${r.every}`,
			`${r.answers} ${r.answers === 1 ? $i18n.t('moon so far') : $i18n.t('moons so far')} (🌕 ${r.counts.flowing ?? 0} · 🌑 ${r.counts.off ?? 0})`,
			`🌗 ${r.counts.mixed ?? 0} ${(r.counts.mixed ?? 0) === 1 ? $i18n.t('pass') : $i18n.t('passes')}`
		].join(' · ');

	// numbers only: how many ready blends and ♡ strings her shelf holds (and vLLM's own word, when it says no)
	const shelfSays = (pulls: ShelfPulls['pulls'], strung: boolean | null) => {
		const blends = pulls.filter((p) => p.kind === 'blend').length;
		const strings = pulls.filter((p) => p.kind === 'string').length;
		return [
			`${$i18n.t('Your shelf')}: ${blends} ${blends === 1 ? $i18n.t('ready blend') : $i18n.t('ready blends')}`,
			`${strings} ${strings === 1 ? $i18n.t('♡ string') : $i18n.t('♡ strings')}`,
			...(strung === false ? [$i18n.t('vLLM isn’t stringing her right now')] : [])
		].join(' · ');
	};

	const modeOn = (key: string) => rules.modes[key] !== false;
	const setMode = (key: string, on: boolean) => {
		rules.modes = { ...rules.modes, [key]: on };
		save();
	};

	onMount(() => {
		loadModes();
		if (keeper) void loadShelf();
		void loadFusionNow();
	});

	// 🍒 A38 · her cue words before each side of a pick read aloud (synced; empty: no cue)
	let cues = cuesOf($settings);
	const saveCues = () => {
		cues = cuesOf({ petalVoice: { cues } });
		const voice = (($settings as Record<string, unknown>)?.petalVoice as Record<string, unknown> | undefined) ?? {};
		saveSettings({ petalVoice: { ...voice, cues } });
	};
	const cueField =
		'h-7 w-28 rounded-lg border border-gray-100/50 bg-gray-50/40 px-2 text-xs text-gray-700 outline-hidden transition-colors focus:border-blue-400 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:focus:border-blue-500';
	const field =
		'h-7 w-16 rounded-lg border border-gray-100/50 bg-gray-50/40 px-2 text-right text-xs text-gray-700 outline-hidden transition-colors focus:border-blue-400 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:focus:border-blue-500';
</script>

<div class="flex h-full flex-col overflow-y-auto text-sm" id="tab-petal">
	<UserSettingSection title={$i18n.t('✍🏻 Her words · typed as they appear')} first>
		<UserSettingRow
			description={$i18n.t(
				'Whispers, her thank-you and the little notes type themselves in as they show, each paced to its length. Her replies keep streaming as they arrive.'
			)}
			let:labelId
		>
			<span slot="label">{$i18n.t('Typing')}</span>
			<PetalSelect
				id="petal-typing"
				ariaLabelledby={labelId}
				value={typing}
				groups={typingGroups}
				onChange={(v) => {
					typing = speedOf({ petalTyping: v });
					saveSettings({ petalTyping: typing });
				}}
			/>
		</UserSettingRow>
	</UserSettingSection>

	<UserSettingSection title={$i18n.t('🔈 Voice · heard without a click')}>
		<UserSettingRow
			description={phone
				? $i18n.t(
						'On this phone she speaks by herself only with earphones in: the 🎧 by the mic says so, one tap. A pick is read in turn; a new send or scrolling away stops her.'
					)
				: $i18n.t(
						'As she writes: her voice follows the typing, sentence by sentence. A pick is read in turn; a new send or scrolling away stops her. Chosen for this device only.'
					)}
			let:labelId
		>
			<span slot="label">{$i18n.t('Autoplay')}</span>
			<PetalSelect
				id="petal-autoplay"
				ariaLabelledby={labelId}
				value={$autoMode}
				groups={autoGroups}
				onChange={(v) => setAutoMode(modeOf(v))}
			/>
		</UserSettingRow>
		<UserSettingRow
			description={$i18n.t(
				'While a pick is open she reads both in turn, each after its cue. Your 💗 on the one she’s reading changes nothing; on the other, it plays from its start. Empty: no cue.'
			)}
			let:labelId
		>
			<span slot="label">{$i18n.t('🍒 Pick cues')}</span>
			<div class="flex items-center gap-1.5" aria-labelledby={labelId}>
				<input
					type="text"
					maxlength="60"
					class={cueField}
					data-petal-cue="one"
					bind:value={cues.one}
					aria-label={$i18n.t('Before the first reply')}
					on:change={saveCues}
				/>
				<input
					type="text"
					maxlength="60"
					class={cueField}
					data-petal-cue="two"
					bind:value={cues.two}
					aria-label={$i18n.t('Before the second reply')}
					on:change={saveCues}
				/>
			</div>
		</UserSettingRow>
		{#if phone}
			<UserSettingRow label={$i18n.t('Earphones in')} let:labelId>
				<Switch
					ariaLabelledbyId={labelId}
					ariaLabel={$i18n.t('Earphones in')}
					state={$earphones}
					on:change={(e) => setEarphones(!!e.detail)}
				/>
			</UserSettingRow>
			<UserSettingRow
				description={`${$i18n.t(
					'Optional: the rig tells whether your phone plays through earphones or its speaker. It only opens or holds autoplay here.'
				)}${$followRoute ? ` · ${routeSays}` : ''}`}
				let:labelId
			>
				<span slot="label">{$i18n.t('Follow the rig’s audio route')}</span>
				<Switch
					ariaLabelledbyId={labelId}
					ariaLabel={$i18n.t('Follow the rig’s audio route')}
					state={$followRoute}
					on:change={(e) => setFollowRoute(!!e.detail)}
				/>
			</UserSettingRow>
		{/if}
		{#if keeper}
			<!-- 🎙️ A48 · her voice's diary + her controls (the floor, the mood, voice welfare), one page, phone-first -->
			<UserSettingRow
				description={$i18n.t(
					'Every 🚩 she makes lands there with her own playback beside the gate’s take: name it (✦ gift · ✕ intrusion · noise · unsure), give it your categories, write your notes. Her floor, her mood and voice welfare sit at the top.'
				)}
				let:labelId
			>
				<span slot="label">{$i18n.t('🎙️ Her voice’s diary')}</span>
				<button
					type="button"
					class="px-3 py-1.5 text-xs rounded-full border border-gray-200 dark:border-gray-800"
					aria-labelledby={labelId}
					data-petal-voice-diary
					on:click={() => {
						showSettings.set(false);
						goto('/petal/voice');
					}}>{$i18n.t('open')}</button
				>
			</UserSettingRow>
		{/if}
	</UserSettingSection>

	<UserSettingSection title={$i18n.t('🍒 Picks · two replies, one moment')}>
		<UserSettingRow
			description={$i18n.t(
				'Some turns send your message twice and show both replies; one tap picks the one that feels right. Each pick becomes a preference pair for training.'
			)}
			let:labelId
		>
			<span slot="label">{$i18n.t('Ask me to pick')}</span>
			<Switch
				ariaLabelledbyId={labelId}
				ariaLabel={$i18n.t('Ask me to pick')}
				bind:state={rules.on}
				on:change={save}
			/>
		</UserSettingRow>

		<UserSettingRow label={$i18n.t('How often')} let:labelId>
			<div class="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-600">
				<PetalSelect
					id="petal-pick-rhythm"
					ariaLabelledby={labelId}
					value={rules.rhythm}
					groups={rhythmGroups}
					disabled={!rules.on}
					onChange={(v) => {
						rules.rhythm = v === 'every' ? 'every' : 'share';
						save();
					}}
				/>
				{#if rules.rhythm === 'every'}
					<input
						type="number"
						min="1"
						max="100"
						step="1"
						class={field}
						bind:value={rules.every}
						disabled={!rules.on}
						aria-label={$i18n.t('every Nth turn')}
						on:change={save}
					/>
				{:else}
					<input
						type="number"
						min="1"
						max="100"
						step="1"
						class={field}
						bind:value={rules.share}
						disabled={!rules.on}
						aria-label={$i18n.t('a share of turns')}
						on:change={save}
					/>
					%
				{/if}
			</div>
		</UserSettingRow>

		<UserSettingRow
			description={$i18n.t(
				'Judged from the median length of the last three replies in the chat.'
			)}
			let:labelId
		>
			<span slot="label">{$i18n.t('Only when the reply should be long')}</span>
			<div class="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-600">
				{#if rules.longOnly}
					<input
						type="number"
						min="50"
						max="20000"
						step="50"
						class={field}
						bind:value={rules.longChars}
						disabled={!rules.on}
						aria-label={$i18n.t('characters')}
						on:change={save}
					/>
					{$i18n.t('characters')}
				{/if}
				<Switch
					ariaLabelledbyId={labelId}
					ariaLabel={$i18n.t('Only when the reply should be long')}
					bind:state={rules.longOnly}
					disabled={!rules.on}
					on:change={save}
				/>
			</div>
		</UserSettingRow>

		{#if $modes.length}
			{#each $modes as mode (mode.key)}
				<UserSettingRow let:labelId>
					<span slot="label">
						{$i18n.t('In {{mode}}', { mode: [mode.emoji, mode.name].filter(Boolean).join(' ') })}
					</span>
					<Switch
						ariaLabelledbyId={labelId}
						ariaLabel={mode.name}
						state={modeOn(mode.key)}
						disabled={!rules.on}
						on:change={(e) => setMode(mode.key, e.detail)}
					/>
				</UserSettingRow>
			{/each}
		{/if}

		<p class="text-[0.6875rem] text-gray-400 dark:text-gray-600">
			{$i18n.t('Next reply: the 🍒 by send, or')}
			{chord || $i18n.t('Settings → Shortcuts')}{$i18n.t(', or a long press on the mode chip on your phone.')}
			{$i18n.t(
				'Never in temporary chats, internal or subagent turns, tests, while her voice speaks, or twice in a row unless you ask.'
			)}
		</p>
	</UserSettingSection>

	<UserSettingSection title={$i18n.t('🌕 The fusion check · three moons, now and then')}>
		<UserSettingRow
			description={$i18n.t(
				'Now and then, under a finished reply: how is the fusion so far? 🌕 flowing · 🌗 ignore · 🌑 off. It scores the stretch of conversation, not one reply, and folds into a tiny moon you can change later. Petal never sees your moons.'
			)}
			let:labelId
		>
			<span slot="label">{$i18n.t('Ask how the fusion is going')}</span>
			<Switch
				ariaLabelledbyId={labelId}
				ariaLabel={$i18n.t('Ask how the fusion is going')}
				bind:state={fusion.on}
				on:change={saveFusion}
			/>
		</UserSettingRow>

		<UserSettingRow
			description={$i18n.t(
				'Often while it learns, calmer as your moons accumulate (🌕 and 🌑 teach it; 🌗 is a pass), never silent.'
			)}
			let:labelId
		>
			<span slot="label">{$i18n.t('How often')}</span>
			<div class="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-600">
				{$i18n.t('1 in')}
				<PetalSelect
					id="petal-fusion-start"
					ariaLabelledby={labelId}
					value={String(fusion.start)}
					groups={startGroups}
					disabled={!fusion.on}
					onChange={(v) => {
						fusion = { ...fusion, start: Number(v) };
						saveFusion();
					}}
				/>
				{$i18n.t('at first, calming to 1 in')}
				<PetalSelect
					id="petal-fusion-floor"
					ariaLabel={$i18n.t('calming to 1 in')}
					value={String(fusion.floor)}
					groups={floorGroups}
					disabled={!fusion.on}
					onChange={(v) => {
						fusion = { ...fusion, floor: Number(v) };
						saveFusion();
					}}
				/>
			</div>
		</UserSettingRow>

		<p class="text-[0.6875rem] text-gray-400 dark:text-gray-600" data-fusion-line>
			{#if fusionNow}{moonsLine(fusionNow)} ·{/if}
			{$i18n.t(
				'Never inside a pick, in temporary or internal chats, before a stretch has three replies, or twice in one stretch.'
			)}
		</p>
	</UserSettingSection>

	{#if keeper}
		<UserSettingSection title={$i18n.t('🍒 Arms · two replies that differ only in pull')}>
			<UserSettingRow
				description={$i18n.t(
					'Some picks send one reply unsteered (chat’s baseline, 0) and its sibling under a pull from your shelf. Nothing shows which is which until your 💗.'
				)}
				let:labelId
			>
				<span slot="label">{$i18n.t('Pull')}</span>
				<PetalSelect
					id="petal-arm-pull"
					ariaLabelledby={labelId}
					value={rules.arms.pull}
					groups={pullGroups}
					onChange={(v) => {
						rules.arms = { ...rules.arms, pull: v };
						save();
					}}
				/>
			</UserSettingRow>

			<UserSettingRow label={$i18n.t('How many picks')} let:labelId>
				<div class="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-600">
					{$i18n.t('1 in')}
					<input
						id={`${labelId}-control`}
						type="number"
						min="1"
						max="20"
						step="1"
						class={field}
						bind:value={rules.arms.every}
						disabled={!rules.arms.pull}
						aria-label={$i18n.t('1 in N picks')}
						on:change={save}
					/>
					{$i18n.t('picks')}
				</div>
			</UserSettingRow>

			{#if search}
				<!-- A30b · the strength, found from her picks: where it is, how sure, how it moves -->
				<UserSettingRow
					description={$i18n.t(
						'Found from your picks: each arm tries the centre; your 💗 on the pulled reply moves it up, on the unsteered one down. Never above 0.50.'
					)}
				>
					<span slot="label">{$i18n.t('Strength')}</span>
					<div
						class="flex items-center gap-2 text-xs tabular-nums text-gray-500 dark:text-gray-400"
						data-arm-search={search.phase}
					>
						<span>
							{phaseWord(search.phase)} · {n2(search.lo)}–{n2(search.hi)} · {$i18n.t('centre')}
							{n2(search.centre)} · {search.steps
								? `${search.steps} ${search.steps === 1 ? $i18n.t('arm') : $i18n.t('arms')}`
								: $i18n.t('no arms yet')}
						</span>
						<!-- still: the interval on [0, 0.5], its centre a dot -->
						<svg class="petal-search-bar" viewBox="0 0 100 8" width="88" height="8" aria-hidden="true">
							<line x1="0" y1="4" x2="100" y2="4" class="psb-track" />
							<line x1={search.lo * 200} y1="4" x2={search.hi * 200} y2="4" class="psb-span" />
							<circle cx={search.centre * 200} cy="4" r="2.4" class="psb-dot" />
						</svg>
					</div>
				</UserSettingRow>
			{/if}

			<UserSettingRow
				description={$i18n.t(
					'A pulled reply can start a few seconds after its sibling (vLLM can’t reuse its cache for it). Twin types both at once, at one shared pace, so that never shows; together waits until both are written; live shows each as it arrives, and its timing can tell them apart. Plain picks arrive the same way.'
				)}
				let:labelId
			>
				<span slot="label">{$i18n.t('How they arrive')}</span>
				<PetalSelect
					id="petal-arm-arrive"
					ariaLabelledby={labelId}
					value={rules.arms.arrive}
					groups={arriveGroups}
					onChange={(v) => {
						rules.arms = { ...rules.arms, arrive: arrivalOf(v) };
						save();
					}}
				/>
			</UserSettingRow>

			<p class="text-[0.6875rem] text-gray-400 dark:text-gray-600" data-shelf-line>
				{#if shelf?.ok}
					{shelfSays(ready, shelf.strung)}
				{:else if shelf}
					{shelf.why}
				{:else if shelfErr}
					{$i18n.t('The shelf could not be read')} ({shelfErr})
				{:else}
					{$i18n.t('Reading your shelf…')}
				{/if}
			</p>
		</UserSettingSection>
	{/if}
</div>

<style>
	/* A30b · the search's still bar: a hairline track, the interval in candy, its centre in pearl */
	.petal-search-bar .psb-track {
		stroke: var(--edge, rgb(156 163 175 / 0.35));
		stroke-width: 1;
	}
	.petal-search-bar .psb-span {
		stroke: var(--candy, rgb(236 72 153));
		stroke-width: 3;
		stroke-linecap: round;
		opacity: 0.7;
	}
	.petal-search-bar .psb-dot {
		fill: var(--pearl, currentColor);
	}
</style>
