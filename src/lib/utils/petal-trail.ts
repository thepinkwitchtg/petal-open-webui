// ✨ the trail (slices A19b · A20 · A21 · A22): where her voice is, as a run of pink under the words she's
// saying. Lily's pick (A21): sparkles and many four-ray stars scattered above and below the line, most
// falling a little, a few floating up, some twinkling on their way out, and now and then a soft petal
// drifting down. a leading sparkle travels the sentence's road on the compositor; every mark appears right
// where her voice is and fades where it fell. it moves only while a sentence plays: it holds still when she
// pauses, and rests off-screen, in a hidden tab or a minimized window. reduced motion shows a still dot
// under her sentence; a low battery (auto quotes) keeps the lead alone.
// A33 · pinned to her voice: the lead goes where the audio's own clock says (each sentence's road laid from the
// rig's B7 timings) and never past it. a lead that got ahead of her (a stall the page never heard of, a clock that
// ran on) eases down and waits for her voice, still once she's far behind; it never jumps back over road it
// already ran, so it can't loop. each road ends at its sentence's end: past the last sentence the rig has told,
// it rests instead of guessing.
// A35 · full beauty while she can see it: every mark flows on the phone as on the rig, and only auto quotes on a low
// battery keep the lead alone (her setting). her voice paused, the lead holds where she is, and what it left behind
// finishes falling and leaves; off her screen or in a hidden tab, everything holds where it is and carries on from
// there. each mark leaves the page the moment its own fall ends (nothing lingers, nothing replays), and a trail
// whose reply left the page (drawn again, or the chat changed) tells petal-voice, which lays it again where her
// words are now.
import { batteryLow } from '$lib/utils/petal-battery';
import { atEnd } from '$lib/utils/petal-sight';

type Spot = { x: number; y: number };

const CAP = 160; // marks alive at once, at most (about 90 at the fullest flow: past it, the oldest leaves at once)
const PETAL_SHARE = 0.035; // now and then a petal among the sparkles
const EASE_MS = 400; // a lead this far ahead of her voice holds still; closer, it slows in proportion

const T = (x: number, y: number, extra = '') => `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) ${extra}`;
const either = () => (Math.random() < 0.5 ? -1 : 1);

/** a sparkle or a four-ray star, scattered above and below the line; most fall a little, a few float up,
 *  some stars twinkle on their way out · each lives 0.8–2 s */
function sparkle(s: HTMLElement, at: Spot): Animation {
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
	return s.animate(frames, { duration: 800 + Math.random() * 1200, easing: 'linear', fill: 'forwards' });
}

// petals' tints: candy, rose, blush, deep candy, a warmer candy · now and then a touch of iris
const TINTS_NIGHT = ['255 120 192', '255 150 205', '255 182 218', '246 102 176', '255 135 200', '228 134 232'];
const TINTS_DAY = ['226 92 166', '234 112 178', '240 140 192', '214 76 152', '226 100 170', '196 102 206'];

/** a petal appears right where her voice is, then drifts down, turning and swaying, and fades · sizes,
 *  tints, turns and falls all vary · each lives 1.6–2.8 s */
function petal(s: HTMLElement, at: Spot): Animation {
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
	return s.animate(
		[
			{ transform: T(x, y, `rotate(${r0}deg) scale(0.7)`), opacity: 0, easing: 'ease-out' },
			{ transform: T(x, y + fall * 0.04, `rotate(${r0 + turn * 0.05}deg) scale(1)`), opacity: peak, offset: 0.05, easing: soft },
			{ transform: T(x + sway, y + fall * 0.45, `rotate(${r0 + turn * 0.5}deg)`), opacity: peak * 0.85, offset: 0.5, easing: soft },
			{ transform: T(x - sway * 0.4, y + fall, `rotate(${r0 + turn}deg) scale(0.85)`), opacity: 0 }
		],
		{ duration: 1600 + Math.random() * 1200, easing: 'linear', fill: 'forwards' }
	);
}

/** the wait before the next mark: a quick, uneven flow, about thirty a second (the phone as the rig, A35) */
const flow = () => 18 + Math.random() * 30;

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

const visible = () => typeof document === 'undefined' || document.visibilityState === 'visible';

export type TrailHooks = {
	back?: () => void; // the watched block came back on screen: meet her where she is
	lost?: () => void; // the watched block left the page (her reply drawn again, or the chat changed)
	simple?: () => boolean; // only the lead travels (auto quotes on a low battery)
};

/** one trail: lay it under a sentence, keep it on her clock, let it rest */
export class Trail {
	private road: Road | null = null;
	private ms = 0;
	private host: HTMLElement | null = null;
	private lead: HTMLElement | null = null; // the leading sparkle (a still dot with reduced motion)
	private leadAnim: Animation | null = null;
	private dust = new Set<HTMLElement>(); // marks alive: each leaves the page when its own fall ends (A35)
	private held = new Set<Animation>(); // marks holding off her screen or in a hidden tab (only these play on)
	private timer: ReturnType<typeof setTimeout> | null = null;
	private io: IntersectionObserver | null = null;
	private hooks: Required<TrailHooks>;
	onScreen = true; // the watched block, against the screen (off it, everything holds where it is)

	/** hooks: back (her block came back on screen), lost (her block left the page), simple (lead alone) · a bare
	 *  function reads as `back` */
	constructor(hooks: TrailHooks | (() => void) = {}) {
		const h = typeof hooks === 'function' ? { back: hooks } : hooks;
		this.hooks = {
			back: h.back ?? (() => {}),
			lost: h.lost ?? (() => {}),
			simple: h.simple ?? batteryLow
		};
	}

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
		if (this.host && this.host !== host) this.clear(false); // another reply (or her reply drawn again): the old trail leaves there
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
		// 🧵 A47 · it shows once it's pinned to her clock (the next pin): never a frame at the sentence's first word
		// while her voice is further on (that flash read as the trail going back)
		this.lead.classList.remove('pv-on');
	}

	/** 🧵 A47 · the sentence's true length is known (the road was laid on an estimate): the road is timed again and the
	 *  lead keeps its place on it (never a step back); the next pin meets her clock from there */
	retime(ms: number) {
		const next = Math.max(120, ms);
		const anim = this.leadAnim;
		if (!anim || next === this.ms) {
			this.ms = next;
			return;
		}
		const frac = this.ms > 0 ? Math.min(1, Number(anim.currentTime ?? 0) / this.ms) : 0;
		this.ms = next;
		try {
			anim.effect?.updateTiming({ duration: next });
			anim.currentTime = frac * next;
		} catch {}
	}

	/** she can see it: its block on screen, the tab visible */
	private seen() {
		return this.onScreen && visible();
	}

	/** may a mark drop right now: a sentence playing, and she can see it */
	private moving() {
		return !!this.leadAnim && this.leadAnim.playState === 'running' && this.seen();
	}

	/** one mark right where her voice is now, left behind to fall and fade · it leaves the page when its fall ends */
	private drop() {
		if (!this.host || !this.leadAnim || this.hooks.simple()) return;
		const at = this.roadAt(Number(this.leadAnim.currentTime ?? 0) / this.ms);
		if (!at) return;
		if (this.dust.size >= CAP) this.away(this.dust.values().next().value as HTMLElement);
		const s = this.mark('', this.host);
		this.dust.add(s);
		const a = (Math.random() < PETAL_SHARE ? petal : sparkle)(s, at);
		const gone = () => this.vanish(s);
		a.addEventListener('finish', gone);
		a.addEventListener('cancel', gone);
	}

	/** a mark leaves the page (its fall ended) */
	private vanish(s: HTMLElement) {
		if (!this.dust.delete(s)) return;
		for (const a of s.getAnimations()) this.held.delete(a);
		s.remove();
	}

	/** a mark leaves at once, mid-fall (held where she can't see it, or past the cap) */
	private away(s: HTMLElement) {
		const anims = s.getAnimations();
		this.vanish(s);
		for (const a of anims) a.cancel();
	}

	private stopDrops() {
		if (this.timer) clearTimeout(this.timer);
		this.timer = null;
	}

	private startDrops() {
		this.stopDrops();
		if (this.hooks.simple() || reduced()) return; // auto quotes on a low battery keep just the lead; reduced motion, the dot
		const tick = () => {
			this.timer = null;
			if (!this.moving()) return;
			this.drop();
			this.timer = setTimeout(tick, flow());
		};
		tick();
	}

	/** the marks held off her screen (or in a hidden tab) carry on from where they were: only those, never one
	 *  whose fall already ended */
	private wake() {
		for (const a of [...this.held]) {
			try {
				if (a.playState !== 'paused') continue;
				if (atEnd(a)) a.finish(); // its fall ended as it was held: it leaves, never replays
				else a.play();
			} catch {}
		}
		this.held.clear();
	}

	/** A33 · pin the lead to her clock (s into the sentence, at her speed): behind or on time, it meets her
	 *  (a step forward); ahead, it never steps back: it slows the more it's ahead, and holds still past EASE_MS
	 *  until her voice catches up (the next pin lets it go) · true when it had to wait for her */
	pin(at: number, rate: number): boolean {
		if (!this.leadAnim) return false;
		this.lead?.classList.add('pv-on'); // 🧵 A47 · placed on her clock: now it may show
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

	/** keep the lead on her clock: where she is (s), at her speed · paused with her · held off her screen */
	time(at: number, rate: number, paused: boolean) {
		if (!this.leadAnim) return;
		try {
			this.pin(at, rate);
			if (!this.seen()) return this.freeze();
			this.wake(); // what held off her screen carries on from where it was
			if (paused) return this.hold();
			this.leadAnim.play();
			this.startDrops();
		} catch {}
	}

	/** her voice paused (or waiting for the stream): the lead holds where she is, no new mark drops, and what it
	 *  left behind finishes its fall and leaves (A35: nothing hangs in the air while she's paused) */
	hold() {
		this.stopDrops();
		try {
			this.leadAnim?.pause();
		} catch {}
	}

	/** off her screen, or the tab hid: the whole trail holds where it is (marks mid-fall too), and carries on from
	 *  there once she can see it */
	freeze() {
		this.stopDrops();
		try {
			this.leadAnim?.pause();
			for (const s of this.dust)
				for (const a of s.getAnimations())
					if (a.playState === 'running') {
						a.pause();
						this.held.add(a);
					}
		} catch {}
	}

	/** between two sentences: the lead fades; what it left behind finishes falling (held marks too, once she can
	 *  see them) */
	rest() {
		this.stopDrops();
		this.leadAnim?.pause();
		this.lead?.classList.remove('pv-on');
		if (this.seen()) this.wake();
	}

	/** the end: no new marks; the lead fades, the marks she can see finish their fall where they are and leave,
	 *  the ones she can't (held, or on a page that left) leave at once · the trail stops watching, unless told to
	 *  keep its watch */
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
		const seen = !!this.host?.isConnected && this.seen();
		for (const s of [...this.dust]) {
			const falling = s.isConnected && s.getAnimations().some((a) => a.playState === 'running');
			if (seen && falling) continue; // it finishes its fall, then leaves by itself
			this.away(s);
		}
		this.held.clear();
		this.road = null;
		this.host = null;
		if (unwatch) this.watch(null);
	}

	/** watch a block: off the screen, everything holds; back on it, `back` resyncs · gone from the page, `lost` */
	watch(el: Element | null) {
		this.io?.disconnect();
		this.io = null;
		this.onScreen = true;
		if (!el || typeof IntersectionObserver === 'undefined') return;
		this.io = new IntersectionObserver((entries) => {
			// A35 · a batch can hold several entries for her block, oldest first: only the newest is now (reading the
			// first one froze a trail she could see, after a quick out-and-in)
			const e = entries[entries.length - 1];
			if (!e) return;
			if (!e.target.isConnected) return this.hooks.lost(); // her block left the page: petal-voice finds her words again
			const was = this.onScreen;
			this.onScreen = e.isIntersecting;
			if (was && !this.onScreen) this.freeze();
			else if (!was && this.onScreen) this.hooks.back();
		});
		this.io.observe(el);
	}

	/** the trail's reply left the page (drawn again, or the chat changed) */
	get orphaned() {
		return !!this.host && !this.host.isConnected;
	}

	/** for the eyes and the tests, numbers only: how its parts are doing */
	get state() {
		let alive = 0;
		for (const s of this.dust) if (s.getAnimations().some((a) => a.playState === 'running')) alive += 1;
		return {
			lead: this.leadAnim?.playState ?? null,
			alive, // marks falling right now
			particles: this.dust.size, // marks on the page (falling or held)
			held: this.held.size, // marks holding off her screen or in a hidden tab
			at: Math.round(Number(this.leadAnim?.currentTime ?? 0)), // ms into the road
			ahead: Math.round(this.ahead), // ms ahead of her voice at the last pin
			ms: Math.round(this.ms), // 🧵 A47 · the road's length (an estimate until the take is over)
			on: !!this.lead?.classList.contains('pv-on') // 🧵 A47 · the lead shows (only once pinned to her clock)
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
