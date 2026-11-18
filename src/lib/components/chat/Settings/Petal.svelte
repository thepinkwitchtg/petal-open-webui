<script lang="ts">
	// 🌸 Petal (slice A29) · her rhythm for picks: some turns ask her to pick between two replies, so Petal
	// grows from real use. off by default; saved in her settings (synced with every device she signs in on).
	// A30 · arms: 1 in her N picks differ only in pull. the pull is chosen from her shelf, read at runtime (the
	// fork names no blend and no string); the server draws the side and the strength from her set
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';

	import { getPulls, type ShelfPulls } from '$lib/apis/petal-shelf';
	import { settings, user } from '$lib/stores';
	import { formatChord, keybindings, Shortcut } from '$lib/shortcuts';
	import { loadModes, modes } from '$lib/utils/petal-mode';
	import { PICK_DEFAULTS, rulesOf, strengthsOf, type PickRules } from '$lib/utils/petal-pick';
	import Switch from '$lib/components/common/Switch.svelte';
	import SettingsSelect from '$lib/components/common/SettingsSelect.svelte';

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
	// 🍒 A30 · arms: her shelf's pulls (names from the shelf, at runtime), her strengths as she writes them
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
	const shown = (xs: number[]) => xs.map((x) => x.toFixed(2)).join(' · ');
	let strengthsText = shown(rules.arms.strengths);
	const setStrengths = () => {
		rules.arms = { ...rules.arms, strengths: strengthsOf(strengthsText) };
		strengthsText = shown(rules.arms.strengths);
		save();
	};
	$: loud = rules.arms.strengths.some((x) => x > 0.5);
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
	});

	const field =
		'h-7 w-16 rounded-lg border border-gray-100/50 bg-gray-50/40 px-2 text-right text-xs text-gray-700 outline-hidden transition-colors focus:border-blue-400 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:focus:border-blue-500';
</script>

<div class="flex h-full flex-col overflow-y-auto text-sm" id="tab-petal">
	<UserSettingSection title={$i18n.t('🍒 Picks · two replies, one moment')} first>
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
				<SettingsSelect
					id={`${labelId}-control`}
					aria-labelledby={labelId}
					bind:value={rules.rhythm}
					disabled={!rules.on}
					on:change={save}
				>
					<option value="every">{$i18n.t('every Nth turn')}</option>
					<option value="share">{$i18n.t('a share of turns')}</option>
				</SettingsSelect>
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
			{$i18n.t('Ask for a pick on your next send')}:
			{chord || $i18n.t('Settings → Shortcuts')}{$i18n.t(', or a long press on the mode chip on your phone.')}
			{$i18n.t(
				'Never in temporary chats, internal or subagent turns, tests, while her voice speaks, or twice in a row unless you ask.'
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
				<SettingsSelect
					id={`${labelId}-control`}
					aria-labelledby={labelId}
					bind:value={rules.arms.pull}
					on:change={save}
				>
					<option value="">{$i18n.t('none · no arms')}</option>
					{#if rules.arms.pull && !offered}
						<option value={rules.arms.pull}>{rules.arms.pull} · {$i18n.t('not on the shelf now')}</option>
					{/if}
					{#if ready.some((p) => p.kind === 'blend')}
						<optgroup label={$i18n.t('blends')}>
							{#each ready.filter((p) => p.kind === 'blend') as p (p.kind + p.id)}
								<option value={p.id}>{p.name}</option>
							{/each}
						</optgroup>
					{/if}
					{#if ready.some((p) => p.kind === 'string')}
						<optgroup label={$i18n.t('♡ strings')}>
							{#each ready.filter((p) => p.kind === 'string') as p (p.kind + p.id)}
								<option value={p.id}>{p.name}</option>
							{/each}
						</optgroup>
					{/if}
					{#if waiting.length}
						<optgroup label={$i18n.t('still waiting')}>
							{#each waiting as p (p.kind + p.id)}
								<option value={p.id} disabled>{p.name}</option>
							{/each}
						</optgroup>
					{/if}
				</SettingsSelect>
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

			<UserSettingRow
				description={loud ? $i18n.t('Heartstrings warns above 0.50.') : ''}
				let:labelId
			>
				<span slot="label">{$i18n.t('Strengths, one drawn per arm')}</span>
				<input
					id={`${labelId}-control`}
					type="text"
					class="h-7 w-40 rounded-lg border border-gray-100/50 bg-gray-50/40 px-2 text-right text-xs text-gray-700 outline-hidden transition-colors focus:border-blue-400 disabled:opacity-50 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:focus:border-blue-500"
					bind:value={strengthsText}
					disabled={!rules.arms.pull}
					aria-label={$i18n.t('Strengths, one drawn per arm')}
					on:change={setStrengths}
				/>
			</UserSettingRow>

			<UserSettingRow
				description={$i18n.t(
					'A pulled reply can start a few seconds after its sibling (vLLM can’t reuse its cache for it), which would tell them apart.'
				)}
				let:labelId
			>
				<span slot="label">{$i18n.t('Show both together, once both are written')}</span>
				<Switch
					ariaLabelledbyId={labelId}
					ariaLabel={$i18n.t('Show both together, once both are written')}
					bind:state={rules.arms.hold}
					disabled={!rules.arms.pull}
					on:change={save}
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
