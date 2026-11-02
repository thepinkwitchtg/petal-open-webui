<script lang="ts">
	// 🌷 Garden harvest — store every chat from a precise time range (md + json).
	// One tap on a chip gathers + previews; one tap on an action stores it.
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import JSZip from 'jszip';
	import fileSaver from 'file-saver';

	import { user } from '$lib/stores';
	import { getAllChats } from '$lib/apis/chats';
	import { plantHarvest, getHarvestInfo } from '$lib/apis/petal-harvest';
	import { copyToClipboard } from '$lib/utils';
	import { harvest, type HarvestMode, type HarvestBundle } from '$lib/utils/petal-harvest';

	const { saveAs } = fileSaver;
	const i18n = getContext('i18n');

	const LAST_KEY = 'petal-harvest-last-end'; // only a timestamp, no chat data

	let chats: any[] | null = null;
	let gathering = false;
	let busy = false;

	let from = ''; // datetime-local strings
	let to = '';
	let mode: HarvestMode = 'alive';
	let trimToRange = false;

	let bundle: HarvestBundle | null = null;
	let lastPlanted = '';
	let gardenRoot = '';

	const pad = (n: number) => String(n).padStart(2, '0');
	const toLocalInput = (d: Date) =>
		`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
	const toSec = (v: string, endOfMinute = false) =>
		v ? Math.floor(new Date(v).getTime() / 1000) + (endOfMinute ? 59 : 0) : 0;

	const gather = async () => {
		if (chats || gathering) return;
		gathering = true;
		try {
			chats = (await getAllChats(localStorage.token)) as any[];
			getHarvestInfo(localStorage.token).then((i) => (gardenRoot = i?.root ?? ''));
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			gathering = false;
		}
	};

	const setRange = async (start: Date, end: Date) => {
		from = toLocalInput(start);
		to = toLocalInput(end);
		await gather();
	};

	const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

	const chips = [
		{ label: 'today', range: () => [startOfDay(new Date()), new Date()] },
		{
			label: 'yesterday',
			range: () => {
				const t = startOfDay(new Date());
				return [new Date(t.getTime() - 864e5), new Date(t.getTime() - 60e3)];
			}
		},
		{
			label: '7 days',
			range: () => [startOfDay(new Date(Date.now() - 6 * 864e5)), new Date()]
		},
		{
			label: '30 days',
			range: () => [startOfDay(new Date(Date.now() - 29 * 864e5)), new Date()]
		},
		{
			label: 'since last harvest',
			range: () => {
				const last = Number(localStorage.getItem(LAST_KEY) ?? 0);
				return [last ? new Date(last * 1000 + 1000) : startOfDay(new Date()), new Date()];
			}
		}
	];

	$: start = toSec(from);
	$: end = toSec(to, true);
	$: bundle =
		chats && start && end && end >= start
			? harvest(chats, {
					start,
					end,
					mode,
					trimToRange,
					userName: $user?.name ?? 'Lily'
				})
			: null;

	const remember = () => {
		if (end) localStorage.setItem(LAST_KEY, String(end));
	};

	const plant = async () => {
		if (!bundle?.chats) return;
		busy = true;
		try {
			const res = await plantHarvest(localStorage.token, bundle.folder, bundle.files);
			lastPlanted = res.path;
			remember();
			toast.success(`🌷 ${bundle.chats} chats planted`);
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			busy = false;
		}
	};

	const zip = async () => {
		if (!bundle?.chats) return;
		busy = true;
		try {
			const z = new JSZip();
			const dir = z.folder(bundle.folder)!;
			for (const f of bundle.files) dir.file(f.name, f.content);
			saveAs(await z.generateAsync({ type: 'blob' }), `${bundle.folder}.zip`);
			remember();
		} finally {
			busy = false;
		}
	};

	const copy = async () => {
		if (!bundle?.chats) return;
		const ok = await copyToClipboard(bundle.combined);
		ok !== false
			? toast.success(`${bundle.chats} chats copied`)
			: toast.error($i18n.t('Copy failed'));
	};

	const modes: { id: HarvestMode; label: string; hint: string }[] = [
		{ id: 'alive', label: 'alive', hint: 'any chat that lived inside the window' },
		{ id: 'born', label: 'born', hint: 'chats started inside the window' },
		{ id: 'touched', label: 'touched', hint: 'chats last updated inside the window' }
	];

	const chipClass =
		'px-2.5 py-1 rounded-full text-xs bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800 transition';
	const actionClass =
		'px-3 py-1.5 rounded-xl text-xs font-medium transition disabled:opacity-40 disabled:cursor-not-allowed';
</script>

<div class="flex flex-col gap-2 py-1.5">
	<div>
		<div class="text-sm font-medium">🌷 {$i18n.t('Garden harvest')}</div>
		<div class="text-xs text-gray-500">
			{$i18n.t('Store every chat from a time range as md + json, for daemon hygiene.')}
		</div>
	</div>

	<div class="flex flex-wrap gap-1.5">
		{#each chips as chip}
			<button
				type="button"
				class={chipClass}
				on:click={() => {
					const [a, b] = chip.range();
					setRange(a, b);
				}}>{chip.label}</button
			>
		{/each}
	</div>

	<div class="flex flex-wrap items-center gap-2 text-xs">
		<label class="flex items-center gap-1.5">
			<span class="text-gray-500">from</span>
			<input
				type="datetime-local"
				bind:value={from}
				on:change={gather}
				class="bg-transparent rounded-lg px-1.5 py-1 border border-gray-100 dark:border-gray-850"
			/>
		</label>
		<label class="flex items-center gap-1.5">
			<span class="text-gray-500">to</span>
			<input
				type="datetime-local"
				bind:value={to}
				on:change={gather}
				class="bg-transparent rounded-lg px-1.5 py-1 border border-gray-100 dark:border-gray-850"
			/>
		</label>
	</div>

	<div class="flex flex-wrap items-center gap-1.5 text-xs">
		{#each modes as m}
			<button
				type="button"
				title={m.hint}
				class="{chipClass} {mode === m.id
					? '!bg-gray-200 dark:!bg-gray-700 text-gray-900 dark:text-white'
					: ''}"
				on:click={() => (mode = m.id)}>{m.label}</button
			>
		{/each}
		<label class="flex items-center gap-1.5 ml-1 text-gray-500" title="md keeps only messages sent inside the window (json stays whole)">
			<input type="checkbox" bind:checked={trimToRange} />
			trim to range
		</label>
	</div>

	<div class="text-xs text-gray-500 min-h-4">
		{#if gathering}
			gathering her chats…
		{:else if bundle}
			{bundle.chats} chats · {bundle.messages} messages
			{#if bundle.chats}<span class="opacity-60"> → {bundle.folder}</span>{/if}
		{:else if from && to && end < start}
			the window ends before it begins~
		{/if}
	</div>

	<div class="flex flex-wrap gap-1.5">
		<button
			type="button"
			class="{actionClass} bg-gray-900 text-white dark:bg-white dark:text-gray-900"
			disabled={!bundle?.chats || busy}
			title={gardenRoot ? `plant into ${gardenRoot}` : 'plant on the Petal rig'}
			on:click={plant}>🌷 plant on Petal</button
		>
		<button
			type="button"
			class="{actionClass} bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800"
			disabled={!bundle?.chats || busy}
			on:click={zip}>zip</button
		>
		<button
			type="button"
			class="{actionClass} bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800"
			disabled={!bundle?.chats || busy}
			on:click={copy}>copy</button
		>
	</div>

	{#if lastPlanted}
		<div class="text-xs text-gray-500 break-all">planted → {lastPlanted}</div>
	{/if}
</div>
