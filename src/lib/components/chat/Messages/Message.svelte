<script lang="ts">
	import { toast } from 'svelte-sonner';

	import { tick, getContext, onMount, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	import { settings } from '$lib/stores';
	import { copyToClipboard } from '$lib/utils';

	import MultiResponseMessages from './MultiResponseMessages.svelte';
	import PetalPick from './PetalPick.svelte'; // 🍒 A29 · two replies, one tap
	import { openPick, pickGlow } from '$lib/utils/petal-pick';
	import ResponseMessage from './ResponseMessage.svelte';
	import UserMessage from './UserMessage.svelte';

	export let chatId;
	export let selectedModels: string[] = [];
	export let idx = 0;

	export let history: any; // typed (A29): the pick reads and binds it
	export let messageId;

	export let user;

	export let setInputText: Function = () => {};
	export let gotoMessage;
	export let showPreviousMessage;
	export let showNextMessage;
	export let updateChat;

	export let editMessage;
	export let saveMessage;
	export let deleteMessage;
	export let rateMessage;
	export let actionMessage;
	export let submitMessage;

	export let regenerateResponse;
	export let continueResponse;
	export let mergeResponses;

	export let addMessages;
	export let onToolCallResolved: Function = () => {};
	export let forkHandler: Function | null = null;
	export let triggerScroll;
	export let readOnly = false;
	export let writeAccess = false;
	export let allowDelete = true;
	export let allowToolApproval: boolean = false;
	export let compactPreview = false;
	export let editCodeBlock = true;
	export let topPadding = false;
	export let onInsertToNote: ((content: string) => void) | null = null;
	export let onOpenArtifacts: ((code?: string) => void) | null = null;

	// 🍒 A29 · a pick still waiting on this turn shows both replies (never in previews or shared views),
	// across the whole chat area: two real columns (A29b)
	$: pick = compactPreview || readOnly ? null : openPick(history, messageId);
	let glowFallback: ReturnType<typeof setTimeout> | null = null;
	$: if ($pickGlow === messageId) {
		clearTimeout(glowFallback ?? undefined);
		glowFallback = setTimeout(() => $pickGlow === messageId && pickGlow.set(null), 4000);
	}
	const glowEnded = (e: AnimationEvent) => {
		if ($pickGlow === messageId && e.animationName.includes('petal-picked')) pickGlow.set(null);
	};

	// Keep the latest turn's real height when assigning a chat ID remounts the message list.
	$: isCurrentTurn =
		messageId === history.currentId || messageId === history.messages[history.currentId]?.parentId;

	// WebKit's content-visibility implementation has paint bugs that leave
	// on-screen messages blank (#26712), so skip virtualization there
	// iOS WebViews and home screen apps carry no Safari token, hence the vendor check
	const isWebKit =
		navigator.vendor === 'Apple Computer, Inc.' ||
		/^((?!chrome|android).)*safari/i.test(navigator.userAgent);

	// Firefox scroll anchoring ignores content-visibility height changes, so scrolling up jumps
	const isFirefox = /firefox/i.test(navigator.userAgent);
</script>

<div
	role="listitem"
	class="flex flex-col justify-between px-3.5 mb-3 w-full {($settings?.widescreenMode ?? null) || pick
		? 'max-w-full'
		: 'max-w-[58rem]'} mx-auto rounded-lg group message-listitem"
	class:message-virtualized={!isWebKit && !isFirefox && !isCurrentTurn}
	class:petal-picked-glow={$pickGlow === messageId}
	on:animationend={glowEnded}
>
	{#if history.messages[messageId]}
		{#if history.messages[messageId].role === 'user'}
			<UserMessage
				{user}
				{chatId}
				{history}
				{messageId}
				isFirstMessage={idx === 0}
				siblings={history.messages[messageId].parentId !== null
					? (history.messages[history.messages[messageId].parentId]?.childrenIds ?? [])
					: (Object.values(history.messages)
							.filter((message) => message.parentId === null)
							.map((message) => message.id) ?? [])}
				{gotoMessage}
				{showPreviousMessage}
				{showNextMessage}
				{editMessage}
				{deleteMessage}
				{allowDelete}
				{readOnly}
				{writeAccess}
				{compactPreview}
				{editCodeBlock}
				{topPadding}
			/>
		{:else if pick}
			<PetalPick
				{chatId}
				bind:history
				pair={pick}
				{selectedModels}
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
			/>
		{:else if compactPreview || (history.messages[history.messages[messageId].parentId]?.models?.length ?? 1) === 1}
			<ResponseMessage
				{chatId}
				{history}
				{messageId}
				{selectedModels}
				isLastMessage={messageId === history.currentId}
				siblings={history.messages[history.messages[messageId].parentId]?.childrenIds ?? []}
				{setInputText}
				{gotoMessage}
				{showPreviousMessage}
				{showNextMessage}
				{updateChat}
				{editMessage}
				{saveMessage}
				{rateMessage}
				{actionMessage}
				{submitMessage}
				{deleteMessage}
				{allowDelete}
				{allowToolApproval}
				{continueResponse}
				{regenerateResponse}
				{addMessages}
				{onToolCallResolved}
				{forkHandler}
				{readOnly}
				{compactPreview}
				{editCodeBlock}
				{topPadding}
				{onInsertToNote}
				{onOpenArtifacts}
				{writeAccess}
			/>
		{:else}
			{#key messageId}
				<MultiResponseMessages
					bind:history
					{chatId}
					{messageId}
					{selectedModels}
					isLastMessage={messageId === history?.currentId}
					{setInputText}
					{updateChat}
					{editMessage}
					{saveMessage}
					{rateMessage}
					{actionMessage}
					{submitMessage}
					{deleteMessage}
					{allowDelete}
					{allowToolApproval}
					{continueResponse}
					{regenerateResponse}
					{mergeResponses}
					{triggerScroll}
					{addMessages}
					{onToolCallResolved}
					{forkHandler}
					{readOnly}
					{compactPreview}
					{editCodeBlock}
					{topPadding}
					{onInsertToNote}
					{onOpenArtifacts}
					{writeAccess}
				/>
			{/key}
		{/if}
	{/if}
</div>

<style>
	/* Browser-native virtualization: skip rendering of off-screen messages
	   without destroying their component trees. Replaces the JS-based
	   culling that caused catastrophic mount/destroy thrashing. */
	.message-virtualized {
		content-visibility: auto;
		contain-intrinsic-size: auto 150px;
	}

	/* 🍒 A29 · the chosen reply glows once, quietly: one opacity fade on a still ring (compositor only),
	   paused while the page is hidden, gone when it ends */
	.petal-picked-glow {
		position: relative;
	}
	.petal-picked-glow::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: 1rem;
		box-shadow:
			0 0 0 1px oklch(0.711 0.214 var(--p-h-accent, 352) / 0.45),
			0 0 24px oklch(0.711 0.214 var(--p-h-accent, 352) / 0.3);
		opacity: 0;
		pointer-events: none;
		animation: petal-picked 1.6s ease-out 1;
	}
	:global(html[data-petal-hidden]) .petal-picked-glow::after {
		animation-play-state: paused;
	}
	@keyframes petal-picked {
		22% {
			opacity: 1;
		}
		100% {
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.petal-picked-glow::after {
			animation-duration: 1ms;
		}
	}
</style>
