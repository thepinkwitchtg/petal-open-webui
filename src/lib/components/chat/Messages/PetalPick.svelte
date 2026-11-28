<script lang="ts">
	// 🍒 the pick (slice A29) — two replies to one moment, built once and sent twice (utils/petal_pick.py).
	// desktop: side by side · phone: one at a time, swipe between them. one tap picks: the chosen reply becomes
	// the branch she's on, the other stays a sibling, never deleted, and the pair goes to the ledger through the
	// thumbs queue (👍🏻 / 👎🏻, both marked petal_pick). nothing to tap while they arrive; at rest nothing moves.
	// A30 · blind: nothing here says which one is pulled until her 💗 (a steered one can start a few seconds later,
	// which would tell them apart). A30d · twin streaming: both type at once (utils/petal-twin.ts): each side keeps
	// what arrives, the cards show only as much as both have received (nothing until both have begun), and once one is
	// done the other shows all it has received, then types on as its words arrive. "together" keeps the A30 hold
	// (still cards until both are written), "live" shows each as it comes (timing can tell). plain picks arrive the
	// same way. ✍🏻 A47 · the twin gate is the one hold: a step runs in the task her words arrive in, so the cards draw
	// them on the next frame (never a pace of its own, never a backlog typed out) · A35 · in a hidden tab, or with the
	// pick off her screen, nothing is drawn; the first look back shows where both are now · nothing runs at rest
	import { getContext, onDestroy, onMount, tick } from 'svelte';
	import { get, type Writable } from 'svelte/store';

	import { updateChatById } from '$lib/apis/chats';
	import { mobile, models, settings } from '$lib/stores';
	import {
		arrivalFor,
		notePicked,
		openPick,
		pickGlow,
		pickVerdicts,
		rulesOf,
		type OpenPick
	} from '$lib/utils/petal-pick';
	import { thumbVerdict } from '$lib/utils/petal-thumbs';
	import { lendPickFocus, pickFocus } from '$lib/utils/petal-voice';
	import { watchSight } from '$lib/utils/petal-sight';
	import { inertAt } from '$lib/utils/petal-screen'; // 🪟 A49 · a pick in a chat she can't see lends her eyes nothing
	import {
		reach,
		reachedOf,
		sideOf,
		twinHold,
		twinStats,
		twinStep,
		twinTarget,
		twinView,
		type Side
	} from '$lib/utils/petal-twin';

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
	$: arrive = arrivalFor(rulesOf($settings)); // A30d · twin · together · live, for every pick
	$: held = !pair.ready && arrive === 'together'; // A30 · both show together, once both are written

	// ── A30d · twin: both type at once, in step · ✍🏻 A47: as their words arrive, the twin gate the one hold ─────
	let view = history; // what the cards show: the replies cut at the shared count while they type
	let shown = -1; // the shared count, in units (-1: not started)
	let raf = 0;
	const isHidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden';
	let hidden = isHidden();
	let away = false; // A35 · the pick is off her screen: both hold where they are, and type on from there

	// where a card begins (shown again, or twin chosen mid-stream): both written → all of both at once · both still
	// typing → where both are now (never one side ahead) · one done → where it was, or where both are, whichever is
	// further (never from the beginning)
	const startAt = ([a, b]: Side[], was = 0) =>
		a.done && b.done
			? Math.max(a.units, b.units)
			: !a.done && !b.done
				? Math.min(a.units, b.units)
				: Math.max(was, Math.min(a.units, b.units));

	$: sides = [sideOf(history.messages[pair.a]), sideOf(history.messages[pair.b])];
	$: target = twinTarget(sides[0], sides[1]);
	$: if (shown < 0) shown = startAt(sides, reachedOf(pair.a) ?? 0);
	let chosen = ''; // her arrival when last seen: twin chosen mid-stream begins from where both are
	$: if (arrive !== chosen) {
		if (arrive === 'twin' && chosen) shown = Math.max(shown, startAt(sides));
		chosen = arrive;
	}
	$: complete = sides[0].done && sides[1].done && shown >= Math.max(sides[0].units, sides[1].units);
	$: typing = arrive === 'twin' && !complete;
	$: if (!typing) view = history;
	$: if (typing && view === history) view = twinView(history, pair.a, pair.b, shown); // never a frame of more
	// ✍🏻 A47 · every change of the history is stepped in the task it arrived in: the cards' frame draws it next
	$: if (typing) wake(history);
	$: Object.assign(twinStats, { arrive, typing, target, shown: Math.max(0, shown), hidden, away });
	$: if (complete) reach(pair.a, null);

	let queued = false;
	let holding: string | null = null; // A33 · a reply that just finished while the other types: drawn typing for a frame
	let scrolling = 0;
	/** a step, once this update has settled (a microtask: still before the frame that draws it) */
	const wake = (_changed?: unknown) => {
		if (queued || hidden || away) return;
		queued = true;
		queueMicrotask(step);
	};
	/** hidden or off her screen: nothing is drawn there · back: the first step shows where both are now (A47) */
	const pause = () => {
		if (raf) cancelAnimationFrame(raf);
		raf = 0;
		holding = null; // its frame is gone: it's whole when she's back
	};

	// the chat follows a growing card while she's at its bottom (its own setting), as it does while words arrive
	const following = (): HTMLElement | null => {
		if (!($settings?.scrollOnResponseGeneration ?? true)) return null;
		const box = scroller?.closest('#messages-container') as HTMLElement | null;
		return box && box.scrollHeight - box.scrollTop <= box.clientHeight + 50 ? box : null;
	};

	const step = async () => {
		queued = false;
		if (!typing || hidden || away) return;
		const box = following();
		const before = shown;
		shown = twinStep(shown, target); // A47 · straight to what may show: both while both type, all once free
		reach(pair.a, shown);
		// A33 · a reply finishing while the other types draws on the same frame as it, held as typing until the next
		const hold = holding ?? twinHold(history, pair.a, pair.b, shown, before);
		if (hold && !holding && typeof requestAnimationFrame !== 'undefined') {
			holding = hold;
			raf = requestAnimationFrame(() => {
				raf = 0;
				holding = null;
				wake(); // the next frame lets it be done
			});
		}
		view = twinView(history, pair.a, pair.b, shown, hold);
		twinStats.frames += 1; // steps (the name stays for the eyes and the tests): only when words arrive
		if (box && !scrolling && typeof requestAnimationFrame !== 'undefined') {
			const top = box.scrollTop; // where she was as they grew: if she scrolls up before the frame, she stays there
			await tick(); // the cards asked for their frame: ours comes after it, once they've grown
			scrolling = requestAnimationFrame(() => {
				scrolling = 0;
				if (box.scrollTop >= top - 1) box.scrollTo({ top: box.scrollHeight });
			});
		}
	};

	// hidden: nothing runs · back: both show where they are now, in step as ever (A47: no backlog typed out)
	const onVisibility = () => {
		hidden = isHidden();
		if (hidden) return pause();
		if (typing) wake();
	};

	// A35 · off her screen (the chat scrolled away from the pick while it types): nothing is drawn; back on it, both
	// show where they are now (A47) · watched only while they type (her sight, utils/petal-sight.ts)
	let root: HTMLElement;
	let unsee: (() => void) | null = null;
	const sighted = (on: boolean) => {
		away = !on;
		if (away) pause();
		else wake();
	};
	$: if (root && typing && !unsee) unsee = watchSight(root, sighted);
	$: if ((!typing || !root) && unsee) {
		unsee();
		unsee = null;
		away = false;
	}

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
		notePicked(history, chosen); // her console: each side's pull, now that she chose (an arm)
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

	// A31 · the floating ▶︎ plays the reply her eyes are on here: the one she swiped to (phone), the one her
	// pointer last rested on (desktop: a pointer passing over the other on its way to the button changes
	// nothing). after her 💗 the pick closes, and the chosen reply is simply the one in view
	const REST_MS = 450;
	let resting: ReturnType<typeof setTimeout> | null = null;
	let over: number | null = null; // the card under her pointer right now (desktop)
	const focus = (slot: number) => {
		const id = ids?.[slot];
		const f = get(pickFocus);
		if (root && inertAt(root)) return; // 🪟 A49 · its chat is not the screen she sees
		if (id && (f?.id !== id || f.ids[0] !== ids[0])) pickFocus.set({ ids: [...ids], id });
	};
	const rest = (e: PointerEvent, slot: number | null) => {
		if (resting) clearTimeout(resting);
		resting = null;
		over = e.pointerType === 'touch' ? null : slot;
		if (slot !== null && e.pointerType !== 'touch') resting = setTimeout(() => focus(slot), REST_MS);
	};
	$: if ($mobile) focus(seen);

	// A33 · her focus, read live at the moment of a tap (the store may still be a step behind): the phone's
	// card centred in the scroller now (a swipe still settling counts where it lands), else the card under
	// her pointer now (a key pressed while she points), else the one her pointer last rested on
	const focusNow = () => {
		if (!ids?.length || (root && inertAt(root))) return null; // 🪟 A49 · only a pick she can see
		let slot: number | null = null;
		if ($mobile && scroller) {
			const box = scroller.getBoundingClientRect();
			const middle = box.left + box.width / 2;
			let off = Infinity;
			cols.forEach((c, i) => {
				if (!c) return;
				const r = c.getBoundingClientRect();
				const d = Math.abs(r.left + r.width / 2 - middle);
				if (d < off) [slot, off] = [i, d];
			});
		} else if (over !== null) slot = over;
		if (slot === null) {
			const f = get(pickFocus);
			return f && f.ids.includes(ids[0]) ? f : null;
		}
		return ids[slot] ? { ids: [...ids], id: ids[slot] } : null;
	};
	let unlend: (() => void) | null = null;

	onMount(() => {
		watch();
		focus(seen);
		unlend = lendPickFocus(focusNow);
		document.addEventListener('visibilitychange', onVisibility);
	});
	onDestroy(() => {
		unlend?.();
		unsee?.();
		io?.disconnect();
		if (resting) clearTimeout(resting);
		if (get(pickFocus)?.ids.includes(pair.a)) pickFocus.set(null);
		if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility);
		if (raf) cancelAnimationFrame(raf);
		if (scrolling) cancelAnimationFrame(scrolling);
		raf = scrolling = 0;
	});
</script>

<div
	bind:this={root}
	class="petal-pick"
	class:pp-phone={$mobile}
	class:pp-wide={$settings?.widescreenMode ?? false}
	data-petal-pick={pair.a}
	data-pick-arrive={arrive}
	data-pick-typing={typing ? '' : undefined}
>
	<div class="pp-head">
		<span aria-hidden="true">🍒</span>
		<span>
			{#if typing}
				{$i18n.t('two replies, typing together')}
			{:else if !pair.ready}
				{held ? $i18n.t('two replies on their way · they show together') : $i18n.t('two replies on their way')}
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
				on:pointerenter={(e) => rest(e, slot)}
				on:pointerleave={(e) => rest(e, null)}
			>
				{#if held}
					<!-- both are still being written: the same still card on both sides, nothing that moves -->
					<div class="pp-held" data-pick-held={slot} aria-hidden="true">
						<span class="pp-bar" style="width: 92%"></span>
						<span class="pp-bar" style="width: 78%"></span>
						<span class="pp-bar" style="width: 85%"></span>
						<span class="pp-bar" style="width: 46%"></span>
					</div>
				{:else}
					<ResponseMessage
						{chatId}
						history={view}
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
				{/if}
				<div class="pp-foot">
					{#if pair.ready && !typing}
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
	/* A30 · held: still bars in the panel's own tones, the same on both sides (no shimmer: nothing redraws) */
	.pp-held {
		display: flex;
		flex-direction: column;
		gap: 0.7rem;
		padding: 0.6rem 0 0.4rem;
	}
	.pp-bar {
		display: block;
		height: 0.6rem;
		border-radius: 999px;
		background: var(--edge-soft, oklch(0.6 0 0 / 0.16));
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
