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
//  · arms (A30): 1 in her N picks differ only in pull, one reply unsteered (chat's baseline, 0), its sibling under
//    the pull she chose from her shelf. the server draws the side, and (A30b) the strength search finds the
//    strength from her picks; this page sends her rules and stays blind: nothing on it says which reply is pulled
//    until her 💗 (the eyes hide the pull, the usage hides, both replies can wait to show together), then a quiet
//    chip shows each side's pull
//  · picks that come to her (A30b): "next reply" (the cherry by send, one tap or her key) arms one pick, then it
//    turns itself off · a share of her replies rests at 22% · and the server can ask for the next one
//    (petal_pick.should_offer, after each of her turns: nothing asks yet), which arms the same cherry
import { get, writable } from 'svelte/store';

import { getOutputText } from '$lib/components/chat/Messages/structuredOutput';
import { createMessagesList, removeAllDetails } from '$lib/utils';
import type { Verdict } from '$lib/utils/petal-thumbs';

export type ArmRules = {
	every: number; // 1 in N of her picks is an arm
	pull: string; // the pull, as her shelf names it (a ready blend or a ♡'d string) · empty: no arms
	hold: boolean; // both replies show together, once both are written (a steered one can start later)
};

// A30b · no strengths here: the strength search finds them (utils/petal_arms.py)
export const ARM_DEFAULTS: ArmRules = { every: 3, pull: '', hold: true };

export type PickRules = {
	on: boolean; // her rhythm picks for her · off by default
	rhythm: 'every' | 'share';
	every: number; // a pick on every Nth turn since the last one
	share: number; // or this share of turns, in %
	longOnly: boolean; // only when the expected reply is long
	longChars: number; // "long": the median of her last replies, in characters
	modes: Record<string, boolean>; // per forge mode (its key): false keeps picks out of it
	arms: ArmRules; // A30
};

export const PICK_DEFAULTS: PickRules = {
	on: false,
	rhythm: 'every',
	every: 5,
	share: 22, // A30b · her share: 22% of replies
	longOnly: false,
	longChars: 600,
	modes: {},
	arms: ARM_DEFAULTS
};

const clamp = (n: unknown, lo: number, hi: number, d: number) =>
	typeof n === 'number' && Number.isFinite(n) ? Math.min(hi, Math.max(lo, Math.round(n))) : d;

function armRulesOf(raw: unknown): ArmRules {
	const a = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
	return {
		every: clamp(a.every, 1, 20, ARM_DEFAULTS.every),
		pull: typeof a.pull === 'string' ? a.pull.trim().slice(0, 200) : '',
		hold: a.hold !== false
	};
}

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
		modes,
		arms: armRulesOf(s.arms)
	};
}

/** A30 · arms are on once she chose a pull from her shelf */
export const armsOn = (rules: PickRules) => rules.arms.pull !== '';
/** what a pick's send carries for the server to draw from (`petal_arms`) · null: no arms */
export const armsAsk = (rules: PickRules) =>
	armsOn(rules) ? { every: rules.arms.every, pull: rules.arms.pull } : null;
/** both replies wait to show until both are written: a steered reply can start a few seconds after its sibling
 * (vLLM can't reuse its cache for it), which would tell them apart before her pick */
export const holdsArrival = (rules: PickRules) => armsOn(rules) && rules.arms.hold;

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
	petal_pick?: {
		pair?: unknown;
		slot?: unknown;
		seed?: unknown;
		pull?: unknown;
		frame_sha?: unknown; // A29b · the request it was sent, minus its seed and pull (sha256)
		arm?: unknown; // A30 · {name, kind, id, strength, steered[, tag, asked]} on both replies of an arm
	} | null;
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
	asked: boolean; // she asked for this one (the cherry, her key, or a long press on the mode chip)
	askedWhy?: string | null; // A30b · Petal asked instead (should_offer), and why
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
	if (ask.asked) return yes(ask.askedWhy ? `Petal asked: ${ask.askedWhy}` : 'she asked');
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

/** A29b · both replies were served one frame: the same request but for their seed and pull. known only once
 * both are done (each learns its `frame_sha` at the send, the page with its last event) */
export const sameFrame = (a: Msg | undefined, b: Msg | undefined) => {
	const [x, y] = [a?.petal_pick?.frame_sha, b?.petal_pick?.frame_sha];
	return typeof x === 'string' && x !== '' && x === y;
};

/** why a pair that was asked for isn't offered (null while it still is, or could be) */
export function dissolvedWhy(history: History, id: string): string | null {
	const pair = pairOf(history, id);
	if (!pair) return null;
	const [a, b] = pair.map((x) => history.messages[x]);
	if (a.error || b.error) return 'a reply failed';
	if (reachedForTool(a) || reachedForTool(b)) return 'a reply reached for a tool';
	if (unfinished(a) || unfinished(b)) return 'a reply did not finish (stopped, cut short or empty)';
	if (a.done === true && b.done === true && !sameFrame(a, b))
		return a.petal_pick?.frame_sha && b.petal_pick?.frame_sha
			? 'the two replies were not served the same frame'
			: 'the two replies carry no frame to compare';
	return null;
}

/** the pick still waiting on this turn, if any: shown while it's the turn she's on and nothing has followed */
export function openPick(history: History, id: string): OpenPick | null {
	const pair = pairOf(history, id);
	if (!pair) return null;
	const [a, b] = pair.map((x) => history.messages[x]);
	if (history.currentId !== a.id && history.currentId !== b.id) return null;
	if (wasPicked(a) || wasPicked(b)) return null;
	if ((a.childrenIds?.length ?? 0) > 0 || (b.childrenIds?.length ?? 0) > 0) return null; // she went on
	if (dissolvedWhy(history, id)) return null; // failed · reached for a tool · unfinished · two frames
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
				pull: (m.petal_pick?.pull as unknown) ?? null,
				...(m.petal_pick?.arm ? { arm: m.petal_pick.arm } : {}) // A30 · an arm: its pull, this side's strength
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

// ── an arm, revealed after her 💗 (A30) ──────────────────────────────────────────────────────────────────
export type ArmRecord = {
	name?: string;
	kind?: 'blend' | 'string';
	id?: string;
	strength?: number;
	steered?: boolean;
	tag?: string;
	asked?: number;
};
const armOf = (m: Msg | undefined): ArmRecord | null => {
	const arm = m?.petal_pick?.arm;
	return arm && typeof arm === 'object' ? (arm as ArmRecord) : null;
};
const dial = (n: unknown) => (typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : '?');

/** a reply's pull, as the chip says it: unsteered (chat's baseline, 0), or her pull's name and its strength */
export const pullLabel = (arm: ArmRecord | null) =>
	arm?.steered ? `${arm.name || arm.id || 'a pull'} · ${dial(arm.strength)}` : 'unsteered';

export type Reveal = {
	mine: string;
	other: string;
	chosen: 'mine' | 'other' | null;
	steered: 'mine' | 'other' | null;
};

/** each side's pull, for the quiet chip under an arm: only once she picked (blind before), never for a plain pick */
export function revealOf(history: History, id: string): Reveal | null {
	const pair = pairOf(history, id);
	if (!pair) return null;
	const me = history.messages[id];
	const other = history.messages[pair[0] === id ? pair[1] : pair[0]];
	if (!wasPicked(me) && !wasPicked(other)) return null; // blind until her 💗
	const [mine, theirs] = [armOf(me), armOf(other)];
	if (!mine && !theirs) return null; // a plain pick: nothing to tell apart
	const chose = (m: Msg) => m.annotation?.petal_pick === true && m.annotation?.rating === 1;
	return {
		mine: pullLabel(mine),
		other: pullLabel(theirs),
		chosen: chose(me) ? 'mine' : chose(other) ? 'other' : null,
		steered: mine?.steered ? 'mine' : theirs?.steered ? 'other' : null
	};
}

/** what the eyes show while the pick is open: every pull hidden (the request's, the wellspring's), nothing else */
export const BLIND = '🙈 hidden until your 💗';
const PULL_KEYS = new Set(['petal_steer', 'petal_pin', 'petal_blend', 'petal_strength', 'petal_tag', 'steer']);
export function blinded<T>(value: T): T {
	if (Array.isArray(value)) return value.map((v) => blinded(v)) as T;
	if (value && typeof value === 'object') {
		const out: Record<string, unknown> = {};
		for (const [k, v] of Object.entries(value as Record<string, unknown>))
			out[k] = PULL_KEYS.has(k) ? BLIND : blinded(v);
		return out as T;
	}
	return value;
}

// ── her ask for the next send, and the glow ──────────────────────────────────────────────────────────────
/** "next reply": a pick on her next send, then it turns itself off (the cherry, her key, a long press on the
 * mode chip · or Petal's own ask, A30b) */
export const pickAsked = writable(false);
/** A30b · why Petal asked (should_offer), while her next reply waits armed · null when she asked herself */
export const pickAskWhy = writable<string | null>(null);
export const askPick = (on = !get(pickAsked), why: string | null = null) => {
	pickAskWhy.set(on ? why : null);
	pickAsked.set(on);
};
/** taken by the send that answers it */
export function takeAsk(): boolean {
	const asked = get(pickAsked);
	if (asked) pickAsked.set(false);
	pickAskWhy.set(null);
	return asked;
}
/** A30b · after a turn of hers ends, the server's answer to "should the next reply be a pick?" arms the cherry
 * (never over her own ask, never when it's already armed) */
export function offered(answer: { offer?: unknown; why?: unknown } | null | undefined): boolean {
	if (answer?.offer !== true || get(pickAsked)) return false;
	askPick(true, typeof answer.why === 'string' && answer.why ? answer.why.slice(0, 200) : 'Petal asked');
	return true;
}

/** the chosen reply glows once, quietly; the glow rests while the page is hidden */
export const pickGlow = writable<string | null>(null);

// her console: `petalPick.last` (the last send's decision and why) · `petalPick.ask()` (a pick next send)
type Last = PickDecision & { at: string; arm?: string; pulls?: { chosen: string; other: string } };
let last: Last | null = null;
export function noteDecision(decision: PickDecision) {
	last = { ...decision, at: new Date().toLocaleTimeString() };
	if (decision.pick) console.log('🍒 a pick this turn:', decision.why);
}
/** A30 · an arm the server drew and her shelf couldn't give: the pick goes on plain, and her console says why */
export function noteArm(why: string) {
	last = { ...(last ?? { pick: true, why: 'a pick' }), arm: why, at: new Date().toLocaleTimeString() };
	console.log('🍒 an arm, refused:', why);
}
/** A30 · her pick, and (an arm) each side's pull, now that she chose */
export function notePicked(history: History, chosen: string) {
	const r = revealOf(history, chosen);
	last = {
		pick: true,
		why: 'she picked',
		at: new Date().toLocaleTimeString(),
		...(r ? { pulls: { chosen: r.mine, other: r.other } } : {})
	};
	if (r) console.log(`🍒 she picked ${r.mine} over ${r.other}`);
}
/** a pair asked for and then not offered: `petalPick.last` says why (no rows are ever written for it) */
export function noteDissolved(why: string) {
	last = { pick: false, why: `the pair dissolved: ${why}`, at: new Date().toLocaleTimeString() };
	console.log('🍒 no pick after all:', why);
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
