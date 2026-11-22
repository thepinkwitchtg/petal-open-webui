<script lang="ts">
	// 🎧 by the mic (slice A37): her voice's two small hands.
	//  · 🎧 on the phone (when Settings → 🌸 Petal → Voice isn't off): one tap says "earphones in", so replies may
	//    speak by themselves here; remembered on this device. when she follows the rig's audio route and it knows,
	//    the route decides and the chip shows it (her tap still counts whenever the rig doesn't know)
	//  · ⏹ on every device, only while her voice speaks or waits paused: one tap stops her (pause is the bubble)
	// nothing here moves at rest: colours change on a tap, never on a timer
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';

	import { audioRoute, autoMode, earphones, followRoute, isPhone, setEarphones } from '$lib/utils/petal-autoplay';
	import { stopAllVoice, voiceUI } from '$lib/utils/petal-voice';

	const i18n: Writable<any> = getContext('i18n');
	const phone = isPhone();

	$: routed = $followRoute && ($audioRoute === 'earphones' || $audioRoute === 'speaker');
	$: inEars = routed ? $audioRoute === 'earphones' : $earphones;
	$: earTitle = routed
		? inEars
			? $i18n.t('Earphones in (the rig says so): replies may speak by themselves')
			: $i18n.t('Speaker (the rig says so): replies wait for your tap')
		: inEars
			? $i18n.t('Earphones in: replies may speak by themselves · tap when they’re out')
			: $i18n.t('No earphones: replies wait for your tap · tap when they’re in');
	$: speaking = $voiceUI.state !== 'idle';
</script>

{#if phone && $autoMode !== 'off'}
	<button
		type="button"
		class="pec"
		class:pec-on={inEars}
		class:pec-routed={routed}
		data-petal-ear={inEars ? 'in' : 'out'}
		title={earTitle}
		aria-label={earTitle}
		aria-pressed={inEars}
		on:click={() => setEarphones(!$earphones)}
	>
		<span class="pec-glyph" aria-hidden="true">🎧</span>
	</button>
{/if}
{#if speaking}
	<button
		type="button"
		class="pec pec-stop"
		data-petal-voice-stop
		title={$i18n.t('Stop her voice')}
		aria-label={$i18n.t('Stop her voice')}
		on:click={() => stopAllVoice()}
	>
		<svg viewBox="0 0 24 24" class="pec-square" aria-hidden="true">
			<rect x="6.5" y="6.5" width="11" height="11" rx="2.5" />
		</svg>
	</button>
{/if}

<style>
	/* the cherry's size and manners (PetalPickArm): arming or stopping never moves anything beside it */
	.pec {
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
		transition:
			background-color 120ms,
			border-color 120ms;
	}
	.pec .pec-glyph {
		opacity: 0.45;
		filter: saturate(0.55);
	}
	.pec:hover .pec-glyph,
	.pec:focus-visible .pec-glyph,
	.pec-on .pec-glyph {
		opacity: 1;
		filter: none;
	}
	.pec:hover {
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.07);
	}
	.pec-on,
	.pec-on:hover {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.45);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.12);
	}
	/* the rig decides: its edge in iris, like Petal's own asks */
	.pec-routed,
	.pec-routed:hover {
		border-style: dashed;
	}
	.pec-stop .pec-square {
		width: 0.95rem;
		height: 0.95rem;
		fill: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.85);
	}
	.pec-stop {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.3);
	}
	.pec:focus-visible {
		outline: 2px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.7);
		outline-offset: 2px;
	}
</style>
