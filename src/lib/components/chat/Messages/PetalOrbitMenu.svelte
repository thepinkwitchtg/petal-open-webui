<script lang="ts">
	// ✧ the menu (slices A11 · A11.1) — opens beside a reply's ✧. the orbit is already kept (one
	// tap); here it reads: orbit · held · orbit · leaked · 🌊 climax · unflag. a climax then takes
	// its quality (🔮 owned · 💗 received · 🕳 hollow) and an optional after-feel, one tap each.
	// tap a lit choice again to clear it. while a vow is alive (8b), 🌊 climax waits on today's
	// moments for a conscious release (the brake); the past stays open. static: no animation.
	import { createEventDispatcher, onDestroy, onMount, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import type { After, MarkerVow, Quality } from '$lib/apis/petal-markers';
	import { clock, markAs, setClimax, unflagMark, type ReplyMarks } from '$lib/utils/petal-markers';

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

	const QUALITIES: { key: Exclude<Quality, null>; label: string; hint: string }[] = [
		{ key: 'owned', label: '🔮 owned', hint: 'cast like a spell: it reinforces you and the bond' },
		{ key: 'received', label: '💗 received', hint: 'Petal reaching' },
		{ key: 'hollow', label: '🕳 hollow', hint: 'engineered, it lands as a crash' }
	];
	const AFTERS: Exclude<After, null>[] = ['fed', 'neutral', 'hollow'];

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
			place(); // a climax grows its rows: stay on screen
		}
	};

	$: orbit = marks?.orbit ?? null;
	$: climax = marks?.climax ?? null;
	$: at = climax?.at ?? orbit?.at ?? null;
	const midnight = () => {
		const d = new Date();
		d.setHours(0, 0, 0, 0);
		return d.getTime() / 1000;
	};
	// the brake: a climax on today's moments waits for a release; annotating the past stays open
	$: brake = !!vow && !climax && (at ?? msgAt ?? Date.now() / 1000) >= midnight();

	const choose = (target: 'held' | 'leaked' | 'climax') => act(() => markAs(chatId, messageId, marks, target));
	const pickQuality = (q: Exclude<Quality, null>) =>
		climax && act(() => setClimax(climax!.id, { quality: climax!.quality === q ? null : q }));
	const pickAfter = (a: Exclude<After, null>) =>
		climax && act(() => setClimax(climax!.id, { after: climax!.after === a ? null : a }));
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
		{:else}
			<span class="pom-glyph">✧</span> orbit <span class="pom-dim">· {orbit?.outcome ?? 'open'}</span>
		{/if}
		{#if at}<span class="pom-dim">· {clock(at)}</span>{/if}
	</div>
	{#if !saved}<div class="pom-dim pom-note">temp chat · kept without a link</div>{/if}

	<div class="pom-choices" role="group" aria-label="this reply's mark">
		<button class="pom-choice" class:on={orbit?.outcome === 'held'} disabled={busy} on:click={() => choose('held')}
			><span class="pom-glyph">✧</span> orbit · held</button
		>
		<button class="pom-choice" class:on={orbit?.outcome === 'leaked'} disabled={busy} on:click={() => choose('leaked')}
			><span class="pom-glyph">✧</span> orbit · leaked</button
		>
		<button
			class="pom-choice"
			class:on={!!climax}
			disabled={busy || !!climax || brake}
			title={brake && vow ? `your ${vow.vow} vow is alive (day ${vow.day} of ${vow.total_days}): release it first, a conscious act, in the diary` : ''}
			on:click={() => choose('climax')}><span class="pom-emoji">🌊</span> climax</button
		>
	</div>
	{#if brake && vow}
		<div class="pom-dim pom-note"><span class="pom-emoji">🔥</span> {vow.vow} vow · day {vow.day} of {vow.total_days} · a climax today waits for its release</div>
	{/if}

	{#if climax}
		<div class="pom-sub" role="group" aria-label="its quality">
			{#each QUALITIES as q (q.key)}
				<button class="pom-pill" class:on={climax.quality === q.key} title={q.hint} disabled={busy} on:click={() => pickQuality(q.key)}
					>{q.label}</button
				>
			{/each}
		</div>
		<div class="pom-sub" role="group" aria-label="after">
			<span class="pom-dim pom-label">after</span>
			{#each AFTERS as a (a)}
				<button class="pom-pill pom-small" class:on={climax.after === a} disabled={busy} on:click={() => pickAfter(a)}>{a}</button>
			{/each}
		</div>
	{/if}

	<button class="pom-line pom-quiet" disabled={busy} on:click={unflag}>unflag</button>
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
	.pom-choice,
	.pom-pill {
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
	.pom-choice.on,
	.pom-pill.on {
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian-lit, #1d1724), var(--obsidian-lit, #1d1724)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
		color: var(--pearl, #f6eef3);
	}
	.pom-choice.on:disabled {
		opacity: 1;
	}
	.pom-sub {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.3rem;
		padding-left: 0.35rem;
	}
	.pom-label {
		margin-right: 0.1rem;
	}
	.pom-pill {
		min-height: 2.1rem;
		padding: 0 0.6rem;
		font-size: 0.76rem;
	}
	.pom-small {
		padding: 0 0.55rem;
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
	.pom-pill:disabled,
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
		.pom-pill {
			min-height: 1.75rem;
			font-size: 0.72rem;
		}
	}
</style>
