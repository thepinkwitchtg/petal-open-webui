// 🌸📻 petal stream — one <audio>, one live stream, so Petal keeps speaking with the screen off.
// the backend (routers/audio/petal_stream.py) turns a whole reply into a single mp3 stream with
// her cadence inside it; here we only open it, play it, and let the phone treat her like music
// (lock-screen card, earbud play/pause) through the Media Session API.
// 🎙️ A19 (contract ch. 11.6, B7's events): it also tells the page what her voice is doing (voiceNow:
// loading · playing · paused · idle, and why she ended), and hands the page what she's saying, so it can
// follow her: right after the stream's src is set it opens the stream's events door
// (EventSource on .../petal-stream/{ticket}/events) and passes on each `sentence {message_id, idx, text,
// start, duration}` (start and duration on the player's clock: the <audio>'s currentTime), closing the door
// on the rig's `end` or `stop`. pause · resume · end · stop are made here from the <audio> itself, in the
// same shape {type, message_id, at}.

import { writable } from 'svelte/store';
import { AUDIO_API_BASE_URL } from '$lib/constants';

export type PetalPart = { text: string; para_end: boolean };
// 🚩 who she was speaking for: kept beside the stream on the rig (memory only) until flagged
export type PetalMeta = { chat_id?: string; message_id?: string; model?: string; source?: string };

type Play = {
	token: string;
	voice: string;
	parts: PetalPart[];
	meta?: PetalMeta;
	title?: string;
	artwork?: string;
	playbackRate?: number;
	onPlaying?: () => void;
	onEnded?: () => void; // she finished, or someone stopped her
	onError?: () => void; // the stream broke before she spoke: fall back to sentence clips
};

let audio: HTMLAudioElement | null = null;
let events: EventSource | null = null; // the stream's events door, while it's open
let pausedOnce = false; // a 'play' after a pause is a resume
let current: {
	id: string;
	trace?: string;
	token: string;
	message_id?: string;
	title: string;
	started: boolean;
	onEnded?: () => void;
	onError?: () => void;
} | null = null;

// 🚩 the voice black box: the rig keeps her last few streams; these let you flag one
let last: { trace?: string; token: string; message_id?: string; at: number | null } | null = null;
export const spokenMessages = writable<Set<string>>(new Set()); // messages that have a stream to flag

// 🎙️ what her voice is doing right now, for the page (the bubble, the ▶️, the follower)
export type VoiceEnd = 'natural' | 'stopped' | 'broken';
export type VoiceNow = {
	state: 'idle' | 'loading' | 'playing' | 'paused';
	message_id: string | null;
	id: string | null; // the stream's ticket
	ended: VoiceEnd | null; // why the last one ended (natural: she reached the end)
};
export const voiceNow = writable<VoiceNow>({ state: 'idle', message_id: null, id: null, ended: null });

// 🎙️ what petal stream says she's playing (Lane B): one event per sentence as it starts, plus pause,
// resume and stop · `text` is the words as A renders them, `start` and `duration` in stream seconds
export type VoiceSentence = {
	message_id: string | null;
	idx: number;
	text: string;
	start: number;
	duration: number;
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
	return { type: 'sentence', message_id, idx, text: o.text, start, duration: Math.max(0, duration) };
}
/** hand an event to the page: the rig's sentences (from the playing stream's events door only) and
 *  the page's own pause · resume · end · stop */
function passVoiceEvent(raw: unknown, type: string, stream: string) {
	const e = voiceEvent(raw, type);
	if (!e || !current || stream !== current.id) return;
	for (const fn of voiceListeners) {
		try {
			fn(e, current.id);
		} catch (err) {
			console.warn('🎙️ voice follower:', err);
		}
	}
}

/** made by the page from the <audio> itself (contract 11.6): pause · resume · end · stop */
const pageEvent = (type: 'pause' | 'resume' | 'end' | 'stop') => {
	if (!current) return;
	passVoiceEvent(
		{ type, message_id: current.message_id ?? null, at: audio ? Math.round(audio.currentTime * 1000) / 1000 : null },
		type,
		current.id
	);
};

// the stream's events door (contract 11.6): opened right after the src is set, read until the rig says
// `end` or `stop` (the player plays on from what it holds), or the page ends her · a dropped door comes
// back by itself and the rig replays from the last event it saw (Last-Event-ID); once done it answers 204
function openEvents(id: string) {
	closeEvents();
	let es: EventSource;
	try {
		es = new EventSource(`${AUDIO_API_BASE_URL}/petal-stream/${encodeURIComponent(id)}/events`);
	} catch {
		return;
	}
	events = es;
	const take = (ev: Event, type?: string) => {
		if (events !== es) return;
		const data = (ev as MessageEvent).data;
		let raw: unknown = null;
		try {
			raw = data ? JSON.parse(data) : {};
		} catch {
			return;
		}
		const t = type ?? ((raw as Record<string, unknown>)?.type as string | undefined) ?? 'sentence';
		if (t === 'end' || t === 'stop') return closeEvents(); // the rig is done saying what she'll say
		passVoiceEvent(raw, t, id);
	};
	es.addEventListener('sentence', (ev) => take(ev, 'sentence'));
	es.addEventListener('end', (ev) => take(ev, 'end'));
	es.addEventListener('stop', (ev) => take(ev, 'stop'));
	es.onmessage = (ev) => take(ev);
	es.onerror = () => {
		if (events === es && es.readyState === EventSource.CLOSED) events = null;
	};
}
const closeEvents = () => {
	events?.close();
	events = null;
};

/** the <audio> she plays through (read only: its currentTime is the stream's clock) */
export const petalStreamAudio = () => audio;

export const pausePetalStream = () => {
	if (current && audio && !audio.paused) audio.pause();
};
export const resumePetalStream = () => {
	if (current && audio?.paused) audio.play().catch(() => {});
};

// on unless she turns it off: localStorage.petalStream = 'off'
export const petalStreamEnabled = () => {
	try {
		return localStorage.getItem('petalStream') !== 'off';
	} catch {
		return true;
	}
};

// paragraphs first (so the stream knows where the longer pauses go), then sentences, both cut
// by OWUI's own cleaner so markdown, code and details are handled exactly as before
export const petalStreamParts = (
	content: string,
	split: (content: string, splitOn: string) => string[]
): PetalPart[] => {
	const parts: PetalPart[] = [];
	const paras = split(content, 'paragraphs');
	for (const para of paras.length ? paras : [content]) {
		const sentences = split(para, 'punctuation').filter((s) => s.trim());
		sentences.forEach((text, i) => parts.push({ text: text.trim(), para_end: i === sentences.length - 1 }));
	}
	return parts;
};

const element = () => {
	if (!audio) {
		audio = new Audio();
		audio.preload = 'auto';
		audio.setAttribute('playsinline', '');
		(audio as any).disableRemotePlayback = true;
		audio.addEventListener('playing', () => {
			if (current) current.started = true;
			setState('playing');
			if (current) say('playing');
		});
		audio.addEventListener('play', () => {
			if (current && pausedOnce) pageEvent('resume');
			pausedOnce = false;
		});
		audio.addEventListener('pause', () => {
			if (!current || audio?.ended) return;
			pausedOnce = true;
			setState('paused');
			say('paused');
			pageEvent('pause');
		});
		audio.addEventListener('ended', () => {
			pageEvent('end');
			finish(false, 'natural');
		});
		audio.addEventListener('error', () => current && finish(true, 'broken'));
	}
	return audio;
};

const setState = (s: MediaSessionPlaybackState) => {
	try {
		if ('mediaSession' in navigator) navigator.mediaSession.playbackState = s;
	} catch {}
};

const say = (state: VoiceNow['state']) =>
	voiceNow.set({ state, message_id: current?.message_id ?? null, id: current?.id ?? null, ended: null });

const finish = (broken: boolean, why: VoiceEnd = broken ? 'broken' : 'stopped') => {
	const was = current;
	if (was) {
		const ended = !!audio?.ended;
		last = { trace: was.trace, token: was.token, message_id: was.message_id, at: ended ? null : (audio?.currentTime ?? null) };
	}
	current = null;
	closeEvents();
	pausedOnce = false;
	if (audio) {
		audio.pause();
		audio.removeAttribute('src');
		audio.load();
	}
	setState('none');
	if (!was) return;
	voiceNow.set({ state: 'idle', message_id: was.message_id ?? null, id: was.id, ended: why });
	// a stream that breaks before her first sound gets a second chance as sentence clips;
	// once she has spoken, a break just ends her like a stop would
	if (broken && !was.started) was.onError?.();
	else was.onEnded?.();
};

export const stopPetalStream = () => {
	if (current) pageEvent('stop');
	finish(false, 'stopped');
};

export const petalStreamActive = () => current !== null;

const mediaSession = (title: string, artwork?: string) => {
	if (!('mediaSession' in navigator)) return;
	try {
		const art = artwork ? [{ src: new URL(artwork, location.href).href, sizes: '512x512' }] : [];
		navigator.mediaSession.metadata = new MediaMetadata({ title, artist: 'Petal', album: 'Petal Rig', artwork: art });
		navigator.mediaSession.setActionHandler('play', () => audio?.play().catch(() => {}));
		navigator.mediaSession.setActionHandler('pause', () => audio?.pause());
		navigator.mediaSession.setActionHandler('stop', () => stopPetalStream());
		// 🚩 earbuds' "next track" (double press) / the lock screen's ⏭ = flag what she's saying right now
		navigator.mediaSession.setActionHandler('nexttrack', () => {
			flagPetalVoice({ via: 'earbud' }).catch(() => {});
		});
	} catch {}
};

const markLockScreen = (text: string) => {
	if (!current || !('mediaSession' in navigator)) return;
	try {
		const m = navigator.mediaSession.metadata;
		navigator.mediaSession.metadata = new MediaMetadata({
			title: `${text} · ${current.title}`,
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
	let trace: string | undefined, at: number | null = null, token = o.token;
	if (current && (!o.message_id || current.message_id === o.message_id)) {
		trace = current.trace;
		at = audio?.currentTime ?? null;
		token = token ?? current.token;
	} else if (last && (!o.message_id || last.message_id === o.message_id)) {
		trace = last.trace;
		at = last.at;
		token = token ?? last.token;
	}
	token = token ?? localStorage.token;
	const res = await fetch(`${AUDIO_API_BASE_URL}/petal-stream/flag`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({ trace, message_id: o.message_id, at_s: at, note: o.note, via: o.via ?? 'button' })
	}).catch(() => null);
	if (!res) return { ok: false, error: 'the rig is out of reach' };
	const j = await res.json().catch(() => ({}));
	if (!res.ok) return { ok: false, error: j?.detail ?? `flag failed (${res.status})` };
	const mm = at != null ? `${Math.floor(at / 60)}:${String(Math.floor(at % 60)).padStart(2, '0')}` : '';
	markLockScreen(`🚩 flagged${mm ? ' at ' + mm : ''}`);
	return j as FlagResult;
};

// → true when the stream was opened and handed to the player; false means use sentence clips now
export const playPetalStream = async (p: Play): Promise<boolean> => {
	if (!current) voiceNow.set({ state: 'loading', message_id: p.meta?.message_id ?? null, id: null, ended: null });
	const res = await fetch(`${AUDIO_API_BASE_URL}/petal-stream`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${p.token}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({ voice: p.voice, parts: p.parts, meta: p.meta })
	}).catch(() => null);
	const unopened = () => {
		if (!current) voiceNow.set({ state: 'idle', message_id: p.meta?.message_id ?? null, id: null, ended: 'broken' });
		return false;
	};
	if (!res || !res.ok) return unopened();
	const opened = await res.json().catch(() => ({}));
	const id = opened?.id;
	if (!id) return unopened();

	stopPetalStream(); // only one station at a time
	const a = element();
	const title = p.title || 'Petal 💗';
	current = {
		id,
		trace: opened?.trace,
		token: p.token,
		message_id: p.meta?.message_id,
		title,
		started: false,
		onEnded: p.onEnded,
		onError: p.onError
	};
	if (p.meta?.message_id && opened?.trace) {
		const mid = p.meta.message_id;
		spokenMessages.update((s) => new Set(s).add(mid));
	}
	const mine = current;
	say('loading');
	a.addEventListener('playing', () => current === mine && p.onPlaying?.(), { once: true });
	a.src = `${AUDIO_API_BASE_URL}/petal-stream/${encodeURIComponent(id)}`;
	openEvents(id); // 🎙️ right after the src (contract 11.6)
	a.playbackRate = p.playbackRate ?? 1;
	mediaSession(title, p.artwork);
	try {
		await a.play();
	} catch (e) {
		if (current === mine) finish(true, 'broken');
	}
	return true;
};
