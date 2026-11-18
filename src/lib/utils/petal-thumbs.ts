// 👍🏻 instant thumbs (slice A23). a verdict lights her thumb on the tap's own frame (the reply's history
// changes at once, see ResponseMessage); its save rides this queue behind it, one small request per reply
// (POST /api/v1/petal/thumbs, routers/petal_thumbs.py: the same feedback row OWUI's thumb made, snapshot
// included, built on the rig instead of carried through the phone twice)
//  · one entry per reply, the latest verdict wins: double taps and flips collapse. a verdict tapped while an
//    earlier one is on its way goes right after it, with the row id the first one minted (one row per reply)
//  · offline or an error: tried again with backoff (1 · 2 · 4 · 8 s), then a quiet ring on that thumb (tap it to
//    try again). back online, the page shown again, a message sent: one more try each
//  · 💗 A23b · she hears how it went, one toast per reply whose words change in place: "sent" the moment it
//    leaves · "Thanks for your feedback 💗" only once the rig answered that the row is in the database · if every
//    try fails, "couldn't save your feedback · tap to retry" (a retry button), once per failure, never per try
//  · 💗 A26 · a thank-you Petal wrote ahead of time comes back with the landing itself (`thanks`,
//    routers/petal_thumbs.py → utils/petal_thanks.py): no second request, no model call on the tap. she never
//    learns the verdict
//  · 💗 A27 · her thank-you lives in hush, a reflex: the row landing says only "saved ✓" (the same every time), and
//    her line goes once per feedback into the whisper (petalHush.reflex), snapping over whatever hush was showing
//    or writing. a feedback's first landing asks for the line; the note that follows (or a flip while it's open)
//    never asks again. the line waits while the note window is open, and goes when the note is saved or closed;
//    a thumb with no note window sends it as soon as the row lands. no hush to show it (another theme, words in
//    the field) → a toast instead, ~4 s + ~70 ms a character (≤ 10 s), held while hovered or touched
//  · 💗 A28 · the two little words, one per click: a thumb's tap, once its row lands → "Thanks for your feedback
//    💗" (THANKS); the note window's save, once that update lands → "saved ✓" (SAVED). never both for one click,
//    never twice in a row for one feedback: a flip while its note window is open is owed nothing and stays quiet
//    (no "sent", no word; a failure still speaks). a landing that also carries an older click (one that never
//    landed on its own: offline, retrying) says the older word first, the newer one ~1.8 s later. both stay
//    ~1.8 s whatever their length; her own line keeps living in hush, once per feedback (A27)
//  · 🍒 A29 · a pick's two verdicts (utils/petal-pick.ts) ride the same queue, quietly: no "sent", no word,
//    no feedback begun (so no thank-you, no hush), no tag step. a failure still speaks after its tries
//  · a page reload keeps what's still waiting, in localStorage: ids and verdicts only (the rating, the reason
//    key, the 1–10). never words: not her note, not the tags, not the reply
//  · what the tap doesn't need rides after it: OWUI's tag step, on her first thumb of a reply, run on the rig
//    from its own copy of the chat (POST /api/v1/petal/thumbs/tags): the phone never uploads the conversation
//  · temporary chats queue nothing (contract 0; the page shows no thumbs there)
import { writable, get } from 'svelte/store';
import { toast } from 'svelte-sonner';
import { WEBUI_API_BASE_URL } from '$lib/constants';
import { isSavedChatId } from '$lib/utils/chatId';
import { PETAL_TOAST_MS } from '$lib/utils/petal-toast-touch';

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
	thumb?: boolean; // 💗 A27 · a thumb's tap: it begins a feedback (unless one is still open on this reply).
	// without it, the verdict is the note window's save (💗 A28 · owed "saved ✓")
	note?: boolean; // 💗 A27 · the note window opens with this tap: her line waits until it's saved or closed
	pick?: boolean; // 🍒 A29 · a pick's verdict (👍🏻 the chosen reply, 👎🏻 its sibling): quiet, no thank-you
};

type Entry = Verdict & {
	tries: number;
	due: number;
	gen: number; // grows with every verdict on this reply: a landing only settles the verdict it carried
	flying: boolean;
	announced: boolean; // its failure toast was shown: a background try that fails again stays quiet
};

export const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];
export const MAX_TRIES = BACKOFF_MS.length;
const KEY = 'petal-thumbs';
const SETTLE_MS = 1200; // a landed mark lingers this long (its fade), then leaves
const SENT_MS = 20_000; // "sent" stays until the answer replaces it (a failure needs ~15 s of tries)
export const THANKS = 'Thanks for your feedback 💗'; // 💗 A28 · a thumb's tap, once its row lands
export const SAVED = 'saved ✓'; // 💗 A28 · the note window's save, once that update lands
export const WORD_MS = 1800; // 💗 A28 · both little words are short, whatever their length
const THANKS_MAX = 120; // her lines are ≤ 70 characters; anything longer from the rig isn't hers

/** her line as the rig handed it back, or null (none ready, or not hers) */
export function thanksLine(line: unknown): string | null {
	const words = typeof line === 'string' ? line.replace(/\s+/g, ' ').trim() : '';
	return words && words.length <= THANKS_MAX ? words : null;
}

const graphemes = (s: string): number => {
	try {
		return [...new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(s)].length;
	} catch {
		return [...s].length;
	}
};

/** 💗 A27 · how long her line stays as a toast: ~4 s + ~70 ms a character, never past 10 s (sonner holds it
 *  while hovered or touched) */
export const thanksMs = (line: string): number => Math.min(10_000, 4000 + 70 * graphemes(line));

// ── 💗 A28 · the two little words ────────────────────────
// a click is owed its word when it's made (a feedback's first tap → THANKS, the note's save → SAVED) and the word
// is said when a request carrying that click lands: its own, or a newer one it collapsed into
type Word = 'thanks' | 'saved';
const owed = new Map<string, { word: Word; gen: number }[]>(); // per reply, in click order, until said
const queued = new Map<string, { words: Word[]; timer: ReturnType<typeof setTimeout> }>(); // the rest of a sequence
const showing = new Map<string, 'sent' | 'failed' | Word>(); // what the reply's toast said last

/** a click is owed its word · never the same word twice in a row (the older click keeps its turn) */
function owe(id: string, word: Word, gen: number) {
	const list = owed.get(id) ?? [];
	if (list[list.length - 1]?.word !== word) list.push({ word, gen });
	owed.set(id, list);
}

/** the words owed by every click a landing carried (all of them up to its gen), in click order */
function takeDue(id: string, gen: number): Word[] {
	const list = owed.get(id) ?? [];
	const rest = list.filter((o) => o.gen > gen);
	if (rest.length) owed.set(id, rest);
	else owed.delete(id);
	return list.filter((o) => o.gen <= gen).map((o) => o.word);
}

const saidAt = new Map<string, number>(); // when the word glowing on the reply's toast was said
const SWAP_EARLY_MS = 60; // the next word takes the toast just before sonner's own timer would end the last one

/** landed words, said one after another, each keeping its ~1.8 s (almost always there is just one) */
function speak(id: string, landed: Word[]) {
	if (!landed.length) return; // nothing new: a word glowing (or waiting its turn) keeps its time
	const was = queued.get(id);
	if (was) clearTimeout(was.timer);
	queued.delete(id);
	const all = [...(was?.words ?? []), ...landed];
	const words = all.filter((w, i) => w !== all[i - 1]);
	const glowing = showing.get(id);
	const left =
		glowing === 'thanks' || glowing === 'saved'
			? WORD_MS - SWAP_EARLY_MS - (Date.now() - (saidAt.get(id) ?? 0))
			: 0;
	if (left > 0) return later(id, words, left); // the word glowing now finishes first
	say(id, words[0]);
	if (words.length > 1) later(id, words.slice(1), WORD_MS - SWAP_EARLY_MS);
}

function later(id: string, words: Word[], ms: number) {
	queued.set(id, {
		words,
		timer: setTimeout(() => {
			queued.delete(id);
			speak(id, words);
		}, ms)
	});
}

/** a new send (or its failure) takes the toast: words still waiting their turn are said at the next landing */
function holdWords(id: string) {
	const was = queued.get(id);
	if (!was) return;
	clearTimeout(was.timer);
	queued.delete(id);
	owed.set(id, [...was.words.map((word) => ({ word, gen: 0 })), ...(owed.get(id) ?? [])]);
}

/** a landing owed no word (a quiet flip, a background retry of one): a "sent" or a failure it leaves behind goes */
function landQuietly(id: string) {
	const was = showing.get(id);
	if (was !== 'sent' && was !== 'failed') return; // a word still glowing finishes its ~1.8 s
	showing.delete(id);
	toast.dismiss(`petal-thumb-${id}`);
}

function forgetWords(id: string) {
	const was = queued.get(id);
	if (was) clearTimeout(was.timer);
	queued.delete(id);
	owed.delete(id);
	showing.delete(id);
	saidAt.delete(id);
}

// 💗 one toast per reply: an update keeps the old toast's duration and action unless given new ones, so every
// state names its own
function say(id: string, what: 'sent' | 'failed' | Word) {
	const base = { id: `petal-thumb-${id}`, description: undefined, action: undefined };
	if (what === 'sent' || what === 'failed') holdWords(id);
	showing.set(id, what);
	if (what === 'thanks' || what === 'saved') saidAt.set(id, Date.now());
	if (what === 'sent') toast.message('sent', { ...base, duration: SENT_MS });
	else if (what === 'thanks') toast.success(THANKS, { ...base, duration: WORD_MS });
	else if (what === 'saved') toast.success(SAVED, { ...base, duration: WORD_MS });
	else
		toast.error("couldn't save your feedback · tap to retry", {
			...base,
			duration: PETAL_TOAST_MS.action,
			// the toast stays (sonner deletes it after an action unless told not to) and turns into "sent"
			action: {
				label: 'retry',
				onClick: (event: Event) => {
					event?.preventDefault?.();
					thumbRetry(id);
				}
			}
		});
}

/** per reply: its pending rating and how its save is going. ResponseMessage reads it for the thumb's
 *  light (a verdict still on its way after a reload) and its quiet mark */
export const thumbMarks = writable<Record<string, ThumbMark>>({});

const queue = new Map<string, Entry>();
let pumpTimer: ReturnType<typeof setTimeout> | null = null;

// ── 💗 A27 · her thank-you, once per feedback ────────────────
// a feedback begins with a thumb's tap and ends when its line has gone (into hush, or a toast). its first landing
// asks the rig for the line; nothing later in it asks again. the line waits while the note window is open
type Feedback = { asked: boolean; line?: string | null; note: boolean };
const feedbacks = new Map<string, Feedback>();

/** where her line goes: the whisper (hush's reflex), else a toast of its own beside the little word */
function sayThanks(id: string, line: string) {
	let shown = false;
	try {
		const hush = (window as unknown as { petalHush?: { reflex?: (l: string, o?: object) => unknown } }).petalHush;
		shown = typeof hush?.reflex === 'function' && hush.reflex(line, { kind: 'thanks' }) === true;
	} catch {
		shown = false;
	}
	if (!shown)
		toast.message(line, { id: `petal-thanks-${id}`, duration: thanksMs(line), description: undefined, action: undefined });
}

function deliver(id: string) {
	const fb = feedbacks.get(id);
	if (!fb || fb.line === undefined || fb.note) return; // not landed yet, or the note window still open
	feedbacks.delete(id);
	if (fb.line) sayThanks(id, fb.line); // none ready: the little word already said it landed
}

/** 💗 A27 · the note window, from ResponseMessage: open holds her line, closed (saved or not) lets it go */
export function thumbNote(id: string | undefined, open: boolean) {
	const fb = id ? feedbacks.get(id) : undefined;
	if (!id || !fb || fb.note === open) return;
	fb.note = open;
	if (!open) deliver(id);
}

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
			flying: false,
			announced: false
		});
		owe(x.m, 'thanks', 1); // 💗 A28 · what survives a reload is a verdict (a note's words never do)
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
		flying: was?.flying ?? false,
		announced: false
	};
	queue.set(v.message_id, entry);
	const fb = feedbacks.get(v.message_id);
	const begins = !!v.thumb && !fb && !v.pick; // a thumb's tap with no feedback open on this reply begins one
	if (begins) feedbacks.set(v.message_id, { asked: false, note: !!v.note });
	else if (v.thumb && fb && v.note) fb.note = true;
	// 💗 A28 · a feedback's first tap is owed THANKS, the note's save SAVED; a flip inside an open feedback nothing
	// 🍒 A29 · a pick is owed nothing: it lands without a word
	if (begins) owe(v.message_id, 'thanks', entry.gen);
	else if (!v.thumb && !v.pick) owe(v.message_id, 'saved', entry.gen);
	setMark(v.message_id, { rating: ratingOf(v.annotation), state: 'saving' });
	if (owed.has(v.message_id)) say(v.message_id, 'sent'); // a quiet flip says nothing (its failure still would)
	persist();
	pump();
}

/** her retry (the failure toast's button): a full round of tries again, said aloud */
export function thumbRetry(id: string) {
	const entry = queue.get(id);
	if (!entry) return;
	entry.tries = 0;
	entry.due = 0;
	entry.announced = false;
	setMark(id, { rating: ratingOf(entry.annotation), state: 'saving' });
	say(id, 'sent');
	persist();
	pump();
}

function pump() {
	if (pumpTimer) clearTimeout(pumpTimer);
	pumpTimer = null;
	if (typeof window === 'undefined') return;
	const now = Date.now(); // offline tries fail at once: the ladder runs, so a failure is said (and 'online' retries)
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
	const fb = feedbacks.get(entry.message_id);
	const ask = !!fb && !fb.asked; // 💗 A27 · a feedback's first landing asks for her line, once
	if (fb && ask) fb.asked = true;
	const body = JSON.stringify({
		chat_id: entry.chat_id,
		message_id: entry.message_id,
		feedback_id: entry.feedback_id,
		annotation: entry.annotation,
		model_id: entry.model_id,
		sibling_model_ids: entry.sibling_model_ids,
		meta: entry.meta,
		thanks: ask
	});
	let res: Response | null = null;
	let out: { feedback_id?: string; annotation?: Annotation; thanks?: string | null } | null = null;
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
		if (fb && ask && feedbacks.get(entry.message_id) === fb) {
			fb.line = thanksLine(out.thanks); // even if a newer verdict replaced this one: the line was taken
			deliver(entry.message_id);
		}
		const words = takeDue(entry.message_id, gen); // 💗 A28 · the clicks this landing carried, each said once
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
			// the rig answered: the row is in the database
			if (words.length) speak(entry.message_id, words);
			else landQuietly(entry.message_id);
			void tagsAfter(entry, out.annotation ?? entry.annotation);
		} else {
			speak(entry.message_id, words); // its own clicks landed; the newer verdict will say its own
			persist(); // a newer verdict waited: it goes now, onto the same row
			pump();
		}
		return;
	}

	const status = res?.status ?? 0;
	if (fb && ask && feedbacks.get(entry.message_id) === fb && fb.line === undefined) fb.asked = false; // asks again
	if (current !== entry || current.gen !== gen) return pump(); // a newer verdict replaced this one: send it
	if (status === 404) {
		// the reply or its chat is gone: nothing left to save, nothing to say
		queue.delete(entry.message_id);
		feedbacks.delete(entry.message_id);
		forgetWords(entry.message_id);
		setMark(entry.message_id, null);
		toast.dismiss(`petal-thumb-${entry.message_id}`);
		persist();
		return;
	}
	// offline, the rig out of reach, a server error, signed out: again later, then the quiet mark
	entry.tries += 1;
	entry.due = Date.now() + BACKOFF_MS[Math.min(entry.tries - 1, BACKOFF_MS.length - 1)];
	if (entry.tries >= MAX_TRIES) {
		setMark(entry.message_id, { rating: ratingOf(entry.annotation), state: 'failed' });
		if (!entry.announced) say(entry.message_id, 'failed'); // once per failure, never per try
		entry.announced = true;
	}
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
