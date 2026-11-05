// 🌙 trip markers · shared state for the status chip and the climax flags
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
import {
	getMarkers,
	getMarkersNow,
	postMarker,
	type MarkersNow,
	type MarkerTimeline,
	type MarkerVia
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

// ── climax flags, per chat ───────────────────────────────────
// message_id → the climax line's id (so a second tap can void it)
const climaxStores = new Map<string, Writable<Record<string, string>>>();
const climaxAsked = new Map<string, number>(); // chatId → when we last asked (one ask per chat, not per message)

export const climaxFor = (chatId: string) => {
	let st = climaxStores.get(chatId);
	if (!st) {
		st = writable<Record<string, string>>({});
		climaxStores.set(chatId, st);
	}
	const asked = climaxAsked.get(chatId);
	if (asked === undefined || (asked < 0 && Date.now() + asked > 60_000)) {
		climaxAsked.set(chatId, Date.now());
		const into = st;
		getMarkers(localStorage.token, { kind: 'climax', chat_id: chatId })
			.then((list) => into.set(Object.fromEntries(list.map((e) => [e.message_id, e.id]))))
			.catch(() => climaxAsked.set(chatId, -Date.now())); // offline → ask again after a minute
	}
	return st;
};

export const toggleClimax = async (chatId: string, messageId: string, markerId?: string) => {
	const st = climaxFor(chatId);
	if (markerId) {
		await postMarker(localStorage.token, {
			kind: 'void',
			via: markerVia(),
			ref: markerId,
			reason: 'unflagged'
		});
		st.update((m) => {
			const { [messageId]: _, ...rest } = m;
			return rest;
		});
		return false;
	}
	const { id } = await postMarker(localStorage.token, {
		kind: 'climax',
		via: markerVia(),
		chat_id: chatId,
		message_id: messageId,
		temp: false
	});
	st.update((m) => ({ ...m, [messageId]: id }));
	return true;
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
		toast(`🌷 trip gathered · ${where}`, {
			description: `${line.moved.length} chat${line.moved.length === 1 ? '' : 's'} moved into the trip folder`,
			duration: 15000,
			action: { label: 'undo', onClick: () => undoGather(line).catch((e) => toast.error(`🌷 ${e}`)) }
		});
	} catch {
		/* offline or not admin: nothing to offer */
	}
};
