// 🌸📻🧵 her voice, one thread (A46 · grown from A19's petal stream, B7's events, A37–A45's autoplay and follow)
// exactly one owner of what's playing now: this module. one <audio> for everything her voice says in the page (her
// petal stream, a quote said alone, sentence clips when the stream can't open) and the browser's own voice for the
// engines that have no server; one store, voiceThread (message_id · the stream's ticket · part · state idle | loading
// | playing | paused | ended | error); every way in (the speaker button, the play button, the bubble and the hotkey,
// autoplay as she writes and after she finishes, a pick read aloud, her stream's own words, a replay, a quote) asks
// speakVoice(), and nothing else creates an Audio element or advances an index.
//  · the newest ask wins at once: the store says loading for it before any network, and an older ask still opening
//    never touches the element nor stops the newer one (its answer is let go when it lands)
//  · the part: the sentence whose audio is sounding now, on the audio's own clock (currentTime, read on timeupdate,
//    playing, seeked and ratechange, and only in the last 300 ms before an edge on animation frames: never a timer),
//    forward only (a sentence told again, re-fed or rebuffered never moves it back). its idx is its place in its own
//    reply (A45), the same index the page cuts, so the trail and the rig agree
//  · never a silent stop: a stream that breaks after her first sound picks up once where it broke (the rig reads on
//    from the sentence she was on); a part the rig gave up arrives as a `skip` and is said in the trail; a clip that
//    fails is asked once more, then skipped and said; a second break ends her with a note (state error)
//  · her controls read mirrors written in the same breath (voiceUI for the ✕, the play button and the bubble;
//    voiceNow for autoplay's view of the stream), so nothing on the page can disagree with what's sounding
//  · the stream (petal_stream.py): POST …/petal-stream → a one-time ticket; the <audio> plays …/petal-stream/{id};
//    its events door (EventSource …/{id}/events) tells each `sentence {message_id, idx, text, start, duration, cue?}`,
//    each `skip {message_id, idx, text, at, why}`, then `end` or `stop` (contract 11.6). pause · resume · end · stop
//    are made here from the <audio> itself, in the same shape
//  · the phone treats her like music (Media Session: the lock-screen card, earbud play/pause, ⏭ flags her)

import { get, writable } from 'svelte/store';
import { AUDIO_API_BASE_URL } from '$lib/constants';

export type PetalPart = { text: string; para_end: boolean };
// 🧵 A45 · a reply the rig follows for her voice (it reads the reply as it's written, so a sleeping page starves
// nothing): its id and chat, the cue said before it (🍒 A38), whether it waits to be written whole, the page's copy
// when it has no other home (a temporary chat's stream message) · 🧵 A46 · given: sentences of it already heard (a
// stream picking up where a broken one left off starts there)
export type FollowSegment = {
	message_id: string;
	chat_id?: string | null;
	lead?: string;
	whole?: boolean;
	text?: string;
	finished?: boolean;
	given?: number;
};
// 🚩 who she was speaking for: kept beside the stream on the rig (memory only) until flagged
export type PetalMeta = { chat_id?: string; message_id?: string; model?: string; source?: string };

// ── the one store ──────────────────────────────────────────────────────────────────────────────────────────
export type VoiceState = 'idle' | 'loading' | 'playing' | 'paused' | 'ended' | 'error';
export type VoiceKind = 'stream' | 'line' | 'clips' | 'browser';
export type VoiceWhy = 'natural' | 'stopped' | 'broken';
export type VoiceThread = {
	state: VoiceState;
	message_id: string | null; // the reply whose words are sounding (a pick's second side once the player reaches it)
	chat_id: string | null;
	ticket: string | null; // the stream's ticket (a stream only)
	part: number | null; // the sounding sentence: its place in its own reply (-1: her cue before it)
	kind: VoiceKind | null;
	seq: number; // which ask this is (every way in takes the next number)
	why: VoiceWhy | null; // why she ended (ended · error)
	note: string | null; // what she should know: a line the voice gave up, a break that couldn't heal
	skipped: number; // lines given up in this ask (each said in the trail)
	resumed: number; // breaks healed in this ask (at most one)
};
const IDLE: VoiceThread = {
	state: 'idle',
	message_id: null,
	chat_id: null,
	ticket: null,
	part: null,
	kind: null,
	seq: 0,
	why: null,
	note: null,
	skipped: 0,
	resumed: 0
};
export const voiceThread = writable<VoiceThread>({ ...IDLE });

// the controls' mirror (the ✕, the play button, the bubble, the heart, the ear chip): loading · playing · paused, else idle
export type VoiceUI = { state: 'idle' | 'loading' | 'playing' | 'paused'; message_id: string | null; kind: VoiceKind | null };
export const voiceUI = writable<VoiceUI>({ state: 'idle', message_id: null, kind: null });

// autoplay's mirror of the stream: what plays, and why the last one ended (natural: she reached the end) · 🧵 A46 ·
// replaced: the stream another ask took her voice from (no idle in between: nothing may think she went quiet)
export type VoiceEnd = 'natural' | 'stopped' | 'broken';
export type VoiceNow = {
	state: 'idle' | 'loading' | 'playing' | 'paused';
	message_id: string | null;
	chat_id?: string | null; // 🔈 A40 · the chat of the reply she speaks (ids only)
	id: string | null; // the stream's ticket
	ended: VoiceEnd | null; // why the last one ended
	replaced?: { message_id: string | null; chat_id: string | null; id: string | null; ended: 'stopped' };
};
export const voiceNow = writable<VoiceNow>({ state: 'idle', message_id: null, id: null, ended: null });

// ── what the rig says she says (contract 11.6) ───────────────────────────────────────────────────────────
export type VoiceSentence = {
	message_id: string | null;
	idx: number;
	text: string;
	start: number;
	duration: number;
	cue?: boolean;
};
export type VoiceEvent =
	| ({ type: 'sentence' } & VoiceSentence)
	| { type: 'pause' | 'resume' | 'end' | 'stop'; message_id: string | null; at: number | null };
type VoiceListener = (e: VoiceEvent, stream: string) => void;
const voiceListeners = new Set<VoiceListener>();
export const onPetalVoice = (fn: VoiceListener) => {
	voiceListeners.add(fn);
	return () => {
		voiceListeners.delete(fn);
	};
};
const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
/** one event from the rig, checked (a malformed one is dropped, never guessed at) */
export function voiceEvent(raw: unknown, type?: string): VoiceEvent | null {
	if (!raw || typeof raw !== 'object') return null;
	const o = raw as Record<string, unknown>;
	const t = (typeof o.type === 'string' && o.type) || type || 'sentence';
	const message_id = typeof o.message_id === 'string' ? o.message_id : null;
	if (t === 'pause' || t === 'resume' || t === 'end' || t === 'stop')
		return { type: t, message_id, at: num(o.at) };
	if (t !== 'sentence') return null;
	const start = num(o.start) ?? num(o.start_s);
	const end = num(o.end_s);
	const duration = num(o.duration) ?? num(o.duration_s) ?? (end !== null && start !== null ? end - start : null);
	const idx = num(o.idx);
	if (typeof o.text !== 'string' || start === null || duration === null || idx === null) return null;
	return {
		type: 'sentence',
		message_id,
		idx,
		text: o.text,
		start,
		duration: Math.max(0, duration),
		...(o.cue === true ? { cue: true } : {})
	};
}

// ── the sounding sentence, for the trail ────────────────────────────────────────────────────────────────────
/** a sentence she says in this ask: its reply, its place in it, its words, where it sits on the player's clock */
export type VoiceRow = {
	mid: string | null;
	idx: number;
	text: string;
	start: number;
	duration: number;
	cue: boolean;
	order: number; // when it first arrived: the stream's own order (forward only follows it)
	stale?: boolean; // its clock belongs to a stream that broke (a healed ask tells it again)
};
/** a line the voice gave up (said in the trail once the player reaches it) */
export type VoiceSkip = { mid: string | null; idx: number; text: string; at: number; why: string; told?: boolean };
export type Sounding = {
	seq: number;
	kind: VoiceKind;
	message_id: string | null;
	row: VoiceRow | null; // the sentence sounding now (null between two)
	at: number; // seconds into it
	rate: number;
	paused: boolean;
	waiting: boolean; // the player waits for more of the stream (the lead holds)
	skip?: VoiceSkip; // a line she just reached that the voice gave up
	ended?: VoiceWhy; // she ended (nothing of the trail stays)
};
type SoundingListener = (s: Sounding) => void;
const soundingListeners = new Set<SoundingListener>();
/** the trail's door: told on every look at her clock (a sentence begins, she moves inside it, pauses, ends) */
export const onSounding = (fn: SoundingListener) => {
	soundingListeners.add(fn);
	return () => {
		soundingListeners.delete(fn);
	};
};

// ── an ask ───────────────────────────────────────────────────────────────────────────────────────────────
/** where a clip comes from (the speaker path when none is given): one per part, asked in order */
export type Clip = { url: string; seg: { start: number; duration: number } | null; skip?: string | null; silent?: boolean };
export type ClipSource = {
	count: number;
	idx?: (i: number) => number; // its place in its reply (default: first + i)
	text: (i: number) => string;
	make?: (i: number, signal: AbortSignal) => Promise<Clip | null>;
};
export type VoiceAsk = {
	kind: VoiceKind;
	message_id: string | null;
	chat_id?: string | null;
	token?: string;
	voice?: string;
	revoice?: () => string | undefined; // the voice she chose, asked again when her settings move (A46 · the picker)
	title?: string;
	artwork?: string;
	playbackRate?: number;
	// a stream
	parts?: PetalPart[];
	first?: number; // where in the reply these parts begin (a whole reply: 0)
	follow?: FollowSegment[];
	growing?: boolean;
	meta?: PetalMeta;
	fallback?: boolean; // a whole reply falls back to its sentence clips when the stream can't open
	onFeed?: (feed: string) => void;
	onPlaying?: () => void;
	onEnded?: () => void; // she finished, or someone stopped her
	onError?: () => void; // the stream broke before her first sound (and had no fallback)
	onSuperseded?: () => void; // a newer ask took her voice while this one was still opening
	// clips · a quote's line (the speaker path, with "petal": {message_id, idx} when the line has a place)
	clips?: ClipSource;
	petal?: { message_id: string; idx: number } | null;
	// the browser's own voice
	text?: string;
	voiceURI?: string;
};
type Ask = VoiceAsk & {
	seq: number;
	token: string;
	voice: string;
	rate: number;
	title: string;
	began: VoiceKind; // what she asked for (a stream may fall back to clips)
	abort: AbortController;
	ticket: string | null;
	trace: string | null;
	feed: string | null;
	attached: boolean; // the <audio> holds this ask
	src: string | null;
	started: boolean; // her first sound
	pausedOnce: boolean;
	playingTold: boolean;
	rows: Map<string, VoiceRow>;
	skips: VoiceSkip[];
	order: number;
	sounding: VoiceRow | null;
	hearing: string | null; // the reply she hears (🍒 a pick's stream changes it midway)
	marks: { start: number; message_id: string }[]; // 🧵 A45 · where each followed reply begins on the player's clock
	keep?: string; // 🧵 A45 · her 💗 on this reply: the player ends where the next one begins
	endSeen: boolean; // the rig said `end`: all of her is in the stream
	stopSeen: string | null; // the rig said `stop` (why)
	door: EventSource | null;
	doorTries: number;
	lastSeq: number;
	resumed: number;
	skipped: number;
	frame: number;
	clip: { i: number; next: Map<number, Promise<Clip | null>>; urls: string[] } | null;
	replacedStream: VoiceNow['replaced'] | null;
	utterance?: SpeechSynthesisUtterance | null;
};

let el: HTMLAudioElement | null = null; // the one <audio>
let active: Ask | null = null; // what is playing now (or opening)
let asked = 0; // the last ask's number
// 🚩 the voice black box: the rig keeps her last few streams; these let you flag one
let last: { trace?: string | null; token: string; message_id?: string | null; at: number | null } | null = null;
export const spokenMessages = writable<Set<string>>(new Set()); // messages that have a stream to flag

const visible = () => typeof document === 'undefined' || document.visibilityState !== 'hidden';
const raf = (f: () => void): number =>
	typeof requestAnimationFrame === 'function' ? requestAnimationFrame(f) : 0;

// ── the mirrors, written with the store ─────────────────────────────────────────────────────────────────────
function emit(patch: Partial<VoiceThread>) {
	const was = get(voiceThread);
	const t = { ...was, ...patch };
	let moved = false;
	for (const k of Object.keys(t) as (keyof VoiceThread)[]) if (t[k] !== was[k]) moved = true;
	if (moved) voiceThread.set(t);
	const live = t.state === 'loading' || t.state === 'playing' || t.state === 'paused';
	const ui: VoiceUI = live
		? { state: t.state as VoiceUI['state'], message_id: t.message_id, kind: t.kind }
		: { state: 'idle', message_id: null, kind: null };
	const u = get(voiceUI);
	if (u.state !== ui.state || u.message_id !== ui.message_id || u.kind !== ui.kind) voiceUI.set(ui);
}
/** autoplay's view of a stream (written after the store and the controls' mirror) */
function sayStream(a: Ask, state: VoiceNow['state']) {
	const v: VoiceNow = {
		state,
		message_id: a.hearing ?? a.message_id,
		chat_id: a.chat_id ?? null,
		id: a.ticket,
		ended: null
	};
	if (a.replacedStream && state === 'loading') {
		v.replaced = a.replacedStream;
		a.replacedStream = null; // said once
	}
	const w = get(voiceNow);
	if (
		w.state !== v.state ||
		w.message_id !== v.message_id ||
		w.chat_id !== v.chat_id ||
		w.id !== v.id ||
		w.ended !== null ||
		!!v.replaced !== !!w.replaced
	)
		voiceNow.set(v);
}
function streamEnded(a: Ask, why: VoiceEnd) {
	voiceNow.set({ state: 'idle', message_id: a.hearing ?? a.message_id, chat_id: a.chat_id ?? null, id: a.ticket, ended: why });
}

/** made by the page from the <audio> itself (contract 11.6): pause · resume · end · stop */
function pageEvent(a: Ask, type: 'pause' | 'resume' | 'end' | 'stop') {
	if (a.began !== 'stream') return;
	const e: VoiceEvent = {
		type,
		message_id: a.hearing ?? a.message_id ?? null,
		at: el && a.attached ? Math.round(el.currentTime * 1000) / 1000 : null
	};
	tell(a, e);
}
function tell(a: Ask, e: VoiceEvent) {
	const stream = a.ticket ?? `ask-${a.seq}`;
	for (const fn of voiceListeners) {
		try {
			fn(e, stream);
		} catch (err) {
			console.warn('🎙️ voice follower:', err);
		}
	}
}
function sound(a: Ask, extra: Partial<Sounding> = {}) {
	const t = el && a.attached ? el.currentTime : 0;
	const row = a.sounding;
	const s: Sounding = {
		seq: a.seq,
		kind: a.kind,
		message_id: a.hearing ?? a.message_id,
		row: row && !extra.ended && t >= row.start && t < row.start + row.duration && !row.stale ? row : null,
		at: row ? Math.max(0, t - row.start) : 0,
		rate: (el && el.playbackRate) || 1,
		paused: !!el?.paused || get(voiceThread).state === 'paused',
		waiting: false,
		...extra
	};
	for (const fn of soundingListeners) {
		try {
			fn(s);
		} catch (err) {
			console.warn('🎙️ voice trail:', err);
		}
	}
}

// ── the element ───────────────────────────────────────────────────────────────────────────────────────────
/** the ask the <audio> plays for now (its events are ours only while it holds this ask's source) */
const mine = (): Ask | null => {
	const a = active;
	return a && a.attached && el && el.src === a.src ? a : null;
};
const element = (): HTMLAudioElement => {
	if (el) return el;
	const e = new Audio();
	el = e;
	e.preload = 'auto';
	e.setAttribute('playsinline', '');
	(e as any).disableRemotePlayback = true;
	e.addEventListener('play', () => {
		const a = mine();
		if (a && a.pausedOnce) pageEvent(a, 'resume');
		if (a) a.pausedOnce = false;
	});
	e.addEventListener('playing', () => {
		const a = mine();
		if (!a) return;
		a.started = true;
		setSession('playing');
		emit({ state: 'playing', message_id: a.hearing ?? a.message_id });
		if (a.began === 'stream' && a.kind === 'stream') sayStream(a, 'playing');
		if (!a.playingTold) {
			a.playingTold = true;
			try {
				a.onPlaying?.();
			} catch {}
		}
		look(a);
	});
	e.addEventListener('pause', () => {
		const a = mine();
		if (!a || e.ended) return;
		a.pausedOnce = true;
		setSession('paused');
		emit({ state: 'paused' });
		if (a.began === 'stream' && a.kind === 'stream') sayStream(a, 'paused');
		pageEvent(a, 'pause');
		sound(a);
	});
	e.addEventListener('ended', () => {
		const a = mine();
		if (a) ended(a);
	});
	e.addEventListener('error', () => {
		const a = mine();
		if (a) broke(a, 'the player could not go on');
	});
	e.addEventListener('waiting', () => {
		const a = mine();
		if (a) sound(a, { waiting: true });
	});
	for (const t of ['timeupdate', 'seeked', 'ratechange'])
		e.addEventListener(t, () => {
			const a = mine();
			if (a) look(a);
		});
	return e;
};

/** the <audio> she plays through (read only: its currentTime is the voice's clock) */
export const petalStreamAudio = () => el;

const setSession = (s: MediaSessionPlaybackState) => {
	try {
		if ('mediaSession' in navigator) navigator.mediaSession.playbackState = s;
	} catch {}
};

function attach(a: Ask, url: string) {
	const e = element();
	a.attached = true;
	e.src = url;
	a.src = e.src; // read back: the absolute form the element reports from now on
	e.playbackRate = a.rate;
	mediaSession(a);
}

/** the <audio> lets go of this ask: marked first, so the pause it makes is never read as hers */
function detach(a: Ask) {
	const held = a.attached;
	a.attached = false;
	a.src = null;
	if (held && el) {
		el.pause();
		el.removeAttribute('src');
		el.load();
	}
}

/** everything this ask holds lets go (the element, its door, its clips, the browser's voice) */
function teardown(a: Ask) {
	try {
		a.abort.abort();
	} catch {}
	closeDoor(a);
	if (a.frame && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(a.frame);
	a.frame = 0;
	detach(a);
	for (const u of a.clip?.urls ?? []) {
		try {
			URL.revokeObjectURL(u);
		} catch {}
	}
	if (a.clip) a.clip.urls = [];
	if (a.kind === 'browser') {
		try {
			if (typeof speechSynthesis !== 'undefined') speechSynthesis.cancel();
		} catch {}
	}
	setSession('none');
}

function end(a: Ask, why: VoiceWhy, note: string | null = null) {
	if (active !== a) return;
	if (a.began === 'stream')
		last = {
			trace: a.trace,
			token: a.token,
			message_id: a.hearing ?? a.message_id,
			at: el && a.attached && !el.ended ? el.currentTime : null
		};
	teardown(a);
	active = null;
	emit({ state: why === 'broken' ? 'error' : 'ended', why, note: note ?? get(voiceThread).note, part: null });
	if (a.kind === 'stream') streamEnded(a, why);
	sound(a, { ended: why, row: null });
	try {
		if (why === 'broken' && !a.started) a.onError?.();
		else a.onEnded?.();
	} catch {}
}

// ── the one door in ─────────────────────────────────────────────────────────────────────────────────────────
const tokenNow = () => {
	try {
		return localStorage.token ?? '';
	} catch {
		return '';
	}
};

/** her voice, from this ask on: whatever was playing stops first (the newest ask always wins) · → true once it's
 *  handed to the player (a stream opened, the first clip asked, the browser's voice started); false when it never
 *  plays (it couldn't open and had no fallback, or a newer ask took her voice meanwhile) */
export function speakVoice(o: VoiceAsk): Promise<boolean> {
	const prev = active;
	const a: Ask = {
		...o,
		seq: ++asked,
		token: o.token || tokenNow(),
		voice: o.voice ?? '',
		rate: o.playbackRate ?? 1,
		title: o.title || 'Petal 💗',
		began: o.kind,
		abort: new AbortController(),
		ticket: null,
		trace: null,
		feed: null,
		attached: false,
		src: null,
		started: false,
		pausedOnce: false,
		playingTold: false,
		rows: new Map(),
		skips: [],
		order: 0,
		sounding: null,
		hearing: null,
		marks: [],
		endSeen: false,
		stopSeen: null,
		door: null,
		doorTries: 0,
		lastSeq: 0,
		resumed: 0,
		skipped: 0,
		frame: 0,
		clip: null,
		replacedStream: null
	};
	if (prev) {
		if (prev.attached) pageEvent(prev, 'stop');
		if (prev.began === 'stream')
			last = { trace: prev.trace, token: prev.token, message_id: prev.hearing ?? prev.message_id, at: el && prev.attached ? el.currentTime : null };
		teardown(prev);
		if (prev.kind === 'stream' && a.kind === 'stream')
			a.replacedStream = { message_id: prev.hearing ?? prev.message_id, chat_id: prev.chat_id ?? null, id: prev.ticket, ended: 'stopped' };
	}
	active = a;
	emit({
		state: 'loading',
		message_id: a.message_id,
		chat_id: a.chat_id ?? null,
		ticket: null,
		part: null,
		kind: a.kind,
		seq: a.seq,
		why: null,
		note: null,
		skipped: 0,
		resumed: 0
	});
	if (a.kind === 'stream') sayStream(a, 'loading');
	else if (prev?.kind === 'stream') streamEnded(prev, 'stopped');
	if (prev) {
		sound(prev, { ended: 'stopped', row: null });
		try {
			if (prev.attached || prev.started || prev.playingTold) prev.onEnded?.();
			else prev.onSuperseded?.();
		} catch {}
	}
	if (a.kind === 'stream') return openStream(a);
	if (a.kind === 'browser') return Promise.resolve(startBrowser(a));
	return startClips(a, 0);
}

/** her voice stops, whatever it was saying (her ⏹, the lock screen's stop, a new send, another tab speaking) */
export function stopVoice() {
	const a = active;
	if (!a) return;
	if (a.attached) pageEvent(a, 'stop');
	end(a, 'stopped');
}
export const pauseVoice = () => {
	const a = active;
	if (!a) return;
	if (a.kind === 'browser') {
		try {
			speechSynthesis.pause();
		} catch {}
		emit({ state: 'paused' });
		return;
	}
	if (a.attached && el && !el.paused) el.pause();
};
export const resumeVoice = () => {
	const a = active;
	if (!a) return;
	if (a.kind === 'browser') {
		try {
			speechSynthesis.resume();
		} catch {}
		emit({ state: 'playing' });
		return;
	}
	if (a.attached && el?.paused)
		el.play().catch(() => {
			if (active === a) broke(a, 'she could not be resumed');
		});
};
/** one tap: pause her while she speaks, resume her while she's paused */
export const toggleVoice = () => {
	const s = get(voiceThread).state;
	if (s === 'paused') resumeVoice();
	else if (s === 'playing' || s === 'loading') pauseVoice();
};
export const pausePetalStream = pauseVoice;
export const resumePetalStream = resumeVoice;

/** she's speaking (on her way, or sounding) · paused counts as quiet */
export const voiceSpeaking = () => {
	const s = get(voiceThread).state;
	return s === 'loading' || s === 'playing';
};

/** 🧵 A46 · the picker: the voice she chose moved (her settings) · the stream speaks in it from its next sentence (the
 *  one she's hearing finishes as it began), clips from their next clip */
export function revoice() {
	const a = active;
	if (!a?.revoice) return;
	let v: string | undefined;
	try {
		v = a.revoice();
	} catch {
		return;
	}
	if (typeof v !== 'string' || v === a.voice) return;
	a.voice = v;
	if (a.kind === 'stream' && a.ticket)
		fetch(`${AUDIO_API_BASE_URL}/petal-stream/${encodeURIComponent(a.ticket)}/voice`, {
			method: 'POST',
			headers: { Authorization: `Bearer ${a.token}`, 'Content-Type': 'application/json' },
			body: JSON.stringify({ voice: v })
		}).catch(() => null);
}

// ── a stream ───────────────────────────────────────────────────────────────────────────────────────────────
async function openStream(a: Ask): Promise<boolean> {
	const body = {
		voice: a.voice,
		parts: a.parts ?? [],
		meta: a.meta,
		...(a.growing || a.follow ? { growing: true } : {}),
		...(a.follow?.length ? { follow: a.follow } : {}),
		...(a.first ? { first: a.first } : {})
	};
	let res: Response | null = null;
	try {
		res = await fetch(`${AUDIO_API_BASE_URL}/petal-stream`, {
			method: 'POST',
			headers: { Authorization: `Bearer ${a.token}`, 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
			signal: a.abort.signal
		});
	} catch {
		res = null;
	}
	if (active !== a) return false; // a newer ask took her voice meanwhile: this one never plays
	const opened = res && res.ok ? await res.json().catch(() => null) : null;
	if (active !== a) return false;
	if (!opened?.id) return cantOpen(a);
	a.ticket = opened.id;
	a.trace = opened.trace ?? null;
	a.feed = opened.feed ?? null;
	a.endSeen = false;
	a.stopSeen = null;
	if (a.message_id && a.trace) {
		const mid = a.message_id;
		spokenMessages.update((s) => (s.has(mid) ? s : new Set(s).add(mid)));
	}
	if ((a.growing || a.follow) && a.feed) a.onFeed?.(a.feed); // after a heal too: her 💗 reaches the stream that plays now
	emit({ ticket: a.ticket });
	sayStream(a, a.started ? 'playing' : 'loading');
	attach(a, `${AUDIO_API_BASE_URL}/petal-stream/${encodeURIComponent(a.ticket!)}`);
	openDoor(a); // 🎙️ right after the src (contract 11.6)
	try {
		await el!.play();
	} catch {
		if (active === a && !a.started) broke(a, 'the stream could not start');
	}
	return true;
}

/** the stream couldn't open (the rig out of reach, lameenc missing): a whole reply speaks as sentence clips */
function cantOpen(a: Ask): boolean | Promise<boolean> {
	if (a.fallback && a.parts?.length && !a.resumed) return toClips(a, 0);
	end(a, 'broken', a.resumed ? 'her voice broke off and could not come back' : null);
	return false;
}

/** a whole reply's stream falls back to its sentence clips (the same ask: nothing else may start meanwhile) */
function toClips(a: Ask, from: number): Promise<boolean> {
	const parts = a.parts ?? [];
	const first = a.first ?? 0;
	a.kind = 'clips';
	a.clips = { count: parts.length, idx: (i) => first + i, text: (i) => parts[i]?.text ?? '' };
	emit({ kind: 'clips', ticket: null });
	streamEnded(a, 'broken');
	return startClips(a, from);
}

/** the player can't go on: before her first sound, the fallback (or her error); after it, the stream heals once */
function broke(a: Ask, why: string) {
	if (active !== a) return;
	if (a.kind === 'clips' || a.kind === 'line') return clipBroke(a);
	if (a.kind !== 'stream') return end(a, 'broken', why);
	if (!a.started) {
		if (a.fallback && a.parts?.length && !a.resumed) {
			teardownStream(a);
			void toClips(a, 0);
			return;
		}
		return end(a, 'broken');
	}
	heal(a, why);
}

/** the element and the door let go, the ask stays hers (a heal or a fallback follows at once) */
function teardownStream(a: Ask) {
	closeDoor(a);
	if (a.frame && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(a.frame);
	a.frame = 0;
	detach(a);
}

/** the element reached its end: the rig said `end` → she finished · otherwise the stream was cut short → it heals */
function ended(a: Ask) {
	if (a.kind === 'clips' || a.kind === 'line') return clipEnded(a);
	if (a.kind !== 'stream') return;
	if (a.endSeen || !a.started || (!a.rows.size && !a.lastSeq)) {
		pageEvent(a, 'end');
		return end(a, 'natural');
	}
	heal(a, a.stopSeen ? `the stream was cut (${a.stopSeen})` : 'the stream ended early');
}

/** 🧵 A46 · a stream that broke after her first sound picks up once, where it broke: from the sentence she was on
 *  (said again from its start) or, if she had heard it through, the next · a second break ends her with a note */
function heal(a: Ask, why: string) {
	if (active !== a) return;
	const from = resumeFrom(a);
	if (from === 'done') {
		pageEvent(a, 'end');
		return end(a, 'natural');
	}
	if (a.resumed >= 1 || !from) {
		pageEvent(a, 'stop');
		return end(a, 'broken', `her voice broke off twice (${why}): it stopped here`);
	}
	a.resumed += 1;
	console.info(`🧵 her voice broke (${why}): picking up where it broke`);
	teardownStream(a);
	for (const r of a.rows.values()) r.stale = true; // their clock was the broken stream's
	a.skips = a.skips.filter((s) => s.told);
	a.marks = [];
	a.parts = from.parts ?? a.parts;
	a.first = from.first ?? a.first;
	a.follow = from.follow ?? a.follow;
	emit({ state: 'loading', resumed: a.resumed, ticket: null });
	sayStream(a, 'loading');
	void openStream(a);
}

/** where a broken stream picks up: the parts (a whole reply) or the replies (followed) from the sentence she was on */
function resumeFrom(a: Ask): 'done' | { parts?: PetalPart[]; first?: number; follow?: FollowSegment[] } | null {
	const t = el && a.attached ? el.currentTime : a.sounding ? a.sounding.start + a.sounding.duration : 0;
	// the last sentence she reached (sounding now, or begun before a quiet stretch), forward only
	let s = a.sounding;
	for (const r of a.rows.values()) if (!r.stale && r.start <= t && (!s || r.order > s.order)) s = r;
	const through = !!s && t >= s.start + s.duration - 0.25; // heard to its end
	if (a.follow?.length) {
		const segs = a.follow;
		const at = s ? Math.max(0, segs.findIndex((g) => g.message_id === s.mid)) : 0;
		const g = segs[at];
		if (!g) return null;
		let given = s && s.mid === g.message_id ? (s.cue ? 0 : s.idx + (through ? 1 : 0)) : 0;
		given = Math.max(given, g.given ?? 0);
		const lead = !s || (s.cue && !through) || (s.mid !== g.message_id && given === 0) ? g.lead : '';
		let rest = segs.slice(at + 1);
		if (a.keep) {
			const k = segs.findIndex((x) => x.message_id === a.keep);
			rest = k >= 0 && k > at ? segs.slice(at + 1, k + 1) : [];
		}
		return { follow: [{ ...g, lead: lead ?? '', given }, ...rest] };
	}
	const parts = a.parts ?? [];
	const first = a.first ?? 0;
	const next = s ? s.idx + (through ? 1 : 0) : first;
	if (next - first >= parts.length) return 'done';
	return { parts: parts.slice(Math.max(0, next - first)), first: next };
}

// ── the events door (contract 11.6) ─────────────────────────────────────────────────────────────────────────
function openDoor(a: Ask, after = 0) {
	closeDoor(a);
	if (!a.ticket || typeof EventSource === 'undefined') return;
	const ticket = a.ticket;
	let es: EventSource;
	try {
		es = new EventSource(
			`${AUDIO_API_BASE_URL}/petal-stream/${encodeURIComponent(ticket)}/events${after ? `?after=${after}` : ''}`
		);
	} catch {
		return;
	}
	a.door = es;
	const take = (ev: Event, type?: string) => {
		if (a.door !== es || active !== a) return;
		const data = (ev as MessageEvent).data;
		let raw: Record<string, unknown> | null = null;
		try {
			raw = data ? JSON.parse(data) : {};
		} catch {
			return;
		}
		const t = type ?? (raw?.type as string | undefined) ?? 'sentence';
		if (typeof raw?.seq === 'number') a.lastSeq = Math.max(a.lastSeq, raw.seq);
		if (t === 'end') {
			a.endSeen = true;
			return closeDoor(a); // the rig is done saying what she'll say: the player plays on from what it holds
		}
		if (t === 'stop') {
			a.stopSeen = typeof raw?.reason === 'string' ? raw.reason : 'cut';
			return closeDoor(a);
		}
		if (t === 'skip') return addSkip(a, raw);
		addRow(a, raw, t);
	};
	es.addEventListener('sentence', (ev) => take(ev, 'sentence'));
	es.addEventListener('skip', (ev) => take(ev, 'skip'));
	es.addEventListener('end', (ev) => take(ev, 'end'));
	es.addEventListener('stop', (ev) => take(ev, 'stop'));
	es.onmessage = (ev) => take(ev);
	es.onerror = () => {
		if (a.door !== es || es.readyState !== (EventSource as any).CLOSED) return; // it comes back by itself (Last-Event-ID)
		a.door = null;
		// 🧵 A46 · a door shut while she still speaks: asked again once, from the last event it gave
		if (active === a && a.ticket === ticket && !a.endSeen && !a.stopSeen && a.doorTries < 1) {
			a.doorTries += 1;
			setTimeout(() => {
				if (active === a && a.ticket === ticket && !a.door) openDoor(a, a.lastSeq);
			}, 1000);
		}
	};
}
function closeDoor(a: Ask) {
	try {
		a.door?.close();
	} catch {}
	a.door = null;
}

/** 🧵 A45 · a followed stream may carry several replies (🍒 a pick, read in one stream): each one's first sentence
 *  marks where it begins, and the reply she's hearing changes when the player reaches it, never earlier */
function noteReply(a: Ask, message_id: string, start: number) {
	if (!a.marks.some((x) => x.message_id === message_id)) {
		a.marks.push({ start, message_id });
		a.marks.sort((x, y) => x.start - y.start);
		if (a.trace) spokenMessages.update((s) => (s.has(message_id) ? s : new Set(s).add(message_id)));
	}
}
/** 🧵 A45 · where her 💗 ends the stream on the player's clock: the first reply to begin after the one she kept */
function cutAt(a: Ask): number | null {
	if (!a.keep) return null;
	const kept = a.marks.find((x) => x.message_id === a.keep);
	const next = a.marks.find((x) => x.message_id !== a.keep && (!kept || x.start > kept.start));
	return next ? next.start : null;
}

const rowKey = (mid: string | null, idx: number) => `${mid ?? ''}\u0000${idx}`;

function addRow(a: Ask, raw: unknown, type: string) {
	const e = voiceEvent(raw, type);
	if (!e || e.type !== 'sentence') return;
	if (e.message_id) noteReply(a, e.message_id, e.start);
	if (a.keep && e.message_id && e.message_id !== a.keep) return look(a); // past her 💗: never heard, never told
	const mid = e.message_id ?? a.message_id;
	const k = rowKey(mid, e.idx);
	const had = a.rows.get(k);
	if (had) {
		// told again (a take made again, a healed stream telling it on its own clock): the later start wins, its order stays
		if (!had.stale && e.start <= had.start) return;
		had.start = e.start;
		had.duration = e.duration;
		had.text = e.text;
		had.stale = false;
	} else
		a.rows.set(k, { mid, idx: e.idx, text: e.text, start: e.start, duration: e.duration, cue: !!e.cue, order: ++a.order });
	tell(a, e);
	look(a);
}

function addSkip(a: Ask, raw: Record<string, unknown> | null) {
	if (!raw) return;
	const idx = num(raw.idx);
	const at = num(raw.at);
	if (idx === null || at === null) return;
	const mid = typeof raw.message_id === 'string' ? raw.message_id : a.message_id;
	if (a.keep && mid && mid !== a.keep) return;
	a.skips.push({ mid, idx, text: typeof raw.text === 'string' ? raw.text : '', at, why: typeof raw.why === 'string' ? raw.why : 'broken' });
	look(a);
}

/** her clock, looked at: the reply she hears, the sentence sounding (forward only), the lines given up she reached, and
 *  (only near an edge) one more look on the next frame */
function look(a: Ask) {
	if (active !== a || !a.attached || !el) return;
	const t = el.currentTime;
	if (a.kind === 'stream') {
		const cut = cutAt(a);
		if (cut !== null && t >= cut - 0.05) {
			// her 💗 kept this reply, and the voice had gone ahead into the next: she ends here, as at a natural end
			pageEvent(a, 'end');
			return end(a, 'natural');
		}
		if (a.marks.length > 1) {
			let at = a.marks[0].message_id;
			for (const x of a.marks) if (x.start <= t + 0.05) at = x.message_id;
			a.hearing = at;
		}
	}
	let cur: VoiceRow | null = null;
	for (const r of a.rows.values())
		if (!r.stale && r.start <= t && t < r.start + r.duration && (!cur || r.order > cur.order)) cur = r;
	if (cur && a.sounding && cur.order < a.sounding.order) cur = null; // forward only: never back to an earlier sentence
	if (cur && cur !== a.sounding) a.sounding = cur;
	let reached: VoiceSkip | undefined;
	for (const s of a.skips)
		if (!s.told && t >= s.at - 0.02) {
			s.told = true;
			a.skipped += 1;
			reached = s;
		}
	const state = get(voiceThread).state;
	emit({
		message_id: a.hearing ?? a.message_id,
		part: a.sounding ? a.sounding.idx : null,
		skipped: a.skipped,
		...(reached
			? { note: `her voice skipped a line it could not say (${reached.why})` }
			: {})
	});
	if (a.began === 'stream' && a.kind === 'stream' && state !== 'loading' && state !== 'idle')
		sayStream(a, el.paused ? 'paused' : 'playing');
	sound(a, reached ? { skip: reached } : {});
	// the next edge: only in its last 300 ms is her clock read again on the next frame (no timer ever decides)
	if (el.paused || !visible() || a.frame) return;
	const rate = el.playbackRate || 1;
	let edge = cur ? cur.start + cur.duration : Infinity;
	for (const r of a.rows.values()) if (!r.stale && r.start > t && r.start < edge) edge = r.start;
	for (const s of a.skips) if (!s.told && s.at > t && s.at < edge) edge = s.at;
	if (edge < Infinity && (edge - t) / rate < 0.3)
		a.frame = raf(() => {
			a.frame = 0;
			look(a);
		});
}

/** the sentence sounding now in her voice (the trail's truth), with its ask · null when none */
export function soundingNow(): { seq: number; row: VoiceRow | null; message_id: string | null } | null {
	const a = active;
	if (!a) return null;
	return { seq: a.seq, row: a.sounding, message_id: a.hearing ?? a.message_id };
}
/** for her console and the tests: the rows the playing ask holds (ids, places, clocks) */
export function voiceRows(): VoiceRow[] {
	return active ? [...active.rows.values()].sort((x, y) => x.order - y.order) : [];
}

// ── clips: a quote's line, a reply's sentences when the stream can't open, the in-browser engine ─────────────────
async function speechClip(a: Ask, i: number, signal: AbortSignal): Promise<Clip | null> {
	const c = a.clips!;
	const text = c.text(i);
	const idx = c.idx ? c.idx(i) : (a.first ?? 0) + i;
	const petal = a.kind === 'line' ? (a.petal ?? null) : a.message_id ? { message_id: a.message_id, idx } : null;
	const res = await fetch(`${AUDIO_API_BASE_URL}/speech`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${a.token}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({ input: text, ...(a.voice ? { voice: a.voice } : {}), ...(petal ? { petal } : {}) }),
		signal
	}).catch(() => null);
	if (!res?.ok) return null;
	let seg: Clip['seg'] = null;
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
	const silent = !!res.headers.get('X-Petal-Silenced');
	const skip = res.headers.get('X-Petal-Welfare') === 'skipped' ? 'welfare spent every take' : null;
	if (silent) return { url: '', seg: null, silent: true };
	const blob = await res.blob().catch(() => null);
	if (!blob) return null;
	return { url: URL.createObjectURL(blob), seg, skip };
}

/** one clip, asked once more if it fails (a short wait between) · null: it failed twice */
function clipFor(a: Ask, i: number): Promise<Clip | null> {
	const c = a.clip!;
	const had = c.next.get(i);
	if (had) return had;
	const make = a.clips?.make ?? ((j: number, s: AbortSignal) => speechClip(a, j, s));
	const once = () => make(i, a.abort.signal).catch(() => null);
	const p = once().then(async (got) => {
		if (got || a.abort.signal.aborted) return got;
		await new Promise((r) => setTimeout(r, 700));
		return a.abort.signal.aborted ? null : once();
	});
	c.next.set(i, p);
	return p;
}

function startClips(a: Ask, from: number): Promise<boolean> {
	a.clip = { i: from - 1, next: new Map(), urls: [] };
	return playClip(a, from);
}

async function playClip(a: Ask, i: number): Promise<boolean> {
	if (active !== a || !a.clip || !a.clips) return false;
	const count = a.clips.count;
	if (i >= count) {
		end(a, 'natural');
		return true;
	}
	a.clip.i = i;
	const got = await clipFor(a, i);
	if (active !== a) return false;
	if (i + 1 < count) void clipFor(a, i + 1); // the next one gets ready while this one plays
	const idx = a.clips.idx ? a.clips.idx(i) : (a.first ?? 0) + i;
	if (!got || got.skip) {
		// 🧵 A46 · given up (twice failed, or welfare spent every take): said in the trail, and on she goes
		const why = got?.skip ?? 'the voice failed it twice';
		a.skips.push({ mid: a.message_id, idx, text: a.clips.text(i), at: 0, why, told: true });
		a.skipped += 1;
		emit({ skipped: a.skipped, note: `her voice skipped a line it could not say (${why})` });
		sound(a, { skip: { mid: a.message_id, idx, text: a.clips.text(i), at: 0, why, told: true }, row: null });
		if (got?.url) a.clip.urls.push(got.url);
		return playClip(a, i + 1);
	}
	if (got.silent) return playClip(a, i + 1); // the gate's floor: a wordless line is silence, nothing to say
	a.clip.urls.push(got.url);
	a.rows.clear();
	a.sounding = null;
	const row: VoiceRow = {
		mid: a.message_id,
		idx,
		text: a.clips.text(i),
		start: got.seg?.start ?? 0,
		duration: got.seg?.duration ?? Infinity,
		cue: false,
		order: ++a.order
	};
	a.rows.set(rowKey(row.mid, row.idx), row);
	attach(a, got.url);
	try {
		await el!.play();
	} catch {
		if (active === a && el && el.src === a.src) {
			clipBroke(a);
		}
		return active === a;
	}
	return true;
}
function clipEnded(a: Ask) {
	if (!a.clip) return end(a, 'natural');
	const i = a.clip.i;
	teardownClip(a);
	void playClip(a, i + 1);
}
function clipBroke(a: Ask) {
	if (!a.clip) return end(a, 'broken');
	const i = a.clip.i;
	const idx = a.clips?.idx ? a.clips.idx(i) : (a.first ?? 0) + i;
	const text = a.clips?.text(i) ?? '';
	a.skips.push({ mid: a.message_id, idx, text, at: 0, why: 'the clip would not play', told: true });
	a.skipped += 1;
	emit({ skipped: a.skipped, note: 'her voice skipped a line it could not play' });
	sound(a, { skip: { mid: a.message_id, idx, text, at: 0, why: 'the clip would not play', told: true }, row: null });
	teardownClip(a);
	if (!a.started && a.kind === 'line') return end(a, 'broken', 'her voice could not say this line');
	void playClip(a, i + 1);
}
function teardownClip(a: Ask) {
	if (a.frame && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(a.frame);
	a.frame = 0;
	detach(a);
}

// ── the browser's own voice (OWUI's engine '' : no server) ─────────────────────────────────────────────────
function startBrowser(a: Ask): boolean {
	if (typeof speechSynthesis === 'undefined' || typeof SpeechSynthesisUtterance === 'undefined') {
		end(a, 'broken', 'this browser has no voice of its own');
		return false;
	}
	const go = () => {
		if (active !== a) return;
		const u = new SpeechSynthesisUtterance(a.text ?? '');
		u.rate = a.rate;
		const v = speechSynthesis.getVoices().find((x) => x.voiceURI === a.voiceURI);
		if (v) u.voice = v;
		u.onstart = () => {
			if (active !== a) return;
			a.started = true;
			emit({ state: 'playing' });
		};
		u.onend = () => active === a && end(a, 'natural');
		u.onerror = () => active === a && end(a, a.started ? 'stopped' : 'broken');
		a.utterance = u;
		speechSynthesis.speak(u);
	};
	if (speechSynthesis.getVoices().length) go();
	else {
		let tries = 0;
		const wait = () => {
			if (active !== a) return;
			if (speechSynthesis.getVoices().length || ++tries > 30) return go();
			setTimeout(wait, 100);
		};
		wait();
	}
	return true;
}

// ── the lock screen, the earbuds ────────────────────────────────────────────────────────────────────────────
function mediaSession(a: Ask) {
	if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return;
	try {
		const art = a.artwork ? [{ src: new URL(a.artwork, location.href).href, sizes: '512x512' }] : [];
		navigator.mediaSession.metadata = new MediaMetadata({ title: a.title, artist: 'Petal', album: 'Petal Rig', artwork: art });
		navigator.mediaSession.setActionHandler('play', () => resumeVoice());
		navigator.mediaSession.setActionHandler('pause', () => pauseVoice());
		navigator.mediaSession.setActionHandler('stop', () => stopVoice());
		// 🚩 earbuds' "next track" (double press) / the lock screen's ⏭ = flag what she's saying right now
		navigator.mediaSession.setActionHandler('nexttrack', () => {
			flagPetalVoice({ via: 'earbud' }).catch(() => {});
		});
	} catch {}
}

const markLockScreen = (text: string) => {
	const a = active;
	if (!a || typeof navigator === 'undefined' || !('mediaSession' in navigator)) return;
	try {
		const m = navigator.mediaSession.metadata;
		navigator.mediaSession.metadata = new MediaMetadata({
			title: `${text} · ${a.title}`,
			artist: m?.artist ?? 'Petal',
			album: m?.album ?? 'Petal Rig',
			artwork: m?.artwork ? [...m.artwork] : []
		});
	} catch {}
	try {
		navigator.vibrate?.([40, 60, 40]);
	} catch {}
};

export type FlagResult = { ok: boolean; planted?: boolean; pending?: boolean; incident?: string; part?: number | null; error?: string };

// 🚩 flag the stream that's playing, or the last one (for message_id when given). where you were
// listening goes with it, so the rig knows which sentence it was.
export const flagPetalVoice = async (
	o: { token?: string; message_id?: string; note?: string; via?: string } = {}
): Promise<FlagResult> => {
	let trace: string | null | undefined, at: number | null = null, token = o.token;
	const a = active && active.began === 'stream' ? active : null;
	// 🧵 A45 · a stream that carries several replies (🍒 one pick, both sides) flags for any of them
	const carries = (m: string) => a?.message_id === m || a?.hearing === m || !!a?.marks.some((x) => x.message_id === m);
	if (a && (!o.message_id || carries(o.message_id))) {
		trace = a.trace;
		at = el && a.attached ? el.currentTime : null;
		token = token ?? a.token;
	} else if (last && (!o.message_id || last.message_id === o.message_id)) {
		trace = last.trace;
		at = last.at;
		token = token ?? last.token;
	}
	token = token ?? tokenNow();
	const res = await fetch(`${AUDIO_API_BASE_URL}/petal-stream/flag`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({ trace: trace ?? undefined, message_id: o.message_id, at_s: at, note: o.note, via: o.via ?? 'button' })
	}).catch(() => null);
	if (!res) return { ok: false, error: 'the rig is out of reach' };
	const j = await res.json().catch(() => ({}));
	if (!res.ok) return { ok: false, error: j?.detail ?? `flag failed (${res.status})` };
	const mm = at != null ? `${Math.floor(at / 60)}:${String(Math.floor(at % 60)).padStart(2, '0')}` : '';
	markLockScreen(`🚩 flagged${mm ? ' at ' + mm : ''}`);
	return j as FlagResult;
};

// ── the stream's own words (A19 · A37 · A38 · A45), kept for every way in ───────────────────────────────────
// on unless she turns it off: localStorage.petalStream = 'off'
export const petalStreamEnabled = () => {
	try {
		return localStorage.getItem('petalStream') !== 'off';
	} catch {
		return true;
	}
};

// 🍒 A38 · a picture isn't words: she never reads one (a markdown image's alt text, an <img> tag), nor waits for it
const PICTURES = [/!\[[^\]]*\]\([^)]*\)/g, /<img\b[^>]*>/gi];
export const withoutPictures = (content: string) =>
	PICTURES.reduce((c, re) => c.replace(re, (m) => (m ? '\u0000' : m)), content).replace(/[ \t]*\u0000[ \t]*/g, ' ');

// paragraphs first (so the stream knows where the longer pauses go), then sentences, both cut
// by OWUI's own cleaner so markdown, code and details are handled exactly as before
export const petalStreamParts = (
	content: string,
	split: (content: string, splitOn: string) => string[]
): PetalPart[] => {
	const parts: PetalPart[] = [];
	content = withoutPictures(content);
	const paras = split(content, 'paragraphs');
	for (const para of paras.length ? paras : [content]) {
		const sentences = split(para, 'punctuation').filter((s) => s.trim());
		sentences.forEach((text, i) => parts.push({ text: text.trim(), para_end: i === sentences.length - 1 }));
	}
	return parts;
};

type Play = {
	token: string;
	voice: string;
	parts: PetalPart[];
	meta?: PetalMeta;
	title?: string;
	artwork?: string;
	playbackRate?: number;
	onPlaying?: () => void;
	onEnded?: () => void;
	onError?: () => void;
	onSuperseded?: () => void;
	growing?: boolean; // 🌱 A37 · her voice as she writes
	onFeed?: (feed: string) => void; // 🌱 the growing stream's feed capability, once it's open
	follow?: FollowSegment[]; // 🧵 A45 · the rig feeds it from these replies, the page never does
	revoice?: () => string | undefined;
	fallback?: boolean;
	first?: number;
};
/** a stream, through the one door (autoplay, her stream's words) → true when it was opened and handed to the player */
export const playPetalStream = (p: Play): Promise<boolean> =>
	speakVoice({
		kind: 'stream',
		message_id: p.meta?.message_id ?? null,
		chat_id: p.meta?.chat_id ?? null,
		token: p.token,
		voice: p.voice,
		revoice: p.revoice,
		parts: p.parts,
		first: p.first,
		meta: p.meta,
		title: p.title,
		artwork: p.artwork,
		playbackRate: p.playbackRate,
		growing: p.growing,
		follow: p.follow,
		fallback: p.fallback,
		onFeed: p.onFeed,
		onPlaying: p.onPlaying,
		onEnded: p.onEnded,
		onError: p.onError,
		onSuperseded: p.onSuperseded
	});

/** the stream stops (only a stream: a quote's line or clips asked on their own are left be) */
export const stopPetalStream = () => {
	if (active?.began === 'stream') stopVoice();
};

export const petalStreamActive = () => active?.began === 'stream';

// 🌱 A37 · more of a reply she's still writing, for a growing stream (POST .../petal-stream/feed/{feed})
// → the rig's {ok, parts, done}, or null when the stream is gone (cut short, played out, the rig asleep)
export const feedPetalStream = async (
	token: string,
	feed: string,
	parts: PetalPart[],
	done: boolean,
	source?: string
): Promise<{ ok: boolean; parts: number; done: boolean } | null> => {
	const res = await fetch(`${AUDIO_API_BASE_URL}/petal-stream/feed/${encodeURIComponent(feed)}`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({ parts, done, ...(source !== undefined ? { source } : {}) })
	}).catch(() => null);
	if (!res || !res.ok) return null;
	return res.json().catch(() => null);
};

// 🧵 A45 · her 💗 on the reply she's hearing: the rig reads nothing after it (a followed stream's later replies)
export const cutPetalStream = async (token: string, feed: string, message_id: string): Promise<boolean> => {
	const a = active;
	if (a && a.began === 'stream') {
		a.keep = message_id; // what the player already holds past it is never heard
		look(a);
	}
	const res = await fetch(`${AUDIO_API_BASE_URL}/petal-stream/feed/${encodeURIComponent(feed)}`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({ cut_after: message_id })
	}).catch(() => null);
	return !!res?.ok;
};

/** the reply she's hearing right now in the playing stream (a pick's second side once the player reaches it) */
export const hearingReply = () => (active && active.began === 'stream' ? (active.hearing ?? active.message_id) : null);

// 🔓 A37 · the phone lets an <audio> play by itself only once a tap has played it: inside her tap (her send),
// her voice's own <audio> plays a breath of silence, so a reply can be heard later without another tap. never while
// an ask is opening or playing (the silence would be no one's)
const SILENT = 'data:audio/wav;base64,UklGRsQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
let unlocked = false;
export const petalStreamUnlocked = () => unlocked;
export const unlockPetalStream = () => {
	if (unlocked || active) return;
	const e = element();
	try {
		e.src = SILENT; // silence itself, unmuted: a muted play would unlock nothing
		const p = e.play();
		const done = () => {
			if (active || e.src !== SILENT) return; // an ask took the element meanwhile
			e.pause();
			e.removeAttribute('src');
			e.load();
			setSession('none');
		};
		if (p && typeof p.then === 'function')
			p.then(() => {
				unlocked = true;
				done();
			}).catch(() => done());
		else {
			unlocked = true;
			done();
		}
	} catch {}
};
