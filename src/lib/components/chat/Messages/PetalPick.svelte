<script lang="ts">
	// 🍒 the pick (slice A29) — two replies to one moment, built once and sent twice (utils/petal_pick.py).
	// desktop: side by side · phone: one at a time, swipe between them. one tap picks: the chosen reply becomes
	// the branch she's on, the other stays a sibling, never deleted, and the pair goes to the ledger through the
	// thumbs queue (👍🏻 / 👎🏻, both marked petal_pick). nothing to tap while they arrive; at rest nothing moves.
	import { getContext, onDestroy, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';

	import { updateChatById } from '$lib/apis/chats';
	import { mobile, models } from '$lib/stores';
	import { openPick, pickGlow, pickVerdicts, type OpenPick } from '$lib/utils/petal-pick';
	import { thumbVerdict } from '$lib/utils/petal-thumbs';

	import ResponseMessage from './ResponseMessage.svelte';

	const i18n: Writable<any> = getContext('i18n');

	export let chatId = '';
	export let history: { currentId: string | null; messages: Record<string, any> };
	export let pair: OpenPick;
	export let selectedModels: string[] = [];

	export let setInputText: Function = () => {};
	export let updateChat: Function;
	export let editMessage: Function;
	export let saveMessage: Function;
	export let rateMessage: Function;
	export let actionMessage: Function;
	export let deleteMessage: Function;
	export let submitMessage: Function;
	export let continueResponse: Function;
	export let regenerateResponse: Function;
	export let addMessages: Function;
	export let onToolCallResolved: Function = () => {};
	export let forkHandler: Function | null = null;
	export let allowDelete = true;
	export let allowToolApproval = false;
	export let editCodeBlock = true;
	export let topPadding = false;
	export let onInsertToNote: ((content: string) => void) | null = null;

	let scroller: HTMLElement;
	let cols: HTMLElement[] = [];
	let seen = 0; // phone: the reply on screen
	let io: IntersectionObserver | null = null;
	let picking = false;

	$: ids = [pair.a, pair.b];

	const pick = (chosen: string) => {
		const open = openPick(history, chosen);
		if (picking || !open?.ready) return;
		picking = true;
		const verdicts = pickVerdicts(history, chatId, chosen, $models ?? []); // 0.13.5: the list starts as null
		if (verdicts.length !== 2) return void (picking = false);
		// her pick, at once on the page: the pair closes and the chosen reply is the branch she's on
		for (const v of verdicts)
			history.messages[v.message_id] = { ...history.messages[v.message_id], annotation: v.annotation };
		history.currentId = chosen;
		history = history;
		pickGlow.set(chosen);
		for (const v of verdicts) thumbVerdict(v); // the ledger's pair, through the thumbs queue (quiet)
		// only the branch moves on the server: the replies' verdicts arrive by the thumbs route
		updateChatById(localStorage.token, chatId, { history: { currentId: chosen, messages: {} } }).catch(
			(e) => console.warn('🍒 the picked branch was not saved yet', e)
		);
		window.dispatchEvent(new CustomEvent('petal:picked', { detail: { chatId, id: chosen } }));
	};

	// the phone shows one reply at a time: which one is on screen (no timer, no animation)
	const watch = () => {
		io?.disconnect();
		io = null;
		if (!$mobile || !scroller || typeof IntersectionObserver === 'undefined') return;
		io = new IntersectionObserver(
			(entries) => {
				for (const e of entries)
					if (e.isIntersecting) seen = Number((e.target as HTMLElement).dataset.pickSlot ?? 0);
			},
			{ root: scroller, threshold: 0.6 }
		);
		cols.forEach((c) => c && io?.observe(c));
	};
	$: if (scroller) {
		void $mobile; // the layout changed: watch again (or stop watching)
		watch();
	}

	const show = (slot: number) => cols[slot]?.scrollIntoView({ block: 'nearest', inline: 'center' });

	onMount(watch);
	onDestroy(() => io?.disconnect());
</script>

<div class="petal-pick" class:pp-phone={$mobile} data-petal-pick={pair.a}>
	<div class="pp-head">
		<span aria-hidden="true">🍒</span>
		<span>
			{#if !pair.ready}
				{$i18n.t('two replies on their way')}
			{:else if $mobile}
				{$i18n.t('swipe between them · tap the one that feels right')}
			{:else}
				{$i18n.t('two replies · tap the one that feels right')}
			{/if}
		</span>
		{#if $mobile}
			<span class="pp-dots" role="tablist" aria-label={$i18n.t('Replies')}>
				{#each ids as id, slot (id)}
					<button
						type="button"
						role="tab"
						class="pp-dot"
						class:pp-dot-on={seen === slot}
						aria-selected={seen === slot}
						aria-label={$i18n.t('Reply {{n}} of 2', { n: slot + 1 })}
						on:click={() => show(slot)}
					></button>
				{/each}
			</span>
		{/if}
	</div>

	<div class="pp-cols" bind:this={scroller}>
		{#each ids as id, slot (id)}
			<section
				class="pp-col"
				data-pick-slot={slot}
				aria-label={$i18n.t('Reply {{n}} of 2', { n: slot + 1 })}
				bind:this={cols[slot]}
			>
				<ResponseMessage
					{chatId}
					{history}
					messageId={id}
					{selectedModels}
					isLastMessage={false}
					siblings={[id]}
					gotoMessage={() => {}}
					showPreviousMessage={() => {}}
					showNextMessage={() => {}}
					{setInputText}
					{updateChat}
					{editMessage}
					{saveMessage}
					{rateMessage}
					{actionMessage}
					{deleteMessage}
					{submitMessage}
					{continueResponse}
					{regenerateResponse}
					{addMessages}
					{onToolCallResolved}
					{forkHandler}
					{allowDelete}
					{allowToolApproval}
					{editCodeBlock}
					{topPadding}
					{onInsertToNote}
					pickOpen
				/>
				<div class="pp-foot">
					{#if pair.ready}
						<button type="button" class="pp-this" data-pick-this={id} on:click={() => pick(id)}>
							<span aria-hidden="true">💗</span>
							{$i18n.t('this one')}
						</button>
					{/if}
					{#if $mobile}
						<!-- at the end of a long reply the header is far above: where she is, in two -->
						<span class="pp-of" aria-hidden="true">{slot + 1} / 2</span>
					{/if}
				</div>
			</section>
		{/each}
	</div>
</div>

<style>
	.petal-pick {
		width: 100%;
	}
	.pp-head {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		margin: 0 0 0.5rem;
		font-size: 0.8rem;
		color: var(--mist, #9a8f98);
	}
	.pp-dots {
		display: inline-flex;
		gap: 0.35rem;
		margin-left: auto;
	}
	.pp-dot {
		width: 0.5rem;
		height: 0.5rem;
		padding: 0;
		border-radius: 999px;
		border: 1px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.55);
		background: transparent;
	}
	.pp-dot-on {
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.75);
	}
	/* desktop: side by side, each reply its own column; both cards as tall as the longer one, so the two
	   "this one" sit on one line whatever their lengths */
	.pp-cols {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		gap: 0.75rem;
		align-items: stretch;
	}
	.pp-col {
		display: flex;
		flex-direction: column;
		min-width: 0;
		padding: 0.75rem 0.9rem 0.6rem;
		border-radius: 1rem;
		border: 1px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.18);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.03);
	}
	.pp-foot {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-top: auto;
		padding-top: 0.5rem;
	}
	.pp-of {
		margin-left: auto;
		font-size: 0.75rem;
		font-variant-numeric: tabular-nums;
		color: var(--mist, #9a8f98);
	}
	/* phone: one at a time, swipe between them (the browser's own scroll, nothing animated by us); the
	   other card's edge peeks in, so she knows there's a second one without reading a word */
	.pp-phone .pp-cols {
		display: flex;
		gap: 0.6rem;
		overflow-x: auto;
		scroll-snap-type: x mandatory;
		overscroll-behavior-x: contain;
		scrollbar-width: none;
	}
	.pp-phone .pp-cols::-webkit-scrollbar {
		display: none;
	}
	.pp-phone .pp-col {
		flex: 0 0 calc(100% - 2.25rem);
		scroll-snap-align: center;
		scroll-snap-stop: always;
	}
	.pp-this {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.35rem 0.85rem;
		border-radius: 999px;
		border: 1px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.45);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.1);
		color: inherit;
		font-size: 0.85rem;
		line-height: 1.2;
	}
	.pp-this:hover {
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.18);
	}
	.pp-this:focus-visible,
	.pp-dot:focus-visible {
		outline: 2px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.7);
		outline-offset: 2px;
	}
</style>
