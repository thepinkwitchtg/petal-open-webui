import { WEBUI_API_BASE_URL } from '$lib/constants';

// 👁 her eyes (slice A10) — what Petal received, byte for byte · admin-only, /api/v1/petal/eyes

export type EyesPart = { source: string; text: string; [extra: string]: unknown };

export type EyesRecord = {
	at: number;
	chat_id: string;
	message_id: string;
	model: string | null; // the OWUI model she chatted with (payload.model is the upstream name)
	req_sha: string; // sha256 of the exact bytes sent · petal-wellspring keeps the same hash
	round: number; // 2+ = a tool follow-up or a continue for the same reply
	to: string | null; // host:port the bytes went to
	payload: Record<string, any>;
	parts: EyesPart[];
};

// 🫗 petal-wellspring (A11.1 · the source tap, every raw character before OWUI prettifies it)
export type WellMeta = {
	id?: string;
	at?: number;
	route?: string;
	path?: string;
	caller?: string;
	model?: string;
	status?: number;
	ms?: number;
	cut?: boolean;
	streamed?: boolean;
	finish?: string;
};

export type WellView = {
	content: string | null;
	reasoning: string | null;
	raw: string | null;
	flags: string[] | null;
	meta: WellMeta;
	keys: string[];
};

export type WellFound = { path: string; view: WellView; record: unknown };

const BASE = `${WEBUI_API_BASE_URL}/petal/eyes`;

const call = async <T>(token: string, url: string): Promise<T> => {
	const res = await fetch(url, {
		headers: { Accept: 'application/json', ...(token && { authorization: `Bearer ${token}` }) }
	});
	const json = await res.json().catch(() => ({}));
	if (!res.ok) throw json?.detail ?? `her eyes answered ${res.status}`;
	return json as T;
};

export const getEyes = (token: string, chat_id: string, message_id: string) =>
	call<{ rounds: EyesRecord[]; kept: 'disk' | 'ring' }>(
		token,
		`${BASE}?${new URLSearchParams({ chat_id, message_id })}`
	);

// 🧵 the rendered view (A13): the round through vLLM's own chat template, asked live, kept nowhere
export type Rendered = {
	text: string; // /tokenize → /detokenize: every special token kept
	count: number; // tokens
	max_model_len: number | null;
	asked: string; // host:port of the vLLM that rendered it
	how: string; // 'connection N' · 'PETAL_EYES_TOKENIZE_URL' · 'the record (…)'
	settings: Record<string, unknown>; // the template settings it was rendered with
	model: string | null;
};

export const getRendered = (token: string, chat_id: string, message_id: string, round: number) =>
	call<Rendered>(
		token,
		`${BASE}/rendered?${new URLSearchParams({ chat_id, message_id, round: String(round) })}`
	);

export const getWellspring = (token: string, req_sha: string, at?: number) =>
	call<WellFound>(
		token,
		`${BASE}/wellspring?${new URLSearchParams({ req_sha, ...(at ? { at: String(at) } : {}) })}`
	);
