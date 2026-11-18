<script lang="ts">
	// 🌸 Petal (slice A29) · her rhythm for picks: some turns ask her to pick between two replies, so Petal
	// grows from real use. off by default; saved in her settings (synced with every device she signs in on)
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';

	import { settings } from '$lib/stores';
	import { formatChord, keybindings, Shortcut } from '$lib/shortcuts';
	import { loadModes, modes } from '$lib/utils/petal-mode';
	import { PICK_DEFAULTS, rulesOf, type PickRules } from '$lib/utils/petal-pick';
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
	const modeOn = (key: string) => rules.modes[key] !== false;
	const setMode = (key: string, on: boolean) => {
		rules.modes = { ...rules.modes, [key]: on };
		save();
	};

	onMount(() => loadModes());

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
</div>
