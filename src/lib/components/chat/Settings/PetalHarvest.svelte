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
	import { getFolders, createNewFolder, deleteFolderById } from '$lib/apis/folders';
	import { updateChatFolderIdById } from '$lib/apis/chats';
	import { refreshSidebar } from '$lib/stores/chatList';
	import PetalWindow from './PetalWindow.svelte';
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

	// 🗂 gathering into an OWUI folder. A chat lives in exactly one folder, so this
	// MOVES the chats (cloning would hand the ledger + Anamnesis duplicate chats).
	const HARVEST_PARENT = '🌷 harvests';
	let pullPlaced = false; // also pull chats already filed elsewhere / pinned
	let lastGather: { folderId: string; name: string; moved: { id: string; prev: string | null }[] } | null =
		null;

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

	// chats already filed in another folder, or pinned (moving unpins them)
	$: placed = bundle?.ids
		? (chats ?? []).filter((c) => bundle!.ids.includes(c.id) && (c.folder_id || c.pinned))
		: [];
	$: toGather = bundle?.ids
		? bundle.ids.filter((id) => pullPlaced || !placed.some((c) => c.id === id))
		: [];

	const gatherFolder = async () => {
		if (!bundle?.chats || !toGather.length) return;
		busy = true;
		const token = localStorage.token;
		try {
			const all: any[] = (await getFolders(token)) ?? [];
			let parent = all.find((f) => f.name === HARVEST_PARENT && !f.parent_id);
			if (!parent) parent = await createNewFolder(token, { name: HARVEST_PARENT });

			const siblings = new Set(all.filter((f) => f.parent_id === parent.id).map((f) => f.name));
			let name = bundle.folder;
			for (let i = 2; siblings.has(name); i++) name = `${bundle.folder} (${i})`;

			const moved: { id: string; prev: string | null }[] = [];
			for (const id of toGather) {
				const c = chats?.find((x) => x.id === id);
				moved.push({ id, prev: c?.folder_id ?? null });
			}

			const folder = await createNewFolder(token, {
				name,
				parent_id: parent.id,
				meta: {
					petal_harvest: {
						range: bundle.range,
						trim_to_range: trimToRange,
						gathered_at: Math.floor(Date.now() / 1000),
						moved // where each chat lived before, so the gather can be undone
					}
				}
			});

			for (const m of moved) {
				await updateChatFolderIdById(token, m.id, folder.id);
				const c = chats?.find((x) => x.id === m.id);
				if (c) {
					c.folder_id = folder.id;
					c.pinned = false;
				}
			}
			chats = chats; // let the counts notice
			lastGather = { folderId: folder.id, name, moved };
			remember();
			await refreshSidebar(token).catch(() => {});
			toast.success(`🗂 ${moved.length} chats gathered into ${name}`);
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			busy = false;
		}
	};

	const undoGather = async () => {
		if (!lastGather) return;
		busy = true;
		const token = localStorage.token;
		try {
			for (const m of lastGather.moved) {
				await updateChatFolderIdById(token, m.id, m.prev ?? undefined);
				const c = chats?.find((x) => x.id === m.id);
				if (c) c.folder_id = m.prev;
			}
			await deleteFolderById(token, lastGather.folderId, false);
			chats = chats;
			toast.success(`chats returned to where they lived`);
			lastGather = null;
			await refreshSidebar(token).catch(() => {});
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

	<PetalWindow bind:from bind:to on:change={gather} />

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
			disabled={!toGather.length || busy}
			title="move these chats into {HARVEST_PARENT} / {bundle?.folder ?? '…'}"
			on:click={gatherFolder}>🗂 gather in OWUI</button
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

	{#if placed.length}
		<label
			class="flex items-center gap-1.5 text-xs text-gray-500"
			title="moving a chat out of its folder takes it out of that folder; moving a pinned chat unpins it"
		>
			<input type="checkbox" bind:checked={pullPlaced} />
			{placed.length} already filed or pinned — pull them into the folder too
		</label>
	{/if}

	{#if lastGather}
		<div class="flex items-center gap-2 text-xs text-gray-500 break-all">
			<span>gathered → {HARVEST_PARENT} / {lastGather.name}</span>
			<button type="button" class="underline opacity-80 hover:opacity-100" disabled={busy} on:click={undoGather}
				>undo</button
			>
		</div>
	{/if}

	{#if lastPlanted}
		<div class="text-xs text-gray-500 break-all">planted → {lastPlanted}</div>
	{/if}
</div>
