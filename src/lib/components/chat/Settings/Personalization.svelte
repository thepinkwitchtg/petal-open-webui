<script lang="ts">
	import Switch from '$lib/components/common/Switch.svelte';
	import { config, settings } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import DropdownMenu from '$lib/components/common/DropdownMenu.svelte';
	import MemoryModal from './Personalization/MemoryModal.svelte';
	import {
		deleteMemoriesByUserId,
		deleteMemoryById,
		getMemories,
		updateMemoryMeta
	} from '$lib/apis/memories';
	import { toast } from 'svelte-sonner';
	import UserSettingRow from './UserSettingRow.svelte';
	import UserSettingSection from './UserSettingSection.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Trash from '$lib/components/icons/Trash.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const dispatch = createEventDispatcher();

	const i18n = getContext<Writable<i18nType>>('i18n');

	export let saveSettings: (settings: any) => void | Promise<void>;

	// ── petal: mirrors backend user-memory budget (utils/memory.py). keep in lockstep. ──
	const BUDGET = 6000;

	// Addons
	let enableMemory = false;
	let memories: Memory[] = [];
	let loadingMemories = true;

	let showMemoryModal = false;
	let selectedMemory: Memory | null = null;
	let showClearConfirmDialog = false;
	let showDeleteConfirm = false;
	let query = '';
	const actionButtonClass =
		'shrink-0 text-xs text-gray-500 transition-colors hover:text-gray-900 dark:text-gray-500 dark:hover:text-white';

	type Memory = {
		id: string;
		content: string;
		type?: string;
		path?: string;
		meta?: Record<string, any>;
		created_at?: number;
		updated_at?: number;
	};

	// ── petal helpers ── (byte-parity with backend memory_label + budget rule) ──
	const labelOf = (m: Memory) => (m.path ? `${m.path}: ${m.content}` : (m.content ?? ''));
	const isEnabled = (m: Memory) => (m.meta?.enabled ?? true) !== false;

	const byOrder = (a: Memory, b: Memory) => {
		const oa = a.meta?.order ?? Number.MAX_SAFE_INTEGER;
		const ob = b.meta?.order ?? Number.MAX_SAFE_INTEGER;
		if (oa !== ob) return oa - ob;
		const pa = a.path ?? '';
		const pb = b.path ?? '';
		if (pa !== pb) return pa < pb ? -1 : 1;
		return (a.created_at ?? 0) - (b.created_at ?? 0);
	};

	const matchesQuery = (m: Memory) => {
		const v = query.trim().toLowerCase();
		if (!v) return true;
		return (
			m.content?.toLowerCase().includes(v) ||
			m.path?.toLowerCase().includes(v) ||
			m.type?.toLowerCase().includes(v)
		);
	};

	// budget pass — mirrors backend exactly: enabled user rows only, in order,
	// cost = len(label) + join-\n, and it BREAKS at the first overflow (so the
	// dropped set is a clean suffix). status: 'in' | 'dropped' | 'off'.
	const computeBudget = (list: Memory[]) => {
		let used = 0;
		let added = 0;
		let over = false;
		const status = new Map<string, string>();
		for (const m of list) {
			if (!isEnabled(m)) {
				status.set(m.id, 'off');
				continue;
			}
			if (over) {
				status.set(m.id, 'dropped');
				continue;
			}
			const cost = labelOf(m).length + (added > 0 ? 1 : 0);
			if (used + cost > BUDGET) {
				over = true;
				status.set(m.id, 'dropped');
			} else {
				used += cost;
				added += 1;
				status.set(m.id, 'in');
			}
		}
		return { used, status };
	};

	$: allUser = memories.filter((m) => (m.type ?? 'user') === 'user').sort(byOrder);
	$: budget = computeBudget(allUser);
	$: userView = allUser.filter(matchesQuery);
	$: contextView = memories
		.filter((m) => m.type === 'context')
		.filter(matchesQuery)
		.sort((a, b) => (b.updated_at ?? 0) - (a.updated_at ?? 0));
	$: pct = Math.min(100, (budget.used / BUDGET) * 100);

	const loadMemories = async () => {
		loadingMemories = true;
		memories =
			(await getMemories(localStorage.token).catch((error) => {
				toast.error(`${error}`);
				return [];
			})) ?? [];
		loadingMemories = false;
	};

	// ── petal: enable/disable without touching content (no re-embed) ──
	const toggleMemory = async (m: Memory) => {
		const next = !isEnabled(m);
		m.meta = { ...(m.meta ?? {}), enabled: next };
		memories = memories;
		try {
			await updateMemoryMeta(localStorage.token, m.id, { enabled: next });
		} catch (error) {
			toast.error(`${error}`);
			m.meta.enabled = !next;
			memories = memories;
		}
	};

	// ── petal: drag-to-order (writes integer meta.order, only for changed rows) ──
	let dragId: string | null = null;
	let overId: string | null = null;

	const onDragStart = (e: DragEvent, id: string) => {
		dragId = id;
		if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
	};
	const onDragOver = (e: DragEvent, id: string) => {
		e.preventDefault();
		overId = id;
	};
	const onDragEnd = () => {
		dragId = null;
		overId = null;
	};
	const onDrop = async (e: DragEvent, id: string) => {
		e.preventDefault();
		const dropped = dragId;
		dragId = null;
		overId = null;
		if (!dropped || dropped === id) return;

		const list = allUser.slice();
		const from = list.findIndex((m) => m.id === dropped);
		const to = list.findIndex((m) => m.id === id);
		if (from < 0 || to < 0) return;
		const [moved] = list.splice(from, 1);
		list.splice(to, 0, moved);
		await persistOrder(list);
	};

	const persistOrder = async (ordered: Memory[]) => {
		const writes: Promise<any>[] = [];
		ordered.forEach((m, i) => {
			if (m.meta?.order !== i) {
				m.meta = { ...(m.meta ?? {}), order: i };
				writes.push(updateMemoryMeta(localStorage.token, m.id, { order: i }));
			}
		});
		memories = memories; // resort from new orders
		if (writes.length) {
			try {
				await Promise.all(writes);
			} catch (error) {
				toast.error(`${error}`);
				await loadMemories();
			}
		}
	};

	const confirmDeleteMemory = (memory: Memory) => {
		selectedMemory = memory;
		showDeleteConfirm = true;
	};

	const editMemory = (memory: Memory) => {
		selectedMemory = memory;
		showMemoryModal = true;
	};

	let onClearConfirmed = async () => {
		const res = await deleteMemoriesByUserId(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res && memories.length > 0) {
			toast.success($i18n.t('Memory cleared successfully'));
			memories = [];
		}
		showClearConfirmDialog = false;
	};

	onMount(async () => {
		enableMemory = $settings?.memory ?? $config?.features?.enable_memories ?? false;
		await loadMemories();
	});
</script>

<form
	id="tab-personalization"
	class="flex flex-col h-full justify-between text-sm"
	on:submit|preventDefault={() => {
		dispatch('save');
	}}
>
	<h2 class="text-sm font-medium text-gray-900 dark:text-white mb-4">
		{$i18n.t('Personalization')}
	</h2>

	<div class="flex-1 min-h-0 overflow-y-auto scrollbar-hover pr-1.5">
		<UserSettingSection title={$i18n.t('Memory')} first>
			<UserSettingRow
				description={$i18n
					.t(
						"You can personalize your interactions with LLMs by adding memories through the 'Manage' button below, making them more helpful and tailored to you."
					)
					.replace($i18n.t('Manage'), $i18n.t('Add Memory'))}
			>
				<Tooltip
					slot="label"
					content={$i18n.t(
						'This is an experimental feature, it may not function as expected and is subject to change at any time.'
					)}
				>
					<div class="flex items-center gap-2">
						{$i18n.t('Memory')}
						<span class="text-[0.625rem] uppercase text-gray-400 dark:text-gray-600"
							>{$i18n.t('Experimental')}</span
						>
					</div>
				</Tooltip>

				<Switch
					bind:state={enableMemory}
					on:change={async () => {
						saveSettings({ memory: enableMemory });
					}}
				/>
			</UserSettingRow>

			{#if enableMemory}
				<div class="petal-mem">
					<div class="mb-1 flex items-center">
						<div class="text-xs text-gray-600 dark:text-gray-400">
							{$i18n.t('Saved Memories')}
							{#if !loadingMemories}
								<span class="ml-1 text-gray-400 dark:text-gray-600">{memories.length}</span>
							{/if}
						</div>
					</div>

					{#if loadingMemories}
						<div class="flex min-h-16 w-full items-center justify-center">
							<Spinner className="size-4" />
						</div>
					{:else}
						<div class="mb-2 flex min-w-0 items-center justify-between gap-3">
							{#if memories.length > 0}
								<div class="flex min-w-0 flex-1 items-center gap-2">
									<Search className="size-3.5 shrink-0 text-gray-400 dark:text-gray-600" />
									<input
										data-settings-search
										class="min-w-0 flex-1 bg-transparent py-0.5 text-xs text-gray-700 outline-hidden placeholder:text-gray-300 dark:text-gray-300 dark:placeholder:text-gray-700"
										bind:value={query}
										placeholder={$i18n.t('Search Memories')}
										maxlength="500"
									/>
									{#if query}
										<div class="shrink-0">
											<button
												class="rounded-lg p-0.5 text-gray-400 transition-colors hover:text-gray-700 dark:text-gray-600 dark:hover:text-gray-300"
												type="button"
												aria-label={$i18n.t('Clear search')}
												on:click={() => {
													query = '';
												}}
											>
												<XMark className="size-3" strokeWidth="2" />
											</button>
										</div>
									{/if}
								</div>
							{:else}
								<div class="min-w-0 flex-1"></div>
							{/if}

							<Dropdown align="end">
								<Tooltip content={$i18n.t('Actions')}>
									<button
										class="flex h-7 items-center gap-1.5 rounded-lg bg-transparent px-1.5 text-xs text-gray-500 transition-colors hover:text-gray-900 dark:text-gray-500 dark:hover:text-white"
										type="button"
									>
										<span>{$i18n.t('Actions')}</span>
										<ChevronDown className="size-3" strokeWidth="2.5" />
									</button>
								</Tooltip>

								<div slot="content">
									<DropdownMenu className="w-[170px] shadow-sm">
										<button
											class="flex h-[1.6875rem] w-full cursor-pointer select-none items-center gap-2 rounded-lg bg-transparent px-2 text-xs hover:text-gray-900 disabled:cursor-default disabled:opacity-30 dark:hover:text-gray-100"
											type="button"
											on:click={() => {
												selectedMemory = null;
												showMemoryModal = true;
											}}
										>
											<Plus className="size-3.5 shrink-0" strokeWidth="1.5" />
											<div class="min-w-0 flex-1 truncate text-left">{$i18n.t('Add Memory')}</div>
										</button>

										<button
											class="flex h-[1.6875rem] w-full cursor-pointer select-none items-center gap-2 rounded-lg bg-transparent px-2 text-xs hover:text-gray-900 disabled:cursor-default disabled:opacity-30 dark:hover:text-gray-100"
											disabled={memories.length === 0}
											type="button"
											on:click={() => {
												showClearConfirmDialog = true;
											}}
										>
											<Trash className="size-3.5 shrink-0" strokeWidth="1.5" />
											<div class="min-w-0 flex-1 truncate text-left">{$i18n.t('Clear memory')}</div>
										</button>
									</DropdownMenu>
								</div>
							</Dropdown>
						</div>

						<!-- ─────────────────────  USER · your shelf  ───────────────────── -->
						<div class="mem-section">
							<div class="mem-sec-head">
								<span class="mem-sec-title">{$i18n.t('User Memory')}</span>
								<span class="mem-sec-sub">your shelf · drag to order</span>
								<span class="mem-flex"></span>
								<span class="mem-sec-count">{allUser.length}</span>
							</div>

							<!-- budget bar -->
							<div class="mem-bar-wrap" title="how full your always-on memory block is">
								<div class="mem-bar">
									<div class="mem-bar-fill" class:hot={pct > 90} style="width:{pct}%"></div>
								</div>
								<span class="mem-bar-num" class:hot={pct > 90}>{budget.used} / {BUDGET}</span>
							</div>

							{#if userView.length === 0}
								<div class="mem-empty">
									{#if allUser.length === 0}
										{$i18n.t('Memories accessible by LLMs will be shown here.')}
									{:else}
										{$i18n.t('No results found')}
									{/if}
								</div>
							{:else}
								<div class="mem-list">
									{#each userView as memory (memory.id)}
										{@const st = budget.status.get(memory.id)}
										<div
											class="mem-row"
											class:off={!isEnabled(memory)}
											class:dropped={st === 'dropped'}
											class:dragging={dragId === memory.id}
											class:over={overId === memory.id && dragId !== memory.id}
											draggable="true"
											on:dragstart={(e) => onDragStart(e, memory.id)}
											on:dragover={(e) => onDragOver(e, memory.id)}
											on:drop={(e) => onDrop(e, memory.id)}
											on:dragend={onDragEnd}
										>
											<span class="mem-grip" aria-hidden="true">⠿</span>

											<button
												type="button"
												class="mem-toggle"
												class:on={isEnabled(memory)}
												aria-label={isEnabled(memory) ? 'disable memory' : 'enable memory'}
												title={isEnabled(memory)
													? 'injected · click to silence'
													: 'silenced · click to arm'}
												on:click={() => toggleMemory(memory)}
											>
												<span class="mem-knob"></span>
											</button>

											<div class="mem-body">
												{#if memory.path}<span class="mem-path">{memory.path}</span>{/if}
												<span class="mem-text">{memory.content}</span>
												{#if st === 'dropped'}
													<span class="mem-flag">not injected · over budget</span>
												{:else if !isEnabled(memory)}
													<span class="mem-flag off">silenced</span>
												{/if}
											</div>

											<span class="mem-cost" title="characters this entry spends"
												>{labelOf(memory).length}</span
											>

											<div class="mem-actions">
												<button
													type="button"
													class={actionButtonClass + ' hover:underline'}
													on:click={() => editMemory(memory)}
												>
													{$i18n.t('Edit')}
												</button>
												<button
													type="button"
													class={actionButtonClass + ' hover:underline'}
													on:click={() => confirmDeleteMemory(memory)}
												>
													{$i18n.t('Remove')}
												</button>
											</div>
										</div>
									{/each}
								</div>
							{/if}
						</div>

						<!-- ─────────────────  CONTEXT · her ledger  ───────────────── -->
						<div class="mem-section context">
							<div class="mem-sec-head">
								<span class="mem-sec-title">{$i18n.t('Context')}</span>
								<span class="mem-sec-sub">what Petal remembers · she manages these</span>
								<span class="mem-flex"></span>
								<span class="mem-sec-count">{contextView.length}</span>
							</div>

							{#if contextView.length === 0}
								<div class="mem-empty">Nothing gathered yet — this fills as she learns.</div>
							{:else}
								<div class="mem-list">
									{#each contextView as memory (memory.id)}
										<div class="mem-row context" class:off={!isEnabled(memory)}>
											<button
												type="button"
												class="mem-toggle"
												class:on={isEnabled(memory)}
												aria-label={isEnabled(memory) ? 'silence context' : 'arm context'}
												title={isEnabled(memory)
													? 'retrievable · click to silence'
													: 'silenced · click to arm'}
												on:click={() => toggleMemory(memory)}
											>
												<span class="mem-knob"></span>
											</button>

											<div class="mem-body">
												{#if memory.path}<span class="mem-path">{memory.path}</span>{/if}
												<span class="mem-text">{memory.content}</span>
												{#if !isEnabled(memory)}<span class="mem-flag off">silenced</span>{/if}
											</div>

											<span class="mem-cost">{labelOf(memory).length}</span>

											<div class="mem-actions">
												<button
													type="button"
													class={actionButtonClass + ' hover:underline'}
													on:click={() => confirmDeleteMemory(memory)}
												>
													{$i18n.t('Remove')}
												</button>
											</div>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{/if}
		</UserSettingSection>
	</div>

	<div class="shrink-0 flex justify-end text-sm font-normal">
		<button
			class="px-3.5 py-1.5 text-sm font-normal bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full"
			type="submit"
		>
			{$i18n.t('Save')}
		</button>
	</div>
</form>

<ConfirmDialog
	title={$i18n.t('Clear Memory')}
	message={$i18n.t('Are you sure you want to clear all memories? This action cannot be undone.')}
	show={showClearConfirmDialog}
	on:confirm={onClearConfirmed}
	on:cancel={() => {
		showClearConfirmDialog = false;
	}}
/>

<ConfirmDialog
	title={$i18n.t('Delete Memory?')}
	show={showDeleteConfirm}
	on:confirm={async () => {
		if (!selectedMemory) return;

		const res = await deleteMemoryById(localStorage.token, selectedMemory.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Memory deleted successfully'));
			await loadMemories();
		}
		showDeleteConfirm = false;
	}}
	on:cancel={() => {
		showDeleteConfirm = false;
	}}
>
	<div class="text-sm text-gray-500 flex-1">
		{$i18n.t('Are you sure you want to delete this memory? This action cannot be undone.')}
		<div
			class="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-gray-100/50 bg-gray-50/40 p-2 text-xs text-gray-600 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-400"
		>
			{selectedMemory?.content}
		</div>
	</div>
</ConfirmDialog>

<MemoryModal
	bind:show={showMemoryModal}
	memory={selectedMemory as any}
	on:save={async () => {
		await loadMemories();
	}}
/>

<style>
	/* 🌸 memory panel — STRUCTURE ONLY. every colour + font drinks from
	   petal/tokens.css on html.petal, so turning a global dial turns this
	   room too. nothing hardcoded → no drift.
	   (map: petal-owui-theme-and-memory-map.md) */

	.mem-section {
		margin-top: 0.5rem;
	}
	.mem-section.context {
		margin-top: 1rem;
		padding-top: 0.75rem;
		border-top: 1px solid var(--edge-soft);
	}

	.mem-sec-head {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
	}
	.mem-flex {
		flex: 1;
	}
	.mem-sec-title {
		font-size: 0.75rem;
		font-weight: 600;
		background: var(--grad-hairline);
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
		letter-spacing: 0.01em;
	}
	.mem-sec-sub {
		font-size: 0.625rem;
		color: var(--whisper);
	}
	.mem-sec-count {
		font-family: var(--font-mono);
		font-size: 0.625rem;
		color: var(--mist);
	}

	/* budget bar */
	.mem-bar-wrap {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.6rem;
	}
	.mem-bar {
		flex: 1;
		height: 6px;
		border-radius: 999px;
		background: var(--obsidian);
		box-shadow: inset 0 0 0 1px var(--edge-soft);
		overflow: hidden;
	}
	.mem-bar-fill {
		height: 100%;
		border-radius: 999px;
		background: linear-gradient(90deg, var(--candy-light), var(--candy) 55%, var(--iris));
		box-shadow: 0 0 10px oklch(0.711 0.214 var(--p-h-accent) / 0.45);
		transition: width 0.25s ease;
	}
	.mem-bar-fill.hot {
		background: linear-gradient(90deg, var(--candy), var(--candy-deep));
		box-shadow: 0 0 10px oklch(0.607 0.198 var(--p-h-accent) / 0.55);
	}
	.mem-bar-num {
		font-family: var(--font-mono);
		font-size: 0.625rem;
		color: var(--mist);
		white-space: nowrap;
	}
	.mem-bar-num.hot {
		color: var(--candy-deep);
	}

	/* rows */
	.mem-list {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.mem-row {
		display: flex;
		align-items: flex-start;
		gap: 0.55rem;
		padding: 0.5rem 0.6rem;
		border-radius: var(--radius-sm, 8px);
		background: linear-gradient(180deg, var(--obsidian-lit), var(--obsidian));
		box-shadow: inset 0 0 0 1px var(--edge-soft);
		transition:
			box-shadow 0.15s ease,
			opacity 0.15s ease,
			transform 0.08s ease;
	}
	.mem-row.over {
		box-shadow: inset 0 0 0 1px transparent;
		background:
			linear-gradient(var(--obsidian), var(--obsidian)) padding-box,
			var(--grad-hairline) border-box;
		border: 1px solid transparent;
	}
	.mem-row.dragging {
		opacity: 0.5;
	}
	.mem-row.off {
		opacity: 0.45;
	}
	.mem-row.dropped {
		opacity: 0.6;
		box-shadow: inset 0 0 0 1px oklch(0.607 0.198 var(--p-h-accent) / 0.35);
	}

	.mem-grip {
		color: var(--whisper);
		cursor: grab;
		font-size: 0.85rem;
		line-height: 1.2;
		user-select: none;
		padding-top: 1px;
	}
	.mem-grip:active {
		cursor: grabbing;
	}
	.mem-row.context .mem-grip {
		display: none;
	}

	/* Abyss toggle — obsidian track, candy when armed, gradient hairline */
	.mem-toggle {
		flex: 0 0 auto;
		width: 26px;
		height: 15px;
		border-radius: 999px;
		position: relative;
		margin-top: 1px;
		background: var(--obsidian);
		box-shadow: inset 0 0 0 1px var(--edge);
		transition:
			background 0.18s ease,
			box-shadow 0.18s ease;
		cursor: pointer;
	}
	.mem-toggle .mem-knob {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 11px;
		height: 11px;
		border-radius: 50%;
		background: var(--whisper);
		transition:
			left 0.18s ease,
			background 0.18s ease;
	}
	.mem-toggle.on {
		background: linear-gradient(135deg, var(--candy), var(--iris));
		box-shadow: 0 0 8px oklch(0.711 0.214 var(--p-h-accent) / 0.4);
	}
	.mem-toggle.on .mem-knob {
		left: 13px;
		background: var(--candy-light);
	}

	.mem-body {
		min-width: 0;
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.mem-path {
		font-family: var(--font-mono);
		font-size: 0.5625rem;
		color: var(--iris);
		opacity: 0.85;
	}
	.mem-text {
		font-size: 0.75rem;
		color: var(--pearl);
		white-space: pre-wrap;
		word-break: break-word;
		line-height: 1.4;
	}
	.mem-flag {
		font-family: var(--font-mono);
		font-size: 0.5rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--candy-deep);
		margin-top: 2px;
	}
	.mem-flag.off {
		color: var(--whisper);
	}

	.mem-cost {
		flex: 0 0 auto;
		font-family: var(--font-mono);
		font-size: 0.5625rem;
		color: var(--mist);
		padding-top: 2px;
		min-width: 2.5ch;
		text-align: right;
	}

	.mem-actions {
		flex: 0 0 auto;
		display: flex;
		gap: 0.5rem;
		padding-top: 1px;
	}

	.mem-empty {
		min-height: 3rem;
		font-size: 0.6875rem;
		color: var(--whisper);
		padding: 0.25rem 0;
	}
</style>
