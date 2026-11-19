<script lang="ts">
	// 🌸 Petal (slice A30b) · a select for the Petal tab, in the app's own menu (common/Select), never the
	// browser's popup (its blue-and-white hover, its bare group lines). the menu is the fork's, so the 🌸 skin
	// dresses it as every menu in the app: violet ground, candy focus ring, the theme's hairlines between groups.
	// groups with a quiet label, items that can't be chosen yet (dimmed), the chosen one checked, arrow keys.
	// the closed control matches the tab's other fields. nothing animates at rest. the options sit in a real
	// listbox: a modal's focus trap lets the keyboard into a portaled listbox (common/Modal), and a screen
	// reader hears options, not buttons.
	import Select from '$lib/components/common/Select.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	type Item = { value: string; label: string; disabled?: boolean };
	type Group = { label?: string; items: Item[] };

	export let value = '';
	export let groups: Group[] = [];
	export let id = '';
	export let ariaLabel = '';
	export let ariaLabelledby = '';
	export let placeholder = '';
	export let disabled = false;
	export let onChange: (value: string) => void = () => {};

	let open = false;
	$: flat = groups.flatMap((g) => g.items);
	$: chosen = flat.find((i) => i.value === value)?.label ?? placeholder;

	const look =
		'flex h-7 w-fit max-w-[16rem] items-center gap-2 rounded-lg border border-gray-100/50 bg-gray-50/40 ps-2.5 pe-2 text-left text-xs text-gray-700 outline-hidden transition-colors focus:border-blue-400 disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:focus:border-blue-500';

	// arrows walk the items she can choose; Home and End reach the ends
	const walk = (e: KeyboardEvent) => {
		if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
		e.stopPropagation();
		const here = e.currentTarget as HTMLButtonElement;
		const all = [
			...(here.parentElement?.querySelectorAll<HTMLButtonElement>('button[data-petal-option]:not([disabled])') ?? [])
		];
		const i = all.indexOf(here);
		const to =
			e.key === 'Home'
				? 0
				: e.key === 'End'
					? all.length - 1
					: (i + (e.key === 'ArrowDown' ? 1 : -1) + all.length) % all.length;
		all[to]?.focus();
		e.preventDefault();
	};
</script>

{#if disabled}
	<button type="button" class={look} {id} aria-label={ariaLabel || undefined} aria-labelledby={ariaLabelledby || undefined} disabled>
		<span class="min-w-0 truncate">{chosen}</span>
		<ChevronDown className="size-3.5 shrink-0 text-gray-400 dark:text-gray-500" strokeWidth="2" />
	</button>
{:else}
	<span class="contents" {id} data-petal-select={id || undefined}>
		<Select
			bind:value
			bind:open
			items={flat}
			{placeholder}
			align="end"
			triggerClass={look}
			contentClass="min-w-[12rem] max-w-[20rem]"
			maxHeight="18rem"
			onChange={(v) => onChange(v)}
		>
			<svelte:fragment slot="trigger">
				<span class="min-w-0 truncate" aria-label={ariaLabel || undefined}>{chosen}</span>
				<ChevronDown className="size-3.5 shrink-0 text-gray-400 dark:text-gray-500" strokeWidth="2" />
			</svelte:fragment>

			<svelte:fragment let:selectItem>
				<div role="listbox" aria-label={ariaLabel || undefined} aria-labelledby={ariaLabelledby || undefined}>
					{#each groups as group, gi (gi)}
						{#if gi > 0}
							<hr class="mx-1 my-0.5 border-gray-100 dark:border-gray-800" data-petal-hairline />
						{/if}
						{#if group.label}
							<div class="petal-select-group" role="presentation" data-petal-group>{group.label}</div>
						{/if}
						{#each group.items as item (item.value)}
							<button
								type="button"
								role="option"
								class="focus-ring petal-select-item flex h-[1.6875rem] w-full items-center gap-2 rounded-xl px-2 text-[0.8125rem] hover:bg-gray-50/60 dark:hover:bg-gray-800/60"
								class:petal-select-on={item.value === value}
								data-petal-option={item.value}
								aria-selected={item.value === value}
								aria-disabled={item.disabled || undefined}
								disabled={item.disabled}
								on:keydown={walk}
								on:click={() => !item.disabled && selectItem(item)}
							>
								<span class="min-w-0 flex-1 truncate text-left">{item.label}</span>
								{#if item.value === value}
									<Check className="size-3.5 shrink-0" strokeWidth="2" />
								{/if}
							</button>
						{/each}
					{/each}
				</div>
			</svelte:fragment>
		</Select>
	</span>
{/if}

<style>
	/* the group's quiet name, above its items (never a choice) */
	:global(.petal-select-group) {
		padding: 0.3rem 0.5rem 0.15rem;
		font-size: 0.6875rem;
		letter-spacing: 0.01em;
		color: var(--whisper, rgb(156 163 175));
		user-select: none;
	}
	:global(.petal-select-item) {
		color: var(--mist, inherit);
	}
	:global(.petal-select-item.petal-select-on) {
		color: var(--pearl, inherit);
	}
	/* waiting: seen, never chosen, no hover */
	:global(.petal-select-item:disabled),
	:global(.petal-select-item:disabled:hover) {
		opacity: 0.45;
		cursor: not-allowed;
		background: transparent !important;
	}
</style>
