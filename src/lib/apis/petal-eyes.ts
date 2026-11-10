import { WEBUI_API_BASE_URL } from '$lib/constants';

// 👁 her eyes (slice A10) — what Petal received, byte for byte · admin-only, /api/v1/petal/eyes

export type EyesPart = { source: string; text: string; [extra: string]: unknown };

export type EyesRecord = {
	at: number;
	chat_id: string;
	message_id: string;
	model: string | null; // the OWUI model she chatted with (payload.model is the upstream name)
	req_sha: string; // sha256 of the exact bytes sent · petal-spill keeps the same hash
	round: number; // 2+ = a tool follow-up or a continue for the same reply
	to: string | null; // host:port the bytes went to
	payload: Record<string, any>;
	parts: EyesPart[];
};

export type SpillView = {
	content: string | null;
	reasoning: string | null;
	flags: unknown;
	keys: string[];
};

export type SpillFound = { path: string; view: SpillView; record: unknown };

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

export const getSpill = (token: string, req_sha: string, at?: number) =>
	call<SpillFound>(
		token,
		`${BASE}/spill?${new URLSearchParams({ req_sha, ...(at ? { at: String(at) } : {}) })}`
	);
