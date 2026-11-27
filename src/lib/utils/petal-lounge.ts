// 🌊 Petal Stream (slice A41) · the lounge, on the page. the rig keeps her profiles, her rhythm and which chats are
// open to it (routers/petal_lounge.py); the page knows what the rig can't see: whether she's typing, whether a
// reply runs or a pick waits, whether her voice is playing, which page she's looking at. each Chat watches its own
// chat: one timer, to the moment her rhythm says, and then one ask, unless something holds it back. the rig checks
// everything again before a word is written.
//  · per chat: off by default · a profile chosen in the 💗 turns it on for that chat only (the heart's dot says
//    so) · off in the 💗, or Esc · A42: no chip, no demos; the sheet says why (the rig unreachable, the status of
//    this chat's stream), she stops trying after three model errors in a row, and her md's edits land within 20 s
//  · holds (the page's): a reply running or owed · a pick still open · her voice playing (any chat) · a voice call ·
//    her typing, while the profile says wait (until a few seconds after her last key)
//  · the lead: the last page she looked at speaks · a visible page claims it with every call; a hidden page that
//    lost it waits until she looks at it again (so the PC in the other room never speaks for the phone in her hand)
//  · a stream message lands through its Chat (a temporary chat's lives on the page only); her voice reads it when
//    the profile and her autoplay agree (petal-autoplay · streamArrived)
//  · nothing runs at rest: no timer while no chat is open to her stream; a held turn looks again every 1.5 s;
//    the 20 s look (her md's mtime) exists only while the page is visible and a stream is on or the sheet is open
import { get, writable } from 'svelte/store';

import { WEBUI_API_BASE_URL } from '$lib/constants';
import { streamArrived } from '$lib/utils/petal-autoplay';
import { stopAllVoice, voiceUI } from '$lib/utils/petal-voice';

export type LoungeVoice = 'on' | 'off' | 'always';
export type LoungeTyping = { mode: 'wait' | 'speak'; rest_s: number };
export type LoungeProfile = {
	name: string;
	title: string;
	emoji: string;
	ok: boolean;
	mean_min?: number;
	spread?: number;
	length?: [number, number] | null; // a hint in the floor note (A43), null when unset
	quiet?: string;
	voice?: LoungeVoice;
	typing?: LoungeTyping;
	words?: number;
	ignored?: string[]; // knobs she wrote that are read no more (A43: place · turns)
	problems?: string[];
};
export type LoungeShelf = { profiles: LoungeProfile[]; asleep: number; folder: string };
export type LoungeState = {
	chat_id: string;
	on: boolean;
	lead?: boolean;
	profile?: string;
	title?: string;
	emoji?: string;
	voice?: LoungeVoice;
	typing?: LoungeTyping;
	spoke?: number;
	passed?: number;
	problems?: string[];
	ignored?: string[];
	n?: number;
	fp?: string;
	quiet_until?: number | null;
	due_at?: number | null;
	gap?: number;
	waiting?: string;
	gone?: string;
	asleep?: string;
	mtime?: number | null;
	stopped?: { errors: number; why: string } | null;
	errors?: number;
};
/** one line for the sheet, while a stream is on: what she is doing, or why not */
export type LoungeStatus = {
	kind: 'next' | 'held' | 'writing' | 'resting' | 'waiting' | 'quiet' | 'refused' | 'stopped' | 'lead';
	why?: string;
	at?: number; // seconds: the due moment (next) or the quiet's end (quiet)
	last?: LoungeLast | null; // what her last ask came to (A43), until the chat moves on
};
/** her last ask, told on the line: she spoke, or let it pass · and how many old turns her window left out */
export type LoungeLast = { kind: 'spoke' | 'passed'; left: number };
/** the turn a normal send of this chat would carry from the page (A43): her filters, the page's variables, her
 * mode · a temporary chat's system prompt and params too (its page holds them) */
export type LoungeTurn = {
	filter_ids?: string[];
	variables?: Record<string, unknown>;
	mode?: string | null;
	system?: string;
	params?: Record<string, unknown>;
};
/** "spoke · 12 old turns left out" · "she let it pass" (words only; the sheet adds the next moment) */
export function lastOf(last: LoungeLast | null | undefined): string {
	if (!last) return '';
	const head = last.kind === 'spoke' ? 'spoke' : 'she let it pass';
	return last.left > 0 ? `${head} · ${last.left} old turn${last.left === 1 ? '' : 's'} left out` : head;
}
/** the model's refusal, in her words: "the model refused · 400 · <reason>" */
export function refusedOf(why: string | undefined): string {
	const m = /^the model answered (\d+)(?: · (.*))?$/s.exec(why ?? '');
	return m ? ['the model refused', m[1], m[2]].filter(Boolean).join(' · ') : `the model refused · ${why ?? ''}`.trim();
}
type Msg = {
	id: string;
	parentId?: string | null;
	childrenIds?: string[];
	role?: string;
	content?: unknown;
	done?: boolean;
	timestamp?: number;
	petal_stream?: unknown;
	[k: string]: unknown;
};
type History = { messages: Record<string, Msg>; currentId: string | null };
export type LoungeHost = {
	chatId: () => string | null;
	history: () => History;
	busy: () => string | null; // why a turn is held by the chat (a reply runs, a pick waits, a call): null when free
	model: () => string | null;
	shown: () => boolean; // this chat is on screen (the tab she's on)
	land: (message: Msg, parentId: string) => boolean; // her words, into the chat's history
	turn?: () => LoungeTurn; // A43 · what a normal send would carry (filters, variables, mode…)
};

const HOLD_MS = 1500;
const BUSY_MS = 3000;
const LEAD_MS = 60000;
const FAR_MS = 5 * 60000; // a far turn is looked at again before then (a sleeping laptop, a moved clock)
const TYPING_NOW_MS = 6000; // {{typing}}: a key within this long

export const PAGE = (() => {
	try {
		return crypto.randomUUID().replace(/-/g, '').slice(0, 16);
	} catch {
		return Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
	}
})();

/** the chats open to her stream on this page (on ones only), for the 💗 row and the 🌊 chip */
export const loungeOn = writable<Record<string, LoungeState>>({});
/** what her folder holds, read when the 💗 opens its stream view */
export const loungeShelf = writable<LoungeShelf | null>(null);
/** why her folder couldn't be read ("couldn't reach the rig · 404"), null when it was */
export const loungeShelfError = writable<string | null>(null);
/** the chat whose stream sheet is open in the 💗 (its looks keep running while visible) */
export const loungeSheet = writable<string | null>(null);
/** each chat's line, while its stream is on */
export const loungeStatus = writable<Record<string, LoungeStatus>>({});
/** a chat she is writing in right now (between the ask and her words) */
export const loungeWriting = writable<Record<string, boolean>>({});

// her stream's last choices, for a look inside (ids and reasons only, never words)
const trail: string[] = [];
const why = (what: string, id?: string | null) => {
	trail.push(`${Math.round(performance.now())} ${what}${id ? ' ' + id.slice(0, 8) : ''}`);
	if (trail.length > 80) trail.shift();
};

function setStatus(chatId: string, st: LoungeStatus | null) {
	loungeStatus.update((all) => {
		const next = { ...all };
		if (st) next[chatId] = st;
		else delete next[chatId];
		return next;
	});
}

async function call<T>(path: string, body?: unknown): Promise<T> {
	const res = await fetch(`${WEBUI_API_BASE_URL}/petal/stream/${path}`, {
		method: body === undefined ? 'GET' : 'POST',
		headers: {
			Authorization: `Bearer ${typeof localStorage !== 'undefined' ? (localStorage.token ?? '') : ''}`,
			...(body === undefined ? {} : { 'Content-Type': 'application/json' })
		},
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!res.ok) throw new Error(`${res.status}`);
	if (!(res.headers?.get?.('content-type') ?? 'application/json').includes('json')) throw new Error(`${res.status} · not the rig`); // an old backend answers unknown paths with the page
	return res.json();
}

const visible = () => typeof document !== 'undefined' && document.visibilityState === 'visible';

function setOn(chatId: string, st: LoungeState | null) {
	if (!st?.on) setStatus(chatId, null);
	loungeOn.update((all) => {
		const next = { ...all };
		if (st?.on) next[chatId] = st;
		else delete next[chatId];
		return next;
	});
}
function setWriting(chatId: string, on: boolean) {
	loungeWriting.update((all) => {
		const next = { ...all };
		if (on) next[chatId] = true;
		else delete next[chatId];
		return next;
	});
}

/** the decision a held turn makes, pure (the tests read it): null = ask now */
export function holdOf(o: {
	busy: string | null;
	voice: string;
	typing: LoungeTyping | undefined;
	typedAgoMs: number;
	hidden: boolean;
	lostLead: boolean;
}): string | null {
	if (o.busy) return o.busy;
	if (o.voice !== 'idle') return 'her voice plays';
	if (o.typing?.mode === 'wait' && o.typedAgoMs < (o.typing.rest_s ?? 12) * 1000) return 'she types';
	if (o.hidden && o.lostLead) return 'another page leads';
	return null;
}

/** where her rhythm counts from: the leaf's time, or later (when this page saw it finish, or began watching) */
export function anchorOf(leafTs: number | undefined, doneSeenMs: number | undefined, watchedSinceMs: number): number {
	return Math.max(leafTs ?? 0, (doneSeenMs ?? 0) / 1000, watchedSinceMs / 1000);
}

/** how long until the next look: the due moment, or sooner when it's far (FAR_MS), never a busy loop */
export function delayOf(dueAtS: number | null | undefined, nowMs: number): number | null {
	if (dueAtS == null) return null;
	return Math.min(FAR_MS, Math.max(200, dueAtS * 1000 - nowMs));
}

/** the branch, root → leaf (a temporary chat's turns ride in the ask) */
function branchOf(h: History): Msg[] {
	const out: Msg[] = [];
	const seen = new Set<string>();
	let id = h?.currentId ?? null;
	while (id && h.messages[id] && !seen.has(id)) {
		seen.add(id);
		out.push(h.messages[id]);
		id = (h.messages[id].parentId as string | null) ?? null;
	}
	return out.reverse();
}
const textOf = (m: Msg) =>
	typeof m.content === 'string'
		? m.content
		: Array.isArray(m.content)
			? (m.content as { type?: string; text?: string }[]).filter((p) => p?.type === 'text').map((p) => p.text ?? '').join('')
			: '';

class Watcher {
	host: LoungeHost;
	chat: string | null = null;
	state: LoungeState | null = null;
	watchedSince = Date.now();
	leafKey = '';
	doneSeen = new Map<string, number>();
	typedAt = 0;
	prompt: string | null = null; // her words in the input, as last told (null: not told yet)
	timer: ReturnType<typeof setTimeout> | null = null;
	refreshing: Promise<void> | null = null;
	asking = false;
	backoff = 0;
	backoffUntil = 0; // ms: after resting · an error · empty words, no ask before this (the 20 s look never shortens it)
	lostLead = false;
	dropped = false;
	sticky: LoungeStatus | null = null; // resting · refused: kept until her next ask says otherwise
	last: LoungeLast | null = null; // spoke · passed (A43): told on the line until the chat moves on

	constructor(host: LoungeHost) {
		this.host = host;
	}

	leaf() {
		const h = this.host.history();
		const id = h?.currentId;
		const m = id ? h.messages[id] : null;
		if (!id || !m) return null;
		return {
			id,
			at: anchorOf(m.timestamp, this.doneSeen.get(id), this.watchedSince),
			role: m.role ?? null,
			done: m.done !== false
		};
	}

	/** Chat tells each change of its history or her words (cheap: most changes change nothing here) */
	poke(prompt?: string) {
		if (this.dropped) return;
		if (typeof prompt === 'string' && prompt !== this.prompt) {
			// a key of hers: words added, or some taken away (a draft restored on open, or the input emptied by a
			// send, is no key)
			if (this.prompt !== null && prompt.trim() && prompt.length !== this.prompt.length) this.typedAt = Date.now();
			this.prompt = prompt;
		}
		const chat = this.host.chatId();
		if (chat !== this.chat) return this.switchTo(chat);
		if (!chat) return;
		const h = this.host.history();
		const id = h?.currentId ?? '';
		const m = id ? h.messages[id] : null;
		const key = `${id}:${m?.role ?? ''}:${m?.done !== false}`;
		if (key === this.leafKey) return;
		const was = this.leafKey;
		this.leafKey = key;
		this.last = null; // the chat moved on: what her last ask came to is no news any more
		if (m && m.role === 'assistant' && m.done !== false && was.startsWith(`${id}:`)) this.doneSeen.set(id, Date.now()); // she saw it finish here
		if (this.doneSeen.size > 50) this.doneSeen.delete(this.doneSeen.keys().next().value as string);
		if (this.state?.on) void this.refresh();
	}

	switchTo(chat: string | null) {
		this.clear();
		if (this.chat) setOn(this.chat, null);
		this.chat = chat;
		this.state = null;
		this.watchedSince = Date.now();
		this.leafKey = '';
		this.lostLead = false;
		this.backoff = 0;
		this.backoffUntil = 0;
		this.sticky = null;
		this.last = null;
		if (chat) void this.refresh();
	}

	clear() {
		if (this.timer) clearTimeout(this.timer);
		this.timer = null;
	}

	adopt(st: LoungeState | null) {
		if (!this.chat || st?.chat_id !== this.chat) return;
		this.state = st;
		if (typeof st.lead === 'boolean') this.lostLead = !st.lead;
		setOn(this.chat, st);
		this.say();
		this.schedule();
	}

	/** the sheet's line, from what the rig said last */
	say(over?: LoungeStatus) {
		const st = this.state;
		if (!this.chat || !st?.on) return;
		if (over) return setStatus(this.chat, over);
		if (this.sticky && !st.stopped) return setStatus(this.chat, this.sticky);
		if (st.stopped) return setStatus(this.chat, { kind: 'stopped', why: refusedOf(st.stopped.why) });
		if (this.lostLead) return setStatus(this.chat, { kind: 'lead' });
		if (st.quiet_until) return setStatus(this.chat, { kind: 'quiet', at: st.quiet_until });
		const last = this.last ? { last: this.last } : {};
		if (st.due_at == null) return setStatus(this.chat, { kind: 'waiting', ...last });
		setStatus(this.chat, { kind: 'next', at: st.due_at, ...last });
	}

	refresh(): Promise<void> {
		if (this.refreshing) return this.refreshing;
		const chat = this.chat;
		if (!chat) return Promise.resolve();
		this.refreshing = call<LoungeState>('state', { chat_id: chat, page: PAGE, visible: visible(), leaf: this.leaf() })
			.then((st) => {
				if (st.on) why(`on · due in ${st.due_at ? Math.round(st.due_at - Date.now() / 1000) + ' s' : '—'}`, chat);
				this.adopt(st);
			})
			.catch(() => this.retry(30000))
			.finally(() => (this.refreshing = null));
		return this.refreshing;
	}

	retry(ms: number) {
		this.clear();
		if (!this.state?.on) return;
		this.timer = setTimeout(() => void this.refresh(), ms);
	}

	schedule() {
		this.clear();
		if (this.dropped || !this.state?.on || this.state.stopped) return; // stopped: her md's change wakes it (the 20 s look)
		let d = delayOf(this.state.due_at, Date.now());
		if (d === null) return; // a reply runs or is owed: the next poke looks again
		d = Math.max(d, this.backoffUntil - Date.now());
		if (this.lostLead && !visible()) return; // she looks elsewhere: visibility brings it back
		this.timer = setTimeout(() => this.tick(), d);
	}

	tick() {
		this.timer = null;
		const st = this.state;
		if (this.dropped || !st?.on || !this.chat) return;
		if (st.due_at && Date.now() < st.due_at * 1000 - 500) return void this.refresh(); // a far turn, looked at again
		const hold = holdOf({
			busy: this.host.busy(),
			voice: get(voiceUI).state,
			typing: st.typing,
			typedAgoMs: Date.now() - this.typedAt,
			hidden: !visible(),
			lostLead: this.lostLead
		});
		if (hold) {
			why(`held: ${hold}`, this.chat);
			this.say({ kind: 'held', why: hold });
			if (hold === 'another page leads') return;
			this.timer = setTimeout(() => this.tick(), HOLD_MS);
			return;
		}
		void this.ask();
	}

	async ask() {
		const chat = this.chat;
		const st = this.state;
		if (!chat || !st?.on || this.asking) return;
		const leaf = this.leaf();
		if (!leaf) return;
		this.asking = true;
		setWriting(chat, true);
		this.sticky = null;
		this.say({ kind: 'writing' });
		why('asks', chat);
		const temp = chat.startsWith('temporary:') || chat.startsWith('local:');
		const turns = temp
			? branchOf(this.host.history())
					.slice(-2000)
					.filter((m) => m.role === 'user' || m.role === 'assistant')
					.map((m) => ({ role: m.role, content: textOf(m), timestamp: m.timestamp, stream: !!m.petal_stream }))
			: undefined;
		let turn: LoungeTurn = {};
		try {
			turn = this.host.turn?.() ?? {};
		} catch {
			turn = {};
		}
		type Answer = {
			status: string;
			message?: Msg;
			parent_id?: string;
			state?: LoungeState;
			why?: string;
			left_out?: number;
		};
		let res: Answer | null = null;
		try {
			res = await call<Answer>('speak', {
				chat_id: chat,
				page: PAGE,
				visible: visible(),
				leaf,
				model: this.host.model(),
				typing: Date.now() - this.typedAt < TYPING_NOW_MS,
				turns,
				filter_ids: turn.filter_ids,
				variables: turn.variables,
				mode: turn.mode ?? undefined,
				...(temp ? { system: turn.system, params: turn.params } : {})
			});
		} catch {
			res = null;
		} finally {
			this.asking = false;
			setWriting(chat, false);
		}
		if (this.dropped || this.chat !== chat) return; // she moved on (a saved chat's words reach it on its own)
		const status = res?.status ?? 'error';
		why(status + (res?.why ? `: ${res.why}` : ''), chat);
		if (status === 'spoke' && res?.message && res.parent_id) {
			this.backoff = 0;
			this.backoffUntil = 0;
			this.lostLead = false;
			const landed = this.host.land(res.message, res.parent_id);
			if (landed) streamArrived(res.message.id, st.voice ?? 'on');
			this.leafKey = `${res.message.id}:assistant:true`;
			this.doneSeen.set(res.message.id, Date.now());
			this.last = { kind: 'spoke', left: res.left_out ?? 0 };
			return this.adopt(res.state ?? null);
		}
		if (status === 'passed') {
			// A43 · she let the moment pass: nothing landed, her gap starts over (never an error)
			this.backoff = 0;
			this.backoffUntil = 0;
			this.last = { kind: 'passed', left: res?.left_out ?? 0 };
			return this.adopt(res?.state ?? null);
		}
		if (status === 'wait' || status === 'quiet') return this.adopt(res?.state ?? null);
		if (status === 'stopped') {
			if (res?.state) this.adopt(res.state);
			return this.say({ kind: 'stopped', why: refusedOf(res?.why) });
		}
		if (status === 'off' || status === 'gone' || status === 'asleep') {
			this.state = res?.state ?? { chat_id: chat, on: false };
			setOn(chat, null);
			return this.clear();
		}
		if (status === 'not_lead') {
			this.lostLead = true;
			return this.retry(LEAD_MS);
		}
		if (status === 'busy' || status === 'speaking' || status === 'yielded') {
			this.say(res?.why?.includes('owed') ? { kind: 'waiting' } : { kind: 'held', why: res?.why ?? status });
			return this.retry(BUSY_MS);
		}
		this.backoff = Math.min(FAR_MS, this.backoff ? this.backoff * 2 : 30000); // resting · empty · error
		this.sticky =
			status === 'resting'
				? { kind: 'resting' }
				: status === 'error'
					? { kind: 'refused', why: refusedOf(res?.why) }
					: { kind: 'held', why: status === 'empty' ? 'her words came back empty' : status };
		this.say(this.sticky);
		this.backoffUntil = Date.now() + this.backoff;
		this.clear();
		this.timer = setTimeout(() => this.tick(), this.backoff);
	}

	drop() {
		this.dropped = true;
		this.clear();
		if (this.chat) setOn(this.chat, null);
		watchers.delete(this);
	}
}

const watchers = new Set<Watcher>();

/** one per Chat: poke() on each change of its history or her words, drop() when it goes */
export function watchLounge(host: LoungeHost) {
	install();
	const w = new Watcher(host);
	watchers.add(w);
	return {
		poke: (prompt?: string) => w.poke(prompt),
		drop: () => w.drop()
	};
}

const watcherOf = (chatId: string) => [...watchers].find((w) => w.chat === chatId) ?? null;

// ── what the 💗 asks ─────────────────────────────────────────────────────────────────────────────────────
export async function loadLoungeShelf(): Promise<LoungeShelf | null> {
	try {
		const shelf = await call<LoungeShelf>('profiles');
		loungeShelf.set(shelf);
		loungeShelfError.set(null);
		return shelf;
	} catch (e) {
		loungeShelfError.set(`couldn't reach the rig · ${(e as Error)?.message || 'no answer'}`);
		return null;
	}
}

/** the knobs reference (the fork's own page of it, shown in place) */
export async function loadLoungeKnobs(): Promise<string | null> {
	try {
		return (await call<{ text: string }>('knobs')).text;
	} catch {
		return null;
	}
}

/** a profile chosen for this chat: on, for this chat only (turning it on is a look: this page leads) */
export async function loungeTurnOn(chatId: string, profile: string): Promise<LoungeState | null> {
	const w = watcherOf(chatId);
	try {
		const st = await call<LoungeState>('on', { chat_id: chatId, profile, page: PAGE, visible: true, leaf: w?.leaf() ?? null });
		why(`on · ${profile}`, chatId);
		if (w) {
			w.lostLead = false;
			w.sticky = null;
			w.backoff = 0;
			w.backoffUntil = 0;
			w.adopt(st);
		} else setOn(chatId, st);
		return st;
	} catch {
		return null;
	}
}

/** one tap, or Esc: off (and her voice, when it is reading words she spoke on her own in this chat) */
export async function loungeTurnOff(chatId: string): Promise<void> {
	const w = watcherOf(chatId);
	setOn(chatId, null);
	const ui = get(voiceUI);
	if (ui.state !== 'idle' && ui.message_id && w?.host.history()?.messages?.[ui.message_id]?.petal_stream) stopAllVoice('the lounge turned off');
	if (w) {
		w.state = { chat_id: chatId, on: false };
		w.clear();
	}
	why('off', chatId);
	try {
		await call('off', { chat_id: chatId });
	} catch {}
}

// ── the 20 s look: her md's edits land (state carries its mtime) · only while visible, and only for a stream that's
// on or the sheet that's open; never while hidden ──────────────────────────────────────────────────────────────
export const LOOK_MS = 20000;
let looking: ReturnType<typeof setInterval> | null = null;
function look() {
	if (!needLook()) return stopLooking();
	const sheet = get(loungeSheet);
	for (const w of watchers) {
		if (w.chat && !w.asking && (w.state?.on || sheet === w.chat)) void w.refresh();
	}
	if (sheet) void loadLoungeShelf();
}
/** only while needed: visible, and a stream on (in a chat this page watches) or the sheet open · at rest, no timer */
const needLook = () => visible() && (!!get(loungeSheet) || Object.keys(get(loungeOn)).length > 0);
function startLooking() {
	if (!needLook()) return stopLooking();
	if (!looking) looking = setInterval(look, LOOK_MS);
}
function stopLooking() {
	if (looking) clearInterval(looking);
	looking = null;
}

// ── installed once by the page ───────────────────────────────────────────────────────────────────────────
let installed = false;
// something else Esc is for: a dialog, a menu, the heart's sheet, the input's suggestions (a / command, a mention)
const dialogOpen = () =>
	!!document.querySelector(
		'[role="dialog"]:not([hidden]), [aria-modal="true"], [data-petal-heart-sheet], [role="menu"], [role="listbox"], #suggestions-container, [data-tippy-root]'
	);
function install() {
	if (installed || typeof window === 'undefined') return;
	installed = true;
	document.addEventListener('visibilitychange', () => {
		if (!visible()) return stopLooking();
		for (const w of watchers) if (w.chat) void w.refresh(); // she looks here: this page leads again
		startLooking();
	});
	loungeOn.subscribe(() => startLooking()); // a stream on or off, a sheet open or closed: the look follows
	loungeSheet.subscribe(() => startLooking());
	window.addEventListener('focus', () => {
		for (const w of watchers) if (w.chat && w.lostLead) void w.refresh();
	});
	// Esc, when nothing else is open: the stream of the chat on screen goes quiet. (the chat input keeps Esc's default
	// for itself, a stop of any running reply, so a prevented default says nothing here; whatever closes on Esc is
	// either open in the page, or stops it on its way)
	// what was open when Esc began (a dialog closing on this very key is gone by the time it bubbles up here)
	let escFoundOpen = false;
	window.addEventListener('keydown', (e) => e.key === 'Escape' && (escFoundOpen = dialogOpen()), true);
	window.addEventListener('keydown', (e) => {
		if (e.key !== 'Escape' || e.isComposing || escFoundOpen || dialogOpen()) return;
		const on = get(loungeOn);
		for (const w of watchers) {
			if (w.chat && on[w.chat]?.on && w.host.shown()) void loungeTurnOff(w.chat);
		}
	});
	(window as unknown as { petalLounge?: object }).petalLounge = {
		get now() {
			return {
				page: PAGE,
				watching: [...watchers].map((w) => ({
					chat: w.chat?.slice(0, 8) ?? null,
					on: !!w.state?.on,
					profile: w.state?.profile ?? null,
					due_in_s: w.state?.due_at ? Math.round(w.state.due_at - Date.now() / 1000) : null,
					lead: !w.lostLead,
					asking: w.asking,
					timer: !!w.timer
				}))
			};
		},
		get why() {
			return [...trail];
		}
	};
}
