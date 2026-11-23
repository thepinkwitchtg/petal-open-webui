// 🌊 Petal Stream (slice A41) · the lounge, on the page. the rig keeps her profiles, her rhythm and which chats are
// open to it (routers/petal_lounge.py); the page knows what the rig can't see: whether she's typing, whether a
// reply runs or a pick waits, whether her voice is playing, which page she's looking at. each Chat watches its own
// chat: one timer, to the moment her rhythm says, and then one ask, unless something holds it back. the rig checks
// everything again before a word is written.
//  · per chat: off by default · a profile chosen in the 💗 turns it on for that chat only · one tap on the 🌊
//    chip beside the heart, or Esc, turns it off
//  · holds (the page's): a reply running or owed · a pick still open · her voice playing (any chat) · a voice call ·
//    her typing, while the profile says wait (until a few seconds after her last key)
//  · the lead: the last page she looked at speaks · a visible page claims it with every call; a hidden page that
//    lost it waits until she looks at it again (so the PC in the other room never speaks for the phone in her hand)
//  · a stream message lands through its Chat (a temporary chat's lives on the page only); her voice reads it when
//    the profile and her autoplay agree (petal-autoplay · streamArrived)
//  · nothing runs at rest: no timer while no chat is open to her stream; a held turn looks again every 1.5 s
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
	length?: [number, number];
	quiet?: string;
	voice?: LoungeVoice;
	typing?: LoungeTyping;
	words?: number;
	problems?: string[];
};
export type LoungeDemo = { name: string; title: string; emoji: string; planted: boolean };
export type LoungeShelf = { profiles: LoungeProfile[]; demos: LoungeDemo[]; folder: string };
export type LoungeState = {
	chat_id: string;
	on: boolean;
	lead?: boolean;
	profile?: string;
	title?: string;
	emoji?: string;
	voice?: LoungeVoice;
	typing?: LoungeTyping;
	turns?: number;
	spoke?: number;
	problems?: string[];
	n?: number;
	fp?: string;
	quiet_until?: number | null;
	due_at?: number | null;
	gap?: number;
	waiting?: string;
	gone?: string;
};
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
/** what her folder holds (and the demos she can copy), read when the 💗 opens its stream view */
export const loungeShelf = writable<LoungeShelf | null>(null);
/** a chat she is writing in right now (between the ask and her words) */
export const loungeWriting = writable<Record<string, boolean>>({});

// her stream's last choices, for a look inside (ids and reasons only, never words)
const trail: string[] = [];
const why = (what: string, id?: string | null) => {
	trail.push(`${Math.round(performance.now())} ${what}${id ? ' ' + id.slice(0, 8) : ''}`);
	if (trail.length > 80) trail.shift();
};

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
	return res.json();
}

const visible = () => typeof document !== 'undefined' && document.visibilityState === 'visible';

function setOn(chatId: string, st: LoungeState | null) {
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
	lostLead = false;
	dropped = false;

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
		this.schedule();
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
		if (this.dropped || !this.state?.on) return;
		const d = delayOf(this.state.due_at, Date.now());
		if (d === null) return; // a reply runs or is owed: the next poke looks again
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
		why('asks', chat);
		const temp = chat.startsWith('temporary:') || chat.startsWith('local:');
		const turns = temp
			? branchOf(this.host.history())
					.slice(-Math.min(200, (st.turns ?? 16) + 8))
					.filter((m) => m.role === 'user' || m.role === 'assistant')
					.map((m) => ({ role: m.role, content: textOf(m), timestamp: m.timestamp, stream: !!m.petal_stream }))
			: undefined;
		type Answer = { status: string; message?: Msg; parent_id?: string; state?: LoungeState; why?: string };
		let res: Answer | null = null;
		try {
			res = await call<Answer>('speak', {
				chat_id: chat,
				page: PAGE,
				visible: visible(),
				leaf,
				model: this.host.model(),
				typing: Date.now() - this.typedAt < TYPING_NOW_MS,
				turns
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
			this.lostLead = false;
			const landed = this.host.land(res.message, res.parent_id);
			if (landed) streamArrived(res.message.id, st.voice ?? 'on');
			this.leafKey = `${res.message.id}:assistant:true`;
			this.doneSeen.set(res.message.id, Date.now());
			return this.adopt(res.state ?? null);
		}
		if (status === 'wait' || status === 'quiet') return this.adopt(res?.state ?? null);
		if (status === 'off' || status === 'gone') {
			this.state = res?.state ?? { chat_id: chat, on: false };
			setOn(chat, null);
			return this.clear();
		}
		if (status === 'not_lead') {
			this.lostLead = true;
			return this.retry(LEAD_MS);
		}
		if (status === 'busy' || status === 'speaking' || status === 'yielded') return this.retry(BUSY_MS);
		this.backoff = Math.min(FAR_MS, this.backoff ? this.backoff * 2 : 30000); // resting · empty · error
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
		return shelf;
	} catch {
		return null;
	}
}

export async function plantLoungeDemos(names?: string[]): Promise<LoungeShelf | null> {
	try {
		const shelf = await call<LoungeShelf & { planted: string[] }>('plant', { names });
		loungeShelf.set(shelf);
		return shelf;
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
	if (ui.state !== 'idle' && ui.message_id && w?.host.history()?.messages?.[ui.message_id]?.petal_stream) stopAllVoice();
	if (w) {
		w.state = { chat_id: chatId, on: false };
		w.clear();
	}
	why('off', chatId);
	try {
		await call('off', { chat_id: chatId });
	} catch {}
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
		if (!visible()) return;
		for (const w of watchers) if (w.chat) void w.refresh(); // she looks here: this page leads again
	});
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
