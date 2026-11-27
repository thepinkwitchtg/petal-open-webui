// 🎧 her playback (slice A48) · the one thread's <audio> keeps a ring of the last ~90 s of what it played, and a
// timeline of how (play · pause · seek · rate · stall · a new source · the sentence sounding · a skip), so a 🚩 carries
// what she heard, not only what the rig made. memory only: nothing is kept, sent or written until she flags; a flag
// hands the ring (as wav) and its timeline to the rig, which keeps them with the incident (V3's clip door).
//  · what she heard: the element's own output, captured where it leaves the page's player (captureStream → a 24 kHz
//    AudioContext → an AudioWorklet ring), never the microphone, never re-routed (the element plays exactly as before;
//    the capture only listens beside it)
//  · only while she plays: the ring records from her first sound to a pause, an end or a new source; paused time is
//    not in it. the context sleeps 3 s after she stops (no audio thread at rest)
//  · the timeline is numbers and ids (her clock, the reply's id, the sentence's place, causes): never a word of hers
//  · where capture can't be (a browser without captureStream, the browser's own voice), the ring says so and a flag
//    carries the thread alone, as before. off switch: localStorage.petalRing = 'off'
//  · her console and the tests: window.petalRing.state() (numbers only)

export const RING_S = 90; // seconds of her playback a 🚩 carries, at most
export const RING_RATE = 24000; // her voice's own rate: nothing is lost going down to it
const SLEEP_MS = 3000; // the capture's context sleeps this long after she stops
const EVENTS_KEPT = 400;

export type RingEvent = {
	at: number; // when (ms since 1970)
	played_s: number; // her played time when it happened (the ring's own clock)
	what: string; // playing · pause · seeking · seeked · rate · waiting · ended · src · part · skip · step · flag · capture
	t?: number | null; // her player's clock then (audio.currentTime)
	from?: number | null; // where a seek began
	rate?: number;
	cause?: string;
	kind?: string | null;
	message_id?: string | null;
	idx?: number | null;
	seq?: number | null;
	floor?: string | null;
};
export type RingContext = {
	seq?: number | null;
	kind?: string | null;
	message_id?: string | null;
	idx?: number | null;
	floor?: string | null;
};
export type RingTimeline = {
	v: 1;
	kind: 'petal-playback';
	rate: number;
	clip_s: number;
	ring_s: number;
	began_at: number | null; // ms since 1970 of the clip's first sample (near enough: her played time is wall time)
	flagged_at: number;
	capture: string;
	events: (Omit<RingEvent, 'played_s'> & { clip_s: number })[];
	pauses: number;
	seeks: number;
	stalls: number;
};
export type RingSnap = { wav: Blob; timeline: RingTimeline; seconds: number };

type Cap = 'off' | 'idle' | 'starting' | 'on' | 'unavailable' | 'refused';

let tapped: HTMLMediaElement | null = null;
let cap: Cap = 'off';
let why: string | null = null; // why capture can't be (numbers-only words)
let ctx: AudioContext | null = null;
let node: AudioWorkletNode | null = null;
let source: MediaStreamAudioSourceNode | null = null;
let stream: MediaStream | null = null;
let track: MediaStreamTrack | null = null;
let starting: Promise<void> | null = null;
let fresh = true; // a new source since the ear last listened: listen to its own track
let rec = false;
let playedMs = 0; // her played time so far (while the ring records)
let since: number | null = null; // performance.now() since she plays
let sleepTimer: ReturnType<typeof setTimeout> | null = null;
let context: RingContext = {};
const events: RingEvent[] = [];
let snapN = 0;
const waiting = new Map<number, (d: { pcm: ArrayBuffer; total: number; rate: number } | null) => void>();
let rate = RING_RATE;

export const ringEnabled = () => {
	try {
		return localStorage.getItem('petalRing') !== 'off';
	} catch {
		return true;
	}
};

const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());
const played = () => (playedMs + (since !== null ? now() - since : 0)) / 1000;
const round3 = (x: number) => Math.round(x * 1000) / 1000;

function push(e: Omit<RingEvent, 'at' | 'played_s'>, at = Date.now()) {
	events.push({ at, played_s: round3(played()), ...e });
	// what the ring no longer holds is let go (one event before it stays: the state the clip opens in)
	const edge = played() - RING_S - 5;
	let drop = 0;
	while (drop < events.length - 1 && events[drop + 1].played_s < edge) drop++;
	if (events.length - drop > EVENTS_KEPT) drop = events.length - EVENTS_KEPT;
	if (drop > 0) events.splice(0, drop);
}

const where = (): Pick<RingEvent, 't' | 'kind' | 'message_id' | 'idx' | 'seq' | 'floor'> => ({
	t: tapped ? round3(tapped.currentTime || 0) : null,
	kind: context.kind ?? null,
	message_id: context.message_id ?? null,
	idx: context.idx ?? null,
	seq: context.seq ?? null,
	...(context.floor ? { floor: context.floor } : {})
});

/** the thread says what is sounding (ids and numbers only): each event carries it */
export function ringContext(c: RingContext) {
	const was = context;
	context = { ...context, ...c };
	if (rec && c.idx !== undefined && c.idx !== was.idx && c.idx !== null) push({ what: 'part', ...where() });
}

/** the thread's own moments (a skip, a transition, a flag): kept on the timeline beside the player's */
export function ringNote(what: string, extra: Partial<RingEvent> = {}) {
	if (!tapped) return;
	push({ what, ...where(), ...extra });
}

function recording(on: boolean) {
	if (on === rec) return;
	rec = on;
	if (on) since = now();
	else if (since !== null) {
		playedMs += now() - since;
		since = null;
	}
	try {
		node?.port.postMessage({ rec: on });
	} catch {}
	if (sleepTimer) clearTimeout(sleepTimer);
	sleepTimer = null;
	if (on) void wake();
	else
		sleepTimer = setTimeout(() => {
			sleepTimer = null;
			if (!rec && ctx && ctx.state === 'running') ctx.suspend().catch(() => {});
		}, SLEEP_MS);
}

async function wake() {
	if (!ringEnabled() || cap === 'unavailable' || cap === 'refused') return;
	if (!ctx) await start();
	const awake = (c: AudioContext) => (c.state as string) === 'running'; // read fresh (it moves under an await)
	if (ctx && !awake(ctx)) {
		try {
			await ctx.resume();
		} catch {}
		if (!awake(ctx)) ringNote('capture', { cause: 'the page could not wake its ear (no tap yet?)' });
	}
	listenTo(); // a new source brings a new track: the ear follows it
}

function start(): Promise<void> {
	if (starting) return starting;
	starting = (async () => {
		const el = tapped as (HTMLMediaElement & { captureStream?: () => MediaStream }) | null;
		if (!el || typeof el.captureStream !== 'function' || typeof AudioContext === 'undefined') {
			cap = 'unavailable';
			why = !el ? 'no player' : typeof AudioContext === 'undefined' ? 'no web audio' : 'no captureStream in this browser';
			return;
		}
		cap = 'starting';
		try {
			try {
				ctx = new AudioContext({ sampleRate: RING_RATE });
			} catch {
				ctx = new AudioContext(); // this browser keeps its own rate: the wav says which
			}
			rate = ctx.sampleRate;
			if (!ctx.audioWorklet) throw new Error('no audio worklet');
			await ctx.audioWorklet.addModule(new URL('./petal-ring-worklet.js', import.meta.url));
			node = new AudioWorkletNode(ctx, 'petal-ring', {
				numberOfInputs: 1,
				numberOfOutputs: 1,
				outputChannelCount: [1],
				processorOptions: { seconds: RING_S }
			});
			node.port.onmessage = (e) => {
				const d = e.data || {};
				const done = waiting.get(d.snap);
				if (done) {
					waiting.delete(d.snap);
					done({ pcm: d.pcm, total: d.total, rate: d.rate });
				}
			};
			// pulled by the graph, heard by no one (a silent gain): the element's own sound is never touched
			const hush = ctx.createGain();
			hush.gain.value = 0;
			node.connect(hush).connect(ctx.destination);
			node.port.postMessage({ rec });
			cap = 'on';
			why = null;
			ringNote('capture', { cause: `captureStream · ${rate} Hz · mono` });
		} catch (e) {
			cap = 'refused';
			why = String((e as Error)?.message ?? e).slice(0, 120);
			try {
				await ctx?.close();
			} catch {}
			ctx = null;
			node = null;
		}
	})();
	return starting;
}

/** the ear follows the player's sound: each new source is captured afresh (a captured stream keeps the track of the
 *  source it was made on, silent once the player moves on), and its first audio track feeds the ring */
function listenTo() {
	const el = tapped as (HTMLMediaElement & { captureStream?: () => MediaStream }) | null;
	if (!ctx || !node || !el || typeof el.captureStream !== 'function') return;
	if (fresh || !stream) {
		fresh = false;
		for (const t of stream?.getTracks() ?? []) t.stop(); // the old capture lets go (the player is untouched)
		stream = el.captureStream();
		const s = stream;
		s.addEventListener('addtrack', (e) => {
			if (s === stream && e.track.kind === 'audio') connect(e.track);
		});
	}
	const live = stream.getAudioTracks().filter((t) => t.readyState === 'live');
	if (live.length) connect(live[live.length - 1]);
}
function connect(t: MediaStreamTrack) {
	if (!ctx || !node || t === track) return;
	try {
		source?.disconnect();
	} catch {}
	track = t;
	source = new MediaStreamAudioSourceNode(ctx, { mediaStream: new MediaStream([t]) });
	source.connect(node);
}

/** the one thread's <audio>: the ring listens beside it (called once, when the element is made) */
export function ringTap(el: HTMLMediaElement) {
	if (tapped === el) return;
	tapped = el;
	cap = 'idle';
	el.addEventListener('playing', () => {
		recording(true);
		push({ what: 'playing', ...where(), rate: el.playbackRate });
	});
	el.addEventListener('pause', () => {
		if (el.ended) return;
		push({ what: 'pause', ...where() });
		recording(false);
	});
	el.addEventListener('ended', () => {
		push({ what: 'ended', ...where() });
		recording(false);
	});
	el.addEventListener('emptied', () => {
		fresh = true;
		if (rec) push({ what: 'src', ...where(), cause: 'the player let go of its source' });
		recording(false);
	});
	el.addEventListener('loadstart', () => {
		fresh = true;
		if (el.currentSrc || el.src) push({ what: 'src', ...where(), cause: 'a new source' });
	});
	el.addEventListener('seeking', () => push({ what: 'seeking', ...where() }));
	el.addEventListener('seeked', () => push({ what: 'seeked', ...where() }));
	el.addEventListener('ratechange', () => push({ what: 'rate', ...where(), rate: el.playbackRate }));
	el.addEventListener('waiting', () => {
		if (rec) push({ what: 'waiting', ...where(), cause: 'her player ran dry (silence while it waits)' });
	});
	exposeConsole();
}

function wav(pcm: Int16Array, sampleRate: number): Blob {
	const head = new ArrayBuffer(44);
	const v = new DataView(head);
	const s = (o: number, t: string) => [...t].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
	const bytes = pcm.length * 2;
	s(0, 'RIFF');
	v.setUint32(4, 36 + bytes, true);
	s(8, 'WAVE');
	s(12, 'fmt ');
	v.setUint32(16, 16, true);
	v.setUint16(20, 1, true); // pcm
	v.setUint16(22, 1, true); // mono
	v.setUint32(24, sampleRate, true);
	v.setUint32(28, sampleRate * 2, true);
	v.setUint16(32, 2, true);
	v.setUint16(34, 16, true);
	s(36, 'data');
	v.setUint32(40, bytes, true);
	return new Blob([head, pcm.buffer as ArrayBuffer], { type: 'audio/wav' });
}
export const wavOf = wav; // for the tests

/** the timeline as the clip holds it: each moment placed on the clip's own seconds (what fell before it is let go,
 *  except the last moment before it, which says how the clip opens) */
export function timelineOf(list: RingEvent[], playedNow: number, clipS: number, flaggedAt: number, how: string): RingTimeline {
	const start = playedNow - clipS;
	let opener = -1;
	for (let i = 0; i < list.length; i++) if (list[i].played_s <= start) opener = i;
	const kept = list.filter((e, i) => i >= Math.max(0, opener));
	const out = kept.map(({ played_s, ...e }) => ({ ...e, clip_s: round3(Math.max(0, played_s - start)) }));
	// her played time is wall time while she plays: the moment the clip opens is the opener's, moved on by the played
	// seconds between them
	const began = opener >= 0 ? Math.round(list[opener].at + (start - list[opener].played_s) * 1000) : null;
	return {
		v: 1,
		kind: 'petal-playback',
		rate,
		clip_s: round3(clipS),
		ring_s: RING_S,
		began_at: began,
		flagged_at: flaggedAt,
		capture: how,
		events: out,
		pauses: out.filter((e) => e.what === 'pause').length,
		seeks: out.filter((e) => e.what === 'seeked').length,
		stalls: out.filter((e) => e.what === 'waiting').length
	};
}

/** a 🚩: the ring as it is right now (oldest first) + its timeline · null when there is nothing to carry */
export async function ringSnapshot(cause = 'her 🚩'): Promise<RingSnap | null> {
	if (!tapped || !node || cap !== 'on') return null;
	ringNote('flag', { cause });
	const id = ++snapN;
	const got = await new Promise<{ pcm: ArrayBuffer; total: number; rate: number } | null>((resolve) => {
		waiting.set(id, resolve);
		try {
			node!.port.postMessage({ snap: id });
		} catch {
			waiting.delete(id);
			resolve(null);
		}
		setTimeout(() => {
			if (waiting.delete(id)) resolve(null);
		}, 2000);
	});
	if (!got || !got.pcm.byteLength) return null;
	const pcm = new Int16Array(got.pcm);
	const seconds = pcm.length / got.rate;
	const timeline = timelineOf(events, played(), seconds, Date.now(), `captureStream · ${got.rate} Hz · mono`);
	return { wav: wav(pcm, got.rate), timeline, seconds: round3(seconds) };
}

/** numbers only: is the ear on, how much it holds, what it saw */
export function ringState() {
	return {
		capture: cap,
		why,
		recording: rec,
		played_s: round3(played()),
		holds_s: round3(Math.min(RING_S, played())),
		events: events.length,
		context: ctx?.state ?? null,
		rate: ctx ? rate : null,
		enabled: ringEnabled()
	};
}

function exposeConsole() {
	if (typeof window === 'undefined') return;
	(window as any).petalRing = { state: ringState, snapshot: ringSnapshot };
}

exposeConsole(); // her console can ask from the start (capture 'off' until her voice first plays)

/** the tests' hand: everything back to nothing */
export function ringReset() {
	events.splice(0, events.length);
	playedMs = 0;
	since = null;
	rec = false;
	context = {};
}
