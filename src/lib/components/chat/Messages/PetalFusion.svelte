<script lang="ts">
	// 🌕 A34 · the fusion check under a reply's own words (utils/petal-fusion.ts). asked: a small card, *how is the
	// fusion so far?*, three moons · 🌕 flowing · 🌗 ignore (the neutral pass, kept as `mixed`) · 🌑 off. one tap
	// folds it into a tiny moon on the reply; a tap on the tiny moon opens the three again to change it (tapping
	// the one already chosen, or Escape, keeps it).
	// mystic, never greedy: an ask that appears on this page glows as it appears, a few soft beats of light over
	// ~2 s (one opacity animation on a still ring, the compositor's alone) while its words type in, then rests as a
	// softly lit card with nothing moving. a hidden tab pauses the beats (static/loader.js, A32); an ask already
	// there when the chat opens rests as it is. the fold is a single short scale, and then nothing runs.
	import { onDestroy, onMount } from 'svelte';
	import { scale } from 'svelte/transition';

	import {
		ASK,
		MOONS,
		freshAsks,
		landMoon,
		moonMarks,
		moonOf,
		retryMoon,
		type FusionStamp,
		type Score
	} from '$lib/utils/petal-fusion';
	import { typeIn } from '$lib/utils/petal-type';

	export let chatId: string;
	export let message: { id: string; petal_fusion?: FusionStamp | null };

	let stamp: FusionStamp | null = message?.petal_fusion ?? null;
	let score: Score | null = moonOf(stamp?.score)?.score ?? null;
	let open = false; // the three moons shown again, to change hers
	let glowing = false; // the appear: beats of light, once
	let words = ASK;
	let typing: { cancel(): void } | null = null;

	// the stamp the rig (or a reload) hands down replaces the one this card began with
	$: if (message?.petal_fusion && message.petal_fusion !== stamp) {
		stamp = message.petal_fusion;
		score = moonOf(stamp?.score)?.score ?? score;
	}
	$: chosen = moonOf(score);
	$: mark = $moonMarks[message?.id] ?? null;
	$: folded = !!score && !open;

	onMount(() => {
		if (!score && freshAsks.has(message.id)) {
			glowing = true;
			words = '';
			typing = typeIn(ASK, (part) => (words = part));
		}
	});
	onDestroy(() => typing?.cancel());

	const glowEnded = (e: AnimationEvent) => {
		if (!e.animationName.includes('petal-fusion-beats')) return;
		glowing = false;
		freshAsks.delete(message.id);
	};
	// a cancelled glow (its card hidden away mid-beat) ends the same way
	const onCancel = (node: HTMLElement, done: (e: AnimationEvent) => void) => {
		const heard = (e: Event) => done(e as AnimationEvent);
		node.addEventListener('animationcancel', heard);
		return { destroy: () => node.removeEventListener('animationcancel', heard) };
	};

	const settle = () => {
		typing?.cancel();
		typing = null;
		words = ASK;
		glowing = false;
		freshAsks.delete(message.id);
	};

	const choose = (next: Score) => {
		if (open && next === score) return void (open = false); // the moon she had: kept
		const now = Math.floor(Date.now() / 1000);
		const told: FusionStamp = { ...(stamp ?? { asked_at: now }), score: next, answered_at: now };
		message.petal_fusion = told; // the page's own copy of the chat keeps it too: a later save never loses it
		stamp = told;
		score = next;
		open = false;
		settle();
		landMoon(chatId, message.id, next);
	};

	const tapMoon = () => {
		if (mark === 'failed') {
			retryMoon(message.id);
			if ($moonMarks[message.id] === 'failed') open = true; // refused for good: choose again
			return;
		}
		open = true;
	};

	const onKey = (e: KeyboardEvent) => {
		if (open && score && e.key === 'Escape') open = false;
	};
</script>

<svelte:window on:keydown={onKey} />

{#if stamp}
	<div
		class="petal-fusion pl-1 @lg:pl-10"
		data-petal-fusion={folded ? 'folded' : glowing ? 'appearing' : 'asking'}
		data-fusion-score={score ?? ''}
		data-moon-state={mark ?? ''}
	>
		{#if folded}
			<button
				type="button"
				class="pf-moon"
				class:pf-saving={mark === 'saving'}
				class:pf-failed={mark === 'failed'}
				data-moon={score}
				aria-label={`${ASK} ${chosen?.label ?? ''} · tap to change`}
				title={mark === 'failed' ? 'not saved yet · tap to try again' : `${chosen?.label ?? ''} · tap to change`}
				on:click={tapMoon}
				in:scale={{ duration: 240, start: 0.4 }}
			>
				<span aria-hidden="true">{chosen?.moon ?? ''}</span>
			</button>
		{:else}
			<div
				class="pf-card"
				class:pf-appear={glowing}
				role="group"
				aria-label={ASK}
				on:animationend={glowEnded}
				use:onCancel={glowEnded}
				out:scale={{ duration: 200, start: 0.86, opacity: 0 }}
			>
				<span class="pf-words"
					><span class="pf-sizer" aria-hidden="true">{ASK}</span><span class="pf-typed">{words}</span></span
				>
				<span class="pf-moons">
					{#each MOONS as m (m.score)}
						<button
							type="button"
							class="pf-choice"
							class:pf-chosen={score === m.score}
							data-moon={m.score}
							aria-label={m.label}
							aria-pressed={score === m.score}
							title={m.score === 'mixed' ? 'ignore · the neutral pass' : m.label}
							on:click={() => choose(m.score)}
						>
							<span class="pf-glyph" aria-hidden="true">{m.moon}</span>
							<span class="pf-label">{m.label}</span>
						</button>
					{/each}
				</span>
			</div>
		{/if}
	</div>
{/if}

<style>
	/* 🌕 A34 · Abyssal Pink: obsidian ground, a candy → iris hairline, a soft still light. the theme's dials when the
	   🌸 skin is on, its own fallbacks when it isn't */
	.petal-fusion {
		display: flex;
		margin: 0.05rem 0 0.4rem;
	}
	.pf-card {
		position: relative;
		display: inline-flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.3rem 0.7rem;
		max-width: 100%;
		padding: 0.38rem 0.45rem 0.38rem 0.8rem;
		border-radius: var(--radius, 14px);
		border: 1px solid transparent;
		background:
			linear-gradient(var(--obsidian, #141018), var(--obsidian, #141018)) padding-box,
			linear-gradient(
					135deg,
					rgb(255 204 233 / 0.5),
					rgb(255 91 176 / 0.42) 46%,
					rgb(168 115 240 / 0.48)
				)
				border-box;
		box-shadow:
			0 0 0 1px rgb(255 91 176 / 0.07),
			0 12px 30px -22px #000,
			0 0 22px -12px rgb(255 159 214 / 0.34);
	}
	/* the beats: one ring of light whose opacity rises and falls three times, then is gone */
	.pf-card::after {
		content: '';
		position: absolute;
		inset: -1px;
		border-radius: inherit;
		pointer-events: none;
		opacity: 0;
		box-shadow:
			0 0 0 1px rgb(255 176 221 / 0.6),
			0 0 26px -4px rgb(255 91 176 / 0.85),
			0 0 48px -10px rgb(168 115 240 / 0.6);
	}
	.pf-card.pf-appear {
		animation: petal-fusion-rise 380ms cubic-bezier(0.2, 0.7, 0.3, 1) 1;
	}
	.pf-card.pf-appear::after {
		animation: petal-fusion-beats 2100ms cubic-bezier(0.4, 0, 0.2, 1) 1;
	}
	@keyframes petal-fusion-rise {
		from {
			opacity: 0;
			transform: translateY(3px) scale(0.985);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}
	@keyframes petal-fusion-beats {
		0% {
			opacity: 0;
		}
		14% {
			opacity: 1;
		}
		30% {
			opacity: 0.26;
		}
		47% {
			opacity: 0.86;
		}
		63% {
			opacity: 0.2;
		}
		80% {
			opacity: 0.58;
		}
		100% {
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.pf-card.pf-appear {
			animation: none;
		}
		.pf-card.pf-appear::after {
			animation: petal-fusion-beats-once 1200ms ease-out 1;
		}
	}
	@keyframes petal-fusion-beats-once {
		0%,
		100% {
			opacity: 0;
		}
		30% {
			opacity: 0.7;
		}
	}

	.pf-words {
		display: inline-grid;
		font-family: var(--font-display, ui-serif, Georgia, serif);
		font-style: italic;
		font-size: 0.86rem;
		letter-spacing: 0.01em;
		color: var(--mist, #cdbfd2);
		white-space: nowrap;
	}
	/* the whole line, unseen, holds the card's size; the typed words lie over it: the card never grows as they type */
	.pf-words > span {
		grid-area: 1 / 1;
	}
	.pf-sizer {
		visibility: hidden;
	}
	.pf-moons {
		display: inline-flex;
		gap: 0.2rem;
	}
	.pf-choice {
		display: inline-flex;
		align-items: center;
		gap: 0.28rem;
		padding: 0.18rem 0.55rem 0.18rem 0.38rem;
		border-radius: 999px;
		border: 1px solid transparent;
		font-size: 0.74rem;
		line-height: 1.2;
		color: var(--whisper, #a397a7);
		transition:
			color 160ms,
			background-color 160ms,
			box-shadow 160ms;
	}
	.pf-choice:hover,
	.pf-choice:focus-visible {
		outline: none;
		color: var(--pearl, #f6eef4);
		background-color: rgb(255 91 176 / 0.08);
		box-shadow: 0 0 14px -7px rgb(255 125 196 / 0.75);
	}
	.pf-choice.pf-chosen {
		color: var(--pearl, #f6eef4);
		border-color: rgb(255 176 221 / 0.35);
		background-color: rgb(255 91 176 / 0.1);
	}
	.pf-glyph {
		font-family: var(--font-emoji, 'Noto Color Emoji', 'Segoe UI Emoji', sans-serif);
		font-size: 0.95rem;
		line-height: 1;
	}
	.pf-moon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.5rem;
		height: 1.5rem;
		border-radius: 999px;
		font-family: var(--font-emoji, 'Noto Color Emoji', 'Segoe UI Emoji', sans-serif);
		font-size: 0.82rem;
		line-height: 1;
		filter: drop-shadow(0 0 5px rgb(255 159 214 / 0.42));
		transition: filter 160ms;
	}
	.pf-moon:hover,
	.pf-moon:focus-visible {
		outline: none;
		filter: drop-shadow(0 0 9px rgb(255 125 196 / 0.8));
	}
	.pf-moon.pf-saving {
		opacity: 0.72;
	}
	.pf-moon.pf-failed {
		box-shadow: 0 0 0 1px rgb(255 91 176 / 0.65);
	}
</style>
