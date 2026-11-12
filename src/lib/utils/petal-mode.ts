// 🌀 the mode chip's mind (slice A15) — which of the forge's modes dresses her next message.
// the modes themselves (their names, emoji and order) live in the forge's own doc and are read
// through its door (/api/v1/petal/forge, admin-only): this fork ships none, names none, and shows
// nothing without them. the pick is sticky per chat and kept in this browser only (a temp chat's
// in memory alone, contract 0); it rides on the request as `petal_mode` (its key), and the server
// hands it to the filters as metadata.
import { get, writable } from 'svelte/store';

import { WEBUI_API_BASE_URL } from '$lib/constants';
import { isSavedChatId } from '$lib/utils/chatId';

export type Mode = { key: string; name: string; emoji: string; lead: boolean };

/** the forge's modes, in its own order · empty: no chip, no hotkey, nothing sent */
export const modes = writable<Mode[]>([]);
/** bumps whenever a pick changes, so every chip (a split view has two) reads it again */
export const modeTick = writable(0);

/** the modes out of the forge's doc: a list (its order is the cycle), or an object keyed by name.
 * each one's key is its id, else its name; retired ones stay out; `default: true` leads a new chat. */
export function modesOf(doc: unknown): Mode[] {
	const raw = doc && typeof doc === 'object' ? (doc as Record<string, unknown>).modes : null;
	const list: [string | null, unknown][] = Array.isArray(raw)
		? raw.map((m) => [null, m])
		: raw && typeof raw === 'object'
			? Object.entries(raw as Record<string, unknown>)
			: [];
	const out: Mode[] = [];
	for (const [k, m] of list) {
		if (!m || typeof m !== 'object') continue;
		const o = m as Record<string, unknown>;
		if (o.retired) continue;
		const key = [o.id, o.key, o.name, k]
			.find((v): v is string => typeof v === 'string' && !!v.trim())
			?.trim();
		if (!key || out.some((x) => x.key === key)) continue;
		const name = typeof o.name === 'string' && o.name.trim() ? o.name.trim() : key;
		out.push({
			key,
			name,
			emoji: typeof o.emoji === 'string' ? o.emoji.trim() : '',
			lead: o.default === true
		});
	}
	return out;
}

/** the mode a chat starts in: the one the forge marks default, else its first */
export const leadOf = (list: Mode[]) => list.find((m) => m.lead) ?? list[0] ?? null;

let asking: Promise<void> | null = null;
let askedAt = 0;

/** read the forge's modes once, again when the page comes back after a while (a rename in the
 * jewelry box shows up without a reload) · never throws: no forge means no chip */
export function loadModes(force = false): Promise<void> {
	if (asking && !force && Date.now() - askedAt < 60_000) return asking;
	askedAt = Date.now();
	asking = (async () => {
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/petal/forge`, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			const j = res.ok ? await res.json() : null;
			modes.set(j?.installed ? modesOf(j.doc) : []);
		} catch {
			modes.set([]);
		}
	})();
	return asking;
}

// ── one pick per chat, in this browser only ──
const KEY = 'petal-mode.chats'; // { [saved chat id]: mode key }, newest last
const KEEP = 400; // the oldest picks fall away past this many chats
let pending: string | null = null; // the new-chat page's pick, until the chat is born
const unsaved = new Map<string, string>(); // temp chats: their pick lives until the page closes, never in storage

const read = (): Record<string, string> => {
	try {
		const o = JSON.parse(localStorage.getItem(KEY) ?? '{}');
		return o && typeof o === 'object' && !Array.isArray(o) ? o : {};
	} catch {
		return {};
	}
};

/** the key kept for a chat (null id: the new-chat page's pick) */
export const keptFor = (chatId: string | null | undefined): string | null =>
	!chatId
		? pending
		: isSavedChatId(chatId)
			? (read()[chatId] ?? null)
			: (unsaved.get(chatId) ?? null);

export function keepMode(chatId: string | null | undefined, key: string) {
	if (!chatId) pending = key;
	else if (!isSavedChatId(chatId)) unsaved.set(chatId, key);
	else {
		const o = read();
		delete o[chatId];
		o[chatId] = key;
		const ids = Object.keys(o);
		for (const id of ids.slice(0, Math.max(0, ids.length - KEEP))) delete o[id];
		try {
			localStorage.setItem(KEY, JSON.stringify(o));
		} catch {
			/* no storage: the pick lives until the page closes */
		}
	}
	modeTick.update((n) => n + 1);
}

/** the new chat is born: the pick made on its empty page follows it */
export function adoptMode(chatId: string | null | undefined) {
	if (chatId && pending) keepMode(chatId, pending);
	pending = null;
}

/** the mode a chat is in now: its pick when the forge still knows it, else the lead */
export function modeOf(list: Mode[], chatId: string | null | undefined): Mode | null {
	if (!list.length) return null;
	const k = keptFor(chatId);
	return list.find((m) => m.key === k) ?? leadOf(list);
}

/** what rides on the request: the key, or nothing at all when the forge declares no modes */
export const modeToSend = (chatId: string | null | undefined): string | null =>
	modeOf(get(modes), chatId)?.key ?? null;

/** the next one along the forge's own order */
export function stepMode(chatId: string | null | undefined): Mode | null {
	const list = get(modes);
	const now = modeOf(list, chatId);
	if (!now) return null;
	const next = list[(list.indexOf(now) + 1) % list.length];
	keepMode(chatId, next.key);
	return next;
}
