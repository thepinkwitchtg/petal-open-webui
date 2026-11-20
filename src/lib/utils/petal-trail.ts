// ✨ the trail (slices A19b · A20 · A21 · A22): where her voice is, as a run of pink under the words she's
// saying. Lily's pick (A21): sparkles and many four-ray stars scattered above and below the line, most
// falling a little, a few floating up, some twinkling on their way out, and now and then a soft petal
// drifting down. a leading sparkle travels the sentence's road on the compositor; every mark appears right
// where her voice is and fades where it fell. it moves only while a sentence plays: it holds still when she
// pauses, and rests off-screen, in a hidden tab or a minimized window. reduced motion shows a still dot
// under her sentence; a low battery (auto quotes) keeps the lead alone. on a phone it flows at 60 %.
// A33 · pinned to her voice: the lead goes where the audio's own clock says (each sentence's road laid from the
// rig's B7 timings) and never past it. a lead that got ahead of her (a stall the page never heard of, a clock that
// ran on) eases down and waits for her voice, still once she's far behind; it never jumps back over road it
// already ran, so it can't loop. each road ends at its sentence's end: past the last sentence the rig has told,
// it rests instead of guessing.
import { batteryLow, deviceKind } from '$lib/utils/petal-battery';

type Spot = { x: number; y: number };

const POOL = 64; // marks kept for reuse (past it, the oldest is reused)
const PETAL_SHARE = 0.035; // now and then a petal among the sparkles
const PHONE_FLOW = 0.6; // a phone's main thread pays for each mark: there it flows at 60 %
const EASE_MS = 400; // a lead this far ahead of her voice holds still; closer, it slows in proportion

const T = (x: number, y: number, extra = '') => `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) ${extra}`;
const either = () => (Math.random() < 0.5 ? -1 : 1);

/** a sparkle or a four-ray star, scattered above and below the line; most fall a little, a few float up,
 *  some stars twinkle on their way out · each lives 0.8–2 s */
function sparkle(s: HTMLElement, at: Spot) {
	const star = Math.random() < 0.45;
	const twinkle = star && Math.random() < 0.4;
	const size = star ? 6 + Math.random() * 8 : 2 + Math.random() * 7;
	s.className = `pv-mark pv-dust${star ? ' pv-star' : ''}`;
	s.style.removeProperty('--pv-core'); // a reused mark may still wear a petal's tint
	s.style.setProperty('--s', `${size.toFixed(1)}px`);
	const x = at.x + (Math.random() - 0.5) * 12;
	const y = at.y + (Math.random() - 0.5) * 16;
	const dx = (Math.random() - 0.5) * 12;
	const dy = Math.random() < 0.25 ? -(2 + Math.random() * 6) : 2 + Math.random() * 8;
	const turn = star ? either() * (10 + Math.random() * 40) : 0;
	const peak = 0.8 + Math.random() * 0.2;
	const out = 'ease-out';
	const frames: Keyframe[] = twinkle
		? [
				{ transform: T(x, y, 'scale(0.5)'), opacity: 0, easing: out },
				{ transform: T(x, y, 'scale(1)'), opacity: peak, offset: 0.05, easing: out },
				{ transform: T(x + dx * 0.4, y + dy * 0.4, `scale(0.7) rotate(${turn * 0.4}deg)`), opacity: peak * 0.3, offset: 0.42 },
				{ transform: T(x + dx * 0.55, y + dy * 0.55, `scale(1.25) rotate(${turn * 0.6}deg)`), opacity: 1, offset: 0.55, easing: out },
				{ transform: T(x + dx, y + dy, `scale(0.3) rotate(${turn}deg)`), opacity: 0 }
			]
		: [
				{ transform: T(x, y, 'scale(0.5)'), opacity: 0, easing: out },
				{ transform: T(x, y, 'scale(1)'), opacity: peak, offset: 0.05, easing: out },
				{ transform: T(x + dx, y + dy, `scale(0.25) rotate(${turn}deg)`), opacity: 0 }
			];
	s.animate(frames, { duration: 800 + Math.random() * 1200, easing: 'linear', fill: 'forwards' });
}

// petals' tints: candy, rose, blush, deep candy, a warmer candy · now and then a touch of iris
const TINTS_NIGHT = ['255 120 192', '255 150 205', '255 182 218', '246 102 176', '255 135 200', '228 134 232'];
const TINTS_DAY = ['226 92 166', '234 112 178', '240 140 192', '214 76 152', '226 100 170', '196 102 206'];

/** a petal appears right where her voice is, then drifts down, turning and swaying, and fades · sizes,
 *  tints, turns and falls all vary · each lives 1.6–2.8 s */
function petal(s: HTMLElement, at: Spot) {
	const tints = document.documentElement.classList.contains('dark') ? TINTS_NIGHT : TINTS_DAY;
	const size = 5 + Math.random() * 6;
	s.className = 'pv-mark pv-petal';
	s.style.setProperty('--s', `${size.toFixed(1)}px`);
	s.style.setProperty('--l', (1.15 + Math.random() * 0.35).toFixed(2));
	s.style.setProperty('--pv-core', Math.random() < 0.1 ? tints[5] : tints[Math.floor(Math.random() * 5)]);
	const x = at.x + (Math.random() - 0.5) * 5;
	const y = at.y + (Math.random() - 0.5) * 4;
	const fall = Math.random() < 0.2 ? 14 + Math.random() * 8 : 5 + Math.random() * 10;
	const sway = either() * (2 + Math.random() * 7);
	const r0 = Math.random() * 360;
	const turn = either() * (40 + Math.random() * 160);
	const peak = 0.72 + Math.random() * 0.22;
	const soft = 'ease-in-out';
	s.animate(
		[
			{ transform: T(x, y, `rotate(${r0}deg) scale(0.7)`), opacity: 0, easing: 'ease-out' },
			{ transform: T(x, y + fall * 0.04, `rotate(${r0 + turn * 0.05}deg) scale(1)`), opacity: peak, offset: 0.05, easing: soft },
			{ transform: T(x + sway, y + fall * 0.45, `rotate(${r0 + turn * 0.5}deg)`), opacity: peak * 0.85, offset: 0.5, easing: soft },
			{ transform: T(x - sway * 0.4, y + fall, `rotate(${r0 + turn}deg) scale(0.85)`), opacity: 0 }
		],
		{ duration: 1600 + Math.random() * 1200, easing: 'linear', fill: 'forwards' }
	);
}

let phone: boolean | null = null;
/** the wait before the next mark: a quick, uneven flow, about thirty a second (eighteen on a phone) */
function flow() {
	phone ??= deviceKind() === 'phone';
	const ms = 18 + Math.random() * 30;
	return phone ? ms / PHONE_FLOW : ms;
}

const reduced = () =>
	typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** the lines a range covers, as boxes (text only: each text node measured on its own) */
export function lineBoxes(range: Range) {
	const out: { left: number; right: number; top: number; bottom: number }[] = [];
	const root = range.commonAncestorContainer;
	const texts: Text[] = [];
	if (root.nodeType === Node.TEXT_NODE) texts.push(root as Text);
	else {
		const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
		for (let n = w.nextNode(); n; n = w.nextNode()) if (range.intersectsNode(n)) texts.push(n as Text);
	}
	for (const t of texts) {
		const r = document.createRange();
		r.setStart(t, t === range.startContainer ? range.startOffset : 0);
		r.setEnd(t, t === range.endContainer ? range.endOffset : t.length);
		for (const b of r.getClientRects()) {
			if (b.width < 0.5 || b.height < 0.5) continue;
			const mid = (b.top + b.bottom) / 2;
			const line = out.find((l) => Math.abs((l.top + l.bottom) / 2 - mid) < b.height * 0.5);
			if (line) {
				line.left = Math.min(line.left, b.left);
				line.right = Math.max(line.right, b.right);
				line.top = Math.min(line.top, b.top);
				line.bottom = Math.max(line.bottom, b.bottom);
			} else out.push({ left: b.left, right: b.right, top: b.top, bottom: b.bottom });
		}
	}
	return out.sort((a, b) => a.top - b.top);
}

type Road = { lines: { x0: number; x1: number; y: number }[]; total: number };

/** a mark let go: it finishes fading where it fell, then leaves (at once if it was holding still) */
function retire(s: HTMLElement) {
	const fading = s.getAnimations().filter((a) => a.playState === 'running');
	if (!fading.length) return s.remove();
	Promise.all(fading.map((a) => a.finished)).then(
		() => s.remove(),
		() => s.remove()
	);
}

/** one trail: lay it under a sentence, keep it on her clock, let it rest */
export class Trail {
	private road: Road | null = null;
	private ms = 0;
	private host: HTMLElement | null = null;
	private lead: HTMLElement | null = null; // the leading sparkle (a still dot with reduced motion)
	private leadAnim: Animation | null = null;
	private marks: HTMLElement[] = [];
	private at = 0;
	private timer: ReturnType<typeof setTimeout> | null = null;
	private io: IntersectionObserver | null = null;
	onScreen = true; // the watched block, against the screen (nothing moves off it)

	/** back: called when the watched block comes back on screen (to meet her where she is) */
	constructor(private back: () => void = () => {}) {}

	private mark(cls: string, host: HTMLElement) {
		const i = document.createElement('i');
		i.className = `pv-mark ${cls}`;
		i.setAttribute('aria-hidden', 'true');
		host.appendChild(i);
		return i;
	}

	/** where the road is at progress p (0 → 1), in the host's own px */
	private roadAt(p: number): Spot | null {
		if (!this.road) return null;
		let left = Math.max(0, Math.min(1, p)) * this.road.total;
		const lines = this.road.lines;
		for (const l of lines) {
			const w = l.x1 - l.x0;
			if (left <= w || l === lines[lines.length - 1]) return { x: l.x0 + Math.min(left, w), y: l.y };
			left -= w;
		}
		return null;
	}

	/** lay the road under a sentence (or a line) for `ms` of her voice, the leading sparkle on it */
	lay(range: Range, host: HTMLElement, ms: number) {
		style();
		this.stopDrops();
		if (this.host && this.host !== host) this.clear(false); // another reply: the old trail fades there
		this.leadAnim?.cancel();
		this.leadAnim = null;
		this.host = host;
		this.ms = Math.max(120, ms);
		const box = host.getBoundingClientRect();
		const lines = lineBoxes(range).map((l) => ({
			x0: l.left - box.left,
			x1: l.right - box.left,
			y: l.bottom - box.top - (l.bottom - l.top) * 0.08 // just under the words
		}));
		this.road = lines.length ? { lines, total: lines.reduce((n, l) => n + (l.x1 - l.x0), 0) || 1 } : null;
		if (!this.road) return this.lead?.classList.remove('pv-on');
		if (!this.lead || this.lead.parentElement !== host) {
			this.lead?.remove();
			this.lead = this.mark('pv-lead', host);
		}
		this.lead.className = 'pv-mark pv-lead';
		if (reduced()) {
			// reduced motion: a still dot under the start of her sentence, nothing travels
			const at = this.roadAt(0)!;
			this.lead.style.transform = T(at.x, at.y);
			this.lead.classList.add('pv-on', 'pv-still');
			return;
		}
		this.lead.style.transform = '';
		const frames: Keyframe[] = [];
		let acc = 0;
		for (const l of this.road.lines) {
			frames.push({ offset: acc / this.road.total, transform: T(l.x0, l.y) });
			acc += l.x1 - l.x0;
			frames.push({ offset: Math.min(1, acc / this.road.total), transform: T(l.x1, l.y) });
		}
		this.leadAnim = this.lead.animate(frames, { duration: this.ms, easing: 'linear', fill: 'forwards' });
		this.leadAnim.pause();
		this.lead.classList.add('pv-on');
	}

	/** may it move right now: a sentence playing, its block on screen, the tab visible */
	private moving() {
		return (
			!!this.leadAnim &&
			this.leadAnim.playState === 'running' &&
			this.onScreen &&
			document.visibilityState === 'visible'
		);
	}

	/** one mark right where her voice is now, left behind to fade */
	private drop() {
		if (!this.host || !this.leadAnim || batteryLow()) return;
		const at = this.roadAt(Number(this.leadAnim.currentTime ?? 0) / this.ms);
		if (!at) return;
		let s = this.marks[this.at];
		if (!s || s.parentElement !== this.host) {
			s?.remove();
			s = this.marks[this.at] = this.mark('', this.host);
		}
		this.at = (this.at + 1) % POOL;
		for (const a of s.getAnimations()) a.cancel();
		(Math.random() < PETAL_SHARE ? petal : sparkle)(s, at);
	}

	private stopDrops() {
		if (this.timer) clearTimeout(this.timer);
		this.timer = null;
	}

	private startDrops() {
		this.stopDrops();
		if (batteryLow() || reduced()) return; // a low battery keeps just the lead; reduced motion, the dot
		const tick = () => {
			this.timer = null;
			if (!this.moving()) return;
			this.drop();
			this.timer = setTimeout(tick, flow());
		};
		tick();
	}

	/** A33 · pin the lead to her clock (s into the sentence, at her speed): behind or on time, it meets her
	 *  (a step forward); ahead, it never steps back: it slows the more it's ahead, and holds still past EASE_MS
	 *  until her voice catches up (the next pin lets it go) · true when it had to wait for her */
	pin(at: number, rate: number): boolean {
		if (!this.leadAnim) return false;
		const want = Math.max(0, Math.min(this.ms, at * 1000));
		const ahead = Number(this.leadAnim.currentTime ?? 0) - want;
		this.ahead = Math.max(0, ahead);
		if (ahead > 0) {
			this.leadAnim.playbackRate = (rate || 1) * Math.max(0, 1 - ahead / EASE_MS);
			return true;
		}
		this.leadAnim.playbackRate = rate || 1;
		if (ahead < -1) this.leadAnim.currentTime = want;
		return false;
	}

	ahead = 0; // ms the lead was ahead of her voice at the last pin (for the eyes and the tests)

	/** keep the lead on her clock: where she is (s), at her speed, paused with her and off-screen */
	time(at: number, rate: number, paused: boolean) {
		if (!this.leadAnim) return;
		try {
			this.pin(at, rate);
			if (paused || !this.onScreen || document.visibilityState !== 'visible') {
				this.leadAnim.pause();
				this.stopDrops();
			} else {
				this.leadAnim.play();
				for (const s of this.marks) for (const a of s.getAnimations()) if (a.playState === 'paused') a.play();
				this.startDrops();
			}
		} catch {}
	}

	/** she paused (or the block left the screen, or the tab hid): the whole trail holds still */
	freeze() {
		this.stopDrops();
		try {
			this.leadAnim?.pause();
			for (const s of this.marks) for (const a of s.getAnimations()) a.pause();
		} catch {}
	}

	/** between two sentences: the lead fades; what it left behind finishes fading */
	rest() {
		this.stopDrops();
		this.leadAnim?.pause();
		this.lead?.classList.remove('pv-on');
	}

	/** the end: no new marks; the lead fades, what it left finishes fading where it fell, then all of it is
	 *  gone (and the trail stops watching, unless told to keep its watch) */
	clear(unwatch = true) {
		this.stopDrops();
		const lead = this.lead;
		const anim = this.leadAnim;
		this.lead = null;
		this.leadAnim = null;
		if (lead) {
			anim?.pause();
			lead.classList.remove('pv-on'); // its own 0.3 s fade
			setTimeout(() => {
				anim?.cancel();
				lead.remove();
			}, 320);
		}
		for (const s of this.marks) retire(s);
		this.marks = [];
		this.at = 0;
		this.road = null;
		this.host = null;
		if (unwatch) this.watch(null);
	}

	/** watch a block: off the screen, nothing of the trail moves; back on it, `back` resyncs */
	watch(el: Element | null) {
		this.io?.disconnect();
		this.io = null;
		this.onScreen = true;
		if (!el || typeof IntersectionObserver === 'undefined') return;
		this.io = new IntersectionObserver(([e]) => {
			if (!e) return;
			const was = this.onScreen;
			this.onScreen = e.isIntersecting;
			if (was && !this.onScreen) this.freeze();
			else if (!was && this.onScreen) this.back();
		});
		this.io.observe(el);
	}

	/** for the eyes and the tests: how its parts are doing */
	get state() {
		return {
			lead: this.leadAnim?.playState ?? null,
			alive: this.marks.filter((s) => s.getAnimations().some((a) => a.playState === 'running')).length,
			at: Math.round(Number(this.leadAnim?.currentTime ?? 0)), // ms into the road
			ahead: Math.round(this.ahead) // ms ahead of her voice at the last pin
		};
	}
}

// Lily's pink, in gradients only: candy on the night skins, a deeper candy on light ones (a petal's tint
// is its own, picked for the skin when it falls)
const STYLE = `
.pv-mark { position: absolute; left: 0; top: 0; z-index: 3; pointer-events: none; }
.pv-lead {
	--pv-core: 255 91 176; width: 12px; height: 12px; margin: -6px 0 0 -6px; border-radius: 50%;
	opacity: 0; transition: opacity 0.3s ease;
	background:
		radial-gradient(circle, rgb(255 255 255 / 0.95) 0, rgb(255 255 255 / 0) 30%),
		radial-gradient(circle, rgb(var(--pv-core) / 0.95) 0, rgb(var(--pv-core) / 0.45) 40%, rgb(var(--pv-core) / 0) 70%),
		linear-gradient(90deg, rgb(var(--pv-core) / 0), rgb(var(--pv-core) / 0.85) 50%, rgb(var(--pv-core) / 0)) center / 100% 1.5px no-repeat,
		linear-gradient(0deg, rgb(var(--pv-core) / 0), rgb(var(--pv-core) / 0.85) 50%, rgb(var(--pv-core) / 0)) center / 1.5px 100% no-repeat;
}
.pv-lead.pv-on { opacity: 1; }
.pv-lead.pv-still { transition: none; }
.pv-dust {
	--pv-core: 255 144 207; width: var(--s, 6px); height: var(--s, 6px);
	margin: calc(var(--s, 6px) / -2) 0 0 calc(var(--s, 6px) / -2); border-radius: 50%; opacity: 0;
	background: radial-gradient(circle, rgb(255 255 255 / 0.85) 0, rgb(var(--pv-core) / 0.9) 30%, rgb(var(--pv-core) / 0) 72%);
}
.pv-dust.pv-star {
	border-radius: 0;
	background:
		radial-gradient(circle, rgb(255 255 255 / 0.9) 0, rgb(var(--pv-core) / 0.8) 18%, rgb(var(--pv-core) / 0) 42%),
		linear-gradient(90deg, rgb(var(--pv-core) / 0), rgb(var(--pv-core) / 0.9) 50%, rgb(var(--pv-core) / 0)) center / 100% 1.2px no-repeat,
		linear-gradient(0deg, rgb(var(--pv-core) / 0), rgb(var(--pv-core) / 0.9) 50%, rgb(var(--pv-core) / 0)) center / 1.2px 100% no-repeat;
}
.pv-petal {
	--pv-core: 255 120 192; width: var(--s, 7px); height: calc(var(--s, 7px) * var(--l, 1.3));
	margin: calc(var(--s, 7px) * var(--l, 1.3) / -2) 0 0 calc(var(--s, 7px) / -2); opacity: 0;
	border-radius: 85% 6% 85% 6%;
	background: linear-gradient(140deg, rgb(255 232 243 / 0.95) 0%, rgb(var(--pv-core) / 0.88) 60%, rgb(var(--pv-core) / 0.55) 100%);
}
html:not(.dark) .pv-lead { --pv-core: 212 64 143; }
html:not(.dark) .pv-dust { --pv-core: 222 84 160; }
@media (prefers-reduced-motion: reduce) { .pv-dust, .pv-petal { display: none; } .pv-lead { transition: none; } }
`;

let styled = false;
function style() {
	if (styled || typeof document === 'undefined') return;
	styled = true;
	const el = document.createElement('style');
	el.id = 'petal-trail-style';
	el.textContent = STYLE;
	document.head.appendChild(el);
}
