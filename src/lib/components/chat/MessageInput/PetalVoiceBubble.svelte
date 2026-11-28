<script context="module" lang="ts">
	// every mounted bubble (a split view holds two): the hotkey belongs to the one whose composer holds
	// the focus, or to a lone bubble when nothing does
	const bubbles = new Set<HTMLElement>();
	let made = 0; // each bubble's own gradient id (its pink glyph)
	let noted = 0; // 🧵 A46 · the last note said (a split view holds two bubbles: said once)
</script>

<script lang="ts">
	// 🎙️ the voice bubble (slices A19 · A19b · A20 · A21 · A22): one button, on the left of the chat bar (Lily
	// is left-handed), when Settings → Interface → Voice control is "bubble". beside the bar where the screen
	// leaves room for it (no words under it), above the bar's left end on the phone. it plays the reply
	// most in view, becomes pause while she speaks, and fades away once that reply has been heard; it comes
	// back when a new reply arrives or you scroll to one you haven't heard. one reply per tap.
	// the hotkey (Settings → Shortcuts → "Her voice", Ctrl+Shift+Space until she binds another) does the
	// same in both modes, so the bubble stays mounted for it even when the speaker by her name is chosen.
	// 👻 the ghost (Lily's pick, A21 · A22): a thin pink ring around a pink glyph, never a fill. ▶ before a
	// play and when paused, at full. ‖ while she speaks, the whole of it at 26 %; a tap, a hover, the hotkey
	// or keyboard focus bring it to full for 2 s. while she speaks it gives way to words: with her words under
	// it or within 24 px it fades out by how close they are. and whenever the speaker button at the bottom of
	// the reply it would play (or is playing) is on screen, it fades out: that button is right there. faded
	// out, taps and selections pass through it (the hotkey still works).
	// 👁 A31 · it follows her eyes: the reply most in view (petal-voice's one IntersectionObserver, never a
	// scroll listener: nothing runs while she's idle), the one she swiped to or pointed at inside an open pick,
	// and its tooltip names that reply by its first words. only while her voice plays does the chat's scroll
	// reach it, for the words-near fade above (they move under it between the observer's steps).
	import { getContext, onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	import { formatChord, keybindings, matchKeybinding, Shortcut } from '$lib/shortcuts';
	import { settings } from '$lib/stores';
	import {
		firstWords,
		heardReplies as heardAll,
		tapTarget,
		speakersInView as speakersAll,
		voiceReplies as repliesAll,
		voiceTap,
		voiceTarget as targetAll,
		voiceNotes as notesAll,
		voiceUI as uiAll,
		watchSoon,
		type VoiceUI
	} from '$lib/utils/petal-voice';
	import { everAlive, gate, inertAt, type PetalScreen } from '$lib/utils/petal-screen';

	const i18n = getContext<Writable<i18nType>>('i18n');
	// 🪟 A49 · the bubble of a chat she can't see (under the phone's tabs drawer, a tab parked behind another) listens
	// to nothing: each of her voice's stores reaches it only while its screen is alive, and alive again it reads them
	// as they are now
	const screen = getContext<PetalScreen | undefined>('petal-screen') ?? everAlive;
	const alive = screen.active;
	const voiceUI = gate(uiAll, screen, 'bubble·voiceUI');
	const voiceTarget = gate(targetAll, screen, 'bubble·voiceTarget');
	const heardReplies = gate(heardAll, screen, 'bubble·heardReplies');
	const voiceReplies = gate(repliesAll, screen, 'bubble·voiceReplies');
	const speakersInView = gate(speakersAll, screen, 'bubble·speakersInView');
	const voiceNotes = gate(notesAll, screen, 'bubble·voiceNotes');
	/** its own chat's box (a tab's chat has its own; outside any chat: the page's) */
	const chatBox = (): HTMLElement | null =>
		screen.root()?.querySelector<HTMLElement>('#messages-container, [id^="note-messages-"]') ??
		document.getElementById('messages-container');
	const gid = `pvb-ink-${++made}`;
	const WAKE_MS = 2000; // a tap's full strength, before it steps back again
	const DIM = 0.26; // the ghost while she speaks
	const NEAR_PX = 24; // her words closer than this: it gives way

	let root: HTMLElement;
	let btn: HTMLElement;
	let beside = false; // room on the bar's left: the bubble sits beside it, never over words

	/** the reply a tap would act on: the one she's speaking, the paused one (or an unheard one in view,
	 *  as voiceTap decides), else the one most in view */
	function subjectOf(ui: VoiceUI, target: string | null, heard: Set<string>): string | null {
		if (ui.state === 'playing' || ui.state === 'loading') return ui.message_id;
		if (ui.state === 'paused') {
			const unheard = target && target !== ui.message_id && !heard.has(target);
			return unheard ? target : ui.message_id;
		}
		return target;
	}

	/** that reply's own speaker (OWUI's Read Aloud, at its bottom) shown on screen: at least half of it in the
	 *  chat's visible box (her eyes say). a button that only appears on hover (older replies) isn't there for
	 *  her eyes until then, so it doesn't count */
	function speakerShown(id: string | null, inView: Set<string>): boolean {
		if (!id || !inView.has(id)) return false;
		const sp =
			(screen.root() ?? document).querySelector<HTMLElement>(`[id="speak-button-${id}"]`) ??
			document.getElementById(`speak-button-${id}`);
		return !!sp && !sp.classList.contains('hover-reveal');
	}

	// room on the bar's left: measured once, and again when the window or the bar changes size (a sidebar)
	let barRO: ResizeObserver | null = null;
	const placeBar = () => {
		const bar = root?.parentElement?.getBoundingClientRect();
		beside = !!bar && bar.left >= 56;
	};

	// awake: full while she speaks. a pointer over it or keyboard focus on it keeps it awake; once they
	// leave (or after a tap, or the hotkey) it stays 2 s, then steps back
	let awake = false;
	let hovering = false;
	let focusing = false;
	let wakeTimer: ReturnType<typeof setTimeout> | null = null;
	const wake = () => {
		if (wakeTimer) clearTimeout(wakeTimer);
		wakeTimer = null;
		awake = true;
	};
	const sleepSoon = () => {
		if (wakeTimer) clearTimeout(wakeTimer);
		wakeTimer = setTimeout(() => {
			wakeTimer = null;
			if (!hovering && !focusing) awake = false;
		}, WAKE_MS);
	};
	const nudge = () => {
		wake();
		sleepSoon();
	};
	const hover = (e: PointerEvent, on: boolean) => {
		if (e.pointerType === 'touch') return; // a finger has no hover: its tap nudges instead
		hovering = on;
		on ? wake() : sleepSoon();
	};
	const focusIn = (e: FocusEvent) => {
		if (!(e.currentTarget as HTMLElement).matches(':focus-visible')) return; // keyboard focus only
		focusing = true;
		wake();
	};
	const focusOut = () => {
		if (!focusing) return;
		focusing = false;
		sleepSoon();
	};

	// ── while she speaks it gives way to words: how clear of them it is, 1 (none within 24 px) to 0 ──
	let near = 1;
	let nearFrame = 0;
	let nearRO: ResizeObserver | null = null;

	/** only the chat's own words count (never the bar's): a grid of probes around the ring finds what's
	 *  there, and each line of their text is measured against it */
	function clearance(b: DOMRect): number {
		const chat = chatBox();
		if (!chat) return 1;
		const R = NEAR_PX;
		let d = R;
		const scanned = new Set<Element>();
		probe: for (let i = 0; i < 5; i++)
			for (let j = 0; j < 6; j++) {
				const x = b.left - R + (i / 4) * (b.width + 2 * R);
				const y = b.top - R + (j / 5) * (b.height + 2 * R);
				for (const el of document.elementsFromPoint(x, y)) {
					if (scanned.has(el) || !chat.contains(el)) continue;
					scanned.add(el);
					for (const n of el.childNodes) {
						if (n.nodeType !== Node.TEXT_NODE || !n.textContent?.trim()) continue;
						const r = document.createRange();
						r.selectNodeContents(n);
						for (const t of r.getClientRects()) {
							const dx = Math.max(0, t.left - b.right, b.left - t.right);
							const dy = Math.max(0, t.top - b.bottom, b.top - t.bottom);
							d = Math.min(d, Math.hypot(dx, dy));
							if (d <= 0) break probe;
						}
					}
				}
			}
		const f = d / R;
		return f * f * (3 - 2 * f); // eased: it fades softly as words come close
	}
	const measure = () => {
		nearFrame = 0;
		near = speaking && btn ? clearance(btn.getBoundingClientRect()) : 1;
	};
	const measureSoon = () => {
		if (speaking && !nearFrame) nearFrame = requestAnimationFrame(measure);
	};
	/** while she speaks: new lines, a growing bar, a resize or the chat scrolling may bring words close (the
	 *  chat's scroll is listened to only now, while her voice plays) */
	let scroller: HTMLElement | null = null;
	function watchNear() {
		scroller?.removeEventListener('scroll', measureSoon);
		scroller = chatBox();
		scroller?.addEventListener('scroll', measureSoon, { passive: true });
		if (typeof ResizeObserver !== 'undefined') {
			nearRO ??= new ResizeObserver(() => measureSoon()); // observing twice is a no-op
			const chat = chatBox();
			const lines = chat?.firstElementChild ?? chat;
			if (lines) nearRO.observe(lines);
			if (root?.parentElement) nearRO.observe(root.parentElement);
		}
		measureSoon();
	}
	function unwatchNear() {
		scroller?.removeEventListener('scroll', measureSoon);
		scroller = null;
		nearRO?.disconnect();
		nearRO = null;
		if (nearFrame) cancelAnimationFrame(nearFrame);
		nearFrame = 0;
		near = 1;
	}

	$: bubble = ($settings?.voiceControl ?? 'bubble') !== 'speaker';
	$: if (bubble) watchSoon(); // chosen again: her eyes find the speaker buttons back
	$: running = $voiceUI.state !== 'idle';
	$: paused = $voiceUI.state === 'paused';
	$: loading = $voiceUI.state === 'loading';
	$: target = $voiceTarget; // the reply most in view (her eyes)
	$: subject = subjectOf($voiceUI, target, $heardReplies);
	// a reply came, went or finished (a speaker may have turned hover-only), or her eyes moved: look again
	let speakerSeen = false;
	$: {
		void $voiceReplies;
		speakerSeen = speakerShown(subject, $speakersInView);
	}
	$: shown = bubble && (running || (!!target && !$heardReplies.has(target)));
	$: speaking = running && !paused; // ‖ at 26 % (before a play and paused: ▶ at full)
	$: if (typeof window !== 'undefined') speaking && $alive ? watchNear() : unwatchNear(); // 🪟 A49 · only while alive
	// the reply's own speaker is right there: it steps out of the way (keyboard focus still shows it)
	$: aside = speakerSeen && !focusing;
	$: presence = aside ? 0 : speaking ? (awake ? 1 : DIM * near) : 1;
	$: yielded = presence < 0.04; // faded out: taps and selections pass through
	$: glyph = loading ? 'spin' : speaking ? 'pause' : 'play';
	$: hint = formatChord($keybindings[Shortcut.PETAL_VOICE] ?? '');
	$: label =
		running && !paused
			? $i18n.t('Pause her voice')
			: paused && (!target || target === $voiceUI.message_id || $heardReplies.has(target))
				? $i18n.t('Resume her voice')
				: $i18n.t('Her voice, for the reply in view');
	// A31 · which reply a tap plays (or pauses, or resumes): a few of its first words
	let words = '';
	$: {
		void $voiceReplies; // its words are there once it registered
		words = firstWords(subject);
	}
	$: named = words ? `${label} · “${words}”` : label;
	$: title = hint ? `${named} · ${hint}` : named;

	const onKey = (e: KeyboardEvent) => {
		if (e.defaultPrevented || e.repeat || $settings?.keyboardShortcuts === false) return;
		if (!screen.isAlive()) return; // 🪟 A49 · a bubble she can't see never takes the hotkey
		if (matchKeybinding(e) !== Shortcut.PETAL_VOICE) return;
		const t = e.target instanceof Node ? e.target : null;
		const box = root?.closest('[data-composer-id]') ?? root?.closest('form') ?? root?.parentElement;
		const inside = !!(box && t && (box.contains(t) || root.contains(t)));
		const loose = !t || t === document.body || t === document.documentElement;
		const lone = [...bubbles].filter((x) => !inertAt(x)).length === 1 && !document.querySelector('.modal, [role="alertdialog"]'); // 🪟 A49 · alone among the bubbles she can see
		if (!inside && !(loose && lone)) return;
		e.preventDefault();
		e.stopPropagation();
		voiceTap(tapTarget()); // A33 · read at the moment of the key, from her focus now
		nudge();
	};

	const tap = () => {
		nudge();
		voiceTap(tapTarget()); // A33 · read at the moment of the tap, never the target she hovered
	};

	// 🧵 A46 · a break her voice couldn't heal is said, once (her voice never stops in silence)
	const offNotes = voiceNotes.subscribe((n) => {
		if (!n || n.seq === noted) return;
		noted = n.seq;
		toast.warning(`🎙️ ${n.note}`);
	});

	onMount(() => {
		bubbles.add(root);
		placeBar();
		if (typeof ResizeObserver !== 'undefined' && root?.parentElement) {
			barRO = new ResizeObserver(placeBar);
			barRO.observe(root.parentElement);
		}
		watchSoon();
		if (speaking && screen.isAlive()) watchNear(); // mounted while she speaks: the bar exists now
		window.addEventListener('keydown', onKey, true);
		window.addEventListener('resize', placeBar, { passive: true });
	});
	onDestroy(() => {
		offNotes();
		bubbles.delete(root);
		if (wakeTimer) clearTimeout(wakeTimer);
		barRO?.disconnect();
		if (typeof window === 'undefined') return;
		unwatchNear();
		window.removeEventListener('keydown', onKey, true);
		window.removeEventListener('resize', placeBar);
	});
</script>

<div
	bind:this={root}
	class="pvb"
	class:pvb-beside={beside}
	class:pvb-away={!shown}
	class:pvb-speaking={speaking}
	class:pvb-yield={yielded}
>
	{#if bubble}
		<button
			bind:this={btn}
			type="button"
			class="pvb-main"
			style:opacity={presence}
			aria-label={named}
			title={title}
			aria-pressed={running ? !paused : undefined}
			aria-hidden={!shown}
			tabindex={shown ? 0 : -1}
			on:click={tap}
			on:pointerenter={(e) => hover(e, true)}
			on:pointerleave={(e) => hover(e, false)}
			on:focus={focusIn}
			on:blur={focusOut}
		>
			<svg
				viewBox="0 0 24 24"
				class="pvb-ink"
				class:pvb-spin={glyph === 'spin'}
				fill="url(#{gid})"
				aria-hidden="true"
			>
				<defs>
					<linearGradient id={gid} gradientUnits="userSpaceOnUse" x1="5" y1="5" x2="19" y2="19">
						<stop offset="0" style="stop-color: var(--candy-light, #ffcbe2)" />
						<stop offset="0.48" style="stop-color: var(--candy, #ff5bb0)" />
						<stop offset="1" style="stop-color: var(--iris, #b15cd1)" />
					</linearGradient>
				</defs>
				{#if glyph === 'spin'}
					<circle
						cx="12"
						cy="12"
						r="7.5"
						fill="none"
						stroke="url(#{gid})"
						stroke-width="2"
						stroke-dasharray="30 18"
						stroke-linecap="round"
					/>
				{:else if glyph === 'pause'}
					<rect x="7" y="6" width="3.4" height="12" rx="1.2" /><rect
						x="13.6"
						y="6"
						width="3.4"
						height="12"
						rx="1.2"
					/>
				{:else}
					<path d="M8.5 6.2v11.6c0 .8.9 1.3 1.6.9l9-5.8c.6-.4.6-1.3 0-1.7l-9-5.8c-.7-.5-1.6 0-1.6.8z" />
				{/if}
			</svg>
		</button>
	{/if}
</div>

<style>
	/* on the left of the chat bar · pink only ever in a gradient */
	.pvb {
		position: absolute;
		left: 0.25rem;
		bottom: calc(100% + 0.5rem); /* the phone: above the bar's left end */
		z-index: 30;
		opacity: 1;
		pointer-events: none; /* only the button itself ever takes a tap, never its frame */
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
	/* faded out: taps and selections reach whatever is under it */
	.pvb-yield .pvb-main {
		pointer-events: none;
	}

	/* the ghost: a thin ring in the accent gradient, no fill. stepping back to 26 %, giving way to words
	   and stepping aside for the reply's own speaker only ever fade opacity: the compositor's work */
	.pvb-main {
		position: relative;
		isolation: isolate;
		display: grid;
		place-items: center;
		width: 2.5rem;
		height: 2.5rem;
		border-radius: 9999px;
		background: transparent;
		pointer-events: auto;
		transition:
			opacity 0.3s ease,
			transform 0.15s ease;
	}
	.pvb-main::after {
		content: '';
		position: absolute;
		inset: 0;
		z-index: -1;
		border-radius: inherit;
		pointer-events: none;
		background-image: var(--grad-fill, linear-gradient(135deg, #ffcbe2 0%, #ff5bb0 48%, #b15cd1 100%));
		-webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 1.75px), #000 calc(100% - 1.25px));
		mask: radial-gradient(farthest-side, transparent calc(100% - 1.75px), #000 calc(100% - 1.25px));
	}
	.pvb-main:hover {
		transform: scale(1.04);
	}
	.pvb-main:active {
		transform: scale(0.94);
	}
	.pvb-main:focus-visible {
		outline: 2px solid var(--iris, #b15cd1);
		outline-offset: 2px;
	}
	.pvb-ink {
		width: 1.35rem;
		height: 1.35rem;
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
