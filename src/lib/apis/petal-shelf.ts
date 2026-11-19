import { WEBUI_API_BASE_URL } from '$lib/constants';

// 💗 her shelf, as a list of pulls for Settings → 🌸 Petal (A30 · arms) — admin-only, read where the 💗 filter
// reads it (petal-emotions' home.json → owui_view). every name comes from her shelf, at runtime.

export type ShelfPull = {
	name: string; // as her shelf names it
	kind: 'blend' | 'string';
	id: string; // a blend's slug, a string's id (what the door sends)
	ready: boolean; // a waiting blend can't pull yet
	waiting?: number | null;
	range?: [number, number]; // a string's card range
};

// A30b · a pull's strength search: where 90% of its belief lies, its centre, its phase
export type ShelfSearch = {
	cap: number; // 0.5, or where the pull's card ends
	lo: number;
	hi: number;
	centre: number;
	width: number;
	phase: 'searching' | 'narrowing' | 'stable';
	steps: number; // arms she picked
	reopens: number;
};

export type ShelfPulls = {
	ok: boolean;
	why: string | null;
	from: string | null;
	body: string | null;
	strung: boolean | null; // vLLM's own word, when its notes are here
	pulls: ShelfPull[];
	search?: Record<string, ShelfSearch>; // by `kind:id`
};

export const getPulls = async (token: string): Promise<ShelfPulls> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/petal/shelf/pulls`, {
		headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error(`the shelf answered ${res.status}`);
	return res.json();
};

// A30b · picks that come to her: should her next reply in this chat be a pick? (petal_pick.should_offer, asked
// after each of her turns · nothing asks yet) · quiet on any failure: no answer is no
export const getOffer = async (
	token: string,
	chatId: string,
	messageId: string
): Promise<{ offer: boolean; why: string } | null> => {
	try {
		const q = new URLSearchParams({ chat_id: chatId, message_id: messageId });
		const res = await fetch(`${WEBUI_API_BASE_URL}/petal/pick/offer?${q}`, {
			headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }
		});
		return res.ok ? await res.json() : null;
	} catch {
		return null;
	}
};
