// 👍🏻 instant thumbs (slice A23). a verdict lights her thumb on the tap's own frame (the reply's history
// changes at once, see ResponseMessage); its save rides this queue behind it, one small request per reply
// (POST /api/v1/petal/thumbs, routers/petal_thumbs.py: the same feedback row OWUI's thumb made, snapshot
// included, built on the rig instead of carried through the phone twice)
//  · one entry per reply, the latest verdict wins: double taps and flips collapse. a verdict tapped while an
//    earlier one is on its way goes right after it, with the row id the first one minted (one row per reply)
//  · offline or an error: tried again with backoff (1 · 2 · 4 · 8 · 15 s), then a quiet mark on that thumb
//    (tap it to try again). back online, or the page shown again: one more try each. never a toast
//  · a page reload keeps what's still waiting, in localStorage: ids and verdicts only (the rating, the reason
//    key, the 1–10). never words: not her note, not the tags, not the reply
//  · what the tap doesn't need rides after it: OWUI's tag step, on her first thumb of a reply, run on the rig
//    from its own copy of the chat (POST /api/v1/petal/thumbs/tags): the phone never uploads the conversation
//  · temporary chats queue nothing (contract 0; the page shows no thumbs there)
import { writable, get } from 'svelte/store';
import { WEBUI_API_BASE_URL } from '$lib/constants';
import { isSavedChatId } from '$lib/utils/chatId';

type Annotation = Record<string, unknown>;

export type ThumbState = 'saving' | 'saved' | 'failed';
export type ThumbMark = {
	rating?: number | null;
	state: ThumbState;
	feedback_id?: string | null;
	annotation?: Annotation | null; // the rig's merged annotation, once landed (memory only)
};

export type Verdict = {
	chat_id: string;
	message_id: string;
	feedback_id: string | null;
	annotation: Annotation; // the reply's whole annotation as the page now holds it
	model_id: string | null;
	sibling_model_ids: string[] | null;
	meta: Record<string, unknown>;
	askTags?: boolean; // her first thumb of a reply: OWUI's tag step follows once the verdict landed
};

type Entry = Verdict & {
	tries: number;
	due: number;
	gen: number; // grows with every verdict on this reply: a landing only settles the verdict it carried
	flying: boolean;
};

export const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];
export const MAX_TRIES = BACKOFF_MS.length;
const KEY = 'petal-thumbs';
const SETTLE_MS = 1200; // a landed mark lingers this long (its fade), then leaves

/** per reply: its pending rating and how its save is going. ResponseMessage reads it for the thumb's
 *  light (a verdict still on its way after a reload) and its quiet mark */
export const thumbMarks = writable<Record<string, ThumbMark>>({});

const queue = new Map<string, Entry>();
let pumpTimer: ReturnType<typeof setTimeout> | null = null;

const ratingOf = (a: Annotation | null | undefined): number | null | undefined =>
	!a || !('rating' in a)
		? undefined
		: typeof a.rating === 'number'
			? (a.rating as number)
			: a.rating == null
				? null
				: Number(a.rating);

function setMark(id: string, mark: ThumbMark | null) {
	thumbMarks.update((all) => {
		const next = { ...all };
		if (mark) next[id] = mark;
		else delete next[id];
		return next;
	});
}

/** what may sleep in localStorage: the verdict itself, never words */
export function verdictOnly(a: Annotation): Annotation {
	const out: Annotation = {};
	if ('rating' in a && (a.rating === null || typeof a.rating === 'number')) out.rating = a.rating;
	if ('reason' in a && (a.reason === null || (typeof a.reason === 'string' && /^[a-z_]{0,48}$/.test(a.reason))))
		out.reason = a.reason;
	if ('details' in a) {
		const d = a.details as { rating?: unknown } | null;
		out.details = d == null ? null : { rating: typeof d.rating === 'number' ? d.rating : null };
	}
	return out;
}

function persist() {
	try {
		const items = [...queue.values()]
			.map((e) => ({
				c: e.chat_id,
				m: e.message_id,
				f: e.feedback_id,
				v: verdictOnly(e.annotation),
				mi: e.model_id,
				s: e.sibling_model_ids,
				meta: e.meta,
				n: e.tries
			}))
			.filter((x) => Object.keys(x.v).length > 0);
		if (items.length) localStorage.setItem(KEY, JSON.stringify({ v: 1, items }));
		else localStorage.removeItem(KEY);
	} catch {
		// private mode, a full disk: the queue still lives in memory
	}
}

function restore() {
	let raw: { items?: unknown[] } | null = null;
	try {
		raw = JSON.parse(localStorage.getItem(KEY) ?? 'null');
	} catch {
		raw = null;
	}
	const marks: Record<string, ThumbMark> = {};
	for (const x of (raw?.items ?? []) as Record<string, any>[]) {
		if (typeof x?.m !== 'string' || typeof x?.c !== 'string' || !isSavedChatId(x.c)) continue;
		const annotation = verdictOnly(x.v ?? {});
		if (!Object.keys(annotation).length || queue.has(x.m)) continue;
		queue.set(x.m, {
			chat_id: x.c,
			message_id: x.m,
			feedback_id: typeof x.f === 'string' ? x.f : null,
			annotation,
			model_id: typeof x.mi === 'string' ? x.mi : null,
			sibling_model_ids: Array.isArray(x.s) ? x.s : null,
			meta: x.meta && typeof x.meta === 'object' ? x.meta : {},
			askTags: false,
			tries: Math.min(Number(x.n) || 0, MAX_TRIES - 1), // a reload always earns one more try
			due: 0,
			gen: 1,
			flying: false
		});
		marks[x.m] = { rating: ratingOf(annotation), state: 'saving' };
	}
	if (Object.keys(marks).length) thumbMarks.update((all) => ({ ...marks, ...all }));
}

/** a verdict from the page (a thumb, a note): it replaces whatever this reply still had waiting */
export function thumbVerdict(v: Verdict) {
	if (!v.message_id || !isSavedChatId(v.chat_id)) return;
	const was = queue.get(v.message_id);
	const entry: Entry = {
		chat_id: v.chat_id,
		message_id: v.message_id,
		feedback_id: v.feedback_id ?? was?.feedback_id ?? null,
		annotation: v.annotation,
		model_id: v.model_id,
		sibling_model_ids: v.sibling_model_ids,
		meta: v.meta,
		askTags: !!(v.askTags || was?.askTags),
		tries: 0,
		due: 0,
		gen: (was?.gen ?? 0) + 1,
		flying: was?.flying ?? false
	};
	queue.set(v.message_id, entry);
	setMark(v.message_id, { rating: ratingOf(v.annotation), state: 'saving' });
	persist();
	pump();
}

function pump() {
	if (pumpTimer) clearTimeout(pumpTimer);
	pumpTimer = null;
	if (typeof window === 'undefined') return;
	if (typeof navigator !== 'undefined' && navigator.onLine === false) return; // 'online' wakes it
	const now = Date.now();
	let next = Infinity;
	for (const entry of queue.values()) {
		if (entry.flying || entry.tries >= MAX_TRIES) continue; // a quiet mark waits for a tap, 'online' or a look
		if (entry.due <= now) void send(entry);
		else next = Math.min(next, entry.due);
	}
	if (next < Infinity) pumpTimer = setTimeout(pump, next - now);
}

async function send(entry: Entry) {
	const token = typeof localStorage !== 'undefined' ? localStorage.token : '';
	if (!token) {
		entry.due = Date.now() + 2000; // signed out for now: look again soon
		return pump();
	}
	entry.flying = true;
	const gen = entry.gen;
	const body = JSON.stringify({
		chat_id: entry.chat_id,
		message_id: entry.message_id,
		feedback_id: entry.feedback_id,
		annotation: entry.annotation,
		model_id: entry.model_id,
		sibling_model_ids: entry.sibling_model_ids,
		meta: entry.meta
	});
	let res: Response | null = null;
	let out: { feedback_id?: string; annotation?: Annotation } | null = null;
	try {
		res = await fetch(`${WEBUI_API_BASE_URL}/petal/thumbs`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
			body,
			keepalive: body.length < 48_000 // a tap right before the tab closes still lands
		});
		if (res.ok) out = await res.json();
	} catch {
		res = null;
	}
	entry.flying = false;
	const current = queue.get(entry.message_id) ?? entry;
	if (current !== entry) current.flying = false;

	if (res?.ok && out?.feedback_id) {
		current.feedback_id = out.feedback_id;
		if (current === entry && entry.gen === gen) {
			queue.delete(entry.message_id);
			setMark(entry.message_id, {
				rating: ratingOf(out.annotation ?? entry.annotation),
				state: 'saved',
				feedback_id: out.feedback_id,
				annotation: out.annotation ?? null
			});
			persist();
			settleLater(entry.message_id);
			void tagsAfter(entry, out.annotation ?? entry.annotation);
		} else {
			persist(); // a newer verdict waited: it goes now, onto the same row
			pump();
		}
		return;
	}

	const status = res?.status ?? 0;
	if (current !== entry || current.gen !== gen) return pump(); // a newer verdict replaced this one: send it
	if (status === 400 || status === 404 || status === 422) {
		// a temporary chat, a reply or chat that's gone, a shape the rig refuses: nothing left to keep
		queue.delete(entry.message_id);
		setMark(entry.message_id, null);
		persist();
		return;
	}
	// offline, the rig out of reach, a server error, signed out: again later, then the quiet mark
	entry.tries += 1;
	entry.due = Date.now() + BACKOFF_MS[Math.min(entry.tries - 1, BACKOFF_MS.length - 1)];
	if (entry.tries >= MAX_TRIES) setMark(entry.message_id, { rating: ratingOf(entry.annotation), state: 'failed' });
	persist();
	pump();
}

function settleLater(id: string) {
	setTimeout(() => {
		if (get(thumbMarks)[id]?.state === 'saved' && !queue.has(id)) setMark(id, null);
	}, SETTLE_MS);
}

/** OWUI's tag step (her first thumb of a reply, while the reply has none), after the verdict landed: the rig
 *  runs it from its own copy of the chat and lands the tags; the page only learns the merged annotation */
async function tagsAfter(entry: Entry, annotation: Annotation) {
	if (!entry.askTags || annotation?.tags) return;
	entry.askTags = false;
	try {
		const res = await fetch(`${WEBUI_API_BASE_URL}/petal/thumbs/tags`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.token}` },
			body: JSON.stringify({ chat_id: entry.chat_id, message_id: entry.message_id }),
			keepalive: true
		});
		const out = res.ok ? await res.json() : null;
		// a newer verdict still on its way brings the tags back with its own landing
		if (out?.annotation && !queue.has(entry.message_id)) {
			setMark(entry.message_id, {
				rating: ratingOf(out.annotation),
				state: 'saved',
				feedback_id: out.feedback_id,
				annotation: out.annotation
			});
			settleLater(entry.message_id);
		}
	} catch (err) {
		console.error(err);
	}
}

/** try everything waiting now: back online, the page shown again, a message about to leave. a quiet mark
 *  gets one more try (a tap on its thumb gets a full round) */
export function thumbsNudge() {
	for (const entry of queue.values()) {
		if (entry.flying) continue;
		if (entry.tries >= MAX_TRIES) entry.tries = MAX_TRIES - 1;
		entry.due = 0;
	}
	pump();
}

if (typeof window !== 'undefined') {
	restore();
	window.addEventListener('online', thumbsNudge);
	document.addEventListener('visibilitychange', () => {
		if (document.visibilityState === 'visible') thumbsNudge();
	});
	if (queue.size) setTimeout(pump, 0);
}
