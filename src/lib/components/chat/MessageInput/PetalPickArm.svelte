<script context="module" lang="ts">
	// every mounted one (a split view holds two): a hotkey pressed outside them all belongs to a lone one only
	const arms = new Set<HTMLElement>();
</script>

<script lang="ts">
	// 🍒 "next reply" (slice A29 · A30b) — beside send, always: one tap (or the hotkey: Settings → Shortcuts →
	// "Ask for a pick on my next send", Ctrl+Alt+P until she binds another, or a long press on the mode chip)
	// arms a pick for her next reply only: it is sent twice and shows both replies, then the cherry turns itself
	// off. tap it again to take the ask back. Petal can arm it too (A30b · petal_pick.should_offer, after a turn
	// of hers): the same cherry, with Petal's why in its title. still at rest, a size that never changes.
	import { getContext, onDestroy, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';

	import { formatChord, keybindings, matchKeybinding, Shortcut } from '$lib/shortcuts';
	import { settings } from '$lib/stores';
	import { askPick, pickAsked, pickAskWhy } from '$lib/utils/petal-pick';

	const i18n: Writable<any> = getContext('i18n');

	let root: HTMLElement;

	$: hint = formatChord($keybindings[Shortcut.ASK_PICK] ?? '');
	$: key = hint ? ` (${hint})` : '';
	$: title = !$pickAsked
		? `${$i18n.t('Next reply: two replies to pick from')}${key}`
		: $pickAskWhy
			? `${$i18n.t('Petal asked for a pick')}: ${$pickAskWhy} · ${$i18n.t('tap to take it back')}${key}`
			: `${$i18n.t('Your next reply is a pick')} · ${$i18n.t('tap to take it back')}${key}`;

	const onKey = (e: KeyboardEvent) => {
		if (e.defaultPrevented || e.repeat || $settings?.keyboardShortcuts === false) return;
		if (matchKeybinding(e) !== Shortcut.ASK_PICK) return;
		const t = e.target instanceof Node ? e.target : null;
		const box = root?.closest('[data-composer-id]') ?? root?.closest('form');
		const inside = !!(box && t && box.contains(t));
		const loose = !t || t === document.body || t === document.documentElement;
		const lone = arms.size === 1 && !document.querySelector('.modal, [role="alertdialog"]');
		if (!inside && !(loose && lone)) return;
		e.preventDefault();
		e.stopPropagation();
		askPick();
	};

	onMount(() => {
		arms.add(root);
		window.addEventListener('keydown', onKey, true);
	});
	onDestroy(() => {
		arms.delete(root);
		window.removeEventListener('keydown', onKey, true);
	});
</script>

<span bind:this={root} class="ppa-root">
	<button
		type="button"
		class="ppa"
		class:ppa-on={$pickAsked}
		class:ppa-petal={$pickAsked && !!$pickAskWhy}
		data-petal-pick-next
		data-petal-pick-asked={$pickAsked ? '' : undefined}
		data-petal-pick-by={$pickAsked ? ($pickAskWhy ? 'petal' : 'her') : undefined}
		{title}
		aria-label={title}
		aria-pressed={$pickAsked}
		on:click={() => askPick()}
	>
		<span class="ppa-cherry" aria-hidden="true">🍒</span>
	</button>
</span>

<style>
	.ppa-root {
		display: contents;
	}
	/* one size in every state: arming it never moves anything beside it */
	.ppa {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		align-self: center;
		flex-shrink: 0;
		height: 1.875rem;
		width: 1.875rem;
		padding: 0;
		margin-right: 0.15rem;
		border-radius: 999px;
		border: 1px solid transparent;
		background: transparent;
		font-size: 0.85rem;
		line-height: 1;
	}
	/* at rest: a quiet cherry, there when she wants it */
	.ppa .ppa-cherry {
		opacity: 0.45;
		filter: saturate(0.55);
	}
	.ppa:hover .ppa-cherry,
	.ppa:focus-visible .ppa-cherry,
	.ppa-on .ppa-cherry {
		opacity: 1;
		filter: none;
	}
	.ppa:hover {
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.07);
	}
	/* armed: her next reply is a pick */
	.ppa-on,
	.ppa-on:hover {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.45);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.12);
	}
	/* armed by Petal: the same, its edge in iris (candy's cooler shadow) */
	.ppa-petal,
	.ppa-petal:hover {
		border-color: oklch(0.622 0.186 calc(var(--p-h-accent, 352) - 36) / 0.6);
	}
	.ppa:focus-visible {
		outline: 2px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.7);
		outline-offset: 2px;
	}
</style>
