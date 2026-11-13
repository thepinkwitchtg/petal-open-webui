// 🌸 the display quote's door (slices A18 + A18b). one door decides WHEN a reply's display quote may
// move and WHO paints it; the painters decide how it looks:
//  · the shimmer: the fork's own light (CSS in PetalQuote), instant, no canvas. it plays once as a quote
//    settles into view and rests in the static gradient
//  · the candy: the rig's quote effect, if one is awake (window.petalQuoteFx, woken by /static/loader.js
//    through /api/v1/petal/fx/*). it paints the quote on a stage under the words, and the words stay real
//    (transparent while painted) for selection, copy and voice
//
// Settings → Interface → Quotes: still · shimmer · candy · candy hypnotic
//  · still: A17's static quote, nothing moves
//  · shimmer: the shimmer plays once when a quote lands framed on screen; a hover or a tap replays it
//  · candy: the candy blooms once when a quote lands framed, then rests as a still; hover or tap replays
//  · candy hypnotic: the candy keeps flowing while framed and she's active, and rests after ~20 s idle
//  candy falls back to the shimmer, never to still: when no effect is awake, or when the effect says a
//  quote isn't one for it (fits(): a long or list-heavy quote, say)
//
// the rules it keeps for the GPU (the 3080, the phone): a quote waits until its reply is done and its
// words have settled · three move at most · nothing moves off-screen or in a hidden tab · reduced motion
// means no motion (the shimmer rests, the candy is dressed still)
//
// the effect answers play(el, call) · replay(el, call) and may answer fits(el, call) · rest(el) (stop
// moving now, keep the look) · release(el) (forget its drawing: the words changed, the setting moved on,
// or the quote left). play and replay may return a promise that settles when a bloom comes to rest.
import { get } from 'svelte/store';
import { settings } from '$lib/stores';

export type QuoteFxMode = 'still' | 'shimmer' | 'candy' | 'hypnotic';
export type CandyMode = 'still' | 'once' | 'flow';
export type QuoteFxCall = { mode: CandyMode; words: string };
export interface QuoteFx {
	play(el: HTMLElement, call: QuoteFxCall): unknown;
	replay(el: HTMLElement, call: QuoteFxCall): unknown;
	fits?(el: HTMLElement, call: QuoteFxCall): boolean;
	rest?(el: HTMLElement): void;
	release?(el: HTMLElement): void;
}
export type ShimmerHooks = { play: () => void; stop: () => void };

declare global {
	interface Window {
		petalQuoteFx?: QuoteFx;
		petalFxOpen?: () => Promise<boolean>;
	}
}

export const PLAY_MS = 5200; // one shimmer, first light to rest
export const SETTLE_MS = 450; // after the reply is done, its words rest this long before a first play
export const MAX_MOVING = 3; // a page full of quotes takes turns (shimmers and candy together)
export const IDLE_MS = 20000; // candy hypnotic rests after this long without her input
export const PLAY_CAP_MS = 12000; // a candy bloom that never says it rested is stopped here
export const NOMINAL_MS = 5000; // a bloom from an effect that doesn't say when it rests holds its slot this long
export const REPLAY_REST_MS = 700; // a hover can't retrigger the instant a play ends
export const FX_EVENT = 'petal-quote-fx'; // the effect announces itself on window

type Paint = 'none' | 'shimmer' | 'candy';
type Timer = ReturnType<typeof setTimeout> | null;
type Quote = {
	el: HTMLElement;
	hooks: ShimmerHooks;
	raw: string;
	done: boolean;
	settled: boolean; // done, and its words stopped changing
	framed: boolean; // enough of it on screen to play
	onScreen: boolean; // any of it on screen
	paint: Paint; // who paints its current words
	fitsFor: string | null; // the words the candy last judged…
	fits: boolean; // …and its answer
	seen: boolean; // its first play (with its current painter) has started
	dressed: boolean; // the candy holds a drawing of these words
	moving: boolean; // a shimmer, a bloom or a flow is running
	shimmering: boolean; // the moving is a shimmer
	flowing: boolean; // the moving is a candy flow
	endedAt: number;
	ticket: number; // the play a timer or a settling promise belongs to
	settleTimer: Timer;
	endTimer: Timer;
};

const quotes = new Map<Element, Quote>();
let io: IntersectionObserver | null = null;
let wired = false;
let rested = false; // flows were rested for her absence; her next touch wakes them
let lastInput = Date.now();
let idleTimer: Timer = null;

/** she hasn't touched anything for IDLE_MS */
const away = () => Date.now() - lastInput >= IDLE_MS;

const effect = (): QuoteFx | null => {
	const f = typeof window !== 'undefined' ? window.petalQuoteFx : undefined;
	return f && typeof f.play === 'function' && typeof f.replay === 'function' ? f : null;
};

const reducedMotion = () =>
	typeof window !== 'undefined' &&
	!!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

const hidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden';

/** the setting (Settings → Interface → Quotes); A18's old switch, if it was turned off, reads as still */
export function fxMode(): QuoteFxMode {
	const s = get(settings);
	const m = s?.quoteFx;
	if (m === 'still' || m === 'shimmer' || m === 'candy' || m === 'hypnotic') return m;
	return s?.quoteShimmer === false ? 'still' : 'candy';
}

/** how the candy may move right now (hypnotic while she's away: a quote landing just blooms) */
const candyMode = (): CandyMode =>
	reducedMotion() ? 'still' : fxMode() === 'hypnotic' && !away() ? 'flow' : 'once';

const movingCount = () => {
	let n = 0;
	for (const q of quotes.values()) if (q.moving) n++;
	return n;
};

const words = (q: Quote) => (q.el.innerText || q.el.textContent || '').trim();

function clearEnd(q: Quote) {
	if (q.endTimer) clearTimeout(q.endTimer);
	q.endTimer = null;
}

/** stop a quote moving now; it keeps its look (the shimmer's resting gradient, the candy's still) */
function rest(q: Quote) {
	if (!q.moving) return;
	q.ticket++;
	clearEnd(q);
	if (q.shimmering) q.hooks.stop();
	else effect()?.rest?.(q.el);
	q.moving = q.shimmering = q.flowing = false;
	q.endedAt = Date.now();
}

function endMove(q: Quote, ticket: number, capped: boolean) {
	if (ticket !== q.ticket || !q.moving) return;
	clearEnd(q);
	if (q.shimmering) q.hooks.stop();
	else if (capped) effect()?.rest?.(q.el);
	q.moving = q.shimmering = q.flowing = false;
	q.endedAt = Date.now();
	pump();
}

function startShimmer(q: Quote) {
	const ticket = ++q.ticket;
	q.seen = true;
	q.moving = q.shimmering = true;
	q.hooks.play();
	q.endTimer = setTimeout(() => endMove(q, ticket, false), PLAY_MS);
}

function callFx(q: Quote, verb: 'play' | 'replay', mode: CandyMode): unknown {
	const f = effect();
	if (!f) return null;
	q.dressed = true;
	try {
		return f[verb](q.el, { mode, words: words(q) });
	} catch (e) {
		console.warn('🌸 quote fx:', e);
		return null;
	}
}

function startCandy(q: Quote, verb: 'play' | 'replay', mode: CandyMode) {
	const ticket = ++q.ticket;
	q.seen = true;
	q.moving = true;
	q.flowing = mode === 'flow';
	const r = callFx(q, verb, mode);
	if (q.flowing) {
		armIdle();
		return;
	}
	q.endTimer = setTimeout(() => endMove(q, ticket, true), PLAY_CAP_MS);
	if (r && typeof (r as Promise<unknown>).then === 'function')
		(r as Promise<unknown>).then(
			() => endMove(q, ticket, false),
			() => endMove(q, ticket, false)
		);
	else setTimeout(() => endMove(q, ticket, false), NOMINAL_MS);
}

/** drop the candy's drawing of this quote (A17's ink comes back) */
function undress(q: Quote) {
	if (q.moving && !q.shimmering) rest(q);
	if (q.dressed) effect()?.release?.(q.el);
	q.dressed = false;
}

/** who paints this settled quote now: still → nobody · shimmer → the shimmer · candy → the candy when
 *  an effect is awake and the quote is one for it, else the shimmer. a change of painter starts fresh */
function choose(q: Quote): Paint {
	const mode = fxMode();
	let paint: Paint = mode === 'still' ? 'none' : 'shimmer';
	const f = mode === 'candy' || mode === 'hypnotic' ? effect() : null;
	if (f) {
		if (q.fitsFor !== q.raw) {
			q.fitsFor = q.raw;
			try {
				q.fits = f.fits ? f.fits(q.el, { mode: candyMode(), words: words(q) }) !== false : true;
			} catch {
				q.fits = false;
			}
		}
		if (q.fits) paint = 'candy';
	}
	if (paint !== q.paint) {
		if (q.moving) rest(q);
		if (q.paint === 'candy') undress(q);
		q.paint = paint;
		q.seen = false;
	}
	return paint;
}

/** give every settled quote on screen what the setting allows, in page order, while there's room */
function pump() {
	if (hidden()) return;
	const motion = !reducedMotion();
	for (const q of quotes.values()) {
		if (!q.settled || !q.onScreen || q.moving) continue;
		const paint = choose(q);
		if (paint === 'none') continue;
		const room = movingCount() < MAX_MOVING;
		if (paint === 'shimmer') {
			if (!q.seen && q.framed && motion && room) startShimmer(q);
			continue;
		}
		const cm = candyMode();
		if (cm === 'still') {
			if (!q.dressed) callFx(q, 'play', 'still');
			continue;
		}
		if (!q.seen) {
			// its first bloom, once it lands framed (a quote already dressed still is asked to bloom again)
			if (q.framed && room) startCandy(q, q.dressed ? 'replay' : 'play', cm);
			continue;
		}
		if (!q.dressed) {
			callFx(q, 'play', 'still');
			continue;
		}
		if (cm === 'flow' && q.framed && room) startCandy(q, 'play', 'flow');
	}
}

// ── hypnotic's rest: no input for IDLE_MS, every flow rests; her next touch wakes the framed ones ──
function armIdle() {
	if (idleTimer || typeof window === 'undefined') return;
	idleTimer = setTimeout(
		() => {
			idleTimer = null;
			if (away()) {
				rested = true;
				for (const q of quotes.values()) if (q.flowing) rest(q);
			} else if ([...quotes.values()].some((q) => q.flowing)) armIdle();
		},
		Math.max(250, IDLE_MS - (Date.now() - lastInput))
	);
}

function onInput() {
	const back = rested || away();
	lastInput = Date.now();
	if (back) {
		rested = false;
		pump();
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
	// a hidden tab stops everything; coming back, a quote that arrived meanwhile has its first play
	document.addEventListener('visibilitychange', () => {
		if (hidden()) for (const q of quotes.values()) rest(q);
		else pump();
	});
	window.matchMedia?.('(prefers-reduced-motion: reduce)').addEventListener?.('change', (e) => {
		if (e.matches) for (const q of quotes.values()) rest(q);
		pump();
	});
	let last: QuoteFxMode | null = null;
	settings.subscribe(() => {
		const mode = fxMode();
		if (last !== null && mode !== last && last === 'hypnotic')
			for (const q of quotes.values()) if (q.flowing) rest(q);
		if ((mode === 'candy' || mode === 'hypnotic') && quotes.size)
			window.petalFxOpen?.().catch(() => {}); // knock on the rig's door (quiet if it's asleep)
		last = mode;
		pump(); // choose() moves every quote on screen to its new painter
	});
	for (const ev of ['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart'])
		window.addEventListener(ev, onInput, { passive: true, capture: true });
	// an effect waking late: quotes it may paint are judged again
	window.addEventListener(FX_EVENT, () => {
		for (const q of quotes.values()) q.fitsFor = null;
		pump();
	});
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
export function enroll(el: HTMLElement, hooks: ShimmerHooks): () => void {
	wire();
	const q: Quote = {
		el,
		hooks,
		raw: '',
		done: false,
		settled: false,
		framed: false,
		onScreen: false,
		paint: 'none',
		fitsFor: null,
		fits: false,
		seen: false,
		dressed: false,
		moving: false,
		shimmering: false,
		flowing: false,
		endedAt: 0,
		ticket: 0,
		settleTimer: null,
		endTimer: null
	};
	quotes.set(el, q);
	io?.observe(el);
	if (fxMode() === 'candy' || fxMode() === 'hypnotic') window.petalFxOpen?.().catch(() => {});
	return () => {
		io?.unobserve(el);
		if (q.settleTimer) clearTimeout(q.settleTimer);
		rest(q);
		undress(q);
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
		undress(q);
		q.paint = 'none';
		q.seen = false;
	}
	if (changed || doneChanged) settle(q);
}

/** a hover or a tap: play it once more, if it's settled, on screen and allowed to move */
export function replay(el: HTMLElement) {
	const q = quotes.get(el);
	if (!q || !q.settled || !q.onScreen || hidden() || reducedMotion()) return;
	if (q.paint === 'none' || Date.now() - q.endedAt < REPLAY_REST_MS) return;
	if (q.paint === 'candy' && q.flowing) {
		callFx(q, 'replay', 'flow'); // a flow blooms again and keeps flowing
		return;
	}
	if (q.moving || movingCount() >= MAX_MOVING) return;
	if (q.paint === 'shimmer') startShimmer(q);
	else if (effect()) startCandy(q, 'replay', candyMode());
}

/** how many quotes are moving, and how many of them shimmer (for tests and the eyes) */
export const moving = () => movingCount();
export const shimmering = () => [...quotes.values()].filter((q) => q.shimmering).length;
