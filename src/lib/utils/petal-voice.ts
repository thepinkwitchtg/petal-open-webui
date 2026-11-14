// 🎙️ her voice on the page (slices A19 · A19b): the way in, where she is, and what she lights on the way.
//  · the registry: every reply on screen says how to speak it (ResponseMessage registers itself)
//  · one control, Lily's choice (Settings → Interface → Voice control): the bubble (PetalVoiceBubble, left
//    of the chat bar: plays the reply most in view, pause while she speaks, fades once that reply is heard)
//    or OWUI's speaker by her name (PetalPlayButton). one reply per tap: she never reads on by herself
//  · the trail: where she is, as a small run of soft pink sparkles under the words she's saying (where she
//    is in a sentence is estimated from its timing). it pauses with her, and nothing of it moves off-screen,
//    in a hidden tab or with reduced motion (a still dot marks her sentence then); on a low battery (auto
//    quotes) only the leading sparkle travels
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
import { batteryLow } from '$lib/utils/petal-battery';

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
const bump = () => voiceReplies.update((n) => n + 1);

// a reply that came while she was here (it registered still arriving), and the newest one that finished:
// the bubble comes back for it, even when an older reply fills more of the screen
const arriving = new Set<string>();
let fresh: string | null = null;

export function registerReply(r: VoiceReply): () => void {
	wire();
	replies.set(r.id, r);
	if (!r.done()) arriving.add(r.id);
	bump();
	return () => {
		if (replies.get(r.id) === r) replies.delete(r.id);
		bump();
	};
}

/** a reply finished arriving (ResponseMessage tells, also for replies that were done from the start) */
export const replyDone = (id: string) => {
	if (!arriving.delete(id)) return;
	fresh = id; // a new one to hear
	bump();
};

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

/** the reply the bubble plays: one that just finished arriving, while any of it is on screen and it's
 *  unheard; otherwise the reply most in view (or the last one, with none in view) */
export function mostInView(): string | null {
	const box = document.getElementById('messages-container')?.getBoundingClientRect();
	const top = box?.top ?? 0;
	const bottom = box?.bottom ?? window.innerHeight;
	let best: string | null = null;
	let bestSeen = 0;
	let freshSeen = 0;
	let last: { id: string; at: number } | null = null;
	for (const r of replies.values()) {
		const el = r.root();
		if (!el || !r.done()) continue;
		const rect = el.getBoundingClientRect();
		if (!last || rect.top > last.at) last = { id: r.id, at: rect.top };
		const seen = Math.min(rect.bottom, bottom) - Math.max(rect.top, top);
		if (r.id === fresh) freshSeen = seen;
		if (seen > bestSeen + 1) [best, bestSeen] = [r.id, seen];
	}
	if (fresh && (freshSeen <= 0 || get(heardReplies).has(fresh))) fresh = null; // gone from view, or heard
	return fresh ?? best ?? last?.id ?? null;
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
		const unheard = target && target !== ui.message_id && !get(heardReplies).has(target);
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

const reduced = () =>
	typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
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

/** the lines a range covers, as boxes (text only: each text node measured on its own) */
function lineBoxes(range: Range) {
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

const BLOCKS = 'p, li, h1, h2, h3, h4, h5, h6, blockquote, td, th, dd, dt, figcaption';
function blockOf(range: Range): Element | null {
	const n = range.startContainer;
	const el = n.nodeType === Node.ELEMENT_NODE ? (n as Element) : n.parentElement;
	return el?.closest(BLOCKS) ?? el;
}

// ── the trail: a leading sparkle under the words, soft pink sparkles fading behind it ─────────────────
type Road = { lines: { x0: number; x1: number; y: number }[]; total: number };
const POOL = 18; // the sparkles it leaves behind, reused
const DROP_MS: [number, number] = [60, 85]; // one dropped this often while she speaks
const FADE_MS: [number, number] = [750, 1100]; // each one fades over this long
let road: Road | null = null;
let roadMs = 0;
let roadHost: HTMLElement | null = null;
let lead: HTMLElement | null = null; // the leading sparkle (a still dot with reduced motion)
let leadAnim: Animation | null = null;
const dust: HTMLElement[] = [];
let dustAt = 0;
let dropTimer: ReturnType<typeof setTimeout> | null = null;
let onScreen = true; // her sentence's block, against the screen (nothing moves off it)
let blockIO: IntersectionObserver | null = null;
const rnd = ([a, b]: [number, number]) => a + Math.random() * (b - a);

function mark(cls: string, host: HTMLElement) {
	const i = document.createElement('i');
	i.className = `pv-mark ${cls}`;
	i.setAttribute('aria-hidden', 'true');
	host.appendChild(i);
	return i;
}

/** where the road is at progress p (0 → 1), in the host's own px */
function roadAt(p: number) {
	if (!road) return null;
	let left = Math.max(0, Math.min(1, p)) * road.total;
	for (const l of road.lines) {
		const w = l.x1 - l.x0;
		if (left <= w || l === road.lines[road.lines.length - 1])
			return { x: l.x0 + Math.min(left, w), y: l.y };
		left -= w;
	}
	return null;
}

/** lay the road under a sentence (or a line) for `ms` of her voice, and set the leading sparkle on it */
function layRoad(range: Range, host: HTMLElement, ms: number) {
	leadAnim?.cancel();
	leadAnim = null;
	stopDrops();
	if (roadHost && roadHost !== host) dropTrail();
	roadHost = host;
	roadMs = Math.max(120, ms);
	const box = host.getBoundingClientRect();
	const lines = lineBoxes(range).map((l) => ({
		x0: l.left - box.left,
		x1: l.right - box.left,
		y: l.bottom - box.top - (l.bottom - l.top) * 0.08 // just under the words
	}));
	road = lines.length ? { lines, total: lines.reduce((n, l) => n + (l.x1 - l.x0), 0) || 1 } : null;
	if (!road) return lead?.classList.remove('pv-on');
	if (!lead || lead.parentElement !== host) {
		lead?.remove();
		lead = mark('pv-lead', host);
	}
	if (reduced()) {
		// reduced motion: a still dot under the start of her sentence, nothing travels
		const at = roadAt(0)!;
		lead.style.transform = `translate(${at.x}px, ${at.y}px)`;
		lead.classList.add('pv-on', 'pv-still');
		return;
	}
	lead.classList.remove('pv-still');
	lead.style.transform = '';
	const frames: Keyframe[] = [];
	let acc = 0;
	for (const l of road.lines) {
		frames.push({ offset: acc / road.total, transform: `translate(${l.x0}px, ${l.y}px)` });
		acc += l.x1 - l.x0;
		frames.push({ offset: Math.min(1, acc / road.total), transform: `translate(${l.x1}px, ${l.y}px)` });
	}
	leadAnim = lead.animate(frames, { duration: roadMs, easing: 'linear', fill: 'forwards' });
	leadAnim.pause();
	lead.classList.add('pv-on');
}

/** may the trail move right now: she's speaking, her sentence is on screen, the tab is visible */
const moving = () =>
	!!leadAnim && leadAnim.playState === 'running' && onScreen && document.visibilityState === 'visible';

/** one soft sparkle where the lead is now, left behind to fade */
function drop() {
	if (!roadHost || !leadAnim || batteryLow()) return;
	const at = roadAt(Number(leadAnim.currentTime ?? 0) / roadMs);
	if (!at) return;
	let s = dust[dustAt];
	if (!s || s.parentElement !== roadHost) {
		s?.remove();
		s = dust[dustAt] = mark('pv-dust', roadHost);
	}
	dustAt = (dustAt + 1) % POOL;
	for (const a of s.getAnimations()) a.cancel();
	const star = Math.random() < 0.35; // now and then a tiny four-ray sparkle among the soft ones
	const size = star ? 7 + Math.random() * 4 : 4 + Math.random() * 5;
	s.classList.toggle('pv-star', star);
	s.style.setProperty('--s', `${size.toFixed(1)}px`);
	const x = at.x + (Math.random() - 0.5) * 5;
	const y = at.y + (Math.random() - 0.5) * 4;
	const dx = (Math.random() - 0.5) * 6;
	const dy = 2 + Math.random() * 4;
	s.animate(
		[
			{ transform: `translate(${x}px, ${y}px) scale(0.5)`, opacity: 0 },
			{ transform: `translate(${x}px, ${y}px) scale(1)`, opacity: 0.95, offset: 0.16 },
			{ transform: `translate(${x + dx}px, ${y + dy}px) scale(0.25)`, opacity: 0 }
		],
		{ duration: rnd(FADE_MS), easing: 'ease-out', fill: 'forwards' }
	);
}

function stopDrops() {
	if (dropTimer) clearTimeout(dropTimer);
	dropTimer = null;
}

function startDrops() {
	stopDrops();
	if (batteryLow() || reduced()) return; // a low battery keeps just the lead; reduced motion, the dot
	const tick = () => {
		dropTimer = null;
		if (!moving()) return;
		drop();
		dropTimer = setTimeout(tick, rnd(DROP_MS));
	};
	tick();
}

/** keep the lead on her clock: where she is in it, at her speed, paused with her and off-screen */
function keepTime(at: number, rate: number, paused: boolean) {
	if (!leadAnim) return;
	try {
		leadAnim.playbackRate = rate || 1;
		leadAnim.currentTime = Math.max(0, at * 1000);
		if (paused || !onScreen || document.visibilityState !== 'visible') {
			leadAnim.pause();
			stopDrops();
		} else {
			leadAnim.play();
			for (const s of dust) for (const a of s.getAnimations()) if (a.playState === 'paused') a.play();
			startDrops();
		}
	} catch {}
}

/** she paused (or her sentence left the screen, or the tab hid): the whole trail holds still */
function freeze() {
	if (nextTimer) clearTimeout(nextTimer);
	nextTimer = null;
	stopDrops();
	try {
		leadAnim?.pause();
		for (const s of dust) for (const a of s.getAnimations()) a.pause();
	} catch {}
}

/** between two sentences: the lead fades; what it left behind finishes fading */
function restTrail() {
	stopDrops();
	leadAnim?.pause();
	lead?.classList.remove('pv-on');
}

/** the end: the trail is gone */
function dropTrail() {
	stopDrops();
	leadAnim?.cancel();
	leadAnim = null;
	lead?.remove();
	lead = null;
	for (const s of dust) s.remove();
	dust.length = 0;
	dustAt = 0;
	road = null;
	roadHost = null;
}

/** watch her sentence's block: off the screen, nothing of the trail moves */
function watchBlock(el: Element | null) {
	blockIO?.disconnect();
	blockIO = null;
	onScreen = true;
	if (!el || typeof IntersectionObserver === 'undefined') return;
	blockIO = new IntersectionObserver(([e]) => {
		if (!e) return;
		const was = onScreen;
		onScreen = e.isIntersecting;
		if (was && !onScreen) freeze();
		else if (!was && onScreen) (lineState !== 'idle' ? lineSync : sync)();
	});
	blockIO.observe(el);
}

function clearFollower() {
	if (nextTimer) clearTimeout(nextTimer);
	nextTimer = null;
	dropTrail();
	hostRO?.disconnect();
	hostRO = null;
	blockIO?.disconnect();
	blockIO = null;
	onScreen = true;
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
	if (!found || !host) return restTrail();
	cursor = found.end;
	layRoad(found.range, host, seg.duration * 1000);
	watchBlock(shown.block);
	for (const q of host.querySelectorAll<HTMLElement>('.petal-quote'))
		if (found.range.intersectsNode(q)) voiceReveal(q); // her voice reached it: the reveal plays again
	if (!hostRO && typeof ResizeObserver !== 'undefined') {
		hostRO = new ResizeObserver(() => {
			// the page moved under her (a resize, an image arriving): the road is laid again
			if (shown?.range && shown.host) {
				layRoad(shown.range, shown.host, shown.seg.duration * 1000);
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
		if (shown) restTrail();
		shown = null;
	} else {
		if (cur !== shown?.seg) show(cur);
		if (shown?.seg === cur) keepTime(t - cur.start, rate, a.paused);
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
			layRoad(lineRange, lineHost, seg.duration * 1000);
			watchBlock(lineQuote);
			lineFollowed = true;
		}
		keepTime(t - seg.start, a.playbackRate, a.paused);
	} else if (lineFollowed) restTrail();
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

// Lily's pink, in gradients only: candy on the night skins, a deeper candy on light ones
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
html:not(.dark) .pv-lead { --pv-core: 212 64 143; }
html:not(.dark) .pv-dust { --pv-core: 222 84 160; }
@media (prefers-reduced-motion: reduce) { .pv-dust { display: none; } .pv-lead { transition: none; } }
`;

function wire() {
	if (wired || typeof window === 'undefined') return;
	wired = true;
	const style = document.createElement('style');
	style.id = 'petal-voice-style';
	style.textContent = STYLE;
	document.head.appendChild(style);

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
		if (lineState !== 'idle') lineSync();
		else sync();
	});
}
