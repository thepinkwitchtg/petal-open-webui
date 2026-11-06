// 🌸 petal · toasts that leave with one tap or one sideways flick (sprint slice A5)
//
// why: on her phone the stock toasts spanned the top, sat over the sidebar + new-chat
// buttons, had a tiny x and lingered — and during a trip she forked chats by accident
// working around them. so, under html.petal only:
//
//   · tap a toast (< 8 px travel, < 350 ms) anywhere but its action button → it goes
//   · flick it sideways ≥ 48 px, either way → it goes (sonner keeps its own vertical swipe;
//     it hands sideways moves back by itself, so the two never fight)
//   · either way we press the toast's own [data-close-button], so sonner runs its own exit
//   · the click that follows a dismissing tap is consumed in capture: nothing under the
//     toast ever receives it, even after the toast has slid away (the ghost click)
//   · the top bar's real height is measured whenever the toaster appears, so the pill
//     lands just under it (toasts.css reads --petal-topbar-h)
//   · lifetimes: 3200 ms default (the Toaster's own prop) · 6000 errors · 8000 with an
//     action — filled in only when the caller didn't choose one
//   · a date in a title or description keeps its hyphens whole (U+2011) on a narrow pill
//
// one delegated set of listeners, passive where they can be, no rAF, nothing runs idle.
import { toast } from 'svelte-sonner';

const TAP_PX = 8;
const TAP_MS = 350;
const SWIPE_PX = 48;
const DRAG_START_PX = 10; // the same touch slop sonner uses before it commits to a direction
const GHOST_MS = 650;
const GHOST_PX = 28;

export const PETAL_TOAST_MS = { default: 3200, error: 6000, action: 8000 } as const;

const isPetal = () => document.documentElement.classList.contains('petal');

type Press = {
	id: number;
	x: number;
	y: number;
	t: number;
	el: HTMLElement;
	onButton: boolean;
	sideways: boolean;
};

// ── lifetimes ───────────────────────────────────────────────
// sonner has no per-type duration and keeps its store private, but every typed call
// (toast.error, toast.success, …) is a property of the one shared `toast` object.
type Method = 'message' | 'success' | 'info' | 'warning' | 'error';
const METHODS: Method[] = ['message', 'success', 'info', 'warning', 'error'];

// a date in a toast never breaks at its hyphens on a narrow pill ("2026-" / "11-05")
const NB = (v: unknown) =>
	typeof v === 'string' ? v.replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, '$1\u2011$2\u2011$3') : v;

const installDurations = () => {
	const original = new Map<Method, (...a: any[]) => any>();
	for (const m of METHODS) {
		const fn = (toast as any)[m];
		if (typeof fn !== 'function' || fn.__petal) continue;
		original.set(m, fn);
		const wrapped = (message: unknown, data?: Record<string, any>) => {
			if (!isPetal()) return fn(message, data);
			message = NB(message);
			if (data && typeof data.description === 'string') data = { ...data, description: NB(data.description) };
			if (data && data.duration !== undefined) return fn(message, data);
			const duration = data?.action
				? PETAL_TOAST_MS.action
				: m === 'error'
					? PETAL_TOAST_MS.error
					: undefined; // the Toaster's 3200 default
			return fn(message, duration === undefined ? data : { ...data, duration });
		};
		(wrapped as any).__petal = true;
		(toast as any)[m] = wrapped;
	}
	return () => original.forEach((fn, m) => ((toast as any)[m] = fn));
};

// ── the top bar, measured (never guessed) ───────────────────
const measureTopbar = () => {
	let h = 0;
	for (const nav of document.querySelectorAll('nav')) {
		const r = nav.getBoundingClientRect();
		if (r.height > 0 && r.top <= 8 && r.bottom > 0) h = Math.max(h, r.height);
	}
	if (h > 0) document.documentElement.style.setProperty('--petal-topbar-h', `${Math.round(h)}px`);
};

// ── install ─────────────────────────────────────────────────
export const installPetalToasts = (host?: HTMLElement | null): (() => void) => {
	let press: Press | null = null;
	let ghost: { until: number; x: number; y: number } | null = null;

	const clearDrag = (el: HTMLElement) => {
		el.style.removeProperty('--petal-dx');
		el.style.removeProperty('--petal-fade');
		delete el.dataset.petalDrag;
	};

	const dismiss = (el: HTMLElement) => {
		const x = el.querySelector<HTMLElement>('[data-close-button]');
		x?.click(); // sonner's own exit (deleteToast + onDismiss)
	};

	const onDown = (e: PointerEvent) => {
		if (!isPetal() || (e.pointerType === 'mouse' && e.button !== 0)) return;
		const target = e.target as Element | null;
		const el = target?.closest?.('[data-sonner-toast]') as HTMLElement | null;
		if (!el || el.dataset.removed === 'true') return;
		press = {
			id: e.pointerId,
			x: e.clientX,
			y: e.clientY,
			t: performance.now(),
			el,
			// the action button keeps its own meaning; the x (desktop) closes by itself
			onButton: !!target?.closest('[data-button], [data-cancel], [data-close-button], a'),
			sideways: false
		};
	};

	const onMove = (e: PointerEvent) => {
		if (!press || e.pointerId !== press.id || press.onButton) return;
		const dx = e.clientX - press.x;
		const dy = e.clientY - press.y;
		if (!press.sideways && Math.abs(dx) > DRAG_START_PX && Math.abs(dx) > Math.abs(dy)) press.sideways = true;
		if (press.sideways) {
			press.el.dataset.petalDrag = 'true';
			press.el.style.setProperty('--petal-dx', `${dx}px`); // follows the finger (toasts.css)
			press.el.style.setProperty('--petal-fade', `${1 - Math.min(0.6, Math.abs(dx) / 160)}`);
		}
	};

	const onUp = (e: PointerEvent) => {
		if (!press || e.pointerId !== press.id) return;
		const p = press;
		press = null;
		const dx = e.clientX - p.x;
		const dy = e.clientY - p.y;
		const tap = Math.abs(dx) < TAP_PX && Math.abs(dy) < TAP_PX && performance.now() - p.t < TAP_MS;
		const flick = p.sideways && Math.abs(dx) >= SWIPE_PX;
		if (p.onButton || !(tap || flick)) {
			clearDrag(p.el); // not enough: it slides back
			return;
		}
		if (flick) {
			// let go: transitions come back and it glides off its own side while sonner fades it
			delete p.el.dataset.petalDrag;
			p.el.style.removeProperty('--petal-fade');
			p.el.style.setProperty('--petal-dx', `${Math.sign(dx) * 110}%`);
		} else {
			clearDrag(p.el);
		}
		dismiss(p.el);
		ghost = { until: performance.now() + GHOST_MS, x: e.clientX, y: e.clientY }; // after our own .click()
	};

	const onCancel = (e: PointerEvent) => {
		if (!press || e.pointerId !== press.id) return;
		clearDrag(press.el);
		press = null;
	};

	// the tap is consumed in capture: its click never reaches anything — not the toast's
	// body, and not whatever sat under it once it slid away
	const onClick = (e: MouseEvent) => {
		if (!ghost) return;
		const near = Math.hypot(e.clientX - ghost.x, e.clientY - ghost.y) < GHOST_PX;
		if (performance.now() > ghost.until || !near) {
			if (performance.now() > ghost.until) ghost = null;
			return;
		}
		ghost = null;
		e.preventDefault();
		e.stopPropagation();
		e.stopImmediatePropagation();
	};

	const opts = { capture: true, passive: true } as const;
	window.addEventListener('pointerdown', onDown, opts);
	window.addEventListener('pointermove', onMove, opts);
	window.addEventListener('pointerup', onUp, opts);
	window.addEventListener('pointercancel', onCancel, opts);
	window.addEventListener('click', onClick, { capture: true });

	// the toaster only exists while toasts do: measure the bar each time it appears
	// (childList on the host only — chat streaming elsewhere never wakes this)
	const observer = host
		? new MutationObserver(() => {
				if (isPetal() && host.querySelector('[data-sonner-toaster]')) measureTopbar();
			})
		: null;
	observer?.observe(host!, { childList: true });

	const restoreDurations = installDurations();

	return () => {
		window.removeEventListener('pointerdown', onDown, opts);
		window.removeEventListener('pointermove', onMove, opts);
		window.removeEventListener('pointerup', onUp, opts);
		window.removeEventListener('pointercancel', onCancel, opts);
		window.removeEventListener('click', onClick, { capture: true });
		observer?.disconnect();
		restoreDurations();
	};
};
