<script lang="ts">
	// ✧ the menu (slice A11) — opens beside a reply's ✧. the orbit is already kept (one tap);
	// here its outcome is one more tap, and 🌊 a spill is reached on purpose: deliberate,
	// never hidden, never shamed. static: no animation, no timers.
	import { createEventDispatcher, onDestroy, onMount, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import type { Outcome } from '$lib/apis/petal-markers';
	import {
		clock,
		orbitToSpill,
		setOutcome,
		spillToOrbit,
		unflagMark,
		type ReplyMarks
	} from '$lib/utils/petal-markers';

	export let anchor: HTMLElement;
	export let chatId: string;
	export let messageId: string;
	export let marks: ReplyMarks | null = null;
	export let saved = true; // a temp chat has no saved message to anchor a spill to

	const dispatch = createEventDispatcher();
	const close = () => dispatch('close');

	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	}

	let el: HTMLDivElement;
	let pos = { left: 8, top: 8 };
	let busy = false;

	const place = () => {
		if (!anchor || !el) return;
		const r = anchor.getBoundingClientRect();
		const vw = window.innerWidth;
		const vh = window.visualViewport?.height ?? window.innerHeight;
		const w = el.offsetWidth;
		const h = el.offsetHeight;
		const left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), vw - w - 8);
		const below = r.bottom + 6;
		pos = { left, top: below + h <= vh - 8 ? below : Math.max(8, r.top - h - 6) };
	};

	const outside = (e: PointerEvent) => {
		const t = e.target as Node;
		if (el?.contains(t) || anchor?.contains(t)) return; // the ✧ itself toggles
		close();
	};
	const onKey = (e: KeyboardEvent) => {
		if (e.key === 'Escape') {
			e.stopPropagation();
			close();
		}
	};

	onMount(async () => {
		await tick();
		place();
		document.addEventListener('pointerdown', outside, true);
		window.addEventListener('resize', close);
		window.addEventListener('scroll', close, true);
	});
	onDestroy(() => {
		document.removeEventListener('pointerdown', outside, true);
		window.removeEventListener('resize', close);
		window.removeEventListener('scroll', close, true);
	});

	const act = async (fn: () => Promise<unknown>, done = false) => {
		if (busy) return;
		busy = true;
		try {
			await fn();
			if (done) close();
		} catch (e) {
			toast.error(`✧ ${e}`);
		} finally {
			busy = false;
		}
	};

	$: orbit = marks?.orbit ?? null;
	$: spill = marks?.spill ?? null;
	const pick = (o: Exclude<Outcome, null>) =>
		orbit && act(() => setOutcome(orbit!.id, orbit!.outcome === o ? null : o));
</script>

<svelte:window on:keydown={onKey} />

<div
	use:portal
	bind:this={el}
	class="pom"
	role="dialog"
	aria-label="the ✧ menu"
	style="left:{pos.left}px; top:{pos.top}px"
>
	{#if orbit}
		<div class="pom-head">
			<span class="pom-glyph">✧</span> orbit <span class="pom-dim">· {clock(orbit.at)}</span>
			{#if !saved}<span class="pom-dim">· temp, kept without a link</span>{/if}
		</div>
		<div class="pom-row" role="group" aria-label="outcome">
			<button class="pom-pill" class:on={orbit.outcome === 'held'} disabled={busy} on:click={() => pick('held')}
				>held</button
			>
			<button class="pom-pill" class:on={orbit.outcome === 'leaked'} disabled={busy} on:click={() => pick('leaked')}
				>leaked</button
			>
			<span class="pom-dim pom-open">{orbit.outcome ? '' : 'open'}</span>
		</div>
		<button
			class="pom-line"
			disabled={busy || !saved}
			title={saved ? 'it was a spill · the orbit steps aside' : 'temporary chat — no saved message to anchor a spill to'}
			on:click={() => orbit && act(() => orbitToSpill(chatId, messageId, orbit!), true)}
			><span class="pom-emoji">🌊</span> it was a spill</button
		>
		<button class="pom-line pom-quiet" disabled={busy} on:click={() => orbit && act(() => unflagMark(chatId, messageId, 'orbit', orbit!.id), true)}
			>unflag</button
		>
	{/if}
	{#if spill}
		<div class="pom-head" class:pom-sep={!!orbit}>
			<span class="pom-emoji">🌊</span> spill <span class="pom-dim">· {clock(spill.at)}</span>
		</div>
		{#if !orbit}
			<button class="pom-line" disabled={busy} on:click={() => spill && act(() => spillToOrbit(chatId, messageId, spill!), true)}
				><span class="pom-glyph">✧</span> it was an orbit</button
			>
		{/if}
		<button class="pom-line pom-quiet" disabled={busy} on:click={() => spill && act(() => unflagMark(chatId, messageId, 'spill', spill!.id), true)}
			>unflag</button
		>
	{/if}
</div>

<style>
	/* the Abyssal Pink tokens; pink only in the gradient glyph. no keyframes, nothing moves. */
	.pom,
	.pom * {
		box-sizing: border-box;
	}
	.pom {
		position: fixed;
		z-index: 9999;
		min-width: 13.5rem;
		max-width: calc(100vw - 16px);
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		padding: 0.6rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		box-shadow:
			inset 0 1px 0 var(--glass-sheen, rgba(255, 255, 255, 0.03)),
			0 18px 40px -18px oklch(0 0 0 / 0.7);
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
	}
	.pom-head {
		display: flex;
		align-items: baseline;
		gap: 0.3rem;
		color: var(--pearl, #f6eef3);
		font-family: var(--font-display, Georgia, serif);
		font-size: 0.95rem;
	}
	.pom-sep {
		margin-top: 0.3rem;
		padding-top: 0.45rem;
		border-top: 1px solid var(--edge-soft, #2a2433);
	}
	.pom-glyph {
		background: var(--grad-text, linear-gradient(100deg, #f9c6dc, #f472b6 46%, #a873f0));
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	.pom-emoji {
		font-family: var(--font-emoji, 'SamsungColorEmoji'), sans-serif;
	}
	.pom-dim {
		color: var(--whisper, #8a7d92);
		font-family: var(--font-ui, system-ui), sans-serif;
		font-size: 0.75rem;
	}
	.pom-row {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		margin: 0.15rem 0 0.2rem;
	}
	.pom-pill {
		min-width: 4.2rem;
		padding: 0.35rem 0.75rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian-lit, #1d1724);
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
	}
	.pom-pill.on {
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian-lit, #1d1724), var(--obsidian-lit, #1d1724)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
		color: var(--pearl, #f6eef3);
	}
	.pom-open {
		margin-left: 0.15rem;
	}
	.pom-line {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		width: 100%;
		padding: 0.4rem 0.5rem;
		border-radius: var(--radius-sm, 8px);
		text-align: left;
		color: var(--mist, #cfc3cc);
	}
	.pom-line:hover:not(:disabled) {
		background: var(--obsidian-lit, #1d1724);
		color: var(--pearl, #f6eef3);
	}
	.pom-line:disabled,
	.pom-pill:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.pom-quiet {
		color: var(--whisper, #8a7d92);
		font-size: 0.75rem;
	}
	@media (pointer: coarse) {
		.pom-pill {
			padding: 0.5rem 0.9rem;
		}
		.pom-line {
			padding: 0.55rem 0.5rem;
		}
	}
</style>
