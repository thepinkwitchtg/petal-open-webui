// 🌸📻 petal stream — one <audio>, one live stream, so Petal keeps speaking with the screen off.
// the backend (routers/audio/petal_stream.py) turns a whole reply into a single mp3 stream with
// her cadence inside it; here we only open it, play it, and let the phone treat her like music
// (lock-screen card, earbud play/pause) through the Media Session API.

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
		});
		audio.addEventListener('pause', () => current && setState('paused'));
		audio.addEventListener('ended', () => finish(false));
		audio.addEventListener('error', () => current && finish(true));
	}
	return audio;
};

const setState = (s: MediaSessionPlaybackState) => {
	try {
		if ('mediaSession' in navigator) navigator.mediaSession.playbackState = s;
	} catch {}
};

const finish = (broken: boolean) => {
	const was = current;
	if (was) {
		const ended = !!audio?.ended;
		last = { trace: was.trace, token: was.token, message_id: was.message_id, at: ended ? null : (audio?.currentTime ?? null) };
	}
	current = null;
	if (audio) {
		audio.pause();
		audio.removeAttribute('src');
		audio.load();
	}
	setState('none');
	if (!was) return;
	// a stream that breaks before her first sound gets a second chance as sentence clips;
	// once she has spoken, a break just ends her like a stop would
	if (broken && !was.started) was.onError?.();
	else was.onEnded?.();
};

export const stopPetalStream = () => finish(false);

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
	const res = await fetch(`${AUDIO_API_BASE_URL}/petal-stream`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${p.token}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({ voice: p.voice, parts: p.parts, meta: p.meta })
	}).catch(() => null);
	if (!res || !res.ok) return false;
	const opened = await res.json().catch(() => ({}));
	const id = opened?.id;
	if (!id) return false;

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
	a.addEventListener('playing', () => current === mine && p.onPlaying?.(), { once: true });
	a.src = `${AUDIO_API_BASE_URL}/petal-stream/${encodeURIComponent(id)}`;
	a.playbackRate = p.playbackRate ?? 1;
	mediaSession(title, p.artwork);
	try {
		await a.play();
	} catch (e) {
		if (current === mine) finish(true);
	}
	return true;
};
