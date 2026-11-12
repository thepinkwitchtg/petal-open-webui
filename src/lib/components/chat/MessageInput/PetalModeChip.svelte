<script context="module" lang="ts">
	// every mounted chip (a split view holds two): a hotkey pressed outside them all belongs to a
	// lone chip only, never to whichever happened to listen first
	const chips = new Set<HTMLElement>();
</script>

<script lang="ts">
	// 🌀 the mode chip (slice A15) — beside send: which of the forge's modes dresses her next message.
	// one tap steps to the next one, and so does the hotkey (Settings → Shortcuts → "Cycle the mode",
	// Ctrl+Space until she binds another). the names, emoji and order are the forge's own: without
	// them the chip isn't here at all. sticky per chat, kept in this browser only. it turns once when
	// the mode changes, then rests: no timer, no loop.
	import { onDestroy, onMount } from 'svelte';

	import { formatChord, keybindings, matchKeybinding, Shortcut } from '$lib/shortcuts';
	import { settings } from '$lib/stores';
	import { loadModes, modeOf, modes, modeTick, stepMode } from '$lib/utils/petal-mode';

	export let chatId: string | null = null;

	let root: HTMLElement;
	let turned = 0; // her steps: the turn plays once per step, never on load or when the chat changes

	$: current = $modeTick >= 0 ? modeOf($modes, chatId) : null; // the tick: another chip (or the hotkey) stepped it
	$: hint = formatChord($keybindings[Shortcut.CYCLE_MODE] ?? '');
	$: label = current ? [current.emoji, current.name].filter(Boolean).join(' ') : '';
	$: title = current ? `${label} · tap${hint ? ` or ${hint}` : ''} for the next mode` : '';

	const step = () => {
		if (stepMode(chatId)) turned += 1;
	};

	// the hotkey answers inside this input's own box (its composer, the way dictation's does), or
	// anywhere when nothing holds the focus and this is the only chip on the page · a field elsewhere
	// (a shortcut being recorded, a modal) is left alone, and so is everything when shortcuts are off
	const onKey = (e: KeyboardEvent) => {
		if (e.defaultPrevented || e.repeat || !current || $settings?.keyboardShortcuts === false)
			return;
		if (matchKeybinding(e) !== Shortcut.CYCLE_MODE) return;
		const t = e.target instanceof Node ? e.target : null;
		const box = root?.closest('[data-composer-id]') ?? root?.closest('form');
		const inside = !!(box && t && box.contains(t));
		const loose = !t || t === document.body || t === document.documentElement;
		const lone = chips.size === 1 && !document.querySelector('.modal, [role="alertdialog"]');
		if (!inside && !(loose && lone)) return;
		e.preventDefault();
		e.stopPropagation();
		step();
	};
	const onShow = () => document.visibilityState === 'visible' && loadModes();

	onMount(() => {
		chips.add(root);
		loadModes();
		window.addEventListener('keydown', onKey, true);
		document.addEventListener('visibilitychange', onShow);
	});
	onDestroy(() => {
		chips.delete(root);
		window.removeEventListener('keydown', onKey, true);
		document.removeEventListener('visibilitychange', onShow);
	});
</script>

<span bind:this={root} class="pmc-root">
	{#if current}
		<button type="button" class="pmc" {title} aria-label={title} on:click={step}>
			{#key turned}
				<span class="pmc-face" class:pmc-turn={turned > 0} class:with-emoji={!!current.emoji}>
					{#if current.emoji}<span class="pmc-emoji" aria-hidden="true">{current.emoji}</span>{/if}
					<span class="pmc-name">{current.name}</span>
				</span>
			{/key}
		</button>
	{/if}
</span>

<style>
	.pmc-root {
		display: contents;
	}
	.pmc {
		display: inline-flex;
		align-items: center;
		align-self: center;
		flex-shrink: 0;
		height: 1.875rem;
		padding: 0 0.6rem;
		margin-right: 0.15rem;
		border-radius: 999px;
		border: 1px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.3);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.08);
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
		line-height: 1;
		white-space: nowrap;
		transition:
			border-color 140ms,
			background-color 140ms;
	}
	.pmc:hover {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.55);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.14);
	}
	.pmc:focus-visible {
		outline: 2px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.7);
		outline-offset: 2px;
	}
	.pmc-face {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
	}
	.pmc-emoji {
		font-size: 0.95rem;
	}
	/* the one movement: a step settles in once, then everything rests */
	.pmc-turn {
		animation: pmc-turn 320ms cubic-bezier(0.2, 0.8, 0.2, 1) 1;
	}
	@keyframes pmc-turn {
		from {
			opacity: 0.3;
			transform: translateY(3px) scale(0.9);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.pmc-turn {
			animation: none;
		}
	}
	/* on the phone her emoji is enough (a mode without one keeps its name) */
	@media (max-width: 640px) {
		.pmc {
			padding: 0 0.5rem;
		}
		.pmc-face.with-emoji .pmc-name {
			display: none;
		}
	}
</style>
