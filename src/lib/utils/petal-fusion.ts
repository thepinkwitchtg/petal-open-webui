// 🌕 the fusion check (slice A34) · now and then, under a finished reply, a small card asks her *how is the fusion
// so far?* with three moons: 🌕 flowing · 🌗 ignore (the neutral pass, kept as `mixed`, never a signal: this moon is
// the dismissal) · 🌑 off. one tap folds it into a tiny moon on that reply, and she can change it later
//  · the rig decides (routers/petal_thumbs.py → petal_pick.ask_fusion: the rails, then her rate, aggressive at
//    first, calming as her moons accumulate). the page only asks, once a reply is finished, sending her numbers
//    from Settings → 🌸 Petal; a yes comes back as the reply's stamp (`petal_fusion`), kept on the rig too
//  · an ask that appears on this page glows as it appears (a few soft beats, then still); one already there when a
//    chat opens rests as it is
//  · her moon rides a small queue behind the tap: the latest moon per reply wins, offline or an error tries again
//    (1 · 2 · 4 · 8 · 15 s), then a quiet ring on the moon (tap it to try again); back online or shown again, one
//    more try. a reload keeps what's still waiting, ids and moons only. it lands through the thumbs door
//    (POST /api/v1/petal/thumbs with `fusion`) as one petal_fusion row per reply, quietly: no toast, no thank-you
//  · temporary chats never ask and keep no moons (contract 0)
//  · Petal never sees any of it: the stamp is not something a request ever carries
import { writable } from 'svelte/store';
import { WEBUI_API_BASE_URL } from '$lib/constants';
import { isSavedChatId } from '$lib/utils/chatId';

export type Score = 'flowing' | 'mixed' | 'off';
export const MOONS: { score: Score; moon: string; label: string }[] = [
	{ score: 'flowing', moon: '🌕', label: 'flowing' },
	{ score: 'mixed', moon: '🌗', label: 'ignore' },
	{ score: 'off', moon: '🌑', label: 'off' }
];
export const ASK = 'how is the fusion so far?';
export const moonOf = (score: unknown) => MOONS.find((m) => m.score === score) ?? null;

export type FusionStamp = {
	asked_at: number;
	why?: string;
	stretch_from?: string | null;
	stretch_replies?: number;
	turn_index?: number;
	mode?: string | null;
	pull?: unknown;
	arm?: unknown;
	substrate?: string;
	score?: Score;
	feedback_id?: string;
	answered_at?: number;
	changes?: number;
};

// ── her numbers (Settings → 🌸 Petal) ────────────────────────────────────────────────────────────────────────
export type FusionRules = { on: boolean; start: number; floor: number };
export const FUSION_DEFAULTS: FusionRules = { on: true, start: 5, floor: 25 };
export const START_CHOICES = [3, 5, 8, 12];
export const FLOOR_CHOICES = [15, 25, 40, 60];

const whole = (v: unknown, lo: number, hi: number): number | null =>
	typeof v === 'number' && Number.isInteger(v) && v >= lo && v <= hi ? v : null;

/** her fusion settings, kept inside their ranges (the rig checks them again) */
export function fusionRules(settings: unknown): FusionRules {
	const raw = (settings as { petalFusion?: Partial<FusionRules> } | null)?.petalFusion ?? {};
	const start = whole(raw.start, 1, 100) ?? FUSION_DEFAULTS.start;
	const floor = Math.max(start, whole(raw.floor, 1, 500) ?? FUSION_DEFAULTS.floor);
	return { on: raw.on !== false, start, floor };
}

// ── the ask ─────────────────────────────────────────────────────────────────────────────────────────────────
/** the asks that appeared on this page: each glows once as it appears (an ask already there rests as it is) */
export const freshAsks = new Set<string>();

type Last = { at: string; ask: boolean; why: string; message_id: string };
let last: Last | null = null;
let once: FusionRules | null = null; // her console's `petalFusion.next()`: the next finished reply asks (rails hold)

/** a reply is finished: may it ask how the fusion is going? → its stamp when the rig said yes, else null.
 *  quiet on any failure (no answer is no) */
export async function askFusion(
	token: string,
	chatId: string,
	messageId: string,
	rules: FusionRules
): Promise<FusionStamp | null> {
	if (!token || !messageId || !isSavedChatId(chatId)) return null;
	const sent = once ?? rules;
	once = null;
	if (!sent.on) return null;
	try {
		const res = await fetch(`${WEBUI_API_BASE_URL}/petal/fusion/ask`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
			body: JSON.stringify({ chat_id: chatId, message_id: messageId, rules: sent })
		});
		if (!res.ok) return null;
		const out = (await res.json()) as { ask?: boolean; why?: string; stamp?: FusionStamp };
		last = { at: new Date().toLocaleTimeString(), ask: out.ask === true, why: String(out.why ?? ''), message_id: messageId };
		if (out.ask !== true || !out.stamp?.asked_at) return null;
		freshAsks.add(messageId);
		console.log('🌕 the fusion check asks:', out.why);
		return out.stamp;
	} catch {
		return null;
	}
}

export type FusionRate = {
	on: boolean;
	every: number;
	rate: number;
	answers: number;
	counts: Record<Score, number>;
	start: number;
	floor: number;
	half: number;
};

/** numbers only: how often a finished reply asks now, and her moons so far · null on any failure */
export async function fusionRate(token: string, rules: FusionRules): Promise<FusionRate | null> {
	try {
		const q = new URLSearchParams({ on: String(rules.on), start: String(rules.start), floor: String(rules.floor) });
		const res = await fetch(`${WEBUI_API_BASE_URL}/petal/fusion/rate?${q}`, {
			headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }
		});
		return res.ok ? await res.json() : null;
	} catch {
		return null;
	}
}

// ── her moons, behind the tap ───────────────────────────────────────────────────────────────────────────────
export type MoonState = 'saving' | 'saved' | 'failed';
export const moonMarks = writable<Record<string, MoonState>>({});

type Entry = { chat_id: string; message_id: string; score: Score; tries: number; due: number; gen: number; flying: boolean };
const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];
const KEY = 'petal-moons';
const queue = new Map<string, Entry>();
let pumpTimer: ReturnType<typeof setTimeout> | null = null;

function mark(id: string, state: MoonState | null) {
	moonMarks.update((all) => {
		const next = { ...all };
		if (state) next[id] = state;
		else delete next[id];
		return next;
	});
}

function persist() {
	try {
		const items = [...queue.values()].map((e) => ({ c: e.chat_id, m: e.message_id, s: e.score }));
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
	for (const x of (raw?.items ?? []) as Record<string, unknown>[]) {
		if (typeof x?.m !== 'string' || typeof x?.c !== 'string' || !isSavedChatId(x.c) || !moonOf(x.s)) continue;
		if (queue.has(x.m)) continue;
		queue.set(x.m, { chat_id: x.c, message_id: x.m, score: x.s as Score, tries: 0, due: 0, gen: 1, flying: false });
		mark(x.m, 'saving');
	}
}

/** her moon on an asked reply: it replaces whatever this reply still had waiting */
export function landMoon(chatId: string, messageId: string, score: Score) {
	if (!messageId || !isSavedChatId(chatId) || !moonOf(score)) return;
	const was = queue.get(messageId);
	queue.set(messageId, {
		chat_id: chatId,
		message_id: messageId,
		score,
		tries: 0,
		due: 0,
		gen: (was?.gen ?? 0) + 1,
		flying: was?.flying ?? false
	});
	mark(messageId, 'saving');
	persist();
	pump();
}

/** her tap on a quiet ring: a full round of tries again */
export function retryMoon(messageId: string) {
	const entry = queue.get(messageId);
	if (!entry) return;
	entry.tries = 0;
	entry.due = 0;
	mark(messageId, 'saving');
	pump();
}

function pump() {
	if (pumpTimer) clearTimeout(pumpTimer);
	pumpTimer = null;
	if (typeof window === 'undefined') return;
	const now = Date.now();
	let next = Infinity;
	for (const entry of queue.values()) {
		if (entry.flying || entry.tries >= BACKOFF_MS.length) continue; // a quiet ring waits for a tap or a look
		if (entry.due <= now) void send(entry);
		else next = Math.min(next, entry.due);
	}
	if (next < Infinity) pumpTimer = setTimeout(pump, next - now);
}

async function send(entry: Entry) {
	const token = typeof localStorage !== 'undefined' ? localStorage.token : '';
	if (!token) {
		entry.due = Date.now() + 2000;
		return pump();
	}
	entry.flying = true;
	const gen = entry.gen;
	let res: Response | null = null;
	try {
		res = await fetch(`${WEBUI_API_BASE_URL}/petal/thumbs`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
			body: JSON.stringify({ chat_id: entry.chat_id, message_id: entry.message_id, annotation: {}, fusion: entry.score }),
			keepalive: true // a moon tapped right before the tab closes still lands
		});
	} catch {
		res = null;
	}
	entry.flying = false;
	const current = queue.get(entry.message_id);
	if (current && current !== entry) current.flying = false;
	if (current !== entry || entry.gen !== gen) return pump(); // a newer moon waited: it goes now, onto the same row

	if (res?.ok) {
		queue.delete(entry.message_id);
		persist();
		mark(entry.message_id, 'saved');
		setTimeout(() => moonMarks.update((all) => {
			if (all[entry.message_id] !== 'saved') return all;
			const next = { ...all };
			delete next[entry.message_id];
			return next;
		}), 1200);
		return pump();
	}
	if (res && [400, 404, 422].includes(res.status)) {
		queue.delete(entry.message_id); // the rig refused it for good (an ask it doesn't know, a chat gone)
		persist();
		mark(entry.message_id, 'failed');
		console.warn('🌕 the moon was refused:', res.status);
		return pump();
	}
	entry.tries += 1;
	if (entry.tries >= BACKOFF_MS.length) mark(entry.message_id, 'failed');
	else entry.due = Date.now() + BACKOFF_MS[entry.tries - 1];
	pump();
}

if (typeof window !== 'undefined') {
	restore();
	const again = () => {
		for (const entry of queue.values()) if (entry.tries >= BACKOFF_MS.length) entry.tries = BACKOFF_MS.length - 1;
		pump();
	};
	window.addEventListener('online', again);
	document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && again());
	pump();
	// her console: `petalFusion.last` (the last ask and why) · `petalFusion.next()` (the next finished reply asks,
	// the rails still hold) · `petalFusion.waiting` (moons still on their way)
	(window as unknown as Record<string, unknown>).petalFusion = {
		get last() {
			return last;
		},
		next: (on = true) => {
			once = on ? { on: true, start: 1, floor: 1 } : null;
			return on;
		},
		get waiting() {
			return queue.size;
		}
	};
}
