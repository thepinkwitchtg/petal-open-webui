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
//    the chosen reply · stop (⏹ by the mic) and pause (the bubble) are one tap each
//  · 🔈 A40 · her voice follows her: it plays on across the app's tabs and views, a dark screen, a menu, the chat
//    scrolled away. only her ⏹, a new send in the chat it speaks for, or another reply's voice stops it (a send in
//    another chat lets that send's reply take over once it speaks; a voice she starts after that send is left be).
//    one voice at a time across her browser tabs too (the newest one speaking wins)
//  · 🔈 A40 · the play button joins a reply still being written (the one in view): a growing stream from its first
//    sentence, fed as she writes, picks aside (A38 reads those)
//  · 🍒 A38 · a pick, read aloud: while a pick is open she reads both in turn, each opened by her cue (Settings →
//    🌸 Petal → Voice, defaults below, empty: no cue): cue one, reply one; cue two, reply two. each follows what
//    the pick shows (twin streaming types both at one pace, so her voice never tells which one is steered), and
//    reply two waits its turn even when it was written first; a picture is never read nor waited for.
//    her 💗 on the reply she's hearing changes nothing (no restart, no gap; the other is simply never read) ·
//    on the other: it stops at once and the chosen one plays from its start · after both were read through,
//    nothing replays · a new send, her ⏹, another tab or scrolling away ends the reading
import { derived, get, writable } from 'svelte/store';
import { config, settings } from '$lib/stores';
import { AUDIO_API_BASE_URL } from '$lib/constants';
import { getMessageContentParts } from '$lib/utils';
import {
	cutPetalStream,
	hearingReply,
	petalStreamAudio,
	petalStreamEnabled,
	petalStreamParts,
	playPetalStream,
	stopPetalStream,
	unlockPetalStream,
	voiceNow,
	type FollowSegment
} from '$lib/utils/petalStream';
import { playReply, replyOf, setLivePlayer, stopAllVoice, voiceUI } from '$lib/utils/petal-voice';

export type AutoMode = 'off' | 'finished' | 'writing';
export type AudioRoute = 'earphones' | 'speaker' | 'unknown';

export const AUTO_MODES: AutoMode[] = ['off', 'finished', 'writing'];
const KEY = { mode: 'petal-autoplay', ear: 'petal-earphones', follow: 'petal-route-follow', heard: 'petal-autoplayed' };
const HEARD_KEEP = 300; // ids remembered, newest kept
const THROTTLE_MS = 280; // a growing reply is looked at this often (and at once when it's done)
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

// ── 🍒 A38 · her cue words for a pick read aloud (synced with her settings, `petalVoice.cues`) ───────────────
export type PickCues = { one: string; two: string };
export const CUE_DEFAULTS: PickCues = { one: 'pick one', two: 'pick two' };
const CUE_MAX = 60;
/** her cue words as saved (a missing one takes its default; an empty one stays empty: no cue) */
export function cuesOf(s: unknown): PickCues {
	const raw = ((s as Record<string, unknown> | null)?.petalVoice as Record<string, unknown> | undefined)?.cues;
	const c = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
	const one = typeof c.one === 'string' ? c.one.trim().slice(0, CUE_MAX) : CUE_DEFAULTS.one;
	const two = typeof c.two === 'string' ? c.two.trim().slice(0, CUE_MAX) : CUE_DEFAULTS.two;
	return { one, two };
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
	lead: string; // 🍒 A38 · her cue, said first (empty: none)
	pick: PickRead | null; // 🍒 A38 · the pick this turn reads
	chat: string | null; // 🔈 A40 · the chat it speaks for
	eager: boolean; // 🔈 A40 · her tap on a reply still being written: open at once, before a sentence is whole
	stream: string | null; // 🧵 A45 · the stream's ticket, once open (a pick's stream changes its reply midway)
	both: boolean; // 🧵 A45 · 🍒 the stream reads the other side too (the rig follows both, in turn)
	lounge: boolean; // 🧵 A45 · 🌊 words she spoke on her own: a stream that never opens still plays them as clips
};
let writing: Writing | null = null;

// 🍒 A38 · a pick read aloud: whose turn it is, what each side shows so far, and her 💗 once given
type PickRead = {
	a: string;
	b: string;
	turn: 0 | 1;
	chosen: string | null;
	shows: Record<string, { content: string; finished: boolean }>;
};
let reading: PickRead | null = null;
const readThrough = new Set<string>(); // both sides of a pick read to the end (ids only, in memory)
export const readingNow = () =>
	reading ? { a: reading.a, b: reading.b, turn: reading.turn, chosen: reading.chosen } : null;

function begin(id: string, content: string, finished: boolean, lead = '', pick: PickRead | null = null) {
	const w: Writing = {
		id,
		feed: null,
		opening: false,
		sent: 0,
		done: false,
		content,
		finished,
		chain: Promise.resolve(),
		timer: null,
		lead,
		pick,
		chat: replyOf(id)?.meta?.()?.chat_id ?? null,
		eager: false,
		stream: null,
		both: false,
		lounge: false
	};
	writing = w;
	handled.add(id);
	return w;
}
export const writingNow = () =>
	writing ? { id: writing.id, sent: writing.sent, done: writing.done, open: !!writing.feed, both: writing.both } : null;

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
		if (streamed.has(id)) return finished && content.trim() ? streamWhole(id) : undefined; // 🌊 A41 · she spoke on her own
		if (!born.has(id) && !(parentId && asked.has(parentId)) && !(later.size && parentId && claim(parentId, parentText?.())))
			return; // the cheapest question first: most replies on a page were never asked here
		const pair = replyOf(id)?.pair?.();
		if (pair) return pickGrew(id, content, finished, parentId, pair); // 🍒 A38 · an open pick reads both in turn
		if (finished && content.trim() && !born.has(id)) return lateWhole(id, parentId);
		if (finished || !content.trim()) return; // a reply that arrives whole is for after-she-finishes
		if (effectiveMode() !== 'writing' || !mayAuto(id, parentId) || handled.has(id) || !ttsReady() || !petalStreamEnabled())
			return;
		const r = replyOf(id);
		if (!r || r.pick?.()) return; // 🍒 a pick waits for her choice
		if (get(voiceUI).state !== 'idle' && !mayTakeOver()) return why('writing waits: she listens', id); // she's listening to something she chose
		why('writing begins', id);
		takeOver();
		w = begin(id, content, finished);
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
		// her cue opens the turn as soon as its reply shows its first words (a picture alone included)
		if (!ready.length && !w.eager && !(w.lead && (w.content.trim() || w.finished))) {
			if (w.finished) {
				letGo(w, false); // nothing she'd say aloud
				if (w.pick && reading === w.pick) nextTurn(w.pick); // a reply with nothing to say never holds the other
			}
			return;
		}
		void open(w, ready);
		return;
	}
	// 🧵 A45 · open: the rig follows the reply itself and feeds her voice (a sleeping page starves nothing, and a
	// page that wakes never says a sentence twice). the page only keeps count of what it has seen
	w.sent = ready.length;
	w.done = w.finished;
}

/** 🧵 A45 · the replies the rig follows for this stream: this one (its cue first), and for 🍒 a pick's first turn the
 *  other side after it, with its own cue (after-she-finishes: it waits until that side is written) */
function segmentsOf(w: Writing): FollowSegment[] {
	const first: FollowSegment = { message_id: w.id, chat_id: w.chat, lead: w.lead };
	if (w.finished) Object.assign(first, { text: w.content, finished: true });
	const segs = [first];
	const p = w.pick;
	if (p && reading === p && p.turn === 0 && !p.chosen && w.id === p.a) {
		segs.push({
			message_id: p.b,
			chat_id: w.chat,
			lead: cuesOf(get(settings)).two,
			whole: effectiveMode() === 'finished'
		});
		w.both = true;
	}
	return segs;
}

async function open(w: Writing, ready: ReturnType<typeof wholeParts>) {
	const r = replyOf(w.id);
	if (!r) return letGo(w, false);
	w.opening = true;
	w.sent = ready.length;
	const m = r.meta?.() ?? {};
	let superseded = false; // 🧵 A46 · her voice went to a newer ask while this one opened (she chose it)
	const opened = await playPetalStream({
		token: read('token') ?? '',
		voice: r.voice() ?? '',
		revoice: () => replyOf(w.id)?.voice() ?? r.voice() ?? '', // 🧵 A46 · a voice she picks while she speaks
		parts: [], // 🧵 A45 · the rig gives every sentence, her cue first, as it follows the reply
		follow: segmentsOf(w),
		meta: { chat_id: m.chat_id, message_id: w.id, model: m.model, source: w.content },
		title: m.title,
		artwork: m.artwork,
		playbackRate: m.playbackRate,
		growing: true,
		onFeed: (f) => {
			w.feed = f;
		},
		onSuperseded: () => {
			superseded = true;
		},
		onError: () => {
			// the stream broke before her first sound: after-she-finishes may still play it
			if (writing === w) letGo(w, false);
			handled.delete(w.id);
			if (w.pick && reading === w.pick) reading = null; // 🍒 a broken voice reads no further
			else if (w.finished && !w.pick) playReply(w.id); // 🧵 A45 · a whole reply still gets its sentence clips
		}
	});
	w.opening = false;
	if (superseded) {
		// 🧵 A46 · another way in took her voice while this opened: it never speaks on, nor replays later by itself
		why('superseded while opening', w.id);
		if (writing === w) letGo(w, true);
		if (w.pick && reading === w.pick) reading = null;
		return;
	}
	if (writing !== w) {
		// a new send (or her stop) let go of it while it opened: the stream it opened doesn't speak on
		const v = get(voiceNow);
		if (opened && v.state !== 'idle' && v.message_id === w.id) stopPetalStream();
		return;
	}
	if (!opened || !w.feed) {
		letGo(w, false);
		handled.delete(w.id); // never opened: after-she-finishes gets its chance
		if (w.pick && reading === w.pick) reading = null;
		if (w.lounge) playReply(w.id); // 🌊 her own words have no after-she-finishes: the clips, as before A45
		return;
	}
	w.stream = get(voiceNow).id;
	markHeard(w.id); // 🧵 A45 · 🍒 the other side is marked heard only once her voice reaches it (voiceNow, below)
	flush(w); // what was written while it opened (the rig has it already: this only keeps count)
}

function letGo(w: Writing, keepHandled: boolean) {
	why(keepHandled ? 'let go (kept)' : 'let go', w.id);
	if (w.timer) clearTimeout(w.timer);
	w.timer = null;
	if (!keepHandled) handled.delete(w.id);
	if (writing === w) writing = null;
}

// ── 🍒 A38 · a pick, read aloud ─────────────────────────────────────────────────────────────────────────────
const turnOf = (p: PickRead) => (p.turn ? p.b : p.a);

function pickGrew(id: string, content: string, finished: boolean, parentId: string | null | undefined, [a, b]: [string, string]) {
	if (!reading || reading.a !== a) {
		if (readThrough.has(a)) return;
		if (effectiveMode() === 'off' || !ttsReady() || !petalStreamEnabled()) return;
		if (!mayAuto(a, parentId) || handled.has(a) || handled.has(b)) return; // heard, or taken, already
		if ((get(voiceUI).state !== 'idle' || writing) && !mayTakeOver()) return why('pick waits: she listens', a); // she chose something to hear
		takeOver();
		reading = { a, b, turn: 0, chosen: null, shows: {} };
		why('pick read begins', a);
	}
	reading.shows[id] = { content, finished };
	pickTurn(reading);
}

/** the turn's reply begins once it shows its first words (after she finishes: once it's written); the other waits */
function pickTurn(p: PickRead) {
	if (reading !== p || p.chosen) return;
	const id = turnOf(p);
	if (writing) return; // a turn is open (its words reach it through grew), or a turn just ended
	if (get(voiceUI).state !== 'idle') return;
	const got = p.shows[id];
	if (!got) return;
	if (!replyOf(id)?.pair?.()) return void (reading = null); // the pick closed or dissolved: no other turn
	const mode = effectiveMode();
	if (mode === 'off') return void (reading = null);
	if (mode === 'finished' && !got.finished) return;
	if (!got.content.trim() && !got.finished) return;
	const cues = cuesOf(get(settings));
	why(p.turn ? 'pick turn two' : 'pick turn one', id);
	flush(begin(id, got.content, got.finished, p.turn ? cues.two : cues.one, p));
}

/** a turn ended by itself (her voice reached its end): the other's turn, unless her 💗 already chose */
function nextTurn(p: PickRead) {
	if (reading !== p) return;
	if (p.chosen || p.turn === 1) {
		if (!p.chosen) {
			readThrough.add(p.a);
			readThrough.add(p.b);
		}
		why(p.chosen ? 'pick read ends with her choice' : 'pick read through', p.a);
		reading = null;
		return;
	}
	p.turn = 1;
	pickTurn(p); // and again once the page's voice says idle (its stores settle one after the other)
}

/** her 💗 (Chat, the moment she picks): did her voice take care of it? (after-she-finishes plays it when not)
 *  · the one she's hearing (its cue included): nothing changes · the other speaking, opening or waiting: it stops
 *    at once and the chosen one plays from its start · both read through already: nothing replays */
export function picked(id: string): boolean {
	const p = reading;
	if (p && (id === p.a || id === p.b)) {
		const ui = get(voiceUI);
		const hearing = writing?.pick === p ? (hearingReply() ?? writing.id) : ui.state !== 'idle' ? ui.message_id : null;
		if (hearing === id) {
			p.chosen = id;
			handled.add(id);
			// 🧵 A45 · one stream reads both sides: the rig reads nothing after the one she chose
			if (writing?.both && writing.feed) void cutPetalStream(read('token') ?? '', writing.feed, id);
			why('picked the one she hears', id);
			return true;
		}
		reading = null;
		if (writing) letGo(writing, true);
		if (ui.state !== 'idle') stopAllVoice();
		const content = replyOf(id)?.content() ?? p.shows[id]?.content ?? '';
		why('picked the other: from its start', id);
		markHeard(id);
		flush(begin(id, content, true));
		return true;
	}
	if (readThrough.has(id)) {
		handled.add(id);
		why('picked after both were read: nothing replays', id);
		return true;
	}
	return false;
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
	return true;
}

// ── 🌊 A41 · her stream: words she wrote on her own, in a chat opened to it (utils/petal-lounge.ts) ──────────────
/** a profile's voice: on (spoken when her autoplay is on) · off (text only) · always (spoken even when autoplay is
 *  off; the phone still waits for earphones, the way autoplay does) */
export type StreamVoice = 'on' | 'off' | 'always';
const streamed = new Map<string, StreamVoice>(); // her stream's words landed on this page, waiting to show (ids only)
/** the page that asked tells each landing: her voice reads it once it shows (grew) */
export function streamArrived(id: string, voice: StreamVoice) {
	if (voice === 'off') return why('stream: text only', id);
	streamed.set(id, voice);
	if (streamed.size > 50) streamed.delete(streamed.keys().next().value as string);
	why('stream arrived', id);
	const r = replyOf(id);
	if (r?.done() && r.content().trim()) streamWhole(id); // already showing
}
/** her autoplay's say for a stream message (pure: the tests read it) */
export function streamMay(voice: StreamVoice, mode: AutoMode, phoneGate: AutoMode): boolean {
	if (voice === 'off') return false;
	return voice === 'always' ? phoneGate !== 'off' : mode !== 'off';
}
// 🌊 🧵 A46 · her stream's words that land while her earlier ones still speak wait their turn, read in order (Petal
// Radio's spine: a long spiral of answers, hands-free) · her ⏹, a send, another voice or a break lets them go
const lounged: { id: string; voice: StreamVoice }[] = [];
function nextLounge() {
	const n = lounged.shift();
	if (!n) return;
	streamed.set(n.id, n.voice);
	why('stream: her next words, in order', n.id);
	streamWhole(n.id);
}
function streamWhole(id: string) {
	const voice = streamed.get(id);
	if (!voice) return;
	streamed.delete(id);
	if (heard.includes(id)) return why('stream: heard already', id);
	const gate = decide('finished', isPhone(), get(earphones), get(followRoute), get(audioRoute));
	if (!streamMay(voice, effectiveMode(), gate))
		return why(voice === 'always' ? 'stream stays: no earphones here' : 'stream stays: autoplay is off', id);
	if (!ttsReady() || !petalStreamEnabled()) return why('stream stays: no voice here', id);
	if (get(voiceUI).state !== 'idle' && writing?.lounge && writing.id !== id && !lounged.some((x) => x.id === id)) {
		lounged.push({ id, voice });
		if (lounged.length > 20) lounged.shift();
		return why('stream waits its turn after her words', id);
	}
	if (get(voiceUI).state !== 'idle' && !mayTakeOver()) return why('stream waits: she listens', id); // her tap keeps it
	why('stream speaks', id);
	takeOver();
	markHeard(id);
	handled.add(id);
	// 🧵 A45 · the same path as her replies: one stream the rig carries (here already whole)
	const r = replyOf(id);
	if (!r) return;
	if (writing) letGo(writing, true);
	const w = begin(id, r.content() ?? '', true);
	w.lounge = true;
	flush(w);
}

/** 🔈 A40 · the voice a send in another chat may hand over to that send's reply (null: none) */
let yieldTo: string | null = null;
const mayTakeOver = () => {
	const ui = get(voiceUI);
	return !!yieldTo && ui.state !== 'idle' && ui.message_id === yieldTo;
};
/** her new reply speaks: the voice it was handed (another chat's) stops, whatever kind it was */
function takeOver() {
	if (!mayTakeOver()) return;
	why('her new reply takes the voice over', yieldTo);
	yieldTo = null;
	if (writing) letGo(writing, true);
	stopAllVoice();
}

/** a new send of hers (Chat, with the chat it's sent in): the voice speaking for that chat stops, and her tap
 *  lets the next reply play · 🔈 A40 · a voice speaking for another chat plays on, until this send's reply speaks */
export function newSend(chatId?: string | null) {
	unlockPetalStream();
	const ui = get(voiceUI);
	const v = get(voiceNow);
	const theirs = ui.state !== 'idle' && v.state !== 'idle' && v.chat_id ? v.chat_id : null; // the chat it speaks for
	if (theirs && theirs !== (chatId ?? '')) {
		yieldTo = ui.message_id;
		why('new send in another chat: she plays on', ui.message_id);
		return;
	}
	why('new send');
	yieldTo = null;
	reading = null;
	lounged.length = 0;
	if (writing) letGo(writing, true);
	if (ui.state !== 'idle') stopAllVoice();
}

/** 🔈 A40 · the play button on a reply still being written: her voice joins it from its first sentence and follows
 *  the typing (one growing stream, fed by grew) · false: not hers to take (finished, gone, or one of an open pick:
 *  A38's rules) */
export function playLive(id: string): boolean {
	const r = replyOf(id);
	if (!r || r.done() || r.pair?.() || !ttsReady() || !petalStreamEnabled()) return false;
	if (writing?.id === id && get(voiceUI).state !== 'idle') return true; // she's already speaking it
	why('her tap joins it as it is written', id);
	yieldTo = null;
	reading = null;
	if (writing) letGo(writing, true);
	if (get(voiceUI).state !== 'idle') stopAllVoice();
	handled.delete(id);
	const w = begin(id, r.content() ?? '', false);
	w.eager = true;
	markHeard(id);
	flush(w);
	return true;
}

// ── one voice across her tabs ───────────────────────────────────────────────────────────────────────────
const TAB = Math.random().toString(36).slice(2, 10);
let bc: BroadcastChannel | null = null;

// ── installed once by the page ──────────────────────────────────────────────────────────────────────────
let installed = false;
export function installAutoplay() {
	if (installed || typeof window === 'undefined') return;
	installed = true;
	setLivePlayer(playLive); // 🔈 A40 · the play button joins a reply still being written
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
		// 🧵 A45 · 🍒 one stream reads both sides: the other side is heard once the player reaches it, never before
		// (stopped before it, her 💗 on it still plays it after she finishes)
		const both = writing?.both && writing.pick && writing.stream && v.id === writing.stream ? writing.pick : null;
		if (both && v.message_id === both.b) markHeard(both.b);
		// 🧵 A46 · another way in took her voice from a stream: its end, said without any idle between the two
		if (v.replaced) voiceEnded(v.replaced);
		if (v.state !== 'idle') return;
		voiceEnded(v);
	});
	/** a stream ended (played out, stopped, broken, or another ask took her voice): the writing voice lets go of it */
	function voiceEnded(v: { message_id: string | null; id: string | null; ended: string | null }) {
		// she ended (played out, stopped, broken): the writing voice lets go of it
		const ended =
			writing &&
			(!v.message_id || v.message_id === writing.id || (!!writing.stream && v.id === writing.stream)) &&
			(writing.feed || !writing.opening)
				? writing
				: null;
		if (ended) letGo(ended, true);
		// 🧵 A45 · 🍒 one stream read both sides: its end is the reading's end, whatever ended it
		if (ended?.both && ended.pick && reading === ended.pick) {
			if (v.ended === 'natural' && !reading.chosen) {
				readThrough.add(reading.a);
				readThrough.add(reading.b);
			}
			why(v.ended === 'natural' ? 'pick read through (one stream)' : 'pick read stops', reading.a);
			reading = null;
		}
		// 🍒 A38 · a pick's turn: reached its end → the other's turn · stopped, faded, broken → the reading ends
		if (reading && v.message_id === turnOf(reading) && (!ended || ended.pick === reading)) {
			if (v.ended === 'natural') nextTurn(reading);
			else {
				why('pick read stops', reading.a);
				reading = null;
			}
		}
		if (v.message_id === yieldTo) yieldTo = null; // the voice she might have handed over has ended
		if (ended?.lounge && v.ended === 'natural') nextLounge(); // 🌊 her stream's next words, in order
		else if (v.ended !== 'natural') lounged.length = 0; // stopped, broken, taken over: the queue lets go
	}
	voiceUI.subscribe((ui) => {
		if (ui.state === 'idle' && reading && !writing) pickTurn(reading); // 🍒 the next turn, once she's quiet
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
				pick: readingNow(),
				voice: get(voiceUI), // ids and states only
				stream: get(voiceNow), // 🧵 A45 · the stream's ticket, its reply and why it last ended (ids only)
				volume: petalStreamAudio()?.volume ?? null
			};
		},
		get why() {
			return [...trail];
		}
	};
}
