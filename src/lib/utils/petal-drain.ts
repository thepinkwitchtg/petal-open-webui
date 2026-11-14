// 🔋 a battery measure (A19): how much the phone drains in a session with the quotes' gloss on.
// started from Settings → Interface (beside Quotes), it reads the battery now and again after the window,
// keeps the screen awake and the gloss awake meanwhile (as if she were reading), and reports numbers only:
// the drop, the time, how long the tab was visible, the mode, and what moved.
import { get, writable } from 'svelte/store';
import { toast } from 'svelte-sonner';
import { battery, batteryNow, watchBattery } from '$lib/utils/petal-battery';
import { fxMode, glossCount, holdAwake } from '$lib/utils/petal-quote-fx';

export type DrainResult = {
	drop: number; // percentage points lost (a gain while charging reads negative)
	ms: number; // how long it ran
	visibleMs: number; // of which the tab was visible
	mode: string;
	charged: boolean; // it was charging at some point (the drop means little then)
	reveals: number;
	shines: number;
	stars: number;
};
export type DrainState = { running: boolean; endsAt: number; last: DrainResult | null };

export const DRAIN_MS = 10 * 60_000;
export const drain = writable<DrainState>({ running: false, endsAt: 0, last: null });

type WakeLockLike = { release: () => Promise<void> };
let run: {
	start: number;
	level: number;
	counts: typeof glossCount;
	visibleMs: number;
	visibleSince: number | null;
	charged: boolean;
	timer: ReturnType<typeof setTimeout>;
	lock: WakeLockLike | null;
	onVis: () => void;
	unsub: () => void;
} | null = null;

const pct = (n: number) => Math.round(n * 100);
const mmss = (ms: number) => {
	const s = Math.round(ms / 1000);
	return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

async function wakeLock(): Promise<WakeLockLike | null> {
	try {
		const wl = (navigator as Navigator & {
			wakeLock?: { request: (t: 'screen') => Promise<WakeLockLike> };
		}).wakeLock;
		return wl ? await wl.request('screen') : null;
	} catch {
		return null;
	}
}

/** start a measure (minutes default to 10) · false when the battery can't be read here */
export async function startDrain(ms = DRAIN_MS): Promise<boolean> {
	if (run) return true;
	await watchBattery();
	const b = batteryNow();
	if (!b.supported || b.level === null) return false;
	const visible = () => document.visibilityState === 'visible';
	const r = {
		start: Date.now(),
		level: b.level,
		counts: { ...glossCount },
		visibleMs: 0,
		visibleSince: visible() ? Date.now() : null,
		charged: !!b.charging,
		timer: setTimeout(() => finishDrain(), ms),
		lock: await wakeLock(),
		onVis: () => {},
		unsub: () => {}
	};
	r.onVis = () => {
		if (visible()) {
			r.visibleSince ??= Date.now();
			// the screen lock is let go while hidden; it's asked for again on return
			if (!r.lock) wakeLock().then((l) => (r.lock = l));
		} else if (r.visibleSince !== null) {
			r.visibleMs += Date.now() - r.visibleSince;
			r.visibleSince = null;
			r.lock = null;
		}
	};
	document.addEventListener('visibilitychange', r.onVis);
	r.unsub = battery.subscribe((now) => {
		if (now.charging) r.charged = true; // it charged meanwhile: the drop means little
	});
	run = r;
	holdAwake('drain', true);
	drain.set({ running: true, endsAt: r.start + ms, last: get(drain).last });
	return true;
}

/** end it now (cancel: no report) or when its time is up (report) */
export function finishDrain(cancel = false) {
	const r = run;
	if (!r) return;
	run = null;
	clearTimeout(r.timer);
	document.removeEventListener('visibilitychange', r.onVis);
	r.unsub();
	r.lock?.release().catch(() => {});
	holdAwake('drain', false);
	if (r.visibleSince !== null) r.visibleMs += Date.now() - r.visibleSince;
	const b = batteryNow();
	if (cancel || b.level === null) {
		drain.set({ running: false, endsAt: 0, last: get(drain).last });
		return;
	}
	const res: DrainResult = {
		drop: pct(r.level) - pct(b.level),
		ms: Date.now() - r.start,
		visibleMs: r.visibleMs,
		mode: fxMode(),
		charged: r.charged || !!b.charging,
		reveals: glossCount.reveals - r.counts.reveals,
		shines: glossCount.shines - r.counts.shines,
		stars: glossCount.stars - r.counts.stars
	};
	drain.set({ running: false, endsAt: 0, last: res });
	toast.success(drainLine(res), { duration: 30_000 });
}

/** the report, numbers only */
export const drainLine = (r: DrainResult) =>
	`🔋 −${r.drop}% in ${mmss(r.ms)} · visible ${mmss(r.visibleMs)} · ${r.mode}${r.charged ? ' · ⚡' : ''} · ✨ ${r.reveals} · ${r.shines} shines · ${r.stars} stars`;
