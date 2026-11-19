// 🍒 twin streaming (slice A30d) — both replies of a pick type at once, in real time, at one shared pace, and
// stay blind. each side's words arrive at their own speed (a pulled reply can start a few seconds late: vLLM can't
// reuse its cache for it), so the page keeps what arrives and reveals, on each side, only as much as both have
// received: reveal = min(received_a, received_b). nothing shows until both have begun. when one side finishes, the
// other goes on freely to its end at the speed its own words came in (a backlog types out, never in a burst), so
// only the lengths differ, and lengths say nothing about the pull.
//
// a unit is one UTF-16 code unit of the text the page renders (the reply's output text, else its content), cut so a
// glyph is never split: an emoji keeps its skin tone, a flag its other half. steps are batched on
// requestAnimationFrame by the pick (PetalPick.svelte), and nothing runs once both are shown or while the page is
// hidden. her choice, Settings → 🍒 Arms → How they arrive: twin (default) · together (the A30 hold: still cards
// until both are written) · live (each as it arrives: timing can tell). plain picks arrive the same way as arms.
import { getOutputText, type OutputItem } from '$lib/components/chat/Messages/structuredOutput';

export type Arrival = 'twin' | 'together' | 'live';
export const ARRIVALS: readonly Arrival[] = ['twin', 'together', 'live'];
export const ARRIVAL_DEFAULT: Arrival = 'twin';

/** her arrival as saved · an older page's A30 hold read the new way: on → twin (its successor), off → live */
export function arrivalOf(arrive: unknown, hold?: unknown): Arrival {
	if (arrive === 'twin' || arrive === 'together' || arrive === 'live') return arrive;
	return hold === false ? 'live' : ARRIVAL_DEFAULT;
}

type Part = { type?: string; text?: unknown; [key: string]: unknown };
type Item = { type?: string; status?: string; content?: Part[]; [key: string]: unknown };
export type TwinMsg = {
	content?: string;
	output?: unknown[];
	done?: boolean;
	error?: unknown;
	[key: string]: unknown;
};

const textOf = (p: Part | undefined) =>
	p?.text === undefined || p?.text === null ? '' : typeof p.text === 'string' ? p.text : String(p.text);
const itemsOf = (m: TwinMsg | undefined): Item[] | null =>
	Array.isArray(m?.output) && m.output.length ? (m.output as Item[]) : null;
const textUnits = (it: Item) =>
	(Array.isArray(it.content) ? it.content : []).reduce((n, p) => n + textOf(p).length, 0);

/** how much of a reply has arrived, in units: what the page renders (its output, else its content). an output item
 * without text (a reasoning or tool block) counts as one */
export function unitsOf(m: TwinMsg | undefined): number {
	const items = itemsOf(m);
	if (!items) return typeof m?.content === 'string' ? m.content.length : 0;
	return items.reduce((n, it) => n + (it?.type === 'message' ? textUnits(it) : 1), 0);
}

export type Side = { units: number; done: boolean };
export const sideOf = (m: TwinMsg | undefined): Side => ({
	units: unitsOf(m),
	done: m?.done === true || !!m?.error
});

/** how many units both sides may show now. while both are still typing: what both have received (the later one
 * sets the pace, and nothing shows until both have begun). once one is done, the other's own (it goes on freely);
 * once both are, all of both */
export function twinTarget(a: Side, b: Side): number {
	if (!a.done && !b.done) return Math.min(a.units, b.units);
	if (a.done && b.done) return Math.max(a.units, b.units);
	return a.done ? b.units : a.units;
}

export const PACE_FLOOR = 0.04; // units per ms: 40 a second, never slower
export const PACE_GUESS = 0.25; // units per ms until a side's own speed is known (about 60 tokens a second)
export const STEP_MAX_MS = 100; // a step never covers more than this much time: no burst after a pause

/** the next shared count. gated (both still typing): straight to the target, it already moves at the slower
 * side's speed. otherwise toward it at `perMs`, the speed the remaining words came in, so a backlog types out the
 * way it arrived and never jumps */
export function twinStep(
	shown: number,
	target: number,
	gated: boolean,
	dtMs: number,
	perMs: number
): number {
	if (target <= shown) return shown;
	if (gated) return target;
	const dt = Math.min(STEP_MAX_MS, Math.max(0, dtMs));
	const step = Math.max(1, Math.round(Math.max(PACE_FLOOR, perMs) * dt));
	return Math.min(target, shown + step);
}

/** a side's own speed: the units it received since its first, over the time they took */
export class Pace {
	private t0 = -1; // not begun
	private u0 = 0;
	private t = 0;
	private u = 0;
	see(units: number, now: number) {
		if (units <= 0) return;
		if (this.t0 < 0) {
			[this.t0, this.u0, this.t, this.u] = [now, units, now, units];
		} else if (units > this.u) {
			[this.t, this.u] = [now, units];
		}
	}
	perMs(fallback = PACE_GUESS): number {
		const [dt, du] = [this.t - this.t0, this.u - this.u0];
		return dt >= 250 && du > 0 ? du / dt : fallback;
	}
}

/** the speed a free step moves at: the side still typing, at its own speed (it goes on freely); once both are
 * done, the side that still has words to show (both: the slower) */
export function paceFor(a: Side, b: Side, shown: number, pa: Pace, pb: Pace): number {
	if (a.done !== b.done) return a.done ? pb.perMs() : pa.perMs();
	const [aLeft, bLeft] = [a.units > shown, b.units > shown];
	if (aLeft && !bLeft) return pa.perMs();
	if (bLeft && !aLeft) return pb.perMs();
	return Math.min(pa.perMs(), pb.perMs());
}

// ── cutting without splitting a glyph ──────────────────────────────────────────────────────────────────────
const isHigh = (c: number) => c >= 0xd800 && c <= 0xdbff;
const isLow = (c: number) => c >= 0xdc00 && c <= 0xdfff;
// combining marks, variation selectors, keycaps, half marks, kana voicing: they attach to the glyph before them
const ATTACHES =
	/[̀-ͯ҃-҉֑-ֽؐ-ًؚ-ٟัิ-ฺ็-๎᪰-᫿᷀-᷿⃐-⃿︀-️︠-゙゚︯]/;
const isRI = (text: string, i: number) =>
	text.charCodeAt(i) === 0xd83c && text.charCodeAt(i + 1) >= 0xdde6 && text.charCodeAt(i + 1) <= 0xddff;

/** the first `n` units of `text`, never splitting a glyph: a surrogate pair stays whole, and what attaches to the
 * last glyph comes with it (marks, variation selectors, a skin tone, a ZWJ and the glyph it joins, a flag's other
 * half, emoji tags) */
export function cutText(text: string, n: number): string {
	const len = text.length;
	let i = Math.max(0, Math.min(len, Math.floor(n)));
	if (i >= len) return text;
	if (i === 0) return '';
	if (isHigh(text.charCodeAt(i - 1)) && isLow(text.charCodeAt(i))) i += 1;
	while (i < len) {
		const c = text.charCodeAt(i);
		const d = text.charCodeAt(i + 1);
		if (c === 0x200d) {
			// a ZWJ joins the next glyph too
			i += 1;
			if (i < len) i += isHigh(text.charCodeAt(i)) && i + 1 < len ? 2 : 1;
			continue;
		}
		if (ATTACHES.test(text[i])) i += 1;
		else if (c === 0xd83c && d >= 0xdffb && d <= 0xdfff) i += 2; // a skin tone
		else if (c === 0xdb40 && d >= 0xdc20 && d <= 0xdc7f) i += 2; // emoji tags (a subdivision's flag)
		else if (isRI(text, i) && i >= 2 && isRI(text, i - 2)) {
			// a flag is two regional indicators: an odd run before the cut wants this one as its pair
			let run = 0;
			for (let k = i - 2; k >= 0 && isRI(text, k); k -= 2) run += 1;
			if (run % 2 === 0) break;
			i += 2;
		} else break;
	}
	return text.slice(0, i);
}

/** output items as far as `n` units reach: whole items while they fit, the item being typed cut inside its text
 * (marked in progress), nothing after it */
export function cutOutput(output: unknown[], n: number): unknown[] {
	const out: unknown[] = [];
	let left = n;
	for (const raw of output) {
		const it = raw as Item;
		if (it?.type !== 'message') {
			if (left < 1) break;
			out.push(it);
			left -= 1;
			continue;
		}
		const total = textUnits(it);
		if (total <= left) {
			out.push(it);
			left -= total;
			continue;
		}
		const kept: Part[] = [];
		for (const p of Array.isArray(it.content) ? it.content : []) {
			const text = textOf(p);
			if (text.length <= left) {
				kept.push(p);
				left -= text.length;
				continue;
			}
			kept.push({ ...p, text: cutText(text, left) });
			break;
		}
		out.push({ ...it, status: 'in_progress', content: kept });
		break;
	}
	return out;
}

/** what a side shows at `n` units: itself when nothing is held back, else a copy cut at `n` and still typing.
 * before anything shows, both sides are the same empty reply (no trace of who has words waiting) */
export function pacedMessage<T extends TwinMsg>(m: T, n: number): T {
	if (!m) return m;
	if (n >= unitsOf(m)) return m;
	if (n <= 0) return { ...m, output: [], content: '', done: false };
	const items = itemsOf(m);
	if (items) {
		const cut = cutOutput(items, n);
		return { ...m, output: cut, content: getOutputText(cut as OutputItem[]), done: false };
	}
	return { ...m, content: cutText(m.content ?? '', n), done: false };
}

// what each reply was shown (its sources, its status line) lands with its first event, the later reply's later: until
// both have it, neither card shows it
const SHARED = ['sources', 'citations', 'statusHistory', 'status'] as const;
const present = (v: unknown) => (Array.isArray(v) ? v.length > 0 : v !== undefined && v !== null && v !== '');

/** the history the cards are shown while twin: both replies cut at the shared count, what only one of them has
 * been shown yet set aside on both, everything else as it is */
export function twinView<H extends { messages: Record<string, TwinMsg> }>(
	history: H,
	a: string,
	b: string,
	n: number
): H {
	const [ma, mb] = [history.messages[a], history.messages[b]];
	let [va, vb] = [pacedMessage(ma, n), pacedMessage(mb, n)];
	const lone = SHARED.filter((k) => present(ma?.[k]) !== present(mb?.[k]));
	if (lone.length) {
		const without = (m: TwinMsg) => {
			const out = { ...m };
			for (const k of lone) delete out[k];
			return out;
		};
		[va, vb] = [without(va), without(vb)];
	}
	if (va === ma && vb === mb) return history;
	return { ...history, messages: { ...history.messages, [a]: va, [b]: vb } };
}

// where a pick's reveal had reached, so a card shown again (a chat reopened mid-stream) doesn't type from the start
const reached = new Map<string, number>();
export const reachedOf = (pairId: string) => reached.get(pairId) ?? null;
export function reach(pairId: string, n: number | null) {
	reached.delete(pairId);
	if (n === null) return;
	reached.set(pairId, n);
	while (reached.size > 20) reached.delete(reached.keys().next().value as string);
}

/** her console, numbers only (`petalPick.twin`): how they arrive, the shared count, steps taken, still typing */
export const twinStats = {
	arrive: ARRIVAL_DEFAULT as Arrival,
	shown: 0,
	target: 0,
	frames: 0,
	typing: false,
	hidden: false
};
