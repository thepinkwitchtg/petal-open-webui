// 🌸 the display quote's door (slices A18 · A19 · A21 · A22). one door decides WHEN a display quote may
// move; PetalQuote decides how it looks. its words never wait on the door: they're painted first, in their
// own ink, and everything the door starts only ever sits on top of them or behind them.
//
// Settings → Interface → Quotes: still · shimmer · auto
//  · still   · the quote at rest (its gradient, its gloss, its halo), nothing moves
//  · shimmer · the reveal plays once as a quote lands framed on screen (a hover, a click or her voice
//              plays it again), and the gloss lives on it the whole time it's on screen (A22): a glossy
//              light gliding across its words, pass after pass with no pause, and now and then a faint star
//  · auto    · the shimmer, minding the battery: low and not charging, the gloss becomes a rare faint star
//              (and her voice's follower goes simpler)
//
// what it keeps for the GPU (the 3080, the phone): a quote waits until its reply is done and its words
// have settled · three reveals at most · everything moves on the compositor only (transform, opacity) ·
// the gloss runs while a quote is on screen (it starts a little before one scrolls in, so it's already
// gliding when it arrives) and stops off-screen, in a hidden or background tab or a minimized window,
// during the quote's reveal and while its words are being selected, after a few minutes without her
// (unless her voice is playing), and with reduced motion (nothing moves at all)
import { get } from 'svelte/store';
import { settings } from '$lib/stores';
import { battery, batteryLow, watchBattery } from '$lib/utils/petal-battery';

export type QuoteFxMode = 'still' | 'shimmer' | 'auto';
export type GlossLevel = 'full' | 'glint' | 'off';
export type QuoteHooks = {
	reveal: () => void; // the reveal begins (A18's shimmer, on the layers)
	stop: () => void; // the reveal ends: the quote rests
	gloss: (on: boolean, soft?: boolean) => void; // the light's loop starts, or stops (soft: it fades out)
	star: () => void; // one faint star by the words
	selecting?: (on: boolean) => void; // words in it are being selected (the layers above step aside)
};

export const PLAY_MS = 5200; // one reveal, first light to rest
export const SETTLE_MS = 450; // after the reply is done, its words rest this long before a first reveal
export const MAX_MOVING = 3; // reveals at once (a page full of quotes takes turns)
export const REPLAY_REST_MS = 700; // a hover can't retrigger the instant a reveal ends
export const IDLE_MS = 3 * 60_000; // the gloss rests after this long without her (her voice keeps it awake)
export const NEAR_PX = 120; // the gloss starts this far before a quote scrolls in: it's gliding as it arrives
export const STAR_BEAT_MS: [number, number] = [6000, 10000]; // a faint star or two on the page, this often
export const MAX_STARS = 2; // per beat
export const GLINT_MS: [number, number] = [25000, 40000]; // low battery: one faint star on the page, this far apart

type Timer = ReturnType<typeof setTimeout> | null;
type Quote = {
	el: HTMLElement;
	hooks: QuoteHooks;
	raw: string;
	done: boolean;
	settled: boolean; // done, and its words stopped changing
	framed: boolean; // enough of it on screen to reveal
	onScreen: boolean; // any of it on screen
	near: boolean; // on screen, or about to scroll in (the gloss's own edge)
	seen: boolean; // its first reveal has started
	revealing: boolean;
	selecting: boolean;
	glossing: boolean; // its light's loop is running
	endedAt: number;
	ticket: number; // the reveal a timer belongs to
	settleTimer: Timer;
	endTimer: Timer;
};

const quotes = new Map<Element, Quote>();
let io: IntersectionObserver | null = null; // on screen and framed: the reveals
// near the screen: the gloss. the chat scrolls inside its own box, which clips a quote before any margin
// on the screen could reach it, so the margin lives on each quote's own scroller (one watcher per scroller)
const nearIos = new Map<Element | null, IntersectionObserver>();
let wired = false;
let lastInput = Date.now();
const awake = new Set<string>(); // what keeps the gloss awake without her touch (her voice, a battery measure)
let beatTimer: Timer = null;
let idleTimer: Timer = null;

/** how much has moved, for the battery measure and the tests (a shine is a gloss loop starting) */
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

/** the gloss may live on it: settled, near the screen, not revealing, not being selected */
const glossy = (q: Quote) => q.settled && q.near && !q.revealing && !q.selecting;

const revealingCount = () => {
	let n = 0;
	for (const q of quotes.values()) if (q.revealing) n++;
	return n;
};

// ── the gloss: a loop per quote, running whenever it may ─────────────────────────────────────────────
/** start or stop one quote's loop (stopping fades it out when anyone could see it, else it just stops ·
 *  past the near edge it's well off-screen, whatever the screen's own watcher has said so far) */
function setGloss(q: Quote, on: boolean) {
	if (on === q.glossing) return;
	q.glossing = on;
	if (on) glossCount.shines++;
	try {
		q.hooks.gloss(on, !on && q.onScreen && q.near && !hidden());
	} catch (e) {
		console.warn('🌸 quote gloss:', e);
	}
}

/** every quote's loop as it should be right now, and the stars' beat */
function glossPump() {
	const full = glossLevel() === 'full';
	let any = false;
	for (const q of quotes.values()) {
		setGloss(q, full && glossy(q));
		any ||= q.glossing;
	}
	if (any) watchIdle();
	else stopIdle(); // nothing glides: nothing to rest
	beat();
}

const anyGlossing = () => [...quotes.values()].some((q) => q.glossing);

function stopIdle() {
	if (idleTimer) clearTimeout(idleTimer);
	idleTimer = null;
}

/** a few minutes without her: the loops rest (her touch or her voice wakes them) */
function watchIdle() {
	if (idleTimer || awake.size || !anyGlossing()) return; // her voice holds it awake (letting go starts the count again)
	idleTimer = setTimeout(
		() => {
			idleTimer = null;
			if (away()) glossPump();
			else watchIdle();
		},
		Math.max(1000, lastInput + IDLE_MS - Date.now())
	);
}

// ── its stars: one clock for the page, ticking only while some quote glosses (or glints) ─────────────
function stopBeat() {
	if (beatTimer) clearTimeout(beatTimer);
	beatTimer = null;
}

function beat() {
	const level = glossLevel();
	let any = false;
	if (level !== 'off') for (const q of quotes.values()) if (glossy(q) && q.onScreen) any = true;
	if (!any) return stopBeat();
	if (beatTimer) return;
	beatTimer = setTimeout(tick, level === 'glint' ? rnd(GLINT_MS) : rnd(STAR_BEAT_MS));
}

function star(q: Quote) {
	if (!glossy(q) || !q.onScreen || glossLevel() === 'off') return; // things changed since it was planned
	try {
		q.hooks.star();
		glossCount.stars++;
	} catch (e) {
		console.warn('🌸 quote star:', e);
	}
}

function tick() {
	beatTimer = null;
	const level = glossLevel();
	if (level === 'off') return; // her touch, the tab, the setting or a quote landing starts it again
	const ready = [...quotes.values()].filter((q) => glossy(q) && q.onScreen);
	// a faint star or two by the words (on a low battery, one for the whole page, far apart)
	const n = Math.min(ready.length, level === 'glint' ? 1 : Math.random() < 0.5 ? 1 : MAX_STARS);
	for (let i = 0; i < n; i++) {
		const q = ready[Math.floor(Math.random() * ready.length)];
		setTimeout(() => star(q), i * (400 + Math.random() * 900));
	}
	beat();
}

// ── the reveal ───────────────────────────────────────────────────────────────────────────────────────
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
	pump(); // its loop comes back at once
}

function startReveal(q: Quote) {
	const ticket = ++q.ticket;
	q.seen = true;
	q.revealing = true;
	setGloss(q, false); // the reveal is its own light: the loop steps aside meanwhile
	glossCount.reveals++;
	try {
		q.hooks.reveal();
	} catch (e) {
		console.warn('🌸 quote reveal:', e);
	}
	q.endTimer = setTimeout(() => endReveal(q, ticket), PLAY_MS);
}

const motionAllowed = () => !hidden() && !reducedMotion() && fxMode() !== 'still';

/** every settled quote that lands framed gets its first reveal, in page order, while there's room; then
 *  every quote's gloss as it should be */
function pump() {
	if (motionAllowed()) {
		for (const q of quotes.values()) {
			if (!q.settled || !q.framed || q.seen || q.revealing) continue;
			if (revealingCount() >= MAX_MOVING) break;
			startReveal(q);
		}
	}
	glossPump();
}

/** keep the gloss awake without her touch while `key` holds (her voice playing, a battery measure) */
export function holdAwake(key: string, on: boolean) {
	if (on) awake.add(key);
	else awake.delete(key);
	if (on) glossPump();
	else watchIdle(); // let go: the idle count resumes from her last touch
}

function onInput() {
	const was = away();
	lastInput = Date.now();
	if (was) glossPump();
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
		glossPump(); // selecting: its loop steps aside · done: it comes back
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
	// at once and a quote that arrived meanwhile has its first reveal
	document.addEventListener('visibilitychange', () => {
		if (hidden()) {
			for (const q of quotes.values()) rest(q);
			stopBeat();
			glossPump();
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
			stopBeat(); // the stars' new rhythm starts from the next beat
		}
		last = mode;
		pump();
	});
	// auto follows the battery: a low one turns the loops into rare stars, charging brings them back
	watchBattery();
	let low = batteryLow();
	battery.subscribe(() => {
		if (batteryLow() === low) return;
		low = batteryLow();
		stopBeat();
		glossPump();
	});
	for (const ev of ['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart', 'scroll'])
		window.addEventListener(ev, onInput, { passive: true, capture: true });
	document.addEventListener('selectionchange', onSelection);
}

/** the box a quote scrolls in (the chat's), or the screen when it scrolls with the page */
function scroller(el: HTMLElement): Element | null {
	if (typeof getComputedStyle !== 'function') return null;
	for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
		const oy = getComputedStyle(p).overflowY;
		if (oy === 'auto' || oy === 'scroll' || oy === 'overlay') return p;
	}
	return null;
}

function onNear(entries: IntersectionObserverEntry[]) {
	for (const e of entries) {
		const q = quotes.get(e.target);
		if (q) q.near = e.isIntersecting;
	}
	glossPump();
}

/** the watcher for that box, its margin reaching NEAR_PX past its edges */
function nearIoFor(el: HTMLElement): IntersectionObserver | null {
	if (typeof IntersectionObserver === 'undefined') return null;
	const root = scroller(el);
	let o = nearIos.get(root);
	if (!o) {
		o = new IntersectionObserver(onNear, { root, rootMargin: `${NEAR_PX}px 0px` });
		nearIos.set(root, o);
	}
	return o;
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
		near: false,
		seen: false,
		revealing: false,
		selecting: false,
		glossing: false,
		endedAt: 0,
		ticket: 0,
		settleTimer: null,
		endTimer: null
	};
	quotes.set(el, q);
	io?.observe(el);
	const near = nearIoFor(el);
	near?.observe(el);
	return () => {
		io?.unobserve(el);
		near?.unobserve(el);
		if (q.settleTimer) clearTimeout(q.settleTimer);
		rest(q);
		q.near = false;
		setGloss(q, false);
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
	if (changed || doneChanged) {
		settle(q);
		glossPump(); // unsettled words: its loop stops until they rest
	}
}

/** a hover, a click or her voice: the reveal once more, if it's settled, on screen and allowed to move.
 *  a hover waits its turn (and a moment after the last reveal); a click or her voice goes first */
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

/** how many quotes' loops run right now (for tests and the eyes) */
export const glossing = () => [...quotes.values()].filter((q) => q.glossing).length;
