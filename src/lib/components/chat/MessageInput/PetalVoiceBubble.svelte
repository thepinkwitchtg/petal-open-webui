<script context="module" lang="ts">
	// every mounted bubble (a split view holds two): the hotkey belongs to the one whose composer holds
	// the focus, or to a lone bubble when nothing does
	const bubbles = new Set<HTMLElement>();
</script>

<script lang="ts">
	// 🎙️ the voice bubble (slices A19 · A19b): one button, on the left of the chat bar (Lily is
	// left-handed), when Settings → Interface → Voice control is "bubble". beside the bar where the screen
	// leaves room for it (no words under it), above the bar's left end on the phone. it plays the reply
	// most in view, becomes pause while she speaks, and fades away once that reply has been heard; it comes
	// back when a new reply arrives or you scroll to one you haven't heard. one reply per tap.
	// the hotkey (Settings → Shortcuts → "Her voice", Ctrl+Shift+Space until she binds another) does the
	// same in both modes, so the bubble stays mounted for it even when the speaker by her name is chosen.
	import { getContext, onDestroy, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	import { formatChord, keybindings, matchKeybinding, Shortcut } from '$lib/shortcuts';
	import { settings } from '$lib/stores';
	import {
		heardReplies,
		mostInView,
		voiceReplies,
		voiceTap,
		voiceUI
	} from '$lib/utils/petal-voice';

	const i18n = getContext<Writable<i18nType>>('i18n');

	let root: HTMLElement;
	let target: string | null = null; // the reply most in view, done
	let beside = false; // room on the bar's left: the bubble sits beside it, never over words
	let frame = 0;
	const look = () => {
		frame = 0;
		target = mostInView();
		const bar = root?.parentElement?.getBoundingClientRect();
		beside = !!bar && bar.left >= 56;
	};
	const lookSoon = () => {
		if (!frame) frame = requestAnimationFrame(look);
	};

	$: bubble = ($settings?.voiceControl ?? 'bubble') !== 'speaker';
	$: running = $voiceUI.state !== 'idle';
	$: paused = $voiceUI.state === 'paused';
	$: loading = $voiceUI.state === 'loading';
	// a reply came, went or finished arriving, one was heard, her voice changed: look again
	$: ($voiceReplies, $heardReplies, $voiceUI, lookSoon());
	$: shown = bubble && (running || (!!target && !$heardReplies.has(target)));
	$: hint = formatChord($keybindings[Shortcut.PETAL_VOICE] ?? '');
	$: label =
		running && !paused
			? $i18n.t('Pause her voice')
			: paused && (!target || target === $voiceUI.message_id || $heardReplies.has(target))
				? $i18n.t('Resume her voice')
				: $i18n.t('Her voice, for the reply in view');
	$: title = hint ? `${label} · ${hint}` : label;

	const onKey = (e: KeyboardEvent) => {
		if (e.defaultPrevented || e.repeat || $settings?.keyboardShortcuts === false) return;
		if (matchKeybinding(e) !== Shortcut.PETAL_VOICE) return;
		const t = e.target instanceof Node ? e.target : null;
		const box = root?.closest('[data-composer-id]') ?? root?.closest('form') ?? root?.parentElement;
		const inside = !!(box && t && (box.contains(t) || root.contains(t)));
		const loose = !t || t === document.body || t === document.documentElement;
		const lone = bubbles.size === 1 && !document.querySelector('.modal, [role="alertdialog"]');
		if (!inside && !(loose && lone)) return;
		e.preventDefault();
		e.stopPropagation();
		voiceTap(mostInView());
	};

	onMount(() => {
		bubbles.add(root);
		look();
		window.addEventListener('keydown', onKey, true);
		// the chat scrolls inside its own container: any scroll, caught on its way down, looks again
		window.addEventListener('scroll', lookSoon, { capture: true, passive: true });
		window.addEventListener('resize', lookSoon, { passive: true });
	});
	onDestroy(() => {
		bubbles.delete(root);
		if (frame) cancelAnimationFrame(frame);
		window.removeEventListener('keydown', onKey, true);
		window.removeEventListener('scroll', lookSoon, { capture: true } as EventListenerOptions);
		window.removeEventListener('resize', lookSoon);
	});
</script>

<div bind:this={root} class="pvb" class:pvb-beside={beside} class:pvb-away={!shown}>
	{#if bubble}
		<button
			type="button"
			class="pvb-main"
			aria-label={label}
			title={title}
			aria-pressed={running ? !paused : undefined}
			aria-hidden={!shown}
			tabindex={shown ? 0 : -1}
			on:click={() => voiceTap(target ?? mostInView())}
		>
			{#if loading}
				<svg viewBox="0 0 24 24" class="pvb-spin" aria-hidden="true"
					><circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="30 18" stroke-linecap="round" /></svg
				>
			{:else if running && !paused}
				<svg viewBox="0 0 24 24" aria-hidden="true"
					><rect x="7" y="6" width="3.4" height="12" rx="1.2" fill="currentColor" /><rect x="13.6" y="6" width="3.4" height="12" rx="1.2" fill="currentColor" /></svg
				>
			{:else}
				<svg viewBox="0 0 24 24" aria-hidden="true"
					><path d="M8.5 6.2v11.6c0 .8.9 1.3 1.6.9l9-5.8c.6-.4.6-1.3 0-1.7l-9-5.8c-.7-.5-1.6 0-1.6.8z" fill="currentColor" /></svg
				>
			{/if}
		</button>
	{/if}
</div>

<style>
	/* on the left of the chat bar · purple up, pink down (pink only ever in a gradient) */
	.pvb {
		position: absolute;
		left: 0.25rem;
		bottom: calc(100% + 0.5rem); /* the phone: above the bar's left end */
		z-index: 30;
		opacity: 1;
		transition: opacity 0.35s ease;
	}
	.pvb-beside {
		left: auto;
		right: calc(100% + 0.6rem); /* room to spare: beside the bar, level with its buttons */
		bottom: 0.3rem;
	}
	/* heard: it fades away (and leaves the tab order), back when there's something new to hear */
	.pvb-away {
		opacity: 0;
		visibility: hidden;
		transition:
			opacity 0.35s ease,
			visibility 0s linear 0.35s;
	}
	.pvb-main {
		display: grid;
		place-items: center;
		width: 2.5rem;
		height: 2.5rem;
		border-radius: 9999px;
		color: #fff;
		background: linear-gradient(180deg, #8f5bd1 0%, #b14fb0 48%, #d4408f 100%);
		box-shadow:
			0 2px 10px rgb(123 79 196 / 0.32),
			inset 0 1px 0 rgb(255 255 255 / 0.28);
		transition:
			transform 0.15s ease,
			box-shadow 0.15s ease;
	}
	.pvb-main svg {
		width: 1.35rem;
		height: 1.35rem;
	}
	.pvb-main:hover {
		box-shadow:
			0 3px 14px rgb(123 79 196 / 0.42),
			inset 0 1px 0 rgb(255 255 255 / 0.32);
	}
	.pvb-main:active {
		transform: scale(0.94);
	}
	.pvb-main:focus-visible {
		outline: 2px solid #8f5bd1;
		outline-offset: 2px;
	}
	.pvb-spin {
		animation: pvb-spin 0.9s linear infinite;
	}
	@keyframes pvb-spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.pvb,
		.pvb-away,
		.pvb-main {
			transition: none;
		}
		.pvb-spin {
			animation: none;
		}
	}
</style>
