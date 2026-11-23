<script lang="ts">
	// 🌊 her stream, on (slice A41): beside the heart while this chat is open to it · one tap turns it off (Esc too,
	// when nothing else is open). it shows only while on, so the bar is as it was the rest of the time. while she
	// writes an utterance its ring warms (a still border, never a pulse: nothing moves at rest)
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';

	import { loungeOn, loungeTurnOff, loungeWriting } from '$lib/utils/petal-lounge';

	export let chatId: string | null = null;

	const i18n: Writable<any> = getContext('i18n');

	$: st = chatId ? ($loungeOn[chatId] ?? null) : null;
	$: writing = chatId ? !!$loungeWriting[chatId] : false;
	$: label = st
		? `${$i18n.t('her stream')} · ${`${st.emoji ?? ''} ${st.title ?? st.profile ?? ''}`.trim()} · ${$i18n.t('tap to turn it off')}`
		: '';
</script>

{#if st?.on}
	<button
		type="button"
		class="plc"
		class:plc-writing={writing}
		data-petal-lounge-chip
		data-petal-lounge-writing={writing ? '' : undefined}
		title={label}
		aria-label={label}
		on:click|preventDefault={() => chatId && loungeTurnOff(chatId)}
	>
		<span class="plc-glyph" aria-hidden="true">🌊</span>
	</button>
{/if}

<style>
	/* the heart's size and manners, so the bar never moves when it comes or goes beside it */
	.plc {
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
		border: 1px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.28);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.06);
		touch-action: manipulation;
		transition:
			border-color 140ms,
			background-color 140ms;
	}
	.plc:hover {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.5);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.12);
	}
	.plc:focus-visible {
		outline: 2px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.7);
		outline-offset: 2px;
	}
	.plc-writing {
		border-color: oklch(0.78 0.16 var(--p-h-accent, 352) / 0.85);
	}
	.plc-glyph {
		font-family: var(--font-emoji, 'SamsungColorEmoji'), sans-serif;
		font-size: 0.92rem;
		line-height: 1;
	}
</style>
