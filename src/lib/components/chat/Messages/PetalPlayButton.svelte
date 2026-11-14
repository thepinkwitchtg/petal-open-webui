<script lang="ts">
	// 🔈 the speaker by her name (slices A19 · A19b), when Settings → Interface → Voice control is
	// "speaker by her name": OWUI's own read-aloud symbol, beside Petal's name. a tap plays this reply from
	// its first sentence; while she reads it, a tap pauses her and the next one resumes. one reply per tap.
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { playReply, togglePause, voiceUI } from '$lib/utils/petal-voice';

	const i18n = getContext<Writable<i18nType>>('i18n');

	export let id: string;

	$: mine = $voiceUI.message_id === id && $voiceUI.state !== 'idle' && $voiceUI.kind !== 'line';
	$: playing = mine && $voiceUI.state === 'playing';
	$: loading = mine && $voiceUI.state === 'loading';
	$: label = !mine
		? $i18n.t('Read Aloud')
		: playing || loading
			? $i18n.t('Pause her voice')
			: $i18n.t('Resume her voice');
</script>

<button
	type="button"
	class="pps"
	class:pps-on={mine}
	aria-label={label}
	title={label}
	aria-pressed={mine ? playing : undefined}
	on:click|stopPropagation={() => (mine ? togglePause() : playReply(id))}
>
	{#if loading}
		<!-- OWUI's own: the speaker's spinner while her voice gets ready -->
		<svg class="pps-spin" aria-hidden="true" stroke-width="1.5" viewBox="0 0 24 24" fill="none">
			<path
				d="M21.8883 13.5C21.1645 18.3113 17.013 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2C16.1006 2 19.6248 4.46819 21.1679 8"
				stroke="currentColor"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
			<path
				d="M17 8H21.4C21.7314 8 22 7.73137 22 7.4V3"
				stroke="currentColor"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
		</svg>
	{:else if playing}
		<!-- the speaker, with a pause where its waves were: a tap pauses her -->
		<svg aria-hidden="true" viewBox="0 0 24 24" stroke-width="1.5" fill="none">
			<path
				d="M1 13.8571V10.1429C1 9.03829 1.89543 8.14286 3 8.14286H5.9C6.09569 8.14286 6.28708 8.08544 6.45046 7.97772L12.4495 4.02228C13.1144 3.5839 14 4.06075 14 4.85714V19.1429C14 19.9392 13.1144 20.4161 12.4495 19.9777L6.45046 16.0223C6.28708 15.9146 6.09569 15.8571 5.9 15.8571H3C1.89543 15.8571 1 14.9617 1 13.8571Z"
				stroke="currentColor"
			/>
			<path d="M18 8.5V15.5M22 8.5V15.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
		</svg>
	{:else}
		<!-- OWUI's own read-aloud speaker (paused: the same, lit) -->
		<svg aria-hidden="true" viewBox="0 0 24 24" stroke-width="1.5" fill="none">
			<path
				d="M1 13.8571V10.1429C1 9.03829 1.89543 8.14286 3 8.14286H5.9C6.09569 8.14286 6.28708 8.08544 6.45046 7.97772L12.4495 4.02228C13.1144 3.5839 14 4.06075 14 4.85714V19.1429C14 19.9392 13.1144 20.4161 12.4495 19.9777L6.45046 16.0223C6.28708 15.9146 6.09569 15.8571 5.9 15.8571H3C1.89543 15.8571 1 14.9617 1 13.8571Z"
				stroke="currentColor"
			/>
			<path
				d="M17.5 7.5C17.5 7.5 19 9 19 11.5C19 14 17.5 15.5 17.5 15.5"
				stroke="currentColor"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
			<path
				d="M20.5 4.5C20.5 4.5 23 7 23 11.5C23 16 20.5 18.5 20.5 18.5"
				stroke="currentColor"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
		</svg>
	{/if}
</button>

<style>
	/* sized and coloured like OWUI's own action buttons, centred on the name's line · on a touch screen
	   the tap target grows, the visible chip stays the size of OWUI's own */
	.pps {
		position: relative;
		display: inline-grid;
		place-items: center;
		flex-shrink: 0;
		width: 1.75rem;
		height: 1.75rem;
		margin-block: -0.375rem; /* the row keeps the name's own height */
		color: rgb(107 114 128);
		transition: color 0.15s ease;
	}
	.pps::before {
		content: '';
		position: absolute;
		inset: 50% auto auto 50%;
		width: 1.75rem;
		height: 1.75rem;
		translate: -50% -50%;
		border-radius: 0.5rem;
		background: transparent;
		transition: background-color 0.15s ease;
	}
	.pps svg {
		position: relative;
		width: 1rem;
		height: 1rem;
	}
	.pps:hover {
		color: rgb(75 85 99);
	}
	.pps:hover::before {
		background: rgb(0 0 0 / 0.05);
	}
	/* while she reads this reply: lit in her colour */
	.pps-on {
		color: #9a4fc0;
	}
	.pps-on::before {
		background: rgb(143 91 209 / 0.1);
	}
	:global(.dark) .pps {
		color: rgb(156 163 175);
	}
	:global(.dark) .pps:hover {
		color: rgb(209 213 219);
	}
	:global(.dark) .pps:hover::before {
		background: rgb(255 255 255 / 0.05);
	}
	:global(.dark) .pps-on {
		color: #e2a6f2;
	}
	:global(.dark) .pps-on::before {
		background: rgb(192 125 224 / 0.16);
	}
	.pps:focus-visible {
		outline: none;
	}
	.pps:focus-visible::before {
		outline: 2px solid #8f5bd1;
		outline-offset: 1px;
	}
	.pps-spin {
		animation: pps-spin 1s linear infinite;
	}
	@keyframes pps-spin {
		to {
			transform: rotate(360deg);
		}
	}
	/* a finger needs more room than the glyph: the tap target grows on touch screens, the row doesn't */
	@media (pointer: coarse) {
		.pps {
			width: 2.25rem;
			height: 2.25rem;
			margin-block: -0.625rem;
			margin-inline: -0.25rem;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.pps-spin {
			animation: none;
		}
	}
</style>
