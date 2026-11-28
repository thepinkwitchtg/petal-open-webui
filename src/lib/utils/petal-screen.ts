// 🪟 one screen alive (slice A49). since 0.13.4's tabs more than one chat can be mounted at once: the page's own
// chat and each tab's chat. on the phone the tabs drawer covers the page's chat (both keep running underneath), and a
// tab behind another is parked, hidden (still mounted, still working). only what she can see runs now:
//  · each chat is a screen (`newScreen`), alive while she can see it. a screen she can't see wears
//    `data-petal-inert` on its root: every css animation inside it holds (one rule), her sight (petal-sight) reads
//    everything in it as off screen (Markdown waits, every motion driven by hand holds), her voice's trail is never
//    drawn there and her eyes never pick a reply there (petal-voice), hush writes only in a field she can see
//  · the voice's listeners inside an inert screen let go (`gate`): nothing upstream hears from them, and alive again
//    they read the voice as it is now (a value, never a replay)
//  · nothing is unmounted: a hidden chat keeps its state (her draft, a reply still arriving, the place it was
//    scrolled to); it simply does no work she can't see. alive again, everything shows where it is now
// 🧪 a lever, for measuring only: `localStorage.petalScreens = 'all-alive'` keeps every screen alive, as before A49
// (her console: `petalScreens.census()` counts what each screen runs, numbers only)
import { get, readable, writable, type Readable } from 'svelte/store';

const INERT = 'data-petal-inert';
const MARK = 'data-petal-screen';

export type ScreenKind = 'main' | 'tab';
export type PetalScreen = {
	id: string;
	kind: ScreenKind;
	/** alive: she can see it (and so it works) */
	active: Readable<boolean>;
	/** what its chat says about being seen (the lever may keep it alive anyway) */
	set: (seen: boolean) => void;
	isAlive: () => boolean;
	root: () => HTMLElement | null;
	attach: (el: HTMLElement | null) => void;
	destroy: () => void;
};

type Inner = PetalScreen & { el: HTMLElement | null; alive: boolean; seen: boolean; flips: number };
const screens = new Map<string, Inner>();
const listeners = new Set<() => void>();
let made = 0;
let queued = false;

/** 🧪 the lever (measuring only): every screen stays alive, as before A49 */
export const allAlive = (): boolean => {
	try {
		return typeof localStorage !== 'undefined' && localStorage.getItem('petalScreens') === 'all-alive';
	} catch {
		return false;
	}
};

let styled = false;
/** the one rule: inside a screen she can't see, every css animation holds where it is · a screen can sit inside
 *  another (a wide screen keeps its tabs inside the page's chat; the phone parks a tab there): a scope stops at the next
 *  screen's root, so each element answers to the screen nearest to it (an inert page's chat never holds a tab in
 *  front of it, an inert tab inside a living page's chat holds) */
function inertStyle() {
	if (styled || typeof document === 'undefined') return;
	styled = true;
	const el = document.createElement('style');
	el.id = 'petal-screens';
	el.textContent =
		`@scope ([${INERT}]) to ([${MARK}]){:scope,:scope::before,:scope::after,*,*::before,*::after` +
		'{animation-play-state:paused!important}}';
	document.head.appendChild(el);
}

/** everyone who follows the screens hears once per change, on a microtask (a drawer opening flips two at once) */
function tell() {
	if (queued) return;
	queued = true;
	queueMicrotask(() => {
		queued = false;
		for (const fn of [...listeners])
			try {
				fn();
			} catch (err) {
				console.warn('🪟 screens:', err);
			}
	});
}

function paint(s: Inner) {
	if (!s.el) return;
	s.el.setAttribute(MARK, s.kind);
	s.el.toggleAttribute(INERT, !s.alive);
}

/** a chat's screen (Chat.svelte makes one and lends it to everything inside through the `petal-screen` context) */
export function newScreen(kind: ScreenKind): PetalScreen {
	const id = `${kind}-${++made}`;
	const alive = writable(true);
	const s: Inner = {
		id,
		kind,
		el: null,
		alive: true,
		seen: true,
		flips: 0,
		active: { subscribe: alive.subscribe },
		set(seen: boolean) {
			s.seen = seen;
			const next = seen || allAlive();
			if (next === s.alive) return;
			s.alive = next;
			s.flips += 1;
			alive.set(next);
			paint(s);
			tell();
		},
		isAlive: () => s.alive,
		root: () => s.el,
		attach(el: HTMLElement | null) {
			if (s.el === el) return;
			if (s.el) {
				s.el.removeAttribute(INERT);
				s.el.removeAttribute(MARK);
			}
			s.el = el;
			inertStyle();
			paint(s);
			tell();
		},
		destroy() {
			if (s.el) {
				s.el.removeAttribute(INERT);
				s.el.removeAttribute(MARK);
			}
			s.el = null;
			screens.delete(id);
			tell();
		}
	};
	screens.set(id, s);
	exposeConsole();
	return s;
}

/** svelte action · `use:screenRoot={screen}`: this element is the screen's root (its chat's container) */
export function screenRoot(node: HTMLElement, screen: PetalScreen | null | undefined) {
	let s = screen ?? null;
	s?.attach(node);
	return {
		update(next: PetalScreen | null | undefined) {
			if (next === s) return;
			if (s?.root() === node) s.attach(null);
			s = next ?? null;
			s?.attach(node);
		},
		destroy() {
			if (s?.root() === node) s.attach(null);
		}
	};
}

/** is this inside a chat screen she can't see (an element, a text node or a range's end) · the screen nearest to it
 *  decides (a tab in front of the page's chat lives inside the page's chat's box on a wide screen) */
export function inertAt(n: Node | null | undefined): boolean {
	const el = !n ? null : n.nodeType === 1 ? (n as Element) : n.parentElement;
	const root = el?.closest?.(`[${MARK}]`);
	return !!root && root.hasAttribute(INERT);
}

/** hear every screen that comes alive or goes inert (once per change, on a microtask) */
export function onScreens(fn: () => void): () => void {
	listeners.add(fn);
	return () => {
		listeners.delete(fn);
	};
}

/** a screen that is always alive: for what lives outside any chat (the diary page, a test harness) */
export const everAlive: PetalScreen = {
	id: 'page',
	kind: 'main',
	active: readable(true),
	set: () => {},
	isAlive: () => true,
	root: () => null,
	attach: () => {},
	destroy: () => {}
};

// ── the gates: the voice's listeners inside a screen let go while it's inert ──────────────────────────────────
type GateRec = { screen: string; name: string; live: boolean };
const gates = new Set<GateRec>();

/** a store as a screen sees it: subscribed upstream only while the screen is alive. inert, nothing upstream hears
 *  from it and its last value stays; alive again it reads the store as it is now (one value, never a replay). a
 *  subscriber that arrives while the screen is inert still gets the value of that moment, read once */
export function gate<T>(store: Readable<T>, screen: PetalScreen | null | undefined, name: string): Readable<T> {
	const s = screen ?? everAlive;
	return {
		subscribe(run, invalidate) {
			const rec: GateRec = { screen: s.id, name, live: false };
			gates.add(rec);
			let up: (() => void) | null = null;
			let first = true;
			const offAlive = s.active.subscribe((alive) => {
				if (alive && !up) {
					up = store.subscribe(run, invalidate);
					rec.live = true;
				} else if (!alive && up) {
					up();
					up = null;
					rec.live = false;
				} else if (!alive && first) run(get(store)); // a value to start from, read once
				first = false;
			});
			return () => {
				offAlive();
				up?.();
				up = null;
				gates.delete(rec);
			};
		}
	};
}

// ── the census (her console and the tests, numbers only) ───────────────────────────────────────────────────────
type Extra = () => Record<string, Record<string, number>>; // per screen id: counts another module knows
const extras = new Map<string, Extra>();
/** another module adds its own counts per screen (petal-voice: replies, trail; petal-sight: watched) */
export function countIn(name: string, fn: Extra) {
	extras.set(name, fn);
}

/** which screen an element belongs to (its id), or 'page' outside any */
export function screenIdOf(n: Node | null | undefined): string {
	const el = !n ? null : n.nodeType === 1 ? (n as Element) : n.parentElement;
	const root = el?.closest?.(`[${MARK}]`);
	if (!root) return 'page';
	for (const s of screens.values()) if (s.el === root) return s.id;
	return 'page';
}

export function census() {
	const out: Record<string, Record<string, unknown>> = {};
	for (const s of screens.values()) {
		const el = s.el;
		const all = (sel: string) => (el ? el.querySelectorAll(sel).length : 0);
		out[s.id] = {
			kind: s.kind,
			alive: s.alive,
			seen: s.seen,
			flips: s.flips,
			lists: all('#messages-container, [id^="note-messages-"]'),
			replies: all('[id^="message-"]:has(.assistant-message-profile-image)'),
			fields: el ? [...el.querySelectorAll('[contenteditable="true"]')].length : 0,
			trail_leads: all('.pv-lead'),
			trail_marks: all('.pv-mark'),
			running_animations: 0,
			voice_listeners: 0,
			voice_listeners_let_go: 0
		};
	}
	out.page = { running_animations: 0, voice_listeners: 0 };
	if (typeof document !== 'undefined')
		for (const a of document.getAnimations()) {
			if (a.playState !== 'running') continue;
			const t = (a.effect as KeyframeEffect | null)?.target ?? null;
			const id = screenIdOf(t);
			const row = out[id] ?? out.page;
			row.running_animations = (row.running_animations as number) + 1;
		}
	for (const g of gates) {
		const row = out[g.screen] ?? out.page;
		if (g.live) row.voice_listeners = ((row.voice_listeners as number) ?? 0) + 1;
		else row.voice_listeners_let_go = ((row.voice_listeners_let_go as number) ?? 0) + 1;
	}
	for (const [name, fn] of extras)
		try {
			for (const [id, counts] of Object.entries(fn())) {
				const row = out[id] ?? (out[id] = {});
				for (const [k, v] of Object.entries(counts)) row[`${name}_${k}`] = v;
			}
		} catch {}
	return { screens: out, all_alive_lever: allAlive() };
}

let exposed = false;
function exposeConsole() {
	if (exposed || typeof window === 'undefined') return;
	exposed = true;
	(window as unknown as { petalScreens?: object }).petalScreens = {
		census,
		/** 🧪 the lever: 'all-alive' (every screen works, as before A49) or 'one' (the default) · reload after */
		lever(v: 'all-alive' | 'one' = 'one') {
			try {
				if (v === 'all-alive') localStorage.setItem('petalScreens', 'all-alive');
				else localStorage.removeItem('petalScreens');
			} catch {}
			return `${v} · reload the page`;
		}
	};
}
