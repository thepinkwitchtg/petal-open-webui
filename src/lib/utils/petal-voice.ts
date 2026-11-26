// 🎙️ her voice on the page (slices A19 · A19b · A20 · A21 · A22 · A31 · 🧵 A46): the way in, where she is, and what she lights on the way.
//  · the registry: every reply on screen says how to speak it (ResponseMessage registers itself)
//  · one control, Lily's choice (Settings → Interface → Voice control): the bubble (PetalVoiceBubble, left
//    of the chat bar: plays the reply most in view, pause while she speaks, fades once that reply is heard)
//    or OWUI's speaker by her name (PetalPlayButton). one reply per tap: she never reads on by herself
//  · her eyes (A31): the reply most in view, followed by one IntersectionObserver (never a scroll listener):
//    the largest share of itself in view, by tenths, a tie to the one nearest the view's middle · inside an
//    open pick, the reply she swiped to (phone) or last pointed at (desktop)
//  · 🧵 A46 · one thread (petalStream.ts) owns what's playing: every way in here asks it (speakReply, speakQuote,
//    playReply, voiceTap), and every control reads its mirror (voiceUI), so the ✕, the play button, the bubble and
//    the trail can never disagree. the voice she speaks in has one answer too (chosenVoice: the reply's model's own,
//    else her pick in Settings → Audio, else her Petal voice), and a pick made while she speaks applies from the
//    next sentence
//  · the trail (petal-trail.ts): where she is, as a small run of soft pink under the words she's saying. 🧵 A46 · it
//    follows the sentence whose audio is sounding (the thread says, on the audio's own clock) and finds it in its own
//    reply by its place there (the reply's sentences walked in order, each after the one before), so it moves forward
//    only: a phrase that repeats an earlier one, a sentence told again, a rebuffer never send it back. it pauses with
//    her, and nothing of it moves off-screen, in a hidden tab or with reduced motion (a still dot marks her sentence
//    then); on a low battery (auto quotes) only the leading mark travels. a line the voice gave up wears a dotted
//    pink underline (said, never a silent stop)
//  · quotes: when her voice reaches a display quote, its reveal plays again; a click on a quote reveals it
//    and has her say only that line (the speaker path, under B's ceiling), if she isn't already speaking
//  · A35 · her voice paused, the lead holds where she is and what it left finishes falling; only off her screen or
//    in a hidden tab does everything hold (and carry on from there). her reply drawn again under her (a pick
//    closing, the list keyed again, its words re-rendered) is found again where it is now, by its place; gone from
//    the page (the chat changed), nothing of the trail stays
import { get, writable } from 'svelte/store';
import { config, settings } from '$lib/stores';
import { getMessageContentParts } from '$lib/utils';
import {
	onSounding,
	petalStreamAudio,
	petalStreamEnabled,
	petalStreamParts,
	revoice,
	speakVoice,
	stopVoice,
	toggleVoice,
	voiceRows,
	voiceSpeaking,
	voiceThread,
	voiceUI,
	type Sounding,
	type VoiceRow,
	type VoiceSkip
} from '$lib/utils/petalStream';
import { fxMode, voiceReveal } from '$lib/utils/petal-quote-fx';
import { batteryLow } from '$lib/utils/petal-battery';
import { Trail } from '$lib/utils/petal-trail';

export { voiceUI };
export type { VoiceUI, VoiceKind } from '$lib/utils/petalStream';

// ── the registry ─────────────────────────────────────────────────────────────────────────────────────
export type VoiceReply = {
	id: string; // its message id
	root: () => HTMLElement | null; // the whole reply (#message-<id>): how much of it is in view
	words: () => HTMLElement | null; // where its words live (positioned: the trail travels inside it)
	done: () => boolean;
	speak: () => unknown; // her voice from its first sentence (petal stream, or its fallback)
	voice: () => string | undefined; // the voice it speaks in
	content: () => string; // its words as written (a quote said alone finds its part here)
	// 🌱 A37 · what a growing stream needs to speak it while she writes (its chat, its model's name and picture)
	meta?: () => { chat_id?: string; model?: string; title?: string; artwork?: string; playbackRate?: number };
	pick?: () => boolean; // 🍒 one of a pair: her voice waits for the pick (contract 11.6)
	pair?: () => [string, string] | null; // 🍒 A38 · shown inside an open pick: both replies, in the order they show
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
	if (shown && r.id === shown.row.mid) relocateSoon(); // A35 · the reply she's hearing, drawn again: the trail follows
	return () => {
		if (replies.get(r.id) === r) replies.delete(r.id);
		bump();
		if (shown && r.id === shown.row.mid) relocateSoon(); // gone, or about to be drawn again: decided on the next frame
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

/** 🌱 A37 · a reply on the page, as it registered itself (autoplay speaks it from here) */
export const replyOf = (id: string): VoiceReply | undefined => replies.get(id);

/** ⏹ A37 · her voice stops, whatever was speaking (🧵 A46 · one thread: the stream, a quote's line, sentence clips, the
 *  browser's own voice all live there) */
export function stopAllVoice() {
	stopVoice();
	try {
		if (typeof speechSynthesis !== 'undefined' && speechSynthesis.speaking) speechSynthesis.cancel();
	} catch {}
}

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

/** 🔈 A40 · a reply still being written, outside an open pick, that already shows words: the play button joins it */
const writingWithWords = (r: VoiceReply) => !r.done() && !r.pair?.() && !!r.content().trim();

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
		if (share <= 0 || (!r.done() && !mine && !writingWithWords(r))) continue;
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


// ── what the page shows of her voice: the one thread's mirror (voiceUI, from petalStream.ts) ──────────────────
/** she's speaking now (on her way or sounding, or the browser's own voice elsewhere) · paused counts as quiet */
export function speakingNow(): boolean {
	if (voiceSpeaking()) return true;
	try {
		return typeof speechSynthesis !== 'undefined' && speechSynthesis.speaking;
	} catch {
		return false;
	}
}

// ── 🧵 A46 · the picker: one answer for the voice she speaks in ────────────────────────────────────────────────
type TTS = { voice?: string; defaultVoice?: string; engine?: string; playbackRate?: number };
const ttsOf = (s: unknown): TTS => ((s as { audio?: { tts?: TTS } } | null)?.audio?.tts ?? {}) as TTS;
/** the voice she picked in Settings → Audio: her own choice, never the copy of the default saved beside it (OWUI
 *  saves the default it saw as defaultVoice) · '' when she picked none */
export function pickedVoice(): string {
	const s = ttsOf(get(settings));
	const pick = typeof s.voice === 'string' ? s.voice.trim() : '';
	if (!pick) return '';
	return pick !== (typeof s.defaultVoice === 'string' ? s.defaultVoice.trim() : '') ? pick : '';
}
/** the voice she speaks in, the same answer for every way in (the speaker, autoplay, a pick, her stream, a quote): the
 *  reply's model's own voice (Workspace → Models) · else her pick (Settings → Audio) · else her Petal voice (the
 *  admin's voice; empty: the rig's own default, her Petal voice) */
export function chosenVoice(modelVoice?: string | null): string {
	if (typeof modelVoice === 'string' && modelVoice.trim()) return modelVoice.trim();
	const pick = pickedVoice();
	if (pick) return pick;
	const c = ttsOf(get(config));
	return typeof c.voice === 'string' ? c.voice.trim() : '';
}

// ── the way in: one reply per tap ─────────────────────────────────────────────────────────────────────
/** her voice from this reply's first sentence (whatever else was playing stops) */
// 🔈 A40 · a reply still being written plays live: autoplay's growing stream joins it and follows the typing
let livePlayer: ((id: string) => boolean) | null = null;
export const setLivePlayer = (f: ((id: string) => boolean) | null) => void (livePlayer = f);

export function playReply(id: string) {
	const r = replies.get(id);
	if (!r) return;
	if (!r.done() && livePlayer?.(id)) return;
	r.speak();
}

/** 🧵 A46 · a whole reply, spoken through the one thread (the speaker button, the bubble, a replay, after she
 *  finishes): her petal stream (its sentence clips if the stream can't open) · the in-browser engine's clips · the
 *  browser's own voice for OWUI's engine '' */
export type ReplyVoice = {
	id: string;
	chat_id?: string | null;
	content: string;
	modelVoice?: string | null;
	model?: string;
	title?: string;
	artwork?: string;
	playbackRate?: number;
	kokoro?: (text: string, voice: string) => Promise<string | null | undefined>; // the in-browser engine (its worker)
	onNatural?: () => void; // the browser's own voice reached her last word (OWUI's conversation mode listens again)
};
export function speakReply(r: ReplyVoice): Promise<boolean> {
	const c = ttsOf(get(config));
	const s = ttsOf(get(settings));
	const voice = chosenVoice(r.modelVoice);
	const base = {
		message_id: r.id,
		chat_id: r.chat_id ?? null,
		title: r.title,
		artwork: r.artwork,
		playbackRate: r.playbackRate ?? s.playbackRate ?? 1,
		voice,
		revoice: () => chosenVoice(r.modelVoice)
	};
	if (!c.engine && s.engine !== 'browser-kokoro')
		return speakVoice({
			...base,
			kind: 'browser',
			text: r.content,
			voiceURI: voice,
			onEnded: () => {
				if (get(voiceThread).why === 'natural') r.onNatural?.();
			}
		});
	const parts = petalStreamParts(r.content, getMessageContentParts);
	if (!parts.length) return Promise.resolve(false);
	const text = (i: number) => parts[i]?.text ?? '';
	if (s.engine === 'browser-kokoro' && r.kokoro) {
		const make = r.kokoro;
		return speakVoice({
			...base,
			kind: 'clips',
			clips: {
				count: parts.length,
				text,
				make: async (i) => {
					const url = await make(text(i), voice);
					return url ? { url, seg: null } : null;
				}
			}
		});
	}
	if (petalStreamEnabled())
		return speakVoice({
			...base,
			kind: 'stream',
			parts,
			fallback: true,
			meta: { chat_id: r.chat_id ?? undefined, message_id: r.id, model: r.model, source: r.content }
		});
	return speakVoice({ ...base, kind: 'clips', clips: { count: parts.length, text } });
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

/** pause her while she speaks, resume her while she's paused (one thread: whatever kind she speaks in) */
export function togglePause() {
	toggleVoice();
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

// ── following her: the sentence sounding now (the thread says, on the audio's own clock) ─────────────────────
type Shown = {
	seq: number;
	row: VoiceRow;
	range: Range | null;
	host: HTMLElement | null;
	block: Element | null;
	running: boolean;
	pos: number; // where its words end in the reply's letters (forward only: her console reads it)
};
let shown: Shown | null = null;
let followSeq = 0;
let hostRO: ResizeObserver | null = null;
let roHost: HTMLElement | null = null; // the words the ResizeObserver watches now (it follows her reply when it's drawn again)
let relocating = 0;

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

/** a sentence's letters, found at or after `from` (never before): near (within a little of `from`) for the
 *  sentences walked on the way, anywhere ahead for the one she's saying · its first words when it reads a
 *  little differently on the page (a table read aloud, a word the cleaner changed) */
function findIn(ix: Index, needle: string, from: number, near: boolean): { pos: number; len: number } | null {
	if (!needle) return null;
	const slack = near ? Math.max(160, needle.length * 2) : Infinity;
	let pos = ix.norm.indexOf(needle, from);
	let len = needle.length;
	if (pos < 0 && needle.length > 30) {
		pos = ix.norm.indexOf(needle.slice(0, 24), from);
		len = Math.min(needle.length, ix.norm.length - pos);
	}
	if (pos < 0 || !len || pos - from > slack) return null;
	return { pos, len };
}
function rangeOf(ix: Index, pos: number, len: number): Range {
	const a = ix.at[pos];
	const b = ix.at[pos + len - 1];
	const range = document.createRange();
	range.setStart(a.node, a.start);
	range.setEnd(b.node, b.end);
	return range;
}

/** find the sentence in the reply after `from` (forward only: a repeated phrase earlier in the reply is never it) */
export function locate(host: HTMLElement, text: string, from = 0): { range: Range; end: number } | null {
	const ix = indexWords(host);
	const f = findIn(ix, letters(text), from, false);
	return f ? { range: rangeOf(ix, f.pos, f.len), end: f.pos + f.len } : null;
}

/** 🧵 A46 · a sentence in its own reply, by its place there (idx): the reply's sentences (the page's own cut, the
 *  rig's too) are walked in order from its start, each found after the one before, so the sentence she's saying is
 *  found where it truly is · a sentence that can't be found leaves the walk where it was (the next ones still are) */
export function place(host: HTMLElement, content: string, idx: number, text: string): { range: Range; end: number } | null {
	const ix = indexWords(host);
	const parts = petalStreamParts(content, getMessageContentParts);
	let from = 0;
	for (let j = 0; j < Math.min(idx, parts.length); j++) {
		const f = findIn(ix, letters(parts[j].text), from, true);
		if (f) from = f.pos + f.len;
	}
	const needle = letters(text);
	const f = findIn(ix, needle, from, true) ?? findIn(ix, needle, from, false);
	return f ? { range: rangeOf(ix, f.pos, f.len), end: f.pos + f.len } : null;
}

const BLOCKS = 'p, li, h1, h2, h3, h4, h5, h6, blockquote, td, th, dd, dt, figcaption';
function blockOf(range: Range): Element | null {
	const n = range.startContainer;
	const el = n.nodeType === Node.ELEMENT_NODE ? (n as Element) : n.parentElement;
	return el?.closest(BLOCKS) ?? el;
}

// ── the trail (petal-trail.ts): a leading sparkle under the words, sparkles and a rare petal behind ─────
const trail = new Trail({
	back: () => resync(), // her block came back on screen: meet her again
	lost: () => relocateSoon(), // her block left the page: find her words where they are now
	simple: () => fxMode() === 'auto' && batteryLow() // auto quotes on a low battery: the lead alone (her setting)
});

function unobserveHost() {
	hostRO?.disconnect();
	hostRO = null;
	roHost = null;
}

function clearFollower() {
	if (relocating && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(relocating);
	relocating = 0;
	trail.clear();
	unobserveHost();
	shown = null;
	lineFollowed = false;
}

/** a range still standing on the page (its words weren't drawn again under it) */
const alive = (r: Range | null) =>
	!!r && r.startContainer.isConnected && r.endContainer.isConnected && !r.collapsed;

/** A35 · her reply was drawn again (a pick closing, the list keyed again) or its words re-rendered under her, or it
 *  left the page: looked at on the next frame, once the page has settled */
function relocateSoon() {
	if (relocating || typeof requestAnimationFrame === 'undefined') return;
	relocating = requestAnimationFrame(relocate);
}

/** the sentence she's on, found again in the page as it is now, by its place · her reply not on the page (the chat
 *  changed): nothing of the trail stays, and it's found again if her reply comes back */
function relocate() {
	relocating = 0;
	if (lineQuote) return lineLost();
	const s = shown;
	if (!s) return;
	const host = replies.get(s.row.mid ?? '')?.words() ?? null;
	if (host?.isConnected && host === s.host && (!s.range || alive(s.range))) return; // nothing moved
	if (!host?.isConnected) {
		trail.clear();
		unobserveHost();
		shown = { ...s, range: null, host: null, block: null, running: false, pos: -1 };
		return;
	}
	shown = null;
	resync();
}

/** watch the words her voice is in for a change of size (one observer, following her reply when it's drawn again) */
function observeHost(host: HTMLElement) {
	if (typeof ResizeObserver === 'undefined' || roHost === host) return;
	hostRO ??= new ResizeObserver(() => {
		// the page moved under her (a resize, an image arriving): the road is laid again · drawn again: found again
		const s = shown;
		if (!s?.range || !s.host) return;
		if (!s.host.isConnected || !alive(s.range)) return relocateSoon();
		trail.lay(s.range, s.host, s.row.duration * 1000);
		s.running = false;
		resync();
	});
	if (roHost) hostRO.unobserve(roHost);
	hostRO.observe(host);
	roHost = host;
}

/** her next sentence: its road under its words, in its own reply, and the quotes it reaches */
function show(seq: number, row: VoiceRow) {
	const r = replies.get(row.mid ?? '');
	const live = r?.words() ?? null;
	const host = live?.isConnected ? live : null;
	const found = host && r && !row.cue ? place(host, r.content(), row.idx, row.text) : null;
	shown = { seq, row, range: found?.range ?? null, host, block: found ? blockOf(found.range) : null, running: false, pos: found?.end ?? -1 };
	if (!found || !host) return trail.rest(); // her cue, or words the page doesn't show: the lead rests
	trail.lay(found.range, host, (Number.isFinite(row.duration) ? row.duration : 2) * 1000);
	trail.watch(shown.block);
	for (const q of host.querySelectorAll<HTMLElement>('.petal-quote'))
		if (found.range.intersectsNode(q)) voiceReveal(q); // her voice reached it: the reveal plays again
	observeHost(host);
}

/** 🧵 A46 · the thread looked at her clock: the trail follows what it says is sounding, never a clock of its own */
function follow(s: Sounding) {
	if (s.seq !== followSeq) {
		clearFollower();
		clearSkips();
		followSeq = s.seq;
	}
	if (s.ended) return clearFollower();
	if (s.kind === 'line') return lineFollow(s);
	if (s.skip) markSkip(s.skip);
	const row = s.row;
	if (!row) {
		// between two sentences (or a line the voice gave up): the lead fades, what it left finishes falling
		if (shown?.range) trail.rest();
		if (shown) shown.running = false;
		return;
	}
	if (shown?.host && (!shown.host.isConnected || (shown.range && !alive(shown.range)))) return relocateSoon(); // A35
	if (!shown || shown.row !== row || shown.seq !== s.seq) show(s.seq, row);
	if (!shown?.range) return;
	if (s.paused || s.waiting) {
		trail.hold(); // paused, or the stream is waiting for words: the lead holds where she is
		shown.running = false;
		return;
	}
	if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return trail.freeze();
	if (!shown.running) {
		trail.time(s.at, s.rate, false);
		shown.running = true;
	} else trail.pin(s.at, s.rate); // A33 · on her clock: never ahead of her voice, never stepping back
}

/** meet her where she is now (her block back on screen, the tab visible again, her reply drawn again) */
function resync() {
	const a = petalStreamAudio();
	const now = get(voiceThread);
	if (!a || (now.state !== 'playing' && now.state !== 'paused')) return;
	if (shown) shown.running = false;
	if (lineQuote) lineFollowed = false;
	a.dispatchEvent?.(new Event('timeupdate')); // the thread looks at her clock and tells the trail
}

// ── 🧵 A46 · a line the voice gave up: a dotted pink underline under its words (said, never a silent stop) ──────
const skipRanges: Range[] = [];
function markSkip(k: VoiceSkip) {
	const r = replies.get(k.mid ?? '');
	const host = r?.words();
	if (!r || !host?.isConnected) return;
	const f = place(host, r.content(), k.idx, k.text);
	if (!f) return;
	skipRanges.push(f.range);
	paintSkips();
}
function clearSkips() {
	if (!skipRanges.length) return;
	skipRanges.length = 0;
	paintSkips();
}
function paintSkips() {
	const H = (globalThis as { Highlight?: new (...r: Range[]) => unknown }).Highlight;
	const reg = (globalThis as { CSS?: { highlights?: Map<string, unknown> } }).CSS?.highlights;
	if (!H || !reg) return;
	if (!document.getElementById('petal-voice-skip-style')) {
		const st = document.createElement('style');
		st.id = 'petal-voice-skip-style';
		st.textContent =
			'::highlight(petal-voice-skip){text-decoration:underline dotted rgb(255 120 192 / 0.8);text-decoration-thickness:2px;text-underline-offset:4px}';
		document.head.appendChild(st);
	}
	const live = skipRanges.filter(alive);
	if (live.length) reg.set('petal-voice-skip', new H(...live));
	else reg.delete('petal-voice-skip');
}

// ── a quote's line: a click has her say just that line ────────────────────────────────────────────────
let lineQuote: HTMLElement | null = null;
let lineSeq = 0;
let lineFollowed = false; // its road is laid

/** the words a quote says aloud: its own (never the layers that echo them), without emoji */
export function quoteText(quote: HTMLElement): string {
	const base = quote.querySelector<HTMLElement>('.pq-base') ?? quote;
	return (base.innerText || base.textContent || '')
		.replace(/\p{Extended_Pictographic}(?:\p{Emoji_Modifier}|️|‍\p{Extended_Pictographic})*/gu, '')
		.replace(/\s+/g, ' ')
		.trim();
}

function voiceFor(quote: HTMLElement): string {
	const id = quote.closest('[id^="message-"]')?.id.slice('message-'.length);
	const own = id ? replies.get(id)?.voice() : undefined;
	return own || chosenVoice();
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

/** the line, followed while she says it (by the rig's timing, or the whole clip without it) */
function lineFollow(s: Sounding) {
	const q = lineQuote;
	if (s.seq !== lineSeq || !q) return;
	const host = q.closest<HTMLElement>('#response-content-container') ?? q;
	if (!host.isConnected) return lineLost(); // A35 · her reply drawn again under the line: the trail lets go
	if (!s.row) {
		if (lineFollowed) trail.rest();
		return;
	}
	if (!lineFollowed) {
		const range = document.createRange();
		range.selectNodeContents(q.querySelector<HTMLElement>('.pq-base') ?? q);
		const a = petalStreamAudio();
		const d = Number.isFinite(s.row.duration) ? s.row.duration : a && Number.isFinite(a.duration) ? a.duration : 3;
		trail.lay(range, host, d * 1000);
		trail.watch(q);
		lineFollowed = true;
		return s.paused ? trail.hold() : trail.time(s.at, s.rate, false);
	}
	if (s.paused || s.waiting) trail.hold();
	else trail.pin(s.at, s.rate);
}

/** A35 · the reply her line lives in left the page (drawn again, the chat changed): the line plays on, the trail
 *  lets go at once (its marks leave with it) */
function lineLost() {
	if (lineQuote?.isConnected) return;
	if (lineFollowed) trail.clear();
	lineFollowed = false;
}

/** a click on a display quote: she says just that line, unless she's already speaking (the reveal plays
 *  either way, from PetalQuote) · only through the speaker path (/audio/speech, under B's ceiling) */
export async function speakQuote(quote: HTMLElement) {
	if (speakingNow()) return;
	const c = ttsOf(get(config));
	const s = ttsOf(get(settings));
	if (!c.engine || s.engine === 'browser-kokoro') return;
	const text = quoteText(quote);
	if (!/[\p{L}\p{N}]/u.test(text)) return;
	wire();
	const mid = quote.closest('[id^="message-"]')?.id.slice('message-'.length) ?? null;
	const idx = mid ? partOf(mid, text) : null;
	lineQuote = quote;
	lineFollowed = false;
	const said = speakVoice({
		kind: 'line',
		message_id: mid,
		voice: voiceFor(quote),
		revoice: () => voiceFor(quote),
		playbackRate: s.playbackRate ?? 1,
		petal: mid && idx !== null ? { message_id: mid, idx } : null,
		clips: { count: 1, idx: () => idx ?? 0, text: () => text }
	});
	lineSeq = get(voiceThread).seq;
	await said;
}

// ── wiring: the thread's look at her clock, the page ──────────────────────────────────────────────────────
let wired = false;
const notes = writable<{ seq: number; note: string } | null>(null);
/** 🧵 A46 · what her voice needs her to know (a break it couldn't heal): the bubble says it once */
export const voiceNotes = { subscribe: notes.subscribe };

function wire() {
	if (wired || typeof window === 'undefined') return;
	wired = true;
	onSounding(follow);
	let noted = 0;
	voiceThread.subscribe((t) => {
		if (t.state === 'ended' && t.why === 'natural' && t.message_id && t.kind !== 'line') {
			// heard to her last word (a whole reply, never a quote said alone): the bubble may rest on this one
			const id = t.message_id;
			heardReplies.update((h) => (h.has(id) ? h : new Set(h).add(id)));
		}
		if (t.state === 'error' && t.note && t.seq !== noted) {
			noted = t.seq;
			notes.set({ seq: t.seq, note: t.note });
		}
		if (t.state !== 'playing' && t.state !== 'paused' && t.state !== 'loading' && lineQuote && t.seq === lineSeq) {
			lineQuote = null;
			lineFollowed = false;
		}
	});
	// 🧵 A46 · a voice she picks while she speaks: the thread speaks in it from the next sentence
	settings.subscribe(() => revoice());
	document.addEventListener('visibilitychange', () => {
		if (document.visibilityState !== 'visible') return trail.freeze();
		if (pending) look(); // A31 · what changed while the page was hidden, decided once
		resync();
	});
	pickFocus.subscribe(() => look()); // A31 · her eyes moved inside an open pick
	(window as unknown as { petalVoice?: object }).petalVoice = {
		get eyes() {
			return { target: get(voiceTarget), ...eyesStats }; // ids and numbers only
		},
		/** A33 · the trail, numbers only: the lead's state, ms into its road, ms it last was ahead of her voice */
		get trail() {
			return trail.state;
		},
		/** 🧵 A46 · the one thread, ids and numbers only: what plays, its part, why it last ended, and its rows */
		get thread() {
			const t = get(voiceThread);
			return {
				...t,
				shown: shown ? { mid: shown.row.mid, idx: shown.row.idx, found: !!shown.range, pos: shown.pos } : null,
				rows: voiceRows().map((r) => ({ mid: r.mid, idx: r.idx, start: r.start, duration: r.duration, cue: r.cue, order: r.order }))
			};
		}
	};
}
