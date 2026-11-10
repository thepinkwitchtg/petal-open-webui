import { WEBUI_API_BASE_URL } from '$lib/constants';
import type { After, Outcome, Quality } from '$lib/apis/petal-markers';

// 📔 her diary (slice A11) — admin-only router at /api/v1/petal/diary

export type DiaryNote = {
	type: 'note';
	id: string;
	at: number;
	text: string;
	petal_sees: boolean;
	via: string;
	amended: boolean;
};
type Base = { id: string; at: number; amended: boolean; temp: boolean };
export type DiaryOrbit = Base & {
	type: 'orbit';
	outcome: Outcome;
	note: string | null;
	chat_id: string | null;
	message_id: string | null;
};
export type DiaryClimax = Base & {
	type: 'climax';
	quality: Quality;
	after: After;
	note: string | null;
	chat_id: string | null;
	message_id: string | null;
};
export type DiaryTrip = Base & {
	type: 'trip';
	emoji: string;
	label: string;
	substance: string;
	dose: string | null;
	dose_unit: string | null;
	strain: string | null;
	tier: string | null;
	note: string | null;
	end: number | null;
	ended_by: 'manual' | 'auto' | null;
	integration: { opens_at: number; closes_at: number } | null;
	mutated: boolean;
	purged: boolean;
};
// 8b · 🔥 a vow (its start, carrying how it stands) and its end (released or fulfilled)
export type DiaryVow = Base & {
	type: 'vow';
	vow: string;
	words: string;
	until: number;
	total_days: number;
	ended_by: 'release' | 'fulfilled' | null;
	reason: string | null;
	alive: boolean;
	day: number | null;
};
export type DiaryVowEnd = Base & {
	type: 'vow_end';
	vow: string;
	how: 'released' | 'fulfilled';
	reason: string | null;
	days_kept: number;
	total_days: number;
	ref: string;
};
export type DiaryItem = DiaryNote | DiaryOrbit | DiaryClimax | DiaryTrip | DiaryVow | DiaryVowEnd;

const BASE = `${WEBUI_API_BASE_URL}/petal/diary`;

const call = async <T>(token: string, url: string, init: RequestInit = {}): Promise<T> => {
	const res = await fetch(url, {
		...init,
		headers: {
			Accept: 'application/json',
			...(init.body ? { 'Content-Type': 'application/json' } : {}),
			...(token && { authorization: `Bearer ${token}` })
		}
	});
	const json = await res.json().catch(() => ({}));
	if (!res.ok) throw json?.detail ?? `the diary answered ${res.status}`;
	return json as T;
};

export const getDiaryStream = (
	token: string,
	q: { q?: string; before?: number; limit?: number } = {}
) =>
	call<{ items: DiaryItem[]; more: boolean }>(
		token,
		`${BASE}/stream?${new URLSearchParams(
			Object.entries(q)
				.filter(([, v]) => v !== undefined && v !== null && v !== '')
				.map(([k, v]) => [k, String(v)])
		)}`
	);

export const postDiary = (token: string, body: Record<string, unknown>) =>
	call<{ id: string }>(token, BASE, { method: 'POST', body: JSON.stringify(body) });
