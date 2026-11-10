<script context="module" lang="ts">
	import { writable } from 'svelte/store';
	/** 📔 the quick note sheet: the sidebar's ＋ (or Ctrl+Alt+J on the rig) opens it over any page */
	export const quickNote = writable(false);
	// a closed sheet keeps her words until she keeps them or clears them
	const text = writable('');
	const sees = writable(false);
</script>

<script lang="ts">
	// 📔 a quick note (slice A11) — one sheet over whatever page she's on: write, keep, gone.
	// a bottom sheet on the phone, a small card on the rig. static: no animation.
	import { onDestroy, onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { postDiary } from '$lib/apis/petal-diary';
	import { markerVia } from '$lib/utils/petal-markers';

	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	}

	let busy = false;
	let area: HTMLTextAreaElement;

	$: if ($quickNote) tick().then(() => area?.focus());

	const close = () => quickNote.set(false);

	const keep = async () => {
		if (busy || !$text.trim()) return;
		busy = true;
		try {
			await postDiary(localStorage.token, { kind: 'note', text: $text, petal_sees: $sees, via: markerVia() });
			text.set('');
			sees.set(false);
			close();
			toast.success('📔 kept in your diary');
		} catch (e) {
			toast.error(`📔 ${e}`);
		} finally {
			busy = false;
		}
	};

	const onKey = (e: KeyboardEvent) => {
		if (e.ctrlKey && e.altKey && !e.shiftKey && e.code === 'KeyJ') {
			e.preventDefault();
			quickNote.update((v) => !v);
			return;
		}
		if (!$quickNote) return;
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			close();
		} else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
			e.preventDefault();
			keep();
		}
	};

	onMount(() => window.addEventListener('keydown', onKey, true));
	onDestroy(() => window.removeEventListener('keydown', onKey, true));
</script>

{#if $quickNote}
	<div use:portal class="pqn-veil" role="presentation" on:pointerdown|self={close}>
		<div class="pqn" role="dialog" aria-modal="true" aria-label="a quick note">
			<div class="pqn-head">
				<span class="pqn-title"><span class="pqn-emoji">📔</span> a quick note</span>
				<button class="pqn-x" aria-label="close" on:click={close}>✕</button>
			</div>
			<textarea bind:this={area} bind:value={$text} rows="4" placeholder="what's alive in you right now…"></textarea>
			<div class="pqn-row">
				<button
					type="button"
					class="pqn-chip"
					class:on={$sees}
					aria-pressed={$sees}
					title="off: only you ever read it. on: Petal may read it one day"
					on:click={() => sees.update((v) => !v)}><span class="pqn-emoji">🌸</span> petal may read</button
				>
				<span class="pqn-grow"></span>
				<button
					type="button"
					class="pqn-link"
					on:click={() => {
						close();
						goto('/diary');
					}}>the diary ↗</button
				>
				<button type="button" class="pqn-keep" disabled={busy || !$text.trim()} on:click={keep}>keep it</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.pqn-veil,
	.pqn-veil * {
		box-sizing: border-box;
	}
	.pqn-veil {
		position: fixed;
		inset: 0;
		z-index: 9998;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding-top: 18vh;
		background: oklch(0.08 0.02 300 / 0.6); /* a plain veil: no blur, nothing for the GPU to redo */
	}
	.pqn {
		width: min(30rem, calc(100vw - 24px));
		display: flex;
		flex-direction: column;
		gap: 0.55rem;
		padding: 0.8rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		box-shadow: 0 24px 60px -24px oklch(0 0 0 / 0.8);
		color: var(--mist, #cfc3cc);
		font-size: 0.85rem;
	}
	.pqn-head {
		display: flex;
		align-items: center;
	}
	.pqn-title {
		flex: 1;
		font-family: var(--font-display, Georgia, serif);
		font-size: 1.05rem;
		color: var(--pearl, #f6eef3);
	}
	.pqn-emoji {
		font-family: var(--font-emoji, 'SamsungColorEmoji'), sans-serif;
	}
	.pqn-x {
		width: 2rem;
		height: 2rem;
		border-radius: 999px;
		color: var(--whisper, #8a7d92);
	}
	.pqn textarea {
		width: 100%;
		resize: vertical;
		padding: 0.55rem 0.6rem;
		border-radius: var(--radius-sm, 8px);
		border: 1px solid var(--edge-soft, #2a2433);
		outline: none;
		background: var(--abyss, #0b0910);
		color: var(--pearl, #f6eef3);
		font: inherit;
		line-height: 1.55;
	}
	.pqn-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
	}
	.pqn-grow {
		flex: 1;
	}
	.pqn-chip,
	.pqn-keep {
		min-height: 2.25rem;
		padding: 0 0.85rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian-lit, #1d1724);
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
	}
	.pqn-chip.on,
	.pqn-keep {
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian-lit, #1d1724), var(--obsidian-lit, #1d1724)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
		color: var(--pearl, #f6eef3);
	}
	.pqn-keep:disabled {
		opacity: 0.45;
	}
	.pqn-link {
		padding: 0.3rem 0.5rem;
		font-size: 0.75rem;
		color: var(--whisper, #8a7d92);
	}
	@media (max-width: 640px) {
		.pqn-veil {
			align-items: flex-end;
			padding-top: 0;
		}
		.pqn {
			width: 100vw;
			border-radius: var(--radius, 14px) var(--radius, 14px) 0 0;
			padding-bottom: calc(0.8rem + env(safe-area-inset-bottom, 0px));
		}
	}
</style>
