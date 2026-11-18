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

export type ShelfPulls = {
	ok: boolean;
	why: string | null;
	from: string | null;
	body: string | null;
	strung: boolean | null; // vLLM's own word, when its notes are here
	pulls: ShelfPull[];
};

export const getPulls = async (token: string): Promise<ShelfPulls> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/petal/shelf/pulls`, {
		headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error(`the shelf answered ${res.status}`);
	return res.json();
};
