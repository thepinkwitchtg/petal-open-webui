// 🌸 the display quote's door (slices A18 · A19). one door decides WHEN a display quote may move;
// PetalQuote decides how it looks. its words never wait on the door: they're painted first, in their
// own ink, and everything the door starts only ever sits on top of them or behind them.
//
// Settings → Interface → Quotes: still · shimmer · auto
//  · still   · the quote at rest (its gradient, its gloss, its halo), nothing moves
//  · shimmer · the reveal plays once as a quote lands framed on screen (a hover, a click or her voice
//              plays it again), and a gentle gloss lives on it while it's on screen: a slow shine, faint stars
//  · auto    · the shimmer, minding the battery: low and not charging, the gloss becomes a rare glint
//              (and her voice's follower goes simpler)
//
// what it keeps for the GPU (the 3080, the phone): a quote waits until its reply is done and its words
// have settled · three reveals at most · the gloss moves only on the compositor (transform, opacity), in
// shared beats: one clock for the page, every few seconds a beat where two quotes catch the light together
// and a faint star or two rides along, then stillness until the next one. so its frames run in short
// stretches, however many quotes are on screen. it rests off-screen, in a hidden or background tab or a
// minimized window, after a few minutes without her (unless her voice is playing), and with reduced motion
// · reduced motion means nothing moves at all
import { get } from 'svelte/store';
import { settings } from '$lib/stores';
import { battery, batteryLow, watchBattery } from '$lib/utils/petal-battery';

export type QuoteFxMode = 'still' | 'shimmer' | 'auto';
export type GlossLevel = 'full' | 'glint' | 'off';
export type QuoteHooks = {
	reveal: () => void; // the reveal begins (A18's shimmer, on the layers)
	stop: () => void; // the reveal ends: the quote rests
	shine: () => void; // one slow band of light across the words
	star: () => void; // one faint star by the words
	selecting?: (on: boolean) => void; // words in it are being selected (the layers above step aside)
};

export const PLAY_MS = 5200; // one reveal, first light to rest
export const SETTLE_MS = 450; // after the reply is done, its words rest this long before a first reveal
export const MAX_MOVING = 3; // reveals at once (a page full of quotes takes turns)
export const REPLAY_REST_MS = 700; // a hover can't retrigger the instant a reveal ends
export const IDLE_MS = 3 * 60_000; // the gloss rests after this long without her (her voice keeps it awake)
// the gloss's rhythm, in ms ranges (each wait is drawn anew)
export const BEAT_MS: [number, number] = [5500, 8500]; // between two beats of the page's clock
export const BREATH_MS = 2500; // a quote's first shine waits this long after its reveal
export const GLINT_MS: [number, number] = [25000, 40000]; // low battery: one glint on the page, this far apart
export const MAX_SHINES = 2; // per beat: the quotes that shone longest ago catch the light together
export const MAX_STARS = 2; // per beat: a faint star or two rides along

type Timer = ReturnType<typeof setTimeout> | null;
type Quote = {
	el: HTMLElement;
	hooks: QuoteHooks;
	raw: string;
	done: boolean;
	settled: boolean; // done, and its words stopped changing
	framed: boolean; // enough of it on screen to reveal
	onScreen: boolean; // any of it on screen
	seen: boolean; // its first reveal has started (the gloss comes after it)
	revealing: boolean;
	selecting: boolean;
	endedAt: number;
	ticket: number; // the reveal a timer belongs to
	lastShine: number; // when it last caught the light (the beat goes to whoever waited longest)
	settleTimer: Timer;
	endTimer: Timer;
};

const quotes = new Map<Element, Quote>();
let io: IntersectionObserver | null = null;
let wired = false;
let lastInput = Date.now();
const awake = new Set<string>(); // what keeps the gloss awake without her touch (her voice, a battery measure)
let beatTimer: Timer = null;

/** how much has moved, for the battery measure and the tests */
export const glossCount = { reveals: 0, shines: 0, stars: 0 };

const reducedMotion = () =>
	typeof window !== 'undefined' &&
	!!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

const hidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden';

const rnd = ([a, b]: [number, number]) => a + Math.random() * (b - a);

/** the setting (Settings → Interface → Quotes) · A18b's candy left the chat, its moving rides on as auto;
 *  A18's old switch, if it was turned off, reads as still */
export function fxMode(): QuoteFxMode {
	const s = get(settings) as { quoteFx?: string; quoteShimmer?: boolean } | undefined;
	const m = s?.quoteFx;
	if (m === 'still' || m === 'shimmer' || m === 'auto') return m;
	if (m === 'candy' || m === 'hypnotic') return 'auto';
	return s?.quoteShimmer === false ? 'still' : 'auto';
}

const away = () => !awake.size && Date.now() - lastInput >= IDLE_MS;

/** how the gloss lives right now: full · glint (auto, on a low battery that isn't charging) · off */
export function glossLevel(): GlossLevel {
	const mode = fxMode();
	if (mode === 'still' || reducedMotion() || hidden() || away()) return 'off';
	return mode === 'auto' && batteryLow() ? 'glint' : 'full';
}

/** the gloss lives on it: settled, on screen, past its first reveal, not revealing, not being selected */
const glossy = (q: Quote) => q.settled && q.onScreen && q.seen && !q.revealing && !q.selecting;
/** and a beat may take it now: a breath past its last reveal */
const eligible = (q: Quote) => glossy(q) && Date.now() - q.endedAt >= BREATH_MS;

const revealingCount = () => {
	let n = 0;
	for (const q of quotes.values()) if (q.revealing) n++;
	return n;
};

function clearEnd(q: Quote) {
	if (q.endTimer) clearTimeout(q.endTimer);
	q.endTimer = null;
}

/** stop a reveal now; the quote keeps its resting look */
function rest(q: Quote) {
	if (!q.revealing) return;
	q.ticket++;
	clearEnd(q);
	q.hooks.stop();
	q.revealing = false;
	q.endedAt = Date.now();
}

function endReveal(q: Quote, ticket: number) {
	if (ticket !== q.ticket || !q.revealing) return;
	clearEnd(q);
	q.hooks.stop();
	q.revealing = false;
	q.endedAt = Date.now();
	pump();
}

function startReveal(q: Quote) {
	const ticket = ++q.ticket;
	q.seen = true;
	q.revealing = true;
	glossCount.reveals++;
	try {
		q.hooks.reveal();
	} catch (e) {
		console.warn('🌸 quote reveal:', e);
	}
	q.endTimer = setTimeout(() => endReveal(q, ticket), PLAY_MS);
}

const motionAllowed = () => !hidden() && !reducedMotion() && fxMode() !== 'still';

/** every settled quote that lands framed gets its first reveal, in page order, while there's room */
function pump() {
	if (motionAllowed()) {
		for (const q of quotes.values()) {
			if (!q.settled || !q.framed || q.seen || q.revealing) continue;
			if (revealingCount() >= MAX_MOVING) break;
			startReveal(q);
		}
	}
	beat();
}

// ── the gloss: one clock for the page, ticking only while some quote can gloss ───────────────────────
function stopBeat() {
	if (beatTimer) clearTimeout(beatTimer);
	beatTimer = null;
}

function beat() {
	const level = glossLevel();
	let any = false;
	if (level !== 'off') for (const q of quotes.values()) if (glossy(q)) any = true;
	if (!any) return stopBeat();
	if (beatTimer) return;
	beatTimer = setTimeout(tick, level === 'glint' ? rnd(GLINT_MS) : rnd(BEAT_MS));
}

function glint(q: Quote, kind: 'shine' | 'star') {
	if (!eligible(q) || glossLevel() === 'off') return; // things changed since it was planned
	try {
		if (kind === 'shine') q.hooks.shine();
		else q.hooks.star();
		glossCount[kind === 'shine' ? 'shines' : 'stars']++;
	} catch (e) {
		console.warn('🌸 quote gloss:', e);
	}
}

function tick() {
	beatTimer = null;
	const level = glossLevel();
	if (level === 'off') return; // her touch, the tab, the setting or a quote landing starts it again
	const ready = [...quotes.values()].filter(eligible);
	if (level === 'glint') {
		// one glint on the page: a star most times, now and then a shine
		const q = ready[Math.floor(Math.random() * ready.length)];
		if (q) glint(q, Math.random() < 0.3 ? 'shine' : 'star');
	} else if (ready.length) {
		// a beat: the quotes that shone longest ago catch the light together (never in lockstep), and a
		// faint star or two rides along while the light crosses · then stillness until the next beat
		const now = Date.now();
		const order = [...ready].sort((a, b) => a.lastShine - b.lastShine || Math.random() - 0.5);
		order.slice(0, MAX_SHINES).forEach((q, i) => {
			q.lastShine = now;
			setTimeout(() => glint(q, 'shine'), i * 220);
		});
		const stars = Math.min(MAX_STARS, Math.random() < 0.5 ? 1 : 2);
		for (let i = 0; i < stars; i++) {
			const q = ready[Math.floor(Math.random() * ready.length)];
			setTimeout(() => glint(q, 'star'), 600 + Math.random() * 900);
		}
	}
	beat();
}

/** keep the gloss awake without her touch while `key` holds (her voice playing, a battery measure) */
export function holdAwake(key: string, on: boolean) {
	if (on) awake.add(key);
	else awake.delete(key);
	if (on) beat();
}

function onInput() {
	const was = away();
	lastInput = Date.now();
	if (was) beat();
}

function onSelection() {
	const sel = document.getSelection();
	const range = sel && !sel.isCollapsed && sel.rangeCount ? sel.getRangeAt(0) : null;
	for (const q of quotes.values()) {
		let on = false;
		try {
			on = !!range && range.intersectsNode(q.el);
		} catch {}
		if (on === q.selecting) continue;
		q.selecting = on;
		q.hooks.selecting?.(on);
		if (!on) beat();
	}
}

function wire() {
	if (wired || typeof window === 'undefined' || typeof IntersectionObserver === 'undefined') return;
	wired = true;
	io = new IntersectionObserver(
		(entries) => {
			const tall = window.innerHeight * 0.4;
			for (const e of entries) {
				const q = quotes.get(e.target);
				if (!q) continue;
				q.onScreen = e.isIntersecting;
				q.framed =
					e.isIntersecting && (e.intersectionRatio >= 0.4 || e.intersectionRect.height >= tall);
				if (!q.onScreen) rest(q); // nothing moves off-screen
			}
			pump();
		},
		{ threshold: [0, 0.4, 1] }
	);
	// a hidden or background tab, a minimized window: everything rests; coming back, the gloss picks up
	// and a quote that arrived meanwhile has its first reveal
	document.addEventListener('visibilitychange', () => {
		if (hidden()) {
			for (const q of quotes.values()) rest(q);
			stopBeat();
		} else pump();
	});
	window.matchMedia?.('(prefers-reduced-motion: reduce)').addEventListener?.('change', (e) => {
		if (e.matches) {
			for (const q of quotes.values()) rest(q);
			stopBeat();
		}
		pump();
	});
	let last: QuoteFxMode | null = null;
	settings.subscribe(() => {
		const mode = fxMode();
		if (last !== null && mode !== last) {
			if (mode === 'still') for (const q of quotes.values()) rest(q);
			stopBeat(); // the new rhythm starts from the next beat
		}
		last = mode;
		pump();
	});
	// auto follows the battery: a low one slows the clock to rare glints, charging brings it back
	watchBattery();
	let low = batteryLow();
	battery.subscribe(() => {
		if (batteryLow() === low) return;
		low = batteryLow();
		stopBeat();
		beat();
	});
	for (const ev of ['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart', 'scroll'])
		window.addEventListener(ev, onInput, { passive: true, capture: true });
	document.addEventListener('selectionchange', onSelection);
}

function settle(q: Quote) {
	q.settled = false;
	if (q.settleTimer) clearTimeout(q.settleTimer);
	q.settleTimer = null;
	if (!q.done) return;
	q.settleTimer = setTimeout(() => {
		q.settleTimer = null;
		q.settled = true;
		pump();
	}, SETTLE_MS);
}

/** a display quote joins the door; the returned function lets it go (on destroy) */
export function enroll(el: HTMLElement, hooks: QuoteHooks): () => void {
	wire();
	const q: Quote = {
		el,
		hooks,
		raw: '',
		done: false,
		settled: false,
		framed: false,
		onScreen: false,
		seen: false,
		revealing: false,
		selecting: false,
		endedAt: 0,
		ticket: 0,
		lastShine: 0,
		settleTimer: null,
		endTimer: null
	};
	quotes.set(el, q);
	io?.observe(el);
	return () => {
		io?.unobserve(el);
		if (q.settleTimer) clearTimeout(q.settleTimer);
		rest(q);
		quotes.delete(el);
		pump();
	};
}

/** its words or its reply's state changed: new words start fresh and wait to settle again */
export function touch(el: HTMLElement, raw: string, done: boolean) {
	const q = quotes.get(el);
	if (!q) return;
	const changed = raw !== q.raw;
	const doneChanged = done !== q.done;
	q.raw = raw;
	q.done = done;
	if (changed) {
		rest(q);
		q.seen = false;
	}
	if (changed || doneChanged) settle(q);
}

/** a hover, a click or her voice: the reveal once more, if it's settled, on screen and allowed to move.
 *  a hover waits its turn (and a breath after the last reveal); a click or her voice goes first */
export function replay(el: HTMLElement, insist = false): boolean {
	const q = quotes.get(el);
	if (!q || !q.settled || !q.onScreen || !motionAllowed()) return false;
	if (q.revealing) return true;
	if (!insist && (Date.now() - q.endedAt < REPLAY_REST_MS || revealingCount() >= MAX_MOVING))
		return false;
	startReveal(q);
	return true;
}

/** her voice reached this quote: its reveal plays again */
export const voiceReveal = (el: HTMLElement) => replay(el, true);

/** how many quotes reveal right now (for tests and the eyes) */
export const moving = () => revealingCount();
