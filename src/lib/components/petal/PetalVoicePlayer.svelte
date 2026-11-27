<script context="module" lang="ts">
	// one diary player sounds at a time: a tap on another lets the first one rest
	const players = new Set<HTMLAudioElement>();
</script>

<script lang="ts">
	// 🎧 a small player for her voice's diary (slice A48): her clip, the gate's take, a single take. a round play
	// button, a line she can tap to move along, the time. it reads its length when it can (preload metadata), moves
	// only while it plays (the audio's own timeupdate, never a frame loop), and rests when another one starts.
	import { onDestroy } from 'svelte';
	import { clock } from '$lib/utils/petal-voice-diary';

	export let src: string;
	export let label = '';
	export let sub = '';
	export let compact = false;

	let el: HTMLAudioElement;
	let playing = false;
	let t = 0;
	let len = 0;
	let failed = false;
	let bar: HTMLElement;

	$: if (el) players.add(el);
	onDestroy(() => {
		if (el) {
			el.pause();
			players.delete(el);
		}
	});

	function toggle() {
		if (!el) return;
		if (el.paused) {
			for (const p of players) if (p !== el && !p.paused) p.pause();
			el.play().catch(() => (failed = true));
		} else el.pause();
	}
	function seek(e: PointerEvent) {
		if (!el || !len || !bar) return;
		const r = bar.getBoundingClientRect();
		const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
		el.currentTime = f * len;
		t = el.currentTime;
	}
	function key(e: KeyboardEvent) {
		if (!el || !len) return;
		if (e.key === 'ArrowRight') el.currentTime = Math.min(len, el.currentTime + 5);
		else if (e.key === 'ArrowLeft') el.currentTime = Math.max(0, el.currentTime - 5);
		else return;
		e.preventDefault();
		t = el.currentTime;
	}
</script>

<div class="pvp" class:pvp-compact={compact} class:pvp-failed={failed} data-petal-player={label || src}>
	<button
		type="button"
		class="pvp-btn"
		aria-label={playing ? `pause ${label}` : `play ${label}`}
		on:click={toggle}
		disabled={failed}
	>
		{#if playing}
			<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14" stroke-width="2.4" stroke-linecap="round" /></svg>
		{:else}
			<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z" stroke-width="1.6" stroke-linejoin="round" /></svg>
		{/if}
	</button>
	<div class="pvp-body">
		{#if label || sub}
			<div class="pvp-head">
				{#if label}<span class="pvp-label">{label}</span>{/if}
				{#if sub}<span class="pvp-sub">{sub}</span>{/if}
			</div>
		{/if}
		<div
			class="pvp-line"
			bind:this={bar}
			role="slider"
			tabindex="0"
			aria-label={`where in ${label || 'the clip'}`}
			aria-valuemin={0}
			aria-valuemax={Math.round(len)}
			aria-valuenow={Math.round(t)}
			on:pointerdown={seek}
			on:keydown={key}
		>
			<div class="pvp-fill" style="width: {len ? (100 * t) / len : 0}%"></div>
		</div>
		<div class="pvp-time">{failed ? 'could not play' : `${clock(t)} / ${len ? clock(len) : '…'}`}</div>
	</div>
	<audio
		bind:this={el}
		{src}
		preload="metadata"
		on:play={() => (playing = true)}
		on:pause={() => (playing = false)}
		on:ended={() => {
			playing = false;
			t = len;
		}}
		on:timeupdate={() => (t = el.currentTime)}
		on:loadedmetadata={() => (len = Number.isFinite(el.duration) ? el.duration : 0)}
		on:durationchange={() => (len = Number.isFinite(el.duration) ? el.duration : len)}
		on:error={() => (failed = true)}
	></audio>
</div>

<style>
	/* static: no transitions, no keyframes (it moves only with her audio's own clock) */
	.pvp {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		min-width: 0;
		padding: 0.55rem 0.65rem;
		border-radius: var(--radius-sm, 8px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian-lit, #1b1622);
	}
	.pvp-compact {
		padding: 0.35rem 0.5rem;
	}
	.pvp-btn {
		flex: none;
		width: 2.1rem;
		height: 2.1rem;
		border-radius: 999px;
		display: grid;
		place-items: center;
		border: 1px solid color-mix(in oklab, var(--candy, #f472b6) 55%, transparent);
		color: var(--candy-light, #f9c6dc);
		background: transparent;
	}
	.pvp-compact .pvp-btn {
		width: 1.7rem;
		height: 1.7rem;
	}
	.pvp-btn svg {
		width: 0.95rem;
		height: 0.95rem;
		fill: none;
		stroke: currentColor;
	}
	.pvp-btn svg path:first-child:last-child {
		fill: currentColor;
	}
	.pvp-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.pvp-head {
		display: flex;
		gap: 0.4rem;
		align-items: baseline;
		min-width: 0;
	}
	.pvp-label {
		font-size: 0.78rem;
		color: var(--pearl, #f3e9f1);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.pvp-sub {
		font-size: 0.7rem;
		color: var(--whisper, #8a7d92);
		white-space: nowrap;
	}
	.pvp-line {
		position: relative;
		height: 0.9rem;
		cursor: pointer;
		touch-action: none;
	}
	.pvp-line::before {
		content: '';
		position: absolute;
		left: 0;
		right: 0;
		top: 50%;
		height: 3px;
		margin-top: -1.5px;
		border-radius: 3px;
		background: var(--edge, #3a3045);
	}
	.pvp-fill {
		position: absolute;
		left: 0;
		top: 50%;
		height: 3px;
		margin-top: -1.5px;
		border-radius: 3px;
		background: var(--grad-fill, linear-gradient(135deg, #f9c6dc, #f472b6 48%, #a873f0));
	}
	.pvp-time {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-variant-numeric: tabular-nums;
		font-size: 0.68rem;
		color: var(--whisper, #8a7d92);
	}
	.pvp-failed .pvp-btn {
		opacity: 0.45;
	}
	audio {
		display: none;
	}
</style>
