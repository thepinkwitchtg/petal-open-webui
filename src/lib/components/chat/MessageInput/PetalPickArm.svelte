<script context="module" lang="ts">
	// every mounted one (a split view holds two): a hotkey pressed outside them all belongs to a lone one only
	const arms = new Set<HTMLElement>();
</script>

<script lang="ts">
	// 🍒 her ask for a pick (slice A29) — beside send: the hotkey (Settings → Shortcuts → "Ask for a pick on my
	// next send", Ctrl+Alt+P until she binds another) or a long press on the mode chip asks for one; the next
	// send is then sent twice and shows both replies. while asked, a small cherry waits here (tap it to take
	// the ask back); otherwise nothing is here at all. it never moves.
	import { getContext, onDestroy, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';

	import { formatChord, keybindings, matchKeybinding, Shortcut } from '$lib/shortcuts';
	import { settings } from '$lib/stores';
	import { askPick, pickAsked } from '$lib/utils/petal-pick';

	const i18n: Writable<any> = getContext('i18n');

	let root: HTMLElement;

	$: hint = formatChord($keybindings[Shortcut.ASK_PICK] ?? '');
	$: title = `${$i18n.t('A pick on your next send')} · ${$i18n.t('tap to take it back')}${hint ? ` (${hint})` : ''}`;

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
	{#if $pickAsked}
		<button
			type="button"
			class="ppa"
			data-petal-pick-asked
			{title}
			aria-label={title}
			aria-pressed="true"
			on:click={() => askPick(false)}
		>
			<span aria-hidden="true">🍒</span>
		</button>
	{/if}
</span>

<style>
	.ppa-root {
		display: contents;
	}
	.ppa {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		align-self: center;
		flex-shrink: 0;
		height: 1.875rem;
		min-width: 1.875rem;
		padding: 0 0.4rem;
		margin-right: 0.15rem;
		border-radius: 999px;
		border: 1px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.45);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.12);
		font-size: 0.85rem;
		line-height: 1;
	}
	.ppa:focus-visible {
		outline: 2px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.7);
		outline-offset: 2px;
	}
</style>
