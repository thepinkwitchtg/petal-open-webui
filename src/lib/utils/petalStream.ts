// 🌸📻 petal stream — one <audio>, one live stream, so Petal keeps speaking with the screen off.
// the backend (routers/audio/petal_stream.py) turns a whole reply into a single mp3 stream with
// her cadence inside it; here we only open it, play it, and let the phone treat her like music
// (lock-screen card, earbud play/pause) through the Media Session API.

import { AUDIO_API_BASE_URL } from '$lib/constants';

export type PetalPart = { text: string; para_end: boolean };

type Play = {
	token: string;
	voice: string;
	parts: PetalPart[];
	title?: string;
	artwork?: string;
	playbackRate?: number;
	onPlaying?: () => void;
	onEnded?: () => void; // she finished, or someone stopped her
	onError?: () => void; // the stream broke before she spoke: fall back to sentence clips
};

let audio: HTMLAudioElement | null = null;
let current: { id: string; started: boolean; onEnded?: () => void; onError?: () => void } | null = null;

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
	} catch {}
};

// → true when the stream was opened and handed to the player; false means use sentence clips now
export const playPetalStream = async (p: Play): Promise<boolean> => {
	const res = await fetch(`${AUDIO_API_BASE_URL}/petal-stream`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${p.token}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({ voice: p.voice, parts: p.parts })
	}).catch(() => null);
	if (!res || !res.ok) return false;
	const id = (await res.json().catch(() => ({})))?.id;
	if (!id) return false;

	stopPetalStream(); // only one station at a time
	const a = element();
	current = { id, started: false, onEnded: p.onEnded, onError: p.onError };
	const mine = current;
	a.addEventListener('playing', () => current === mine && p.onPlaying?.(), { once: true });
	a.src = `${AUDIO_API_BASE_URL}/petal-stream/${encodeURIComponent(id)}`;
	a.playbackRate = p.playbackRate ?? 1;
	mediaSession(p.title || 'Petal 💗', p.artwork);
	try {
		await a.play();
	} catch (e) {
		if (current === mine) finish(true);
	}
	return true;
};
