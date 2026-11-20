// 🎙️ her voice on the page (slices A19 · A19b · A20 · A21 · A22 · A31): the way in, where she is, and what she lights on the way.
//  · the registry: every reply on screen says how to speak it (ResponseMessage registers itself)
//  · one control, Lily's choice (Settings → Interface → Voice control): the bubble (PetalVoiceBubble, left
//    of the chat bar: plays the reply most in view, pause while she speaks, fades once that reply is heard)
//    or OWUI's speaker by her name (PetalPlayButton). one reply per tap: she never reads on by herself
//  · her eyes (A31): the reply most in view, followed by one IntersectionObserver (never a scroll listener):
//    the largest share of itself in view, by tenths, a tie to the one nearest the view's middle · inside an
//    open pick, the reply she swiped to (phone) or last pointed at (desktop)
//  · the trail (petal-trail.ts): where she is, as a small run of soft pink under the words she's saying
//    (where she is in a sentence is estimated from its timing). it pauses with her, and nothing of it moves
//    off-screen, in a hidden tab or with reduced motion (a still dot marks her sentence then); on a low
//    battery (auto quotes) only the leading mark travels
//  · quotes: when her voice reaches a display quote, its reveal plays again; a click on a quote reveals it
//    and has her say only that line (the speaker path, under B's ceiling), if she isn't already speaking
// built on contract ch. 11.6 (B7's events): petal stream's events door gives each `sentence {message_id,
// idx, text, start, duration}` on the player's clock; a sentence is kept by idx (a later start replaces it)
// and followed while start ≤ currentTime < start + duration. pause · resume · end · stop are the page's own.
// a quote said alone asks the speaker path with "petal": {message_id, idx} and reads its timing back from
// X-Petal-Voice ({v: 1, events: [sentence, end]}).
import { get, writable } from 'svelte/store';
import { audioQueue, config, settings } from '$lib/stores';
import { AUDIO_API_BASE_URL } from '$lib/constants';
import { getMessageContentParts } from '$lib/utils';
import {
	onPetalVoice,
	pausePetalStream,
	petalStreamParts,
	petalStreamAudio,
	resumePetalStream,
	voiceNow,
	type VoiceSentence
} from '$lib/utils/petalStream';
import { holdAwake, voiceReveal } from '$lib/utils/petal-quote-fx';
import { Trail } from '$lib/utils/petal-trail';

// ── the registry ─────────────────────────────────────────────────────────────────────────────────────
export type VoiceReply = {
	id: string; // its message id
	root: () => HTMLElement | null; // the whole reply (#message-<id>): how much of it is in view
	words: () => HTMLElement | null; // where its words live (positioned: the trail travels inside it)
	done: () => boolean;
	speak: () => unknown; // her voice from its first sentence (petal stream, or its fallback)
	voice: () => string | undefined; // the voice it speaks in
	content: () => string; // its words as written (a quote said alone finds its part here)
};
const replies = new Map<string, VoiceReply>();
// Lily's own messages only lend their words (a quote of hers said alone finds its part here)
const lent = new Map<string, () => string>();
export function lendWords(id: string, content: () => string): () => void {
	lent.set(id, content);
	return () => {
		if (lent.get(id) === content) lent.delete(id);
	};
}
// it moves whenever a reply comes, goes or finishes arriving: the bubble looks again
export const voiceReplies = writable(0);
const bump = () => {
	voiceReplies.update((n) => n + 1);
	watchSoon(); // her eyes follow the replies on screen (and their speaker buttons, once there)
};

export function registerReply(r: VoiceReply): () => void {
	wire();
	replies.set(r.id, r);
	bump();
	return () => {
		if (replies.get(r.id) === r) replies.delete(r.id);
		bump();
	};
}

/** a reply finished arriving (ResponseMessage tells, also for replies that were done from the start): it
 *  can be played now, and its speaker button is there */
const doneOnce = new Set<string>();
export const replyDone = (id: string) => {
	if (doneOnce.has(id)) return;
	doneOnce.add(id);
	bump();
};

// ── her eyes (A31): the reply most in view ──────────────────────────────────────────────────────────
// one IntersectionObserver on the chat's own scroll box watches every reply on screen and its speaker button,
// at steps of a tenth. a reply's share is how much of itself is in view (one taller than the view counts whole
// when it fills it); shares compare by those tenths, and a tie goes to the reply nearest the view's middle. it
// decides again only when a share crosses a step, a reply comes, goes or finishes, or her eyes move inside an
// open pick: nothing runs while she's idle, and nothing is decided while the page is hidden (once back, it
// looks once). still-arriving replies wait (nothing to play yet); with none in view, the newest one
export const voiceTarget = writable<string | null>(null); // the reply a tap plays now
export const speakersInView = writable<Set<string>>(new Set()); // replies whose own speaker is half in view
/** inside an open pick (PetalPick tells): the reply she swiped to (phone) or last pointed at (desktop) */
export const pickFocus = writable<{ ids: string[]; id: string } | null>(null);
// A33 · a tap never trusts a focus that may be a step behind (her swipe still settling, an observer not yet
// heard from): each open pick lends its own live reading, asked at the moment of the tap
type PickNow = () => { ids: string[]; id: string } | null;
const pickReaders = new Set<PickNow>();
/** an open pick lends its live focus (PetalPick) · the returned function takes it back */
export function lendPickFocus(read: PickNow): () => void {
	pickReaders.add(read);
	return () => pickReaders.delete(read);
}
/** her console, ids and numbers only (`petalVoice.eyes`): the reply a tap plays, decisions, batches, watched */
export const eyesStats = { looks: 0, batches: 0, watched: 0 };

const STEPS = Array.from({ length: 11 }, (_, i) => i / 10);
type Watch = { id: string; kind: 'reply' | 'speaker' };
const watching = new Map<Element, Watch>();
const shares = new Map<string, number>(); // reply id → how much of it is in view (0 … 1)
let io: IntersectionObserver | null = null;
let ioRoot: Element | null | undefined; // its box: the chat's (null: the window's), unset before the first
let pending = false; // a change came while the page was hidden: look once she's back
let queued = false;

const pageHidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden';

function observer(): IntersectionObserver | null {
	if (typeof IntersectionObserver === 'undefined' || typeof document === 'undefined') return null;
	const root = document.getElementById('messages-container'); // the chat's box (else the window's)
	if (io && ioRoot === root) return io;
	io?.disconnect(); // another chat's box: start over
	watching.clear();
	shares.clear();
	speakersInView.set(new Set());
	ioRoot = root;
	io = new IntersectionObserver(seen, { root, threshold: STEPS });
	return io;
}

/** watch what's on screen now: each reply, and its speaker button once it's there (stale ones let go) */
function watchAll() {
	const obs = observer();
	if (!obs) return;
	const want = new Map<Element, Watch>();
	for (const r of replies.values()) {
		const el = r.root();
		if (el) want.set(el, { id: r.id, kind: 'reply' });
		const sp = document.getElementById(`speak-button-${r.id}`);
		if (sp) want.set(sp, { id: r.id, kind: 'speaker' });
	}
	let gone = false;
	for (const [el, w] of watching)
		if (!want.has(el)) {
			obs.unobserve(el);
			watching.delete(el);
			if (w.kind === 'reply') shares.delete(w.id);
			else gone = true;
		}
	if (gone) {
		const kept = new Set([...watching.values()].filter((w) => w.kind === 'speaker').map((w) => w.id));
		speakersInView.update((v) => new Set([...v].filter((id) => kept.has(id))));
	}
	for (const [el, w] of want)
		if (!watching.has(el)) {
			obs.observe(el); // its first sight arrives on its own
			watching.set(el, w);
		}
	eyesStats.watched = watching.size;
	look();
}
// a microtask: the reply's buttons row is in the page by then
export function watchSoon() {
	if (queued || typeof window === 'undefined') return;
	queued = true;
	queueMicrotask(() => {
		queued = false;
		watchAll();
	});
}

function seen(entries: IntersectionObserverEntry[]) {
	eyesStats.batches += 1;
	let speakers: Set<string> | null = null;
	for (const e of entries) {
		const w = watching.get(e.target);
		if (!w) continue;
		if (w.kind === 'speaker') {
			const on = e.isIntersecting && e.intersectionRatio >= 0.5;
			speakers ??= new Set(get(speakersInView));
			if (on) speakers.add(w.id);
			else speakers.delete(w.id);
			continue;
		}
		// its height in view, of what could be (a reply taller than the view fills it whole), times its width in
		// view (a pick's card swiped aside on the phone only peeks in)
		const [view, part, box] = [e.rootBounds, e.intersectionRect, e.boundingClientRect];
		const tall = Math.min(box.height, view?.height ?? innerHeight);
		const share =
			e.isIntersecting && tall > 0 && box.width > 0
				? Math.min(1, part.height / tall) * Math.min(1, part.width / box.width)
				: 0;
		shares.set(w.id, share);
	}
	if (speakers) speakersInView.set(speakers);
	look();
}

/** an open pick's sibling her eyes are not on (A33): never the one a tap plays */
function aside(id: string): boolean {
	const f = get(pickFocus);
	return !!f && f.id !== id && f.ids.includes(id);
}

/** the newest reply that can be played (with none in view) */
function newest(): string | null {
	let last: { id: string; at: number } | null = null;
	for (const r of replies.values()) {
		const el = r.root();
		if (!el || !r.done() || aside(r.id)) continue;
		const at = el.getBoundingClientRect().top;
		if (!last || at > last.at) last = { id: r.id, at };
	}
	return last?.id ?? null;
}

/** of replies tied by their share, the one whose visible part sits nearest the view's middle (measured
 *  now, only when there is a tie to break) */
function nearestMiddle(ids: string[]): string | null {
	const view = ioRoot?.getBoundingClientRect() ?? { top: 0, bottom: innerHeight, height: innerHeight };
	const middle = view.top + view.height / 2;
	let [best, bestOff] = [ids[0] ?? null, Infinity];
	for (const id of ids) {
		const r = replies.get(id)?.root()?.getBoundingClientRect();
		if (!r) continue;
		const [top, bottom] = [Math.max(r.top, view.top), Math.min(r.bottom, view.bottom)];
		const off = Math.abs((top + bottom) / 2 - middle);
		if (off < bestOff) [best, bestOff] = [id, off];
	}
	return best;
}

/** decide: the largest share by tenths, a tie to the nearest the middle · in an open pick, her focus */
function look() {
	if (pageHidden()) {
		pending = true;
		return;
	}
	pending = false;
	eyesStats.looks += 1;
	// A33 · an open pick counts once, through the reply her eyes are on, with the larger share of its two
	// (a swipe moves her eyes between them, never away from the pick); its other reply never competes
	const f = get(pickFocus);
	let pickShare = 0;
	if (f) for (const id of f.ids) pickShare = Math.max(pickShare, shares.get(id) ?? 0);
	let step = -1;
	let tied: string[] = [];
	let waiting = false; // the pick wins her eyes, but the reply she's on is still arriving
	for (const r of replies.values()) {
		const mine = !!f && f.ids.includes(r.id);
		if (mine && r.id !== f!.id) continue;
		const share = mine ? pickShare : (shares.get(r.id) ?? 0);
		if (share <= 0 || (!r.done() && !mine)) continue;
		const s = Math.floor(share * 10 + 1e-6); // by tenths, as the observer sees them
		if (s > step) [step, tied] = [s, [r.id]];
		else if (s === step) tied.push(r.id);
	}
	let best = tied.length > 1 ? nearestMiddle(tied) : (tied[0] ?? null);
	if (best && f && best === f.id && !replies.get(best)?.done()) [best, waiting] = [null, true];
	if (!waiting) best ??= newest(); // nothing to play yet where she looks: the bubble waits with her
	if (best !== get(voiceTarget)) voiceTarget.set(best);
}

/** A33 · the reply a tap plays, decided at the moment of the tap: an open pick's focus read live (the card
 *  centred in its scroller now, the card under her pointer now), then her eyes once more */
export function tapTarget(): string | null {
	for (const read of pickReaders) {
		let now: { ids: string[]; id: string } | null = null;
		try {
			now = read();
		} catch {
			now = null;
		}
		if (!now) continue;
		const f = get(pickFocus);
		if (!f || f.id !== now.id || f.ids[0] !== now.ids[0]) pickFocus.set(now); // looks again by itself
		break;
	}
	pending = false;
	look();
	return mostInView();
}

// replies heard to their end, this visit (the bubble fades on one, comes back on an unheard one)
export const heardReplies = writable<Set<string>>(new Set());

// ── what the page shows of her voice: the stream first, then a quote's line, then sentence clips ──────
export type VoiceKind = 'stream' | 'line' | 'clips';
export type VoiceUI = {
	state: 'idle' | 'loading' | 'playing' | 'paused';
	message_id: string | null;
	kind: VoiceKind | null;
};
export const voiceUI = writable<VoiceUI>({ state: 'idle', message_id: null, kind: null });

type LineState = 'idle' | 'loading' | 'playing' | 'paused';
let lineState: LineState = 'idle';
let lineMessage: string | null = null;
let clips: { state: 'idle' | 'playing' | 'paused'; message_id: string | null } = {
	state: 'idle',
	message_id: null
};

function refresh() {
	const s = get(voiceNow);
	let ui: VoiceUI = { state: 'idle', message_id: null, kind: null };
	if (s.state !== 'idle') ui = { state: s.state, message_id: s.message_id, kind: 'stream' };
	else if (lineState !== 'idle') ui = { state: lineState, message_id: lineMessage, kind: 'line' };
	else if (clips.state !== 'idle') ui = { state: clips.state, message_id: clips.message_id, kind: 'clips' };
	const was = get(voiceUI);
	if (was.state !== ui.state || was.message_id !== ui.message_id || was.kind !== ui.kind) {
		voiceUI.set(ui);
		holdAwake('voice', ui.state === 'playing' || ui.state === 'loading');
	}
}

/** she's speaking now (a stream on its way or playing, a line, clips, the browser's own voice) ·
 *  paused counts as quiet */
export function speakingNow(): boolean {
	const s = get(voiceNow).state;
	if (s === 'loading' || s === 'playing') return true;
	if (lineState === 'loading' || lineState === 'playing') return true;
	if (clips.state === 'playing') return true;
	try {
		return typeof speechSynthesis !== 'undefined' && speechSynthesis.speaking;
	} catch {
		return false;
	}
}

// ── the way in: one reply per tap ─────────────────────────────────────────────────────────────────────
/** her voice from this reply's first sentence (whatever else was playing stops) */
export function playReply(id: string) {
	const r = replies.get(id);
	if (!r) return;
	stopLine();
	r.speak();
}

/** the reply the bubble plays: the one most in view (her eyes, above), or the newest with none in view */
export function mostInView(): string | null {
	return get(voiceTarget) ?? newest();
}

/** a few of a reply's first words: the bubble's tooltip names the reply a tap plays */
export function firstWords(id: string | null, n = 5): string {
	const text = (id ? (replies.get(id)?.content() ?? '') : '')
		.replace(/```[\s\S]*?```/g, ' ')
		.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
		.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
		.replace(/<[^>]+>/g, ' ')
		.replace(/[#>*_`~|[\]]/g, ' ')
		.replace(/\s+/g, ' ')
		.trim();
	const words = text ? text.split(' ') : [];
	return words.slice(0, n).join(' ') + (words.length > n ? '…' : '');
}

export function togglePause() {
	const ui = get(voiceUI);
	if (ui.kind === 'stream') {
		if (ui.state === 'paused') {
			stopLine();
			resumePetalStream();
		} else pausePetalStream();
	} else if (ui.kind === 'line' && line) {
		if (line.paused) line.play().catch(() => stopLine());
		else line.pause();
	} else if (ui.kind === 'clips') {
		const el = clipElement();
		if (!el) return;
		if (el.paused) el.play().catch(() => {});
		else el.pause();
	}
}

/** what one tap does, for the bubble and the hotkey: pause her while she speaks; while she's paused,
 *  resume her, unless an unheard reply is the one in view now (then that one plays); in the quiet, play
 *  the reply most in view */
export function voiceTap(target: string | null = mostInView()) {
	const ui = get(voiceUI);
	if (ui.state === 'playing' || ui.state === 'loading') return togglePause();
	if (ui.state === 'paused') {
		// A33 · inside an open pick, the reply her eyes moved to plays, heard or not (she's comparing them)
		const f = get(pickFocus);
		const turned = !!target && !!f && f.ids.includes(target) && f.ids.includes(ui.message_id ?? '');
		const unheard = target && target !== ui.message_id && (turned || !get(heardReplies).has(target));
		return unheard ? playReply(target) : togglePause();
	}
	if (target) playReply(target);
}

// ── following her: the sentence she's on, from the rig's events ──────────────────────────────────────
type Shown = { seg: VoiceSentence; range: Range | null; host: HTMLElement | null; block: Element | null };
let segs: VoiceSentence[] = [];
let segsStream: string | null = null;
let segsMessage: string | null = null;
let cursor = 0; // where the last sentence ended, in the reply's letters
let shown: Shown | null = null;
let nextTimer: ReturnType<typeof setTimeout> | null = null;
let hostRO: ResizeObserver | null = null;

const LETTER = /[\p{L}\p{N}]/u;
// what never carries her words: code blocks, buttons, icons, layers that only echo the words
const SKIP =
	'pre, button, svg, script, style, textarea, input, [aria-hidden="true"], [inert], .katex-mathml';

/** the letters only, lowercased (spaces, punctuation, quote marks and emoji fall away on both sides) */
export function letters(text: string): string {
	let out = '';
	for (const ch of text) for (const c of ch.normalize('NFKC').toLowerCase()) if (LETTER.test(c)) out += c;
	return out;
}

type Index = { norm: string; at: { node: Text; start: number; end: number }[] };

/** the reply's words as letters, each one tied back to its place in the page */
function indexWords(host: HTMLElement): Index {
	const at: Index['at'] = [];
	let norm = '';
	const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT, {
		acceptNode(n) {
			const skip = n.parentElement?.closest(SKIP);
			return skip && host.contains(skip) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
		}
	});
	for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
		const s = n.data;
		for (let i = 0; i < s.length; ) {
			const ch = String.fromCodePoint(s.codePointAt(i) ?? 32);
			for (const c of ch.normalize('NFKC').toLowerCase())
				if (LETTER.test(c)) {
					norm += c;
					at.push({ node: n, start: i, end: i + ch.length });
				}
			i += ch.length;
		}
	}
	return { norm, at };
}

/** find the sentence in the reply, after the last one (or anywhere, or by its first words) */
export function locate(host: HTMLElement, text: string, from = 0): { range: Range; end: number } | null {
	const needle = letters(text);
	if (!needle) return null;
	const idx = indexWords(host);
	let pos = idx.norm.indexOf(needle, from);
	let len = needle.length;
	if (pos < 0) pos = idx.norm.indexOf(needle);
	if (pos < 0 && needle.length > 30) {
		// a sentence a little different from the page (a table read aloud, a word the cleaner changed):
		// its first words still say where she is
		const head = needle.slice(0, 24);
		pos = idx.norm.indexOf(head, from);
		if (pos < 0) pos = idx.norm.indexOf(head);
		len = Math.min(needle.length, idx.norm.length - pos);
	}
	if (pos < 0 || !len) return null;
	const a = idx.at[pos];
	const b = idx.at[pos + len - 1];
	const range = document.createRange();
	range.setStart(a.node, a.start);
	range.setEnd(b.node, b.end);
	return { range, end: pos + len };
}

const BLOCKS = 'p, li, h1, h2, h3, h4, h5, h6, blockquote, td, th, dd, dt, figcaption';
function blockOf(range: Range): Element | null {
	const n = range.startContainer;
	const el = n.nodeType === Node.ELEMENT_NODE ? (n as Element) : n.parentElement;
	return el?.closest(BLOCKS) ?? el;
}

// ── the trail (petal-trail.ts): a leading sparkle under the words, sparkles and a rare petal behind ─────
const trail = new Trail(
	() => (lineState !== 'idle' ? lineSync : sync)() // her block came back on screen: meet her again
);

/** she paused (or the tab hid): the whole trail holds still, and the next edge waits for her */
function freeze() {
	if (nextTimer) clearTimeout(nextTimer);
	nextTimer = null;
	trail.freeze();
}

function clearFollower() {
	if (nextTimer) clearTimeout(nextTimer);
	nextTimer = null;
	trail.clear();
	hostRO?.disconnect();
	hostRO = null;
	shown = null;
}

function resetFollower(stream: string | null, message: string | null) {
	clearFollower();
	segs = [];
	segsStream = stream;
	segsMessage = message;
	cursor = 0;
}

/** her next sentence: its road, and the quotes it reaches */
function show(seg: VoiceSentence) {
	const host = replies.get(segsMessage ?? '')?.words() ?? null;
	const found = host ? locate(host, seg.text, cursor) : null;
	shown = { seg, range: found?.range ?? null, host, block: found ? blockOf(found.range) : null };
	if (!found || !host) return trail.rest();
	cursor = found.end;
	trail.lay(found.range, host, seg.duration * 1000);
	trail.watch(shown.block);
	for (const q of host.querySelectorAll<HTMLElement>('.petal-quote'))
		if (found.range.intersectsNode(q)) voiceReveal(q); // her voice reached it: the reveal plays again
	if (!hostRO && typeof ResizeObserver !== 'undefined') {
		hostRO = new ResizeObserver(() => {
			// the page moved under her (a resize, an image arriving): the road is laid again
			if (shown?.range && shown.host) {
				trail.lay(shown.range, shown.host, shown.seg.duration * 1000);
				sync();
			}
		});
		hostRO.observe(host);
	}
}

/** meet her where she is: the sentence followed while start ≤ currentTime < start + duration (none
 *  between two), and a timer for the next edge */
function sync() {
	if (nextTimer) clearTimeout(nextTimer);
	nextTimer = null;
	const a = petalStreamAudio();
	if (!a || !segs.length || get(voiceNow).state === 'idle') return;
	const t = a.currentTime;
	const rate = a.playbackRate || 1;
	const cur = segs.find((s) => s.start <= t && t < s.start + s.duration) ?? null;
	if (!cur) {
		if (shown) trail.rest();
		shown = null;
	} else {
		if (cur !== shown?.seg) show(cur);
		if (shown?.seg === cur) trail.time(t - cur.start, rate, a.paused);
	}
	if (a.paused || document.visibilityState === 'hidden') return;
	let edge = Infinity;
	for (const s of segs) {
		if (s.start > t) edge = Math.min(edge, s.start);
		if (s === cur) edge = Math.min(edge, s.start + s.duration);
	}
	if (edge < Infinity) nextTimer = setTimeout(sync, Math.max(10, ((edge - t) / rate) * 1000 + 5));
}

// ── a quote's line: a click has her say just that line ────────────────────────────────────────────────
let line: HTMLAudioElement | null = null;
let lineQuote: HTMLElement | null = null;
let lineUrl: string | null = null;
let lineTicket = 0;

function setLine(state: LineState, quote: HTMLElement | null = lineQuote) {
	lineState = state;
	lineQuote = quote;
	lineMessage = quote?.closest('[id^="message-"]')?.id.slice('message-'.length) ?? null;
	refresh();
}

function stopLine() {
	if (lineState === 'idle') return;
	lineTicket++;
	if (line) {
		line.pause();
		line.removeAttribute('src');
		line.load();
	}
	if (lineUrl) URL.revokeObjectURL(lineUrl);
	lineUrl = null;
	if (lineTimer) clearTimeout(lineTimer);
	lineTimer = null;
	if (lineFollowed) clearFollower();
	lineFollowed = false;
	lineSeg = lineRange = lineHost = null;
	setLine('idle', null);
}

/** the words a quote says aloud: its own (never the layers that echo them), without emoji */
export function quoteText(quote: HTMLElement): string {
	const base = quote.querySelector<HTMLElement>('.pq-base') ?? quote;
	return (base.innerText || base.textContent || '')
		.replace(/\p{Extended_Pictographic}(?:\p{Emoji_Modifier}|️|‍\p{Extended_Pictographic})*/gu, '')
		.replace(/\s+/g, ' ')
		.trim();
}

function voiceFor(quote: HTMLElement): string | undefined {
	const id = quote.closest('[id^="message-"]')?.id.slice('message-'.length);
	const own = id ? replies.get(id)?.voice() : undefined;
	if (own) return own;
	for (const r of replies.values()) {
		const v = r.voice();
		if (v) return v;
	}
	const s = get(settings) as { audio?: { tts?: { voice?: string } } };
	const c = get(config) as { audio?: { tts?: { voice?: string } } } | undefined;
	return s?.audio?.tts?.voice ?? c?.audio?.tts?.voice;
}

/** which of the message's parts (as petal stream would cut them) holds this quote: its idx */
function partOf(message_id: string, text: string): number | null {
	const content = replies.get(message_id)?.content() ?? lent.get(message_id)?.();
	const target = letters(text);
	if (!content || !target) return null;
	const parts = petalStreamParts(content, getMessageContentParts);
	for (let i = 0; i < parts.length; i++) {
		const l = letters(parts[i].text);
		if (l && (l.includes(target) || target.includes(l))) return i;
	}
	return null;
}

type LineSeg = { start: number; duration: number };
/** the speaker path, with the line's place in its message (contract 11.6): the rig answers the clip and
 *  its events in X-Petal-Voice, url-encoded JSON ({v: 1, events: [sentence, end]}; a bare [sentence, end]
 *  reads the same) */
async function speakLine(token: string, voice: string | undefined, text: string, petal: object | null) {
	const res = await fetch(`${AUDIO_API_BASE_URL}/speech`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({ input: text, ...(voice ? { voice } : {}), ...(petal ? { petal } : {}) })
	}).catch(() => null);
	if (!res?.ok) return null;
	let seg: LineSeg | null = null;
	try {
		const h = res.headers.get('X-Petal-Voice');
		const told = h ? JSON.parse(decodeURIComponent(h)) : null;
		const events: { type?: string; start?: number; duration?: number }[] = Array.isArray(told)
			? told
			: Array.isArray(told?.events)
				? told.events
				: [];
		const said = events.find((e) => e?.type === 'sentence') ?? (Array.isArray(told) ? told[0] : null);
		if (said && Number.isFinite(said.start) && Number.isFinite(said.duration))
			seg = { start: said.start as number, duration: Math.max(0, said.duration as number) };
	} catch {}
	const blob = await res.blob().catch(() => null);
	return blob ? { blob, seg } : null;
}

let lineSeg: LineSeg | null = null;
let lineRange: Range | null = null;
let lineHost: HTMLElement | null = null;
let lineFollowed = false; // its road is laid
let lineTimer: ReturnType<typeof setTimeout> | null = null;

/** the line, followed while she says it (by the rig's timing, or the whole clip without it) */
function lineSync() {
	if (lineTimer) clearTimeout(lineTimer);
	lineTimer = null;
	const a = line;
	if (!a || lineState === 'idle' || !lineRange || !lineHost) return;
	const t = a.currentTime;
	const seg = lineSeg ?? { start: 0, duration: Number.isFinite(a.duration) ? a.duration : 0 };
	const on = seg.duration > 0 && seg.start <= t && t < seg.start + seg.duration;
	if (on) {
		if (!lineFollowed) {
			trail.lay(lineRange, lineHost, seg.duration * 1000);
			trail.watch(lineQuote);
			lineFollowed = true;
		}
		trail.time(t - seg.start, a.playbackRate, a.paused);
	} else if (lineFollowed) trail.rest();
	if (a.paused) return;
	const edge = t < seg.start ? seg.start : t < seg.start + seg.duration ? seg.start + seg.duration : Infinity;
	if (edge < Infinity)
		lineTimer = setTimeout(lineSync, ((edge - t) / (a.playbackRate || 1)) * 1000 + 5);
}

/** a click on a display quote: she says just that line, unless she's already speaking (the reveal plays
 *  either way, from PetalQuote) · only through the speaker path (/audio/speech, under B's ceiling) */
export async function speakQuote(quote: HTMLElement) {
	if (speakingNow()) return;
	const c = get(config) as { audio?: { tts?: { engine?: string } } } | undefined;
	const s = get(settings) as { audio?: { tts?: { engine?: string; playbackRate?: number } } };
	if (!c?.audio?.tts?.engine || s?.audio?.tts?.engine === 'browser-kokoro') return;
	const text = quoteText(quote);
	if (!/[\p{L}\p{N}]/u.test(text)) return;
	wire();
	const ticket = ++lineTicket;
	setLine('loading', quote);
	let token = '';
	try {
		token = localStorage.token ?? '';
	} catch {}
	const mid = lineMessage;
	const idx = mid ? partOf(mid, text) : null;
	const got = await speakLine(token, voiceFor(quote), text, mid && idx !== null ? { message_id: mid, idx } : null);
	if (ticket !== lineTicket) return;
	if (!got) return stopLine();
	if (!line) {
		line = new Audio();
		line.setAttribute('playsinline', '');
	}
	const a = line;
	lineUrl = URL.createObjectURL(got.blob);
	a.src = lineUrl;
	a.playbackRate = s?.audio?.tts?.playbackRate ?? 1;
	lineSeg = got.seg;
	lineHost = quote.closest<HTMLElement>('#response-content-container') ?? quote;
	lineRange = document.createRange();
	lineRange.selectNodeContents(quote.querySelector<HTMLElement>('.pq-base') ?? quote);
	lineFollowed = false;
	a.onplaying = () => {
		if (ticket !== lineTicket) return;
		setLine('playing', quote);
		lineSync();
	};
	a.onpause = () => {
		if (ticket !== lineTicket || a.ended) return;
		setLine('paused', quote);
		if (lineTimer) clearTimeout(lineTimer);
		lineTimer = null;
		freeze();
	};
	a.onended = a.onerror = () => {
		if (ticket === lineTicket) stopLine();
	};
	a.play().catch(() => ticket === lineTicket && stopLine());
}

// ── wiring: the stream's state, its sentences, sentence clips, the page ──────────────────────────────
let wired = false;
let hookedAudio: HTMLAudioElement | null = null;
let clipIdle: ReturnType<typeof setTimeout> | null = null;

const clipElement = () =>
	typeof document !== 'undefined'
		? (document.getElementById('audioElement') as HTMLAudioElement | null)
		: null;

function hookAudio() {
	const a = petalStreamAudio();
	if (!a || a === hookedAudio) return;
	hookedAudio = a;
	// the page's own pause and resume arrive as events; these keep her clock in step in between
	a.addEventListener('playing', sync);
	a.addEventListener('seeked', sync);
	a.addEventListener('ratechange', sync);
	a.addEventListener('waiting', freeze);
	a.addEventListener('timeupdate', pinNow); // A33 · a few times a second while she plays: on her clock
}

/** A33 · between two edges, a few times a second while she plays (the audio's own timeupdate, no timer): the
 *  lead stays pinned to her clock, never ahead of her voice and never stepping back · a sentence that ended,
 *  or one the rig has told meanwhile, is met at its edge */
function pinNow() {
	if (lineState !== 'idle') return;
	const a = petalStreamAudio();
	if (!a || a.paused || document.visibilityState === 'hidden' || get(voiceNow).state === 'idle') return;
	const seg = shown?.seg;
	if (!seg) return segs.length ? sync() : undefined;
	const t = a.currentTime;
	if (t < seg.start || t >= seg.start + seg.duration) return sync();
	trail.pin(t - seg.start, a.playbackRate || 1);
}

/** the sentence clips (petal stream's fallback) are her voice too: the bubble can pause them */
function hookClips() {
	const el = clipElement();
	if (!el || (el as HTMLAudioElement & { __petalVoice?: boolean }).__petalVoice) return;
	(el as HTMLAudioElement & { __petalVoice?: boolean }).__petalVoice = true;
	const set = (state: typeof clips.state) => {
		if (clipIdle) clearTimeout(clipIdle);
		clipIdle = null;
		const real = !!el.currentSrc && !el.currentSrc.startsWith('data:'); // not the silent unlock
		const id = (get(audioQueue) as { id?: string | null } | null)?.id ?? null;
		if (state === 'idle' || !real) {
			// between two clips the element rests a moment: only a longer rest is the end
			clipIdle = setTimeout(() => {
				clips = { state: 'idle', message_id: null };
				refresh();
			}, 600);
			return;
		}
		clips = { state, message_id: id };
		refresh();
	};
	el.addEventListener('playing', () => set('playing'));
	el.addEventListener('pause', () => set(el.ended || !el.currentSrc ? 'idle' : 'paused'));
	el.addEventListener('emptied', () => set('idle'));
}

function wire() {
	if (wired || typeof window === 'undefined') return;
	wired = true;
	voiceNow.subscribe((v) => {
		hookAudio();
		hookClips();
		if (v.state === 'idle') {
			if (segsStream && (!v.id || v.id === segsStream)) resetFollower(null, null);
			if (v.ended === 'natural' && v.message_id) {
				// heard to her last word: the bubble may rest on this one
				const id = v.message_id;
				heardReplies.update((h) => new Set(h).add(id));
			}
		} else if (v.id && v.id !== segsStream) resetFollower(v.id, v.message_id);
		refresh();
	});
	onPetalVoice((e, stream) => {
		if (stream !== segsStream) resetFollower(stream, e.message_id ?? get(voiceNow).message_id);
		if (e.type === 'sentence') {
			// kept by idx: a later start replaces it (a take the rig made again)
			const had = segs.find((s) => s.idx === e.idx);
			if (had && had.start > e.start) return;
			segs = [...segs.filter((s) => s.idx !== e.idx), e].sort((a, b) => a.start - b.start);
			sync();
		} else if (e.type === 'pause') freeze();
		else if (e.type === 'resume') sync();
		else clearFollower(); // end · stop
	});
	document.addEventListener('visibilitychange', () => {
		if (document.visibilityState !== 'visible') return freeze();
		if (pending) look(); // A31 · what changed while the page was hidden, decided once
		if (lineState !== 'idle') lineSync();
		else sync();
	});
	pickFocus.subscribe(() => look()); // A31 · her eyes moved inside an open pick
	(window as unknown as { petalVoice?: object }).petalVoice = {
		get eyes() {
			return { target: get(voiceTarget), ...eyesStats }; // ids and numbers only
		},
		/** A33 · the trail, numbers only: the lead's state, ms into its road, ms it last was ahead of her voice */
		get trail() {
			return trail.state;
		}
	};
}
