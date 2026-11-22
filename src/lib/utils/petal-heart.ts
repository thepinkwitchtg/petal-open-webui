// 💗 the heart by send (slice A39) — her bar regrouped under one heart. one tap opens a picker where every Petal
// control lives (the mode, the next reply's pick, her voice, the trip window, the fusion check, her pinned filters),
// with deeper menus where a control has more to it. she keeps one or two of them pinned on the bar beside it.
//  · the pins are hers per device (this browser's own storage, never synced: the phone and the rig differ);
//    defaults: 🎧 on the phone (beside the mic, where it was), nothing on the desktop · two at most: a third pin
//    lets the oldest go
//  · the controls stay mounted while unpinned (only their chips hide), so their keys keep working on the desktop
//    (Ctrl+Space steps the mode, Ctrl+Alt+P asks for a pick, or whatever she bound in Settings → Shortcuts)
//  · one placement for every sheet that opens from the bar (the picker, the trip window): on the phone a sheet the
//    width of the screen, held inside what she can see above the keyboard; on the desktop a panel above its button
import { writable, get } from 'svelte/store';

export type HeartPin = 'mode' | 'pick' | 'ear' | 'trip' | `filter:${string}`;
export const PIN_MAX = 2;
const KEY = 'petal-heart-pins';

/** a phone (or a tablet): a coarse pointer and no hover, or a narrow screen */
export const phoneLike = (): boolean => {
	try {
		return (
			(matchMedia('(pointer: coarse)').matches && !matchMedia('(hover: hover)').matches) ||
			matchMedia('(max-width: 640px)').matches
		);
	} catch {
		return false;
	}
};

export const pinDefaults = (phone = phoneLike()): HeartPin[] => (phone ? ['ear'] : []);

const isPin = (v: unknown): v is HeartPin =>
	typeof v === 'string' && (['mode', 'pick', 'ear', 'trip'].includes(v) || (v.startsWith('filter:') && v.length > 7));

/** her pins as kept on this device (a missing or broken entry takes the defaults; an empty list is hers) */
export function pinsOf(raw: string | null, phone = phoneLike()): HeartPin[] {
	if (raw === null) return pinDefaults(phone);
	try {
		const v = JSON.parse(raw);
		return Array.isArray(v) ? [...new Set(v.filter(isPin))].slice(-PIN_MAX) : pinDefaults(phone);
	} catch {
		return pinDefaults(phone);
	}
}

const stored = (): string | null => {
	try {
		return localStorage.getItem(KEY);
	} catch {
		return null;
	}
};

export const heartPins = writable<HeartPin[]>(typeof window === 'undefined' ? [] : pinsOf(stored()));

/** pin or unpin one control (a third pin lets the oldest go) · returns her pins now */
export function togglePin(key: HeartPin): HeartPin[] {
	const now = get(heartPins);
	const next = now.includes(key) ? now.filter((k) => k !== key) : [...now, key].slice(-PIN_MAX);
	heartPins.set(next);
	try {
		localStorage.setItem(KEY, JSON.stringify(next));
	} catch {}
	return next;
}

/** the picker's open state (one heart per bar; a split view's second bar opens its own) */
export const heartOpen = writable<string | null>(null);

export type Place = { phone: boolean; left: number; width: number; bottom: number; maxH: number };

/** where a sheet opened from the bar goes: the phone gets the screen's width (8 px from each edge), held between
 *  the top of what she sees and the bar (or the keyboard, whichever is higher); the desktop gets `width` px above
 *  its button, its right edge at the button's (or its left edge, `align: 'start'`) */
export function placeSheet(anchor: HTMLElement, width: number, align: 'end' | 'start' = 'end'): Place {
	const r = anchor.getBoundingClientRect();
	const vw = window.innerWidth;
	const ih = window.innerHeight;
	const vv = window.visualViewport;
	const seenTop = vv?.offsetTop ?? 0;
	const seenBottom = vv ? vv.offsetTop + vv.height : ih;
	const floor = Math.min(r.top, seenBottom); // the bar's top, or the keyboard's, whichever is higher
	const room = Math.max(160, floor - seenTop - 16);
	if (phoneLike()) {
		return { phone: true, left: 8, width: vw - 16, bottom: Math.max(8, ih - floor + 8), maxH: room };
	}
	const w = Math.min(width, vw - 16);
	const left = align === 'end' ? r.right - w : r.left;
	return {
		phone: false,
		left: Math.min(Math.max(8, left), vw - w - 8),
		width: w,
		bottom: Math.max(8, ih - floor + 8),
		maxH: room
	};
}
