// 🌙 trip markers · shared state for the status chip and the ✧ marks on replies
// the server is the truth (it replays markers.jsonl and writes auto-transitions when it
// notices a boundary); between reads the page only re-derives the phase from the
// timestamps it was given. no polling: a read happens on mount, when the page comes
// back into view, after every action, and when a boundary passes while she's looking.
import { writable, type Writable } from 'svelte/store';
import { toast } from 'svelte-sonner';
import {
	getChatById,
	getChatPinnedStatusById,
	toggleChatPinnedStatusById,
	updateChatFolderIdById
} from '$lib/apis/chats';
import { refreshSidebar } from '$lib/stores/chatList';
import { isSavedChatId } from '$lib/utils/chatId';
import {
	getMarkers,
	getMarkersNow,
	postMarker,
	postTrip,
	type MarkersNow,
	type MarkerTimeline,
	type MarkerVia,
	type MarkerVow,
	type After,
	type Outcome,
	type Quality
} from '$lib/apis/petal-markers';

export const markersNow = writable<MarkersNow | null>(null);
export const markersError = writable<string | null>(null);

let inflight: Promise<void> | null = null;
export const refreshMarkers = (): Promise<void> => {
	if (inflight) return inflight;
	inflight = (async () => {
		try {
			markersNow.set(await getMarkersNow(localStorage.token));
			markersError.set(null);
		} catch (e) {
			markersError.set(`${e}`);
		} finally {
			inflight = null;
		}
	})();
	return inflight;
};

export const markerVia = (): MarkerVia =>
	typeof matchMedia !== 'undefined' && matchMedia('(pointer: coarse)').matches ? 'phone' : 'owui';

export const writeMarker = async (body: Record<string, unknown>) => {
	const r = await postMarker(localStorage.token, { via: markerVia(), ...body });
	await refreshMarkers();
	return r;
};

/** a new status, past or present (one lock: the start, then her real end) · dry_run writes nothing */
export const writeTrip = async (body: Record<string, unknown>) => {
	const r = await postTrip(localStorage.token, { via: markerVia(), ...body });
	if (r.written) await refreshMarkers();
	return r;
};

// ── time ─────────────────────────────────────────────────────
export const nowS = () => Math.floor(Date.now() / 1000);

export type Phase = 'upcoming' | 'peak' | 'active' | 'integration' | 'over';

export const phaseAt = (tl: MarkerTimeline, t: number): Phase => {
	if (t < tl.taken_at) return 'upcoming';
	if (tl.end === null || t < tl.end) {
		if (tl.peak && tl.peak[0] <= t && t < tl.peak[1]) return 'peak';
		return 'active';
	}
	const ig = tl.integration;
	if (ig && !ig.empty && ig.opens_at <= t && t < ig.closes_at) return 'integration';
	return 'over';
};

/** the next moment the chip's picture changes on its own (a phase edge), or null */
export const nextEdge = (n: MarkersNow | null, t: number): number | null => {
	if (!n) return null;
	const edges: number[] = [];
	const s = n.status;
	if (s) {
		edges.push(s.taken_at);
		if (s.peak) edges.push(s.peak[0], s.peak[1]);
		if (s.end !== null) edges.push(s.end);
		if (s.integration) edges.push(s.integration.opens_at, s.integration.closes_at);
	}
	if (n.integration) edges.push(n.integration.closes_at);
	const future = edges.filter((e) => e > t);
	return future.length ? Math.min(...future) : null;
};

/** 42m · 5h 12m · 2d 4h */
export const span = (seconds: number) => {
	const m = Math.max(0, Math.round(seconds / 60));
	if (m < 60) return `${m}m`;
	const h = Math.floor(m / 60);
	if (h < 24) return `${h}h${m % 60 ? ` ${String(m % 60).padStart(2, '0')}m` : ''}`;
	const d = Math.floor(h / 24);
	return `${d}d${h % 24 ? ` ${h % 24}h` : ''}`;
};

const WEEK = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const pad = (n: number) => String(n).padStart(2, '0');

/** 21:40 today · sat 17:40 within a week · nov 8 17:40 beyond */
export const clock = (s: number, t: number = nowS()) => {
	const d = new Date(s * 1000);
	const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
	const today = new Date(t * 1000);
	if (d.toDateString() === today.toDateString()) return hm;
	if (Math.abs(s - t) < 6 * 86400) return `${WEEK[d.getDay()]} ${hm}`;
	return `${d.toLocaleString('en', { month: 'short' }).toLowerCase()} ${d.getDate()} ${hm}`;
};

export const doseText = (dose: string | null, unit: string | null) => {
	if (dose === null || dose === undefined || dose === '') return '';
	return /[a-zµ]/i.test(dose) || !unit ? dose : `${dose} ${unit}`;
};

// ── ✧ marks on replies, per chat (slices A11 · A11.1) ────────
// ✧ an orbit is the primary gesture: one tap, its outcome open until she says held or leaked.
// 🌊 a climax is reached from the ✧ menu, deliberate. its quality (🔮 owned · 💗 received ·
// 🕳 hollow) and after-feel (fed · neutral · hollow) stay on the event, set later by Petal's
// digestion layer: no picker sets them (A13).
// both may live away from any chat (the diary); a temp chat keeps them without any link
// (contract 0), so there the page only remembers what it tapped itself.
export type ReplyMarks = {
	orbit?: { id: string; at: number; outcome: Outcome };
	climax?: { id: string; at: number; quality: Quality; after: After };
};
type Marks = Record<string, ReplyMarks>;

const markStores = new Map<string, Writable<Marks>>();
const markAsked = new Map<string, number>(); // chatId → when we last asked (one ask per chat, not per message)

export const marksFor = (chatId: string) => {
	let st = markStores.get(chatId);
	if (!st) {
		st = writable<Marks>({});
		markStores.set(chatId, st);
	}
	if (!isSavedChatId(chatId)) return st;
	const asked = markAsked.get(chatId);
	if (asked === undefined || (asked < 0 && Date.now() + asked > 60_000)) {
		markAsked.set(chatId, Date.now());
		const into = st;
		Promise.all([
			getMarkers(localStorage.token, { kind: 'orbit', chat_id: chatId }),
			getMarkers(localStorage.token, { kind: 'climax', chat_id: chatId })
		])
			.then(([orbits, climaxes]) => {
				const m: Marks = {};
				for (const o of orbits)
					if (o.message_id)
						m[o.message_id] = {
							...m[o.message_id],
							orbit: { id: o.id, at: o.at, outcome: o.outcome ?? null }
						};
				for (const c of climaxes)
					if (c.message_id)
						m[c.message_id] = {
							...m[c.message_id],
							climax: { id: c.id, at: c.at, quality: c.quality ?? null, after: c.after ?? null }
						};
				into.update((cur) => {
					// a tap that landed while we were asking wins over the older read
					const out: Marks = { ...m };
					for (const [k, v] of Object.entries(cur)) out[k] = { ...out[k], ...v };
					return out;
				});
			})
			.catch(() => markAsked.set(chatId, -Date.now())); // offline → ask again after a minute
	}
	return st;
};

const patchMarks = (
	chatId: string,
	messageId: string,
	patch: Partial<ReplyMarks> | null,
	drop?: keyof ReplyMarks
) =>
	marksFor(chatId).update((m) => {
		const cur: ReplyMarks = { ...(m[messageId] ?? {}) };
		if (drop) delete cur[drop];
		Object.assign(cur, patch ?? {});
		const out = { ...m, [messageId]: cur };
		if (!cur.orbit && !cur.climax) delete out[messageId];
		return out;
	});

/** every open chat's view of one mark, patched in place (the diary and the chip act by id) */
const patchById = (id: string, fn: (v: ReplyMarks) => ReplyMarks) => {
	for (const st of markStores.values())
		st.update((m) => {
			let hit = false;
			const out: Marks = {};
			for (const [k, v] of Object.entries(m)) {
				if (v.orbit?.id === id || v.climax?.id === id) {
					hit = true;
					out[k] = fn(v);
				} else out[k] = v;
			}
			return hit ? out : m;
		});
};

const post = (body: Record<string, unknown>) =>
	postMarker(localStorage.token, { via: markerVia(), ...body });

const anchor = (chatId: string, messageId: string) =>
	isSavedChatId(chatId) ? { chat_id: chatId, message_id: messageId, temp: false } : { temp: true };

// ── 🔥 the vow's brake (8b · A13) ──────────────────────────
/** the start of today, on her clock (the rig keeps the same one) */
export const todayStart = (t: number = nowS()) => {
	const d = new Date(t * 1000);
	d.setHours(0, 0, 0, 0);
	return Math.floor(d.getTime() / 1000);
};

/** the moment a new mark on a reply lands at: a reply from a past day is annotated at its own
 * moment (so it sits on its day, and no integration window opens now); today's is the tap itself */
export const markMoment = (msgAt: number | null | undefined): number | undefined =>
	msgAt && msgAt < todayStart() ? Math.floor(msgAt) : undefined;

/** while a vow is alive, today's moments hold back both 🌊 a climax and ✧ an orbit (an orbit is
 * a climax held); a past day stays open. mirrors the server's own check (core._brake). */
export const vowBrakes = (vow: MarkerVow | null | undefined, moment: number = nowS()) =>
	!!vow && !vow.ended_by && nowS() < vow.until && moment >= todayStart();

/** 🔥 a vow, committed (8b): its name, until when, her words · it begins now, never backdated */
export const commitVow = async (vow: string, until: number, words: string) => {
	const r = await post({ kind: 'vow.start', vow: vow.trim(), until, words: words.trim() });
	await refreshMarkers();
	return r;
};

/** 🔥 a release: a conscious act, her reason kept beside it */
export const releaseVow = async (id: string, reason: string) => {
	await post({ kind: 'vow.release', ref: id, reason: reason.trim() });
	await refreshMarkers();
};

/** ✧ one tap on a reply: an orbit with its outcome open (it opens its own integration window) ·
 * `at` = markMoment(the reply's time): only a past day's reply carries its own moment */
export const castOrbit = async (chatId: string, messageId: string, at?: number) => {
	const { id } = await post({ kind: 'orbit', outcome: null, ...(at ? { at } : {}), ...anchor(chatId, messageId) });
	patchMarks(chatId, messageId, { orbit: { id, at: at ?? nowS(), outcome: null } });
	refreshMarkers();
	return id;
};

/** ✧ an orbit away from any chat (the diary's quick button) */
export const castFreeOrbit = async () => {
	const { id } = await post({ kind: 'orbit', outcome: null, temp: false });
	refreshMarkers();
	return id;
};

/** 🌊 a climax away from any chat (the diary's quick button · contract 1 bends for it, A11.1) */
export const castFreeClimax = async () => {
	const { id } = await post({ kind: 'climax', quality: null, after: null, temp: false });
	refreshMarkers();
	return id;
};

/** held · leaked · or back to open (null), from the ✧ menu, the chip or the diary */
export const setOutcome = async (orbitId: string, outcome: Outcome) => {
	await post({ kind: 'amend', ref: orbitId, fields: { outcome } });
	patchById(orbitId, (v) => (v.orbit ? { ...v, orbit: { ...v.orbit, outcome } } : v));
	refreshMarkers();
};

/** a climax's quality and/or after-feel (null clears one), from the ✧ menu or the diary */
export const setClimax = async (climaxId: string, fields: { quality?: Quality; after?: After }) => {
	await post({ kind: 'amend', ref: climaxId, fields });
	patchById(climaxId, (v) => (v.climax ? { ...v, climax: { ...v.climax, ...fields } } : v));
	refreshMarkers();
};

/** unflag: the mark is voided (kept in the log, gone from the view) */
export const unflagMark = async (
	chatId: string,
	messageId: string,
	which: keyof ReplyMarks,
	id: string
) => {
	await post({ kind: 'void', ref: id, reason: 'unflagged' });
	patchMarks(chatId, messageId, null, which);
	refreshMarkers();
};

/** the ✧ menu's choice for a reply: orbit · held, orbit · leaked, or 🌊 climax. from an orbit,
 * held/leaked is one amend (tap the lit one again → open); switching between orbit and climax
 * writes the new mark at the old one's moment, then the old one steps aside (a void). */
export const markAs = async (
	chatId: string,
	messageId: string,
	cur: ReplyMarks | null,
	target: 'held' | 'leaked' | 'climax',
	moment?: number // a reply without a mark yet: markMoment(its time)
) => {
	if (!cur?.orbit && !cur?.climax) {
		const kind = target === 'climax' ? 'climax' : 'orbit';
		const extra = target === 'climax' ? { quality: null, after: null } : { outcome: target };
		const { id } = await post({ kind, ...extra, ...(moment ? { at: moment } : {}), ...anchor(chatId, messageId) });
		const at = moment ?? nowS();
		patchMarks(
			chatId,
			messageId,
			target === 'climax' ? { climax: { id, at, quality: null, after: null } } : { orbit: { id, at, outcome: target } }
		);
	} else if (target === 'climax') {
		if (cur?.climax || !cur?.orbit) return;
		const at = cur.orbit.at;
		const { id } = await post({ kind: 'climax', quality: null, after: null, at, ...anchor(chatId, messageId) });
		await post({ kind: 'void', ref: cur.orbit.id, reason: 'it was a climax' });
		patchMarks(chatId, messageId, { climax: { id, at, quality: null, after: null } }, 'orbit');
	} else if (cur?.orbit) {
		return setOutcome(cur.orbit.id, cur.orbit.outcome === target ? null : target);
	} else if (cur?.climax) {
		const at = cur.climax.at;
		const { id } = await post({ kind: 'orbit', outcome: target, at, ...anchor(chatId, messageId) });
		await post({ kind: 'void', ref: cur.climax.id, reason: 'it was an orbit' });
		patchMarks(chatId, messageId, { orbit: { id, at, outcome: target } }, 'climax');
	} else return;
	refreshMarkers();
};

// ── 🌷 trip gathered · undo (contract 1.1) ───────────────────
// the ledger gathers a trip's chats into its OWUI folder when the harvest lands and keeps
// every move on the harvest line. OWUI only offers the undo, quietly, once per device:
// the latest gathered line it hasn't shown yet. seen ids (ids only, no content) live in
// localStorage. undo puts each chat back in its previous folder + pin — but only a chat
// that still sits in the trip folder (anything rearranged since is left alone). folders
// are never deleted.
type Move = { chat_id: string; prev_folder: string | null; prev_pinned: boolean };
const SEEN_KEY = 'petal-trip-gathered-seen';
const LOOKBACK_S = 14 * 86400;

const seenIds = (): string[] => {
	try {
		const v = JSON.parse(localStorage.getItem(SEEN_KEY) ?? '[]');
		return Array.isArray(v) ? v : [];
	} catch {
		return [];
	}
};
const markSeen = (ids: string[]) => {
	try {
		localStorage.setItem(SEEN_KEY, JSON.stringify([...new Set([...seenIds(), ...ids])].slice(-200)));
	} catch {
		/* private mode: it may offer again next time, nothing worse */
	}
};

const undoGather = async (line: { owui_folder: string | null; moved: Move[] }) => {
	const token = localStorage.token;
	let back = 0;
	let left = 0;
	for (const m of line.moved) {
		try {
			const chat = await getChatById(token, m.chat_id);
			if (!chat || (line.owui_folder && chat.folder_id !== line.owui_folder)) {
				left += 1; // moved since, or gone: hers now, not ours to pull back
				continue;
			}
			await updateChatFolderIdById(token, m.chat_id, m.prev_folder ?? undefined);
			const pinned = !!(await getChatPinnedStatusById(token, m.chat_id));
			if (pinned !== !!m.prev_pinned) await toggleChatPinnedStatusById(token, m.chat_id);
			back += 1;
		} catch {
			left += 1;
		}
	}
	await refreshSidebar(token).catch(() => {});
	toast.success(
		`🌷 ${back} chat${back === 1 ? '' : 's'} back where they lived${left ? ` · ${left} left as they are` : ''}`
	);
};

let gatherOffered = false;
export const offerGatherUndo = async () => {
	if (gatherOffered) return; // once per page load
	gatherOffered = true;
	try {
		const lines = (await getMarkers(localStorage.token, {
			kind: 'harvest',
			from: nowS() - LOOKBACK_S
		})) as any[];
		const seen = new Set(seenIds());
		const fresh = lines
			.filter((e) => e.via === 'ledger' && Array.isArray(e.moved) && e.moved.length && !seen.has(e.id))
			.sort((a, b) => a.at - b.at);
		if (!fresh.length) return;
		markSeen(fresh.map((e) => e.id)); // quiet: offered once, the latest only
		const line = fresh[fresh.length - 1];
		const where = String(line.folder ?? '').replace(/\//g, ' · ');
		toast.message(`🌷 trip gathered · ${where}`, {
			description: `${line.moved.length} chat${line.moved.length === 1 ? '' : 's'} moved into the trip folder`,
			action: { label: 'undo', onClick: () => undoGather(line).catch((e) => toast.error(`🌷 ${e}`)) }
		});
	} catch {
		/* offline or not admin: nothing to offer */
	}
};
