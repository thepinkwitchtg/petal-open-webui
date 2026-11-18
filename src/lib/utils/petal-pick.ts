// 🍒 the pair generator's mind (slice A29) — some of her turns ask her to pick between two replies, so
// preference pairs are born from real use. this file holds when a turn asks (her rhythm, set in Settings →
// Petal, synced, off by default; or her ask for the next send), whether a pair is still open, and what a pick
// writes. the server builds the turn once and sends it twice (utils/petal_pick.py): both replies share the
// exact served stamp, nothing downstream fires twice, and the second never acts.
//
//  · the pick writes through the thumbs queue (A23): 👍🏻 on the chosen one, 👎🏻 on its sibling, both marked
//    `petal_pick: true` with `pick_of` (the sibling's id) and `pull` (the steer that reply was sent with), so
//    the ledger's sibling pairing makes the pair with no new pipe. no words, no thank-you, no hush: a quiet
//    glow on the chosen reply is all she sees (a failure still says so, after its tries)
//  · no pick (she just goes on): no rows, the first reply stays active, nothing nags
//  · never in temporary chats, internal or subagent turns, 🧪 tries (the server refuses those), while her voice
//    speaks, in a call, with more than one model, or when the turn could act (tools, a terminal, search, code,
//    images). never two picks in a row unless she asked
import { get, writable } from 'svelte/store';

import { getOutputText } from '$lib/components/chat/Messages/structuredOutput';
import { createMessagesList, removeAllDetails } from '$lib/utils';
import type { Verdict } from '$lib/utils/petal-thumbs';

export type PickRules = {
	on: boolean; // her rhythm picks for her · off by default
	rhythm: 'every' | 'share';
	every: number; // a pick on every Nth turn since the last one
	share: number; // or this share of turns, in %
	longOnly: boolean; // only when the expected reply is long
	longChars: number; // "long": the median of her last replies, in characters
	modes: Record<string, boolean>; // per forge mode (its key): false keeps picks out of it
};

export const PICK_DEFAULTS: PickRules = {
	on: false,
	rhythm: 'every',
	every: 5,
	share: 20,
	longOnly: false,
	longChars: 600,
	modes: {}
};

const clamp = (n: unknown, lo: number, hi: number, d: number) =>
	typeof n === 'number' && Number.isFinite(n) ? Math.min(hi, Math.max(lo, Math.round(n))) : d;

/** her rules as saved in her settings (`petalPick`), every value kept inside its range */
export function rulesOf(settings: unknown): PickRules {
	const raw = (settings as Record<string, unknown> | null)?.petalPick;
	const s = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
	const modes: Record<string, boolean> = {};
	if (s.modes && typeof s.modes === 'object')
		for (const [k, v] of Object.entries(s.modes as Record<string, unknown>))
			if (typeof v === 'boolean') modes[k] = v;
	return {
		on: s.on === true,
		rhythm: s.rhythm === 'share' ? 'share' : 'every',
		every: clamp(s.every, 1, 100, PICK_DEFAULTS.every),
		share: clamp(s.share, 1, 100, PICK_DEFAULTS.share),
		longOnly: s.longOnly === true,
		longChars: clamp(s.longChars, 50, 20000, PICK_DEFAULTS.longChars),
		modes
	};
}

type Msg = {
	id: string;
	role?: string;
	parentId?: string | null;
	childrenIds?: string[];
	content?: string;
	output?: unknown[];
	done?: boolean;
	error?: unknown;
	model?: string;
	selectedModelId?: string;
	arena?: boolean;
	annotation?: Record<string, unknown> | null;
	feedbackId?: string | null;
	petal_pick?: { pair?: unknown; slot?: unknown; seed?: unknown; pull?: unknown } | null;
};
type History = { currentId: string | null; messages: Record<string, Msg> };

/** a reply's words as she reads them */
export const wordsOf = (m: Msg | undefined): string =>
	removeAllDetails(getOutputText(m?.output as never) || m?.content || '');

const isPickReply = (m: Msg | undefined) =>
	m?.role === 'assistant' && Array.isArray(m?.petal_pick?.pair);

/** her replies along the branch, newest last */
const repliesOf = (branch: Msg[]) => branch.filter((m) => m?.role === 'assistant');

/** the turn she's answering was a pick (picked or not): never two in a row unless she asks */
export const lastWasPick = (branch: Msg[]) => isPickReply(repliesOf(branch).at(-1));

/** her turns since the last pick on this branch (all of them when there was none) */
export function turnsSincePick(branch: Msg[]): number {
	const replies = repliesOf(branch);
	let n = 0;
	for (let i = replies.length - 1; i >= 0 && !isPickReply(replies[i]); i--) n += 1;
	return n;
}

/** how long her next reply is likely to be: the median of the last three on this branch (null: none yet) */
export function expectedLength(branch: Msg[]): number | null {
	const lengths = repliesOf(branch)
		.slice(-3)
		.map((m) => wordsOf(m).length)
		.sort((a, b) => a - b);
	if (!lengths.length) return null;
	const mid = Math.floor(lengths.length / 2);
	return lengths.length % 2 ? lengths[mid] : Math.round((lengths[mid - 1] + lengths[mid]) / 2);
}

export type PickAsk = {
	asked: boolean; // she asked for this one (the shortcut, or a long press on the mode chip)
	temp: boolean; // a temporary chat
	voice: boolean; // her voice is speaking
	call: boolean; // a voice call, or the bridge
	models: number; // models answering this turn
	acting: boolean; // tools, a terminal, web search, code or images on for this turn
	mode: string | null; // the forge mode dressing it
	branch: Msg[]; // root → the reply her new message answers (her new message not in it)
	rng?: () => number;
};
export type PickDecision = { pick: boolean; why: string };

const yes = (why: string): PickDecision => ({ pick: true, why });
const no = (why: string): PickDecision => ({ pick: false, why });

/** does this send ask her to pick? (and why, for the console) */
export function decidePick(rules: PickRules, ask: PickAsk): PickDecision {
	if (ask.temp) return no('a temporary chat never picks');
	if (ask.call) return no('a call never picks');
	if (ask.voice) return no('her voice is speaking');
	if (ask.models !== 1) return no('more than one model answers');
	if (ask.acting) return no('this turn could act (tools, a terminal, search, code or images)');
	if (ask.asked) return yes('she asked');
	if (!rules.on) return no('her rhythm is off');
	if (ask.mode && rules.modes[ask.mode] === false) return no(`not in ${ask.mode}`);
	if (lastWasPick(ask.branch)) return no('never two picks in a row');
	if (rules.longOnly) {
		const expected = expectedLength(ask.branch);
		if (expected === null) return no('no reply yet to tell its length');
		if (expected < rules.longChars) return no(`the reply should be short (~${expected} characters)`);
	}
	if (rules.rhythm === 'share') {
		const roll = (ask.rng ?? Math.random)() * 100;
		return roll < rules.share ? yes(`her share (${rules.share}%)`) : no(`not this time (${rules.share}%)`);
	}
	const turn = turnsSincePick(ask.branch) + 1;
	return turn >= rules.every
		? yes(`turn ${turn} since the last pick (every ${rules.every})`)
		: no(`turn ${turn} of ${rules.every}`);
}

// ── an open pair ─────────────────────────────────────────────────────────────────────────────────────────
/** the pair this reply belongs to (its own id first or second, as the server ordered them) */
export function pairOf(history: History, id: string): [string, string] | null {
	const pair = history?.messages?.[id]?.petal_pick?.pair;
	if (!Array.isArray(pair) || pair.length !== 2) return null;
	const [a, b] = pair as unknown[];
	if (typeof a !== 'string' || typeof b !== 'string' || a === b) return null;
	if (!history.messages[a] || !history.messages[b]) return null;
	return [a, b];
}

/** a reply that reached for a tool is never compared (the second one's calls were held, never run) */
export const reachedForTool = (m: Msg | undefined) =>
	(m?.output ?? []).some((item) => (item as { type?: string })?.type === 'function_call');

/** a reply that didn't finish (stopped, or cut short) is never compared, nor one that came back empty */
export const unfinished = (m: Msg | undefined) =>
	(m?.output ?? []).some((item) => (item as { status?: string })?.status === 'incomplete') ||
	(m?.done === true && !wordsOf(m).trim());

/** already picked: a pick's verdict lives on both replies */
export const wasPicked = (m: Msg | undefined) => m?.annotation?.petal_pick === true;

export type OpenPick = { a: string; b: string; ready: boolean };

/** the pick still waiting on this turn, if any: shown while it's the turn she's on and nothing has followed */
export function openPick(history: History, id: string): OpenPick | null {
	const pair = pairOf(history, id);
	if (!pair) return null;
	const [a, b] = pair.map((x) => history.messages[x]);
	if (history.currentId !== a.id && history.currentId !== b.id) return null;
	if (wasPicked(a) || wasPicked(b)) return null;
	if ((a.childrenIds?.length ?? 0) > 0 || (b.childrenIds?.length ?? 0) > 0) return null; // she went on
	if (a.error || b.error || reachedForTool(a) || reachedForTool(b) || unfinished(a) || unfinished(b)) return null;
	return { a: a.id, b: b.id, ready: a.done === true && b.done === true };
}

// ── the pick ─────────────────────────────────────────────────────────────────────────────────────────────
type ModelInfo = { id: string; info?: { base_model_id?: string | null } };

/** the two verdicts a pick writes, shaped like a thumb's (A23): 👍🏻 the chosen one, 👎🏻 its sibling */
export function pickVerdicts(
	history: History,
	chatId: string,
	chosen: string,
	models: ModelInfo[] = []
): Verdict[] {
	const pair = pairOf(history, chosen);
	if (!pair) return [];
	const other = pair[0] === chosen ? pair[1] : pair[0];
	return [chosen, other].map((id) => {
		const m = history.messages[id];
		const sibling = id === chosen ? other : chosen;
		const model_id = m.selectedModelId ?? m.model ?? '';
		const siblings = history.messages[m.parentId ?? '']?.childrenIds ?? [];
		const sibling_model_ids =
			siblings.length > 1
				? siblings
						.filter((x) => x !== id)
						.map((x) => history.messages[x]?.selectedModelId ?? history.messages[x]?.model ?? '')
				: null;
		const base_models: Record<string, string | null> = {};
		for (const mid of [model_id, ...(sibling_model_ids ?? [])]) {
			const found = models.find((x) => x.id === mid);
			if (found) base_models[found.id] = found.info?.base_model_id ?? null;
		}
		return {
			chat_id: chatId,
			message_id: id,
			feedback_id: m.feedbackId ?? null,
			annotation: {
				...(m.annotation ?? {}),
				rating: id === chosen ? 1 : -1,
				petal_pick: true, // less preferred, not bad: a pair (DPO), never a lone negative
				pick_of: sibling,
				pull: (m.petal_pick?.pull as unknown) ?? null
			},
			model_id,
			sibling_model_ids,
			meta: {
				arena: m.arena ?? false,
				model_id: m.model,
				message_id: id,
				message_index: createMessagesList(history, id).length,
				chat_id: chatId,
				base_models
			},
			askTags: false,
			pick: true
		} as Verdict;
	});
}

// ── her ask for the next send, and the glow ──────────────────────────────────────────────────────────────
/** she asked for a pick on her next send (the shortcut, or a long press on the mode chip) */
export const pickAsked = writable(false);
export const askPick = (on = !get(pickAsked)) => pickAsked.set(on);
/** taken by the send that answers it */
export function takeAsk(): boolean {
	const asked = get(pickAsked);
	if (asked) pickAsked.set(false);
	return asked;
}

/** the chosen reply glows once, quietly; the glow rests while the page is hidden */
export const pickGlow = writable<string | null>(null);

// her console: `petalPick.last` (the last send's decision and why) · `petalPick.ask()` (a pick next send)
let last: (PickDecision & { at: string }) | null = null;
export function noteDecision(decision: PickDecision) {
	last = { ...decision, at: new Date().toLocaleTimeString() };
	if (decision.pick) console.log('🍒 a pick this turn:', decision.why);
}
if (typeof window !== 'undefined')
	(window as unknown as Record<string, unknown>).petalPick = {
		get last() {
			return last;
		},
		ask: (on = true) => askPick(on)
	};

if (typeof document !== 'undefined') {
	const mark = () =>
		document.documentElement.toggleAttribute('data-petal-hidden', document.visibilityState === 'hidden');
	document.addEventListener('visibilitychange', mark);
	mark();
}
