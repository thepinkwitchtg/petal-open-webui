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
// A35 · full beauty while she can see it: every quote that lands framed reveals (no turns to wait), and the gloss
// lives on a quote the whole time it's near her screen, however long she stays still. only off her screen or in a
// hidden or background tab does anything hold, and it holds where it is: a reveal mid-light, the gloss mid-pass, a
// star mid-twinkle all carry on from there when she's back (the reveal's own clock waits with them). a quote waits
// until its reply is done and its words have settled · everything moves on the compositor only (transform,
// opacity) · the gloss steps aside during the quote's reveal and while its words are being selected · reduced
// motion keeps everything still · each star leaves the page when its twinkle ends
import { get } from 'svelte/store';
import { settings } from '$lib/stores';
import { battery, batteryLow, watchBattery } from '$lib/utils/petal-battery';
import { sightStyle } from '$lib/utils/petal-sight';

export type QuoteFxMode = 'still' | 'shimmer' | 'auto';
export type GlossLevel = 'full' | 'glint' | 'off';
export type QuoteHooks = {
	reveal: () => void; // the reveal begins (A18's shimmer, on the layers)
	stop: () => void; // the reveal ends: the quote rests
	gloss: (on: boolean, soft?: boolean) => void; // the light's loop starts, or stops (soft: it fades out)
	hold?: (held: boolean) => void; // A35 · the loop holds where it is (off her screen, a hidden tab), or carries on
	star: () => void; // one faint star by the words
	selecting?: (on: boolean) => void; // words in it are being selected (the layers above step aside)
};

export const PLAY_MS = 5200; // one reveal, first light to rest (counted only while she can see it, A35)
export const SETTLE_MS = 450; // after the reply is done, its words rest this long before a first reveal
export const REPLAY_REST_MS = 700; // a hover can't retrigger the instant a reveal ends
export const NEAR_PX = 120; // the gloss plays on this far before a quote scrolls in: it's gliding as it arrives
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
	glossing: boolean; // its light's loop exists (playing, or holding where it is)
	held: boolean; // its loop holds where it is: off her screen, a hidden tab (A35)
	endedAt: number;
	ticket: number; // the reveal a timer belongs to
	played: number; // ms of the reveal she has seen so far (its clock runs only while she can see it)
	since: number | null; // when its clock last started running (null: holding)
	settleTimer: Timer;
	endTimer: Timer;
};

const quotes = new Map<Element, Quote>();
let io: IntersectionObserver | null = null; // on screen and framed: the reveals
// near the screen: the gloss. the chat scrolls inside its own box, which clips a quote before any margin
// on the screen could reach it, so the margin lives on each quote's own scroller (one watcher per scroller)
const nearIos = new Map<Element | null, IntersectionObserver>();
let wired = false;
let beatTimer: Timer = null;

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

/** how the gloss lives: full · glint (auto, on a low battery that isn't charging) · off (still, reduced motion) ·
 *  A35 · nothing rests because she's still: a quote near her screen glosses as long as it's there */
export function glossLevel(): GlossLevel {
	const mode = fxMode();
	if (mode === 'still' || reducedMotion()) return 'off';
	return mode === 'auto' && batteryLow() ? 'glint' : 'full';
}

/** the gloss may live on it: settled, not revealing, not being selected */
const glossy = (q: Quote) => q.settled && !q.revealing && !q.selecting;
/** she can see its gloss's ground: near her screen, the tab visible */
const nearSight = (q: Quote) => q.near && !hidden();
/** she can see it: on her screen, the tab visible */
const inSight = (q: Quote) => q.onScreen && !hidden();

const revealingCount = () => {
	let n = 0;
	for (const q of quotes.values()) if (q.revealing) n++;
	return n;
};

// ── the gloss: a loop per quote, gliding whenever she can see it ─────────────────────────────────────
/** start or stop one quote's loop (stopping fades it out when anyone could see it, else it just stops ·
 *  past the near edge it's well off-screen, whatever the screen's own watcher has said so far) */
function setGloss(q: Quote, on: boolean) {
	if (on === q.glossing) return;
	q.glossing = on;
	q.held = false;
	if (on) glossCount.shines++;
	try {
		q.hooks.gloss(on, !on && q.onScreen && nearSight(q));
	} catch (e) {
		console.warn('🌸 quote gloss:', e);
	}
}

/** A35 · a loop that exists holds where it is while she can't see it, and glides on from there when she can */
function holdGloss(q: Quote, held: boolean) {
	if (!q.glossing || held === q.held) return;
	q.held = held;
	try {
		q.hooks.hold?.(held);
	} catch (e) {
		console.warn('🌸 quote gloss hold:', e);
	}
}

/** every quote's loop as it should be right now, and the stars' beat · a loop is made the first time its quote
 *  comes near her screen (never for quotes far down a long chat), and after that only holds or glides */
function glossPump() {
	const full = glossLevel() === 'full';
	for (const q of quotes.values()) {
		if (!full || !glossy(q)) setGloss(q, false);
		else if (nearSight(q)) {
			if (!q.glossing) setGloss(q, true);
			else holdGloss(q, false);
		} else holdGloss(q, true);
	}
	beat();
}

// ── its stars: one clock for the page, ticking only while some quote glosses (or glints) ─────────────
function stopBeat() {
	if (beatTimer) clearTimeout(beatTimer);
	beatTimer = null;
}

function beat() {
	const level = glossLevel();
	let any = false;
	if (level !== 'off') for (const q of quotes.values()) if (glossy(q) && inSight(q)) any = true;
	if (!any) return stopBeat();
	if (beatTimer) return;
	beatTimer = setTimeout(tick, level === 'glint' ? rnd(GLINT_MS) : rnd(STAR_BEAT_MS));
}

function star(q: Quote) {
	if (!glossy(q) || !inSight(q) || glossLevel() === 'off') return; // things changed since it was planned
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
	if (level === 'off') return; // the setting or a quote landing starts it again
	const ready = [...quotes.values()].filter((q) => glossy(q) && inSight(q));
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
	q.since = null;
	q.hooks.stop();
	q.revealing = false;
	q.endedAt = Date.now();
}

function endReveal(q: Quote, ticket: number) {
	if (ticket !== q.ticket || !q.revealing) return;
	clearEnd(q);
	q.since = null;
	q.hooks.stop();
	q.revealing = false;
	q.endedAt = Date.now();
	pump(); // its loop comes back at once
}

/** A35 · the reveal's clock runs only while she can see it: off her screen or in a hidden tab its light holds
 *  where it is (its css waits too: data-petal-offscreen, A32's hidden rule) and the rest of its play waits with it */
function clock(q: Quote) {
	if (!q.revealing) return;
	const now = performance.now();
	if (inSight(q)) {
		if (q.since !== null) return;
		q.since = now;
		const ticket = q.ticket;
		q.endTimer = setTimeout(() => endReveal(q, ticket), Math.max(0, PLAY_MS - q.played));
	} else if (q.since !== null) {
		q.played += now - q.since;
		q.since = null;
		clearEnd(q);
	}
}

function startReveal(q: Quote) {
	++q.ticket;
	q.seen = true;
	q.revealing = true;
	q.played = 0;
	q.since = null;
	setGloss(q, false); // the reveal is its own light: the loop steps aside meanwhile
	glossCount.reveals++;
	try {
		q.hooks.reveal();
	} catch (e) {
		console.warn('🌸 quote reveal:', e);
	}
	clock(q);
}

const motionAllowed = () => !hidden() && !reducedMotion() && fxMode() !== 'still';

/** every settled quote that lands framed gets its first reveal, in page order, all of them at once (A35: no turns
 *  to wait); then every quote's gloss as it should be */
function pump() {
	if (motionAllowed()) {
		for (const q of quotes.values()) {
			if (!q.settled || !q.framed || q.seen || q.revealing) continue;
			startReveal(q);
		}
	}
	glossPump();
}

/** A35 · nothing rests because she's still, so there's nothing to keep awake: kept for its callers (the battery
 *  measure) */
export function holdAwake(_key: string, _on: boolean) {}

/** her sight of one quote changed (on screen, near, the tab): its css holds or plays on, its reveal's clock waits
 *  or runs, its loop holds or glides */
function look(q: Quote) {
	q.el.toggleAttribute('data-petal-offscreen', !q.onScreen);
	clock(q);
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
	sightStyle(); // data-petal-offscreen holds a quote's css where it is (petal-sight's one rule)
	io = new IntersectionObserver(
		(entries) => {
			const tall = window.innerHeight * 0.4;
			for (const e of entries) {
				const q = quotes.get(e.target);
				if (!q) continue;
				q.onScreen = e.isIntersecting;
				q.framed =
					e.isIntersecting && (e.intersectionRatio >= 0.4 || e.intersectionRect.height >= tall);
				look(q); // off her screen it holds where it is (A35), back on it it carries on
			}
			pump();
		},
		{ threshold: [0, 0.4, 1] }
	);
	// a hidden or background tab, a minimized window: everything holds where it is (A32's rule holds the css, the
	// reveal's clock and the loop wait here); coming back, all of it carries on and a quote that arrived meanwhile
	// has its first reveal
	document.addEventListener('visibilitychange', () => {
		for (const q of quotes.values()) clock(q);
		if (hidden()) {
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
		if (q) q.near = e.isIntersecting; // in time order: the newest word for each quote is the one that stays
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
		held: false,
		endedAt: 0,
		ticket: 0,
		played: 0,
		since: null,
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
		el.removeAttribute('data-petal-offscreen');
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
 *  a hover waits a moment after the last reveal; a click or her voice plays it at once */
export function replay(el: HTMLElement, insist = false): boolean {
	const q = quotes.get(el);
	if (!q || !q.settled || !q.onScreen || !motionAllowed()) return false;
	if (q.revealing) return true;
	if (!insist && Date.now() - q.endedAt < REPLAY_REST_MS) return false;
	startReveal(q);
	return true;
}

/** her voice reached this quote: its reveal plays again */
export const voiceReveal = (el: HTMLElement) => replay(el, true);

/** how many quotes reveal right now (for tests and the eyes) */
export const moving = () => revealingCount();

/** how many quotes the door knows right now (A35, for tests and the eyes: a quote that left the page leaves it) */
export const enrolled = () => quotes.size;

/** how many quotes' loops run right now (for tests and the eyes) */
export const glossing = () => [...quotes.values()].filter((q) => q.glossing).length;
