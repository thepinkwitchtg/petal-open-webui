// 👁 her sight (slice A35): in OWUI everything she can see moves at full beauty. only what is off her screen holds
// its frame (this module: one IntersectionObserver for the page), or everything in a hidden tab (static/loader.js,
// A32), and either way it carries on from where it was once she can see it again.
//  · a watched element wears `data-petal-offscreen` while it is out of view: every css animation inside holds where
//    it is (one rule, beside A32's hidden one) and plays on from there when it comes back
//  · whoever drives motion by hand (a typing job, a WAAPI loop) hears `seen(false | true)` and holds or goes on
//  · watched only while something on it moves (`use:sight={moving}`): at rest nothing is observed
//  · a batch of entries can carry an older word first: only the newest one per element counts
const OFF = 'data-petal-offscreen';

type Seen = (on: boolean) => void;
const watched = new Map<Element, { seen: Seen }>();
let io: IntersectionObserver | null = null;
let styled = false;

/** the one rule: an element off her screen holds every css animation inside it where it is */
export function sightStyle() {
	if (styled || typeof document === 'undefined') return;
	styled = true;
	const el = document.createElement('style');
	el.id = 'petal-sight';
	el.textContent =
		`[${OFF}],[${OFF}]::before,[${OFF}]::after,[${OFF}] *,[${OFF}] *::before,[${OFF}] *::after` +
		'{animation-play-state:paused!important}';
	document.head.appendChild(el);
}

function observer(): IntersectionObserver | null {
	if (io || typeof IntersectionObserver === 'undefined') return io;
	io = new IntersectionObserver((entries) => {
		const newest = new Map<Element, IntersectionObserverEntry>();
		for (const e of entries) newest.set(e.target, e); // entries come in time order: the last one is now
		for (const [el, e] of newest) {
			const w = watched.get(el);
			if (!w) continue;
			const on = e.isIntersecting;
			el.toggleAttribute(OFF, !on);
			try {
				w.seen(on);
			} catch (err) {
				console.warn('🌸 sight:', err);
			}
		}
	});
	return io;
}

/** watch an element while something on it moves · `seen(on)` hears each change · the returned function lets it go
 *  (its css animations play freely again) */
export function watchSight(el: Element, seen: Seen = () => {}): () => void {
	sightStyle();
	const o = observer();
	if (!o) return () => {};
	const w = { seen };
	watched.set(el, w);
	o.observe(el);
	return () => {
		if (watched.get(el) !== w) return;
		watched.delete(el);
		o.unobserve(el);
		el.removeAttribute(OFF);
	};
}

/** is it out of her view right now (as last seen; unwatched counts as in view) */
export const offScreen = (el: Element | null | undefined) => !!el?.hasAttribute(OFF);

type SightArg = boolean | { on?: boolean; seen?: Seen } | null | undefined;

/** svelte action · `use:sight={moving}` or `use:sight={{ on: moving, seen: (on) => … }}`: watched while `on` */
export function sight(node: HTMLElement, arg: SightArg = true) {
	let off: (() => void) | null = null;
	let seen: Seen = () => {};
	const relay: Seen = (on) => seen(on);
	const apply = (a: SightArg) => {
		const on = typeof a === 'object' && a !== null ? (a.on ?? true) : a !== false && a !== null;
		seen = (typeof a === 'object' && a?.seen) || (() => {});
		if (on && !off) off = watchSight(node, relay);
		else if (!on && off) {
			off();
			off = null;
		}
	};
	apply(arg);
	return {
		update: apply,
		destroy() {
			off?.();
			off = null;
		}
	};
}

/** an animation held right at its end (a pause lands on the next frame, so one a frame from its end is held at the
 *  end): playing it again would start it over from nothing, so whoever wakes it finishes it instead */
export const atEnd = (a: Animation) =>
	Number(a.currentTime ?? 0) >= Number(a.effect?.getComputedTiming().endTime ?? Infinity) - 0.5;

/** for her console and the tests: how many elements are watched right now (numbers only) */
export const sightCount = () => watched.size;
