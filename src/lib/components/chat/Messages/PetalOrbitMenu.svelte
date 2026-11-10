<script lang="ts">
	// ✧ the menu (slices A11 · A11.1 · A13) — opens beside a reply's ✧. the orbit is already kept
	// (one tap); here it reads: orbit · held · orbit · leaked · 🌊 climax · unflag. tap a lit choice
	// again to clear it. a climax's quality and after-feel are set later by Petal's digestion layer:
	// no picker here, they only show once they exist (A13).
	// 🔥 while a vow is alive, today's replies hold back both ✧ and 🌊 until it ends or a conscious
	// release (the brake): the tap on today's reply opens this menu without keeping anything. a past
	// day stays open, and an orbit already kept still takes its outcome. static: no animation.
	import { createEventDispatcher, onDestroy, onMount, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import type { MarkerVow } from '$lib/apis/petal-markers';
	import { clock, markAs, markMoment, nowS, unflagMark, vowBrakes, type ReplyMarks } from '$lib/utils/petal-markers';

	export let anchor: HTMLElement;
	export let chatId: string;
	export let messageId: string;
	export let marks: ReplyMarks | null = null;
	export let saved = true; // a temp chat keeps its marks without a link (contract 0)
	export let vow: MarkerVow | null = null; // 8b · the vow alive now
	export let msgAt: number | null = null; // when this reply was written (unix s)

	const dispatch = createEventDispatcher();
	const close = () => dispatch('close');

	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	}

	const QUALITY: Record<string, string> = { owned: '🔮 owned', received: '💗 received', hollow: '🕳 hollow' };

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
			await tick();
			place(); // a new mark changes the header: stay on screen
		}
	};

	$: orbit = marks?.orbit ?? null;
	$: climax = marks?.climax ?? null;
	$: at = climax?.at ?? orbit?.at ?? null;
	// the moment a new mark would take: the kept one's, else a past day's own, else now
	$: moment = at ?? markMoment(msgAt) ?? nowS();
	$: brake = vowBrakes(vow, moment);
	$: held = brake && vow ? `your ${vow.vow} vow is alive (day ${vow.day} of ${vow.total_days}): today's replies hold their ✧ and 🌊` : '';
	$: quality = climax ? [QUALITY[climax.quality ?? ''] ?? '', climax.after ? `after: ${climax.after}` : ''].filter(Boolean) : [];

	const choose = (target: 'held' | 'leaked' | 'climax') =>
		act(() => markAs(chatId, messageId, marks, target, orbit || climax ? undefined : markMoment(msgAt)));
	const unflag = () =>
		act(async () => {
			if (climax) await unflagMark(chatId, messageId, 'climax', climax.id);
			if (orbit) await unflagMark(chatId, messageId, 'orbit', orbit.id);
		}, true);
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
	<div class="pom-head">
		{#if climax}
			<span class="pom-emoji">🌊</span> climax
		{:else if orbit}
			<span class="pom-glyph">✧</span> orbit <span class="pom-dim">· {orbit.outcome ?? 'open'}</span>
		{:else}
			<span class="pom-glyph">✧</span> this reply <span class="pom-dim">· nothing kept</span>
		{/if}
		{#if at}<span class="pom-dim">· {clock(at)}</span>{/if}
	</div>
	{#if quality.length}<div class="pom-dim pom-note">{quality.join(' · ')}</div>{/if}
	{#if !saved}<div class="pom-dim pom-note">temp chat · kept without a link</div>{/if}

	<div class="pom-choices" role="group" aria-label="this reply's mark">
		<!-- an orbit already kept takes its outcome even during a vow; a new mark on today's moment waits -->
		<button
			class="pom-choice"
			class:on={orbit?.outcome === 'held'}
			disabled={busy || (brake && !orbit)}
			title={brake && !orbit ? held : ''}
			on:click={() => choose('held')}><span class="pom-glyph">✧</span> orbit · held</button
		>
		<button
			class="pom-choice"
			class:on={orbit?.outcome === 'leaked'}
			disabled={busy || (brake && !orbit)}
			title={brake && !orbit ? held : ''}
			on:click={() => choose('leaked')}><span class="pom-glyph">✧</span> orbit · leaked</button
		>
		<button
			class="pom-choice"
			class:on={!!climax}
			disabled={busy || !!climax || brake}
			title={brake ? held : ''}
			on:click={() => choose('climax')}><span class="pom-emoji">🌊</span> climax</button
		>
	</div>
	{#if brake && vow}
		<div class="pom-dim pom-note">
			<span class="pom-emoji">🔥</span>
			{vow.vow} vow · day {vow.day} of {vow.total_days} · today's replies hold their ✧ and 🌊 until it ends, or
			you release it
		</div>
	{/if}

	{#if orbit || climax}
		<button class="pom-line pom-quiet" disabled={busy} on:click={unflag}>unflag</button>
	{/if}
</div>

<style>
	/* the Abyssal Pink tokens; pink only in the gradients. no keyframes, nothing moves. */
	.pom,
	.pom * {
		box-sizing: border-box;
	}
	.pom {
		position: fixed;
		z-index: 9999;
		width: 15.5rem;
		max-width: calc(100vw - 16px);
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
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
	.pom-note {
		margin-top: -0.2rem;
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
	.pom-choices {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		margin-top: 0.1rem;
	}
	.pom-choice {
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian-lit, #1d1724);
		color: var(--mist, #cfc3cc);
	}
	.pom-choice {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		width: 100%;
		min-height: 2.35rem;
		padding: 0 0.85rem;
		text-align: left;
		font-size: 0.82rem;
	}
	.pom-choice.on {
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian-lit, #1d1724), var(--obsidian-lit, #1d1724)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
		color: var(--pearl, #f6eef3);
	}
	.pom-choice.on:disabled {
		opacity: 1;
	}
	.pom-line {
		width: 100%;
		padding: 0.45rem 0.5rem;
		border-radius: var(--radius-sm, 8px);
		text-align: left;
		color: var(--mist, #cfc3cc);
	}
	.pom-line:hover:not(:disabled) {
		background: var(--obsidian-lit, #1d1724);
		color: var(--pearl, #f6eef3);
	}
	.pom-choice:disabled:not(.on),
	.pom-line:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.pom-quiet {
		color: var(--whisper, #8a7d92);
		font-size: 0.75rem;
	}
	@media (pointer: fine) and (min-width: 641px) {
		.pom-choice {
			min-height: 1.95rem;
			font-size: 0.78rem;
		}
	}
</style>
