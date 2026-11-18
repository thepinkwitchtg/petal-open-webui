<script lang="ts">
	// 🍒 the pick (slice A29) — two replies to one moment, built once and sent twice (utils/petal_pick.py).
	// desktop: side by side · phone: one at a time, swipe between them. one tap picks: the chosen reply becomes
	// the branch she's on, the other stays a sibling, never deleted, and the pair goes to the ledger through the
	// thumbs queue (👍🏻 / 👎🏻, both marked petal_pick). nothing to tap while they arrive; at rest nothing moves.
	import { getContext, onDestroy, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';

	import { updateChatById } from '$lib/apis/chats';
	import { mobile, models, settings } from '$lib/stores';
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
		const verdicts = pickVerdicts(history, chatId, chosen, $models);
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

<div
	class="petal-pick"
	class:pp-phone={$mobile}
	class:pp-wide={$settings?.widescreenMode ?? false}
	data-petal-pick={pair.a}
>
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
	/* 🍒 Abyssal Pink (the openwebui + petal-gen refs): every colour is a petal token, each with a quiet
	   fallback for the other themes. nothing here animates: at rest the pick costs the 3080 nothing */
	.petal-pick {
		width: 100%;
	}
	.pp-head {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.45rem;
		margin: 0.15rem 0 0.75rem;
		font-size: 0.8rem;
		letter-spacing: 0.01em;
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
	/* desktop: the chat area split into two real columns. each is as wide as the chat reads (its own max
	   width), or half the chat when the window can't hold two; both as tall as the longer reply, so the two
	   "this one" sit on one line; a quiet gutter between them */
	.pp-cols {
		--pp-col: 58rem; /* the chat column's own max width */
		--pp-gutter: 2.25rem;
		position: relative;
		display: grid;
		grid-template-columns: repeat(2, minmax(0, var(--pp-col)));
		justify-content: center;
		column-gap: var(--pp-gutter);
		align-items: stretch;
	}
	.pp-wide .pp-cols {
		--pp-col: 1fr; /* widescreen: the whole chat, split evenly */
	}
	/* the gutter: one still hairline down its middle, fading at both ends (petal-gen's splitter, at rest) */
	.pp-cols::before {
		content: '';
		position: absolute;
		top: 1.5rem;
		bottom: 1.5rem;
		left: 50%;
		width: 1px;
		transform: translateX(-50%);
		background: linear-gradient(
			to bottom,
			transparent,
			var(--edge, oklch(0.6 0 0 / 0.22)) 20%,
			var(--edge, oklch(0.6 0 0 / 0.22)) 80%,
			transparent
		);
		pointer-events: none;
	}
	.pp-col {
		display: flex;
		flex-direction: column;
		min-width: 0;
		padding: 1rem 1.35rem 0.9rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, oklch(0.6 0 0 / 0.16));
		background: linear-gradient(180deg, var(--obsidian-lit, transparent) 0%, transparent 6rem);
		box-shadow: inset 0 1px 0 var(--glass-sheen, transparent);
	}
	.pp-foot {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-top: auto;
		padding-top: 0.75rem;
	}
	.pp-of {
		margin-left: auto;
		font-size: 0.75rem;
		font-variant-numeric: tabular-nums;
		color: var(--mist, #9a8f98);
	}
	/* phone: one at a time, swipe between them (the browser's own scroll, nothing animated by us); the
	   other card's edge peeks in, so she knows there's a second one without reading a word */
	.pp-phone .pp-head {
		justify-content: flex-start;
	}
	.pp-phone .pp-cols {
		display: flex;
		justify-content: flex-start; /* a centred row that overflows clips its start: the first card from its edge */
		gap: 0.6rem;
		overflow-x: auto;
		scroll-snap-type: x mandatory;
		overscroll-behavior-x: contain;
		scrollbar-width: none;
	}
	.pp-phone .pp-cols::before {
		display: none;
	}
	.pp-phone .pp-cols::-webkit-scrollbar {
		display: none;
	}
	.pp-phone .pp-col {
		flex: 0 0 calc(100% - 2.25rem);
		padding: 0.75rem 0.9rem 0.6rem;
		scroll-snap-align: center;
		scroll-snap-stop: always;
	}
	.pp-this {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.38rem 0.9rem;
		border-radius: 999px;
		border: 1px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.45);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.1);
		color: var(--pearl, inherit);
		font-size: 0.85rem;
		line-height: 1.2;
	}
	.pp-this:hover {
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian, #141018), var(--obsidian, #141018)) padding-box,
			var(--grad-hairline, oklch(0.711 0.214 var(--p-h-accent, 352) / 0.6)) border-box;
	}
	.pp-this:focus-visible,
	.pp-dot:focus-visible {
		outline: 2px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.7);
		outline-offset: 2px;
	}
</style>
