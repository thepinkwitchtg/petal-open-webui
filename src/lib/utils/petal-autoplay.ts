// 🔈 her voice plays on its own (slice A37 · Settings → 🌸 Petal → Voice), so Petal is heard without a click.
//  · three ways, chosen per device (this browser's own storage, never synced: the phone and the rig differ):
//    off · after she finishes (the whole reply, once written) · as she writes (sentence by sentence while the
//    reply is still arriving: one growing petal stream, fed each sentence the moment it's whole, so her voice
//    follows the typing and the trail follows her voice through the stream's own events, contract 11.6)
//  · as she writes is the default everywhere; on the phone it speaks only with earphones: the 🎧 chip by the mic
//    (one tap, remembered on this device) or, when she opts in, the rig's audio route (earphones · speaker) read
//    through the fork's neutral door (/api/v1/audio/petal-route), which only opens or holds the gate
//  · the rules: only replies this tab asked for speak by themselves (a reload, another tab, an old chat: never) ·
//    a reply speaks by itself once (its id is remembered on this device, ids only) · a pick waits and plays only
//    the chosen reply · a new send stops her · scrolled away (or gone from the page) while the page is visible,
//    she fades and stops; a hidden page or a dark screen never counts as away · one voice across her tabs (the
//    newest one speaking wins) · stop (⏹ by the mic) and pause (the bubble) are one tap each
import { derived, get, writable } from 'svelte/store';
import { config, settings } from '$lib/stores';
import { AUDIO_API_BASE_URL } from '$lib/constants';
import { getMessageContentParts } from '$lib/utils';
import {
	feedPetalStream,
	petalStreamAudio,
	petalStreamEnabled,
	petalStreamParts,
	playPetalStream,
	stopPetalStream,
	unlockPetalStream,
	voiceNow
} from '$lib/utils/petalStream';
import { playReply, replyOf, stopAllVoice, voiceReplies, voiceUI } from '$lib/utils/petal-voice';

export type AutoMode = 'off' | 'finished' | 'writing';
export type AudioRoute = 'earphones' | 'speaker' | 'unknown';

export const AUTO_MODES: AutoMode[] = ['off', 'finished', 'writing'];
const KEY = { mode: 'petal-autoplay', ear: 'petal-earphones', follow: 'petal-route-follow', heard: 'petal-autoplayed' };
const HEARD_KEEP = 300; // ids remembered, newest kept
const THROTTLE_MS = 280; // a growing reply is looked at this often (and at once when it's done)
const AWAY_MS = 1500; // out of sight this long while the page is visible: she fades
const FADE_MS = 900;
const ROUTE_FRESH_MS = 10000;
const ROUTE_EVERY_MS = 20000;

const read = (k: string): string | null => {
	try {
		return localStorage.getItem(k);
	} catch {
		return null;
	}
};
const write = (k: string, v: string) => {
	try {
		localStorage.setItem(k, v);
	} catch {}
};

/** a phone (or a tablet): a coarse pointer and no hover */
export const isPhone = (): boolean => {
	try {
		return matchMedia('(pointer: coarse)').matches && !matchMedia('(hover: hover)').matches;
	} catch {
		return false;
	}
};

export const modeOf = (v: unknown): AutoMode => (AUTO_MODES.includes(v as AutoMode) ? (v as AutoMode) : 'writing');

// ── her choices on this device ───────────────────────────────────────────────────────────────────────
export const autoMode = writable<AutoMode>(modeOf(read(KEY.mode)));
export const earphones = writable<boolean>(read(KEY.ear) === 'on');
export const followRoute = writable<boolean>(read(KEY.follow) === 'on');
export const audioRoute = writable<AudioRoute | null>(null); // the rig's last word (only while she follows it)

export const setAutoMode = (m: AutoMode) => {
	autoMode.set(modeOf(m));
	write(KEY.mode, modeOf(m));
};
export const setEarphones = (on: boolean) => {
	earphones.set(on);
	write(KEY.ear, on ? 'on' : 'off');
};
export const setFollowRoute = (on: boolean) => {
	followRoute.set(on);
	write(KEY.follow, on ? 'on' : 'off');
	if (on) void refreshRoute(true);
	else audioRoute.set(null);
};

/** what autoplay does on this device right now: the desktop does what she chose; the phone, only with earphones
 *  (the rig's route when she follows it and it knows, else the 🎧 chip) */
export function decide(mode: AutoMode, phone: boolean, ear: boolean, follow: boolean, route: AudioRoute | null): AutoMode {
	if (mode === 'off' || !phone) return mode;
	if (follow && route === 'earphones') return mode;
	if (follow && route === 'speaker') return 'off';
	return ear ? mode : 'off';
}
export const autoNow = derived([autoMode, earphones, followRoute, audioRoute], ([m, e, f, r]) =>
	decide(m, isPhone(), e, f, r)
);
export const effectiveMode = (): AutoMode =>
	decide(get(autoMode), isPhone(), get(earphones), get(followRoute), get(audioRoute));

// ── the rig's audio route (opt-in, phone only, gates only) ──────────────────────────────────────────────
let routeAt = 0;
let routeAsking: Promise<void> | null = null;
export function refreshRoute(force = false): Promise<void> {
	if (!get(followRoute) || !isPhone()) return Promise.resolve();
	if (!force && Date.now() - routeAt < ROUTE_FRESH_MS) return Promise.resolve();
	if (routeAsking) return routeAsking;
	const ctl = new AbortController();
	const t = setTimeout(() => ctl.abort(), 1200);
	routeAsking = fetch(`${AUDIO_API_BASE_URL}/petal-route`, {
		headers: { Authorization: `Bearer ${read('token') ?? ''}` },
		signal: ctl.signal
	})
		.then((r) => (r.ok ? r.json() : null))
		.then((j) => {
			const r = j?.route;
			audioRoute.set(r === 'earphones' || r === 'speaker' ? r : 'unknown');
			routeAt = Date.now();
		})
		.catch(() => audioRoute.set('unknown'))
		.finally(() => {
			clearTimeout(t);
			routeAsking = null;
		});
	return routeAsking;
}

// ── which replies may speak by themselves ───────────────────────────────────────────────────────────────
const born = new Map<string, number>(); // replies this tab asked for (in memory: a reload forgets them)
const asked = new Map<string, number>(); // her messages sent from this tab: a reply to one (a queued send's, answered later) is hers too
// her voice's last choices, for a look inside (ids and reasons only, never words)
const trail: string[] = [];
const why = (what: string, id?: string | null) => {
	trail.push(`${Math.round(performance.now())} ${what}${id ? ' ' + id.slice(0, 8) : ''}`);
	if (trail.length > 60) trail.shift();
};
const handled = new Set<string>(); // replies the writing voice took (after-she-finishes leaves them)
let heard: string[] = (() => {
	try {
		const v = JSON.parse(read(KEY.heard) ?? '[]');
		return Array.isArray(v) ? v.filter((x) => typeof x === 'string').slice(-HEARD_KEEP) : [];
	} catch {
		return [];
	}
})();
const markHeard = (id: string) => {
	if (heard.includes(id)) return;
	heard = [...heard, id].slice(-HEARD_KEEP);
	write(KEY.heard, JSON.stringify(heard));
};

/** Chat marks each reply placeholder of her own send (a pick's two included) */
export function bornHere(id: string) {
	born.set(id, Date.now());
	why('born', id);
	if (born.size > 200) born.delete(born.keys().next().value as string);
}

/** Chat marks each message she sends from this tab (a send queued behind a running reply is answered later,
 *  under a reply id this tab never made) */
export function askedHere(id: string) {
	asked.set(id, Date.now());
	why('asked', id);
	if (asked.size > 200) asked.delete(asked.keys().next().value as string);
}

/** a send of hers queued behind a running reply: the backend folds it (with any others queued there) into a new
 *  message of its own, so its id never comes back. her words find it again: held here only, in memory, until
 *  the reply to them is claimed (or ten minutes pass) */
const later = new Map<string, number>();
const LATER_MS = 10 * 60 * 1000;
export function askedLater(words: string) {
	const w = (words ?? '').trim();
	if (!w) return;
	later.set(w, Date.now());
	if (later.size > 20) later.delete(later.keys().next().value as string);
}
const folded = (text: string, w: string) =>
	text === w || text.startsWith(w + '\n\n') || text.endsWith('\n\n' + w) || text.includes('\n\n' + w + '\n\n');
function claim(parentId: string, parentText?: string | null) {
	if (!later.size || !parentText) return false;
	const text = parentText.trim();
	const now = Date.now();
	let hit = false;
	for (const [w, at] of later) {
		if (now - at > LATER_MS) later.delete(w);
		else if (folded(text, w)) {
			later.delete(w);
			hit = true;
		}
	}
	if (hit) {
		asked.set(parentId, now);
		why('asked (folded by the queue)', parentId);
	}
	return hit;
}

const mine = (id: string, parentId?: string | null, parentText?: string | null) =>
	born.has(id) || (!!parentId && (asked.has(parentId) || claim(parentId, parentText)));

/** may this reply speak by itself? asked from this tab (its placeholder or its question), never heard by itself before */
export const mayAuto = (id: string, parentId?: string | null) => mine(id, parentId) && !heard.includes(id);

const ttsReady = () => {
	const c = get(config) as { audio?: { tts?: { engine?: string } } } | undefined;
	const s = get(settings) as { audio?: { tts?: { engine?: string } } } | undefined;
	return !!c?.audio?.tts?.engine && s?.audio?.tts?.engine !== 'browser-kokoro';
};

// ── as she writes: one growing stream, fed sentence by sentence ─────────────────────────────────────────
type Writing = {
	id: string;
	feed: string | null;
	opening: boolean;
	sent: number; // parts already given to the stream
	done: boolean; // the last feed (done: true) is on its way
	content: string;
	finished: boolean; // the reply is fully written
	chain: Promise<unknown>;
	timer: ReturnType<typeof setTimeout> | null;
};
let writing: Writing | null = null;
export const writingNow = () => (writing ? { id: writing.id, sent: writing.sent, done: writing.done, open: !!writing.feed } : null);

/** ResponseMessage tells each change of a reply's words (while it streams, and once it's done) */
export function grew(
	id: string,
	content: string,
	finished: boolean,
	parentId?: string | null,
	parentText?: () => string | null | undefined
) {
	if (typeof window === 'undefined' || !id) return;
	let w = writing;
	if (!w || w.id !== id) {
		if (!born.has(id) && !(parentId && asked.has(parentId)) && !(later.size && parentId && claim(parentId, parentText?.())))
			return; // the cheapest question first: most replies on a page were never asked here
		if (finished && content.trim() && !born.has(id)) return lateWhole(id, parentId);
		if (finished || !content.trim()) return; // a reply that arrives whole is for after-she-finishes
		if (effectiveMode() !== 'writing' || !mayAuto(id, parentId) || handled.has(id) || !ttsReady() || !petalStreamEnabled())
			return;
		const r = replyOf(id);
		if (!r || r.pick?.()) return; // 🍒 a pick waits for her choice
		if (get(voiceUI).state !== 'idle') return why('writing waits: she listens', id); // she's already listening to something she chose
		why('writing begins', id);
		w = writing = {
			id,
			feed: null,
			opening: false,
			sent: 0,
			done: false,
			content,
			finished,
			chain: Promise.resolve(),
			timer: null
		};
		handled.add(id);
	}
	w.content = content;
	w.finished = finished;
	if (finished) {
		if (w.timer) clearTimeout(w.timer);
		w.timer = null;
		flush(w);
	} else if (!w.timer) {
		const mine = w;
		w.timer = setTimeout(() => {
			mine.timer = null;
			flush(mine);
		}, THROTTLE_MS);
	}
}

/** the sentences that are whole: all of them once she's done, all but the last while she writes */
export function wholeParts(content: string, finished: boolean) {
	const parts = petalStreamParts(content, getMessageContentParts);
	return finished ? parts : parts.slice(0, -1);
}

function flush(w: Writing) {
	if (writing !== w || w.done) return;
	if (w.opening) return; // once it's open, it looks again (the feed can arrive before the stream is in hand)
	const ready = wholeParts(w.content, w.finished);
	if (!w.feed) {
		if (!ready.length) {
			if (w.finished) letGo(w, false); // nothing she'd say aloud
			return;
		}
		void open(w, ready);
		return;
	}
	const fresh = ready.slice(w.sent);
	if (!fresh.length && !w.finished) return;
	w.sent += fresh.length;
	w.done = w.finished;
	const feed = w.feed;
	const done = w.done;
	const source = w.content;
	w.chain = w.chain
		.then(() => feedPetalStream(read('token') ?? '', feed, fresh, done, source))
		.then((r) => {
			if (!r && writing === w && !w.done) letGo(w, true); // the stream is gone (she stopped it)
		});
}

async function open(w: Writing, ready: ReturnType<typeof wholeParts>) {
	const r = replyOf(w.id);
	if (!r) return letGo(w, false);
	w.opening = true;
	w.sent = ready.length; // what the stream opens with is already given
	const m = r.meta?.() ?? {};
	const opened = await playPetalStream({
		token: read('token') ?? '',
		voice: r.voice() ?? '',
		parts: ready,
		meta: { chat_id: m.chat_id, message_id: w.id, model: m.model, source: w.content },
		title: m.title,
		artwork: m.artwork,
		playbackRate: m.playbackRate,
		growing: true,
		onFeed: (f) => {
			w.feed = f;
		},
		onError: () => {
			// the stream broke before her first sound: after-she-finishes may still play it
			if (writing === w) letGo(w, false);
			handled.delete(w.id);
		}
	});
	w.opening = false;
	if (writing !== w) {
		// a new send (or her stop) let go of it while it opened: the stream it opened doesn't speak on
		const v = get(voiceNow);
		if (opened && v.state !== 'idle' && v.message_id === w.id) stopPetalStream();
		return;
	}
	if (!opened || !w.feed) {
		letGo(w, false);
		handled.delete(w.id); // never opened: after-she-finishes gets its chance
		return;
	}
	markHeard(w.id);
	watchAway(w.id);
	flush(w); // what was written while it opened
}

function letGo(w: Writing, keepHandled: boolean) {
	why(keepHandled ? 'let go (kept)' : 'let go', w.id);
	if (w.timer) clearTimeout(w.timer);
	w.timer = null;
	if (!keepHandled) handled.delete(w.id);
	if (writing === w) writing = null;
}

/** a reply to a send of hers that was queued behind a running reply: the backend answers it later and the page
 *  receives it whole (Chat's after-a-reply never sees it), so it speaks from here, once, as after she finishes */
function lateWhole(id: string, parentId?: string | null) {
	if (get(voiceUI).state !== 'idle') return why('late waits: she listens', id); // she's listening to something: it waits for her tap
	if (replyOf(id)?.pick?.()) return why('late waits: a pick', id);
	const ok = autoAfter(id, parentId);
	why(ok ? 'late speaks' : 'late stays', id);
	if (ok) playReply(id);
}

// ── after she finishes ──────────────────────────────────────────────────────────────────────────────────
/** Chat asks once a reply is finished (or picked): should it speak it now? (marks it heard when yes) */
export function autoAfter(id: string, parentId?: string | null, parentText?: string | null): boolean {
	if (handled.has(id)) return false; // the writing voice has it (or she stopped it)
	const mode = effectiveMode();
	if (mode === 'off') return false;
	if (!mine(id, parentId, parentText) || !mayAuto(id, parentId)) return (why('after: not hers here', id), false);
	why('after: yes', id);
	markHeard(id);
	watchAway(id);
	return true;
}

/** a new send of hers: whatever her voice was saying stops (and her tap lets the next reply play) */
export function newSend() {
	why('new send');
	unlockPetalStream();
	if (writing) letGo(writing, true);
	if (get(voiceUI).state !== 'idle') stopAllVoice();
}

// ── away: scrolled out of sight (or gone from the page) while the page is visible ───────────────────────
let awayIO: IntersectionObserver | null = null;
let awayId: string | null = null;
let awayTimer: ReturnType<typeof setTimeout> | null = null;
let unReplies: (() => void) | null = null;
let fading: ReturnType<typeof setInterval> | null = null;

function clearAway() {
	awayIO?.disconnect();
	awayIO = null;
	awayId = null;
	if (awayTimer) clearTimeout(awayTimer);
	awayTimer = null;
	unReplies?.();
	unReplies = null;
}

function soonAway() {
	if (awayTimer || document.visibilityState !== 'visible') return;
	awayTimer = setTimeout(() => {
		awayTimer = null;
		if (document.visibilityState === 'visible') fadeOut();
	}, AWAY_MS);
}
function back() {
	if (awayTimer) clearTimeout(awayTimer);
	awayTimer = null;
}

function watchAway(id: string) {
	clearAway();
	if (typeof IntersectionObserver === 'undefined') return;
	awayId = id;
	const el = replyOf(id)?.root();
	if (el) {
		awayIO = new IntersectionObserver((entries) => {
			const e = entries[entries.length - 1];
			if (!e || awayId !== id) return;
			if (e.isIntersecting) back();
			else soonAway();
		});
		awayIO.observe(el);
	}
	// the chat changed under her (the reply left the page): away too
	unReplies = voiceReplies.subscribe(() => {
		if (awayId === id && !replyOf(id)) soonAway();
	});
}

/** her voice fades over FADE_MS and stops (only the stream's <audio> can fade; anything else just stops) */
export function fadeOut(ms = FADE_MS) {
	if (fading) return;
	const a = petalStreamAudio();
	const ui = get(voiceUI);
	if (ui.state === 'idle') return clearAway();
	if (!a || ui.kind !== 'stream' || a.paused) {
		stopAllVoice();
		return clearAway();
	}
	const from = a.volume;
	const t0 = performance.now();
	fading = setInterval(() => {
		const k = Math.min(1, (performance.now() - t0) / ms);
		a.volume = Math.max(0, from * (1 - k));
		if (k >= 1) {
			if (fading) clearInterval(fading);
			fading = null;
			stopAllVoice();
			a.volume = from;
			clearAway();
		}
	}, 50);
}

// ── one voice across her tabs ───────────────────────────────────────────────────────────────────────────
const TAB = Math.random().toString(36).slice(2, 10);
let bc: BroadcastChannel | null = null;

// ── installed once by the page ──────────────────────────────────────────────────────────────────────────
let installed = false;
export function installAutoplay() {
	if (installed || typeof window === 'undefined') return;
	installed = true;
	// her first touch of the page lets her stream's <audio> play by itself later (phones ask for a tap)
	const unlock = () => {
		if (effectiveMode() !== 'off') unlockPetalStream();
	};
	document.addEventListener('pointerdown', unlock, true);
	document.addEventListener('keydown', unlock, true);
	try {
		bc = new BroadcastChannel('petal-voice');
		bc.onmessage = (ev) => {
			const d = ev.data as { t?: string; tab?: string } | null;
			if (d?.t === 'speaking' && d.tab !== TAB && get(voiceUI).state !== 'idle') stopAllVoice();
		};
	} catch {}
	let was = 'idle';
	let wasId: string | null = null;
	voiceUI.subscribe((ui) => {
		const speaking = ui.state === 'loading' || ui.state === 'playing';
		if (speaking && (was === 'idle' || ui.message_id !== wasId)) {
			try {
				bc?.postMessage({ t: 'speaking', tab: TAB });
			} catch {}
		}
		was = ui.state;
		wasId = ui.message_id;
	});
	voiceNow.subscribe((v) => {
		if (v.state !== 'idle') return;
		// she ended (played out, stopped, broken): the writing voice and the away watch let go of it
		if (writing && (!v.message_id || v.message_id === writing.id) && (writing.feed || !writing.opening))
			letGo(writing, true);
		if (awayId && get(voiceUI).state === 'idle') clearAway();
	});
	voiceUI.subscribe((ui) => {
		if (ui.state === 'idle' && awayId && !fading) clearAway();
	});
	// the rig's audio route, while she follows it on the phone and the page is visible: no clock at all otherwise
	let routeClock: ReturnType<typeof setInterval> | null = null;
	followRoute.subscribe((on) => {
		if (on && isPhone() && !routeClock)
			routeClock = setInterval(() => {
				if (document.visibilityState === 'visible') void refreshRoute();
			}, ROUTE_EVERY_MS);
		else if (!(on && isPhone()) && routeClock) {
			clearInterval(routeClock);
			routeClock = null;
		}
	});
	document.addEventListener('visibilitychange', () => {
		if (document.visibilityState === 'visible') void refreshRoute();
		else back(); // a hidden page or a dark screen is never away
	});
	void refreshRoute(true);
	(window as unknown as { petalAutoplay?: object }).petalAutoplay = {
		get now() {
			return {
				mode: get(autoMode),
				effective: effectiveMode(),
				phone: isPhone(),
				ear: get(earphones),
				follow: get(followRoute),
				route: get(audioRoute),
				writing: writingNow(),
				voice: get(voiceUI), // ids and states only
				volume: petalStreamAudio()?.volume ?? null
			};
		},
		get why() {
			return [...trail];
		}
	};
}
