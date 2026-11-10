import { WEBUI_API_BASE_URL } from '$lib/constants';

// 🌙 trip markers (sprint contract 1) — admin-only router at /api/v1/petal/markers

export type MarkerVia = 'owui' | 'phone' | 'petal' | 'hand';

export type MarkerStrain = {
	key: string;
	label: string;
	potency: number | null; // null = not tuned yet: the strain shows its note and changes nothing
	duration_x: number | null;
	note: string | null;
};

export type MarkerTimeline = {
	id: string;
	substance: string;
	label: string;
	emoji: string;
	dose: string | null;
	dose_unit: string | null;
	dose_eff: number | null; // the dose after the strain's potency (what the curve + tiers read)
	strain: MarkerStrain | null;
	tier: { label: string; from: number; has_note: boolean } | null;
	note: string | null;
	temp: boolean;
	taken_at: number;
	ends_at: number | null;
	expected_end: number | null; // after mutation / purge
	end: number | null;
	ended_by: 'manual' | 'auto' | null;
	why_no_end: string | null;
	peak: [number, number] | null;
	integration: {
		id: string;
		opens_at: number;
		closes_at: number;
		closed_by: 'manual' | 'auto';
		empty: boolean;
	} | null;
	amended: boolean;
	mutated: { id: string; at: number } | null;
	purged: { id: string; at: number } | null;
	can_mutate: boolean;
	can_purge: boolean;
	harvested: Record<'trip' | 'integration', { id: string; at: number; folder: string } | null>;
	phase?: 'upcoming' | 'peak' | 'active' | 'integration' | 'over';
};

// A11 · ✧ an orbit's outcome once she knows it (null = still open)
export type Outcome = 'held' | 'leaked' | null;

export type MarkerWindow = {
	id: string;
	source: 'status' | 'manual' | 'orbit'; // an orbit window's id is the orbit's own id
	outcome?: Outcome;
	chat_id?: string | null;
	message_id?: string | null;
	status_ref?: string;
	status?: MarkerTimeline; // the status a derived window grew from (👽 stays reachable after its end)
	label: string | null;
	note: string | null;
	opens_at: number;
	closes_at: number;
	closed_by: 'manual' | 'auto';
	temp: boolean;
};

export type MarkerSubstance = {
	key: string;
	label: string;
	emoji: string;
	dose_unit: string | null;
	needs_dose: boolean; // a `curve` substance: no number → no end, so "set" waits for one
	strain_default: string | null;
	strains: MarkerStrain[];
	mutation_h: number | null; // 👽 stays on until taken_at + this
	purge_after_h: number | null; // the end moves to purge + this, if earlier
	tiers: { from: number; label: string }[];
};

export type MarkersNow = {
	now: number;
	status: MarkerTimeline | null;
	also: MarkerTimeline[];
	integration: MarkerWindow | null; // a trip's (or a hand-opened) window leads, an orbit's follows
	integrations?: MarkerWindow[]; // every open window
	last_dose: Record<string, string>;
	table: MarkerSubstance[];
};

export type MarkerPreview = {
	duration_h: number | null;
	integration_from: number;
	peak_h: [number, number] | null;
	tier: { label: string; from: number } | null;
	why_no_end: string | null;
	dose_unit: string | null;
	dose_eff: number | null;
	strain: MarkerStrain | null;
};

const BASE = `${WEBUI_API_BASE_URL}/petal/markers`;

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
	if (!res.ok) throw json?.detail ?? `trip markers answered ${res.status}`;
	return json as T;
};

export const getMarkersNow = (token: string) => call<MarkersNow>(token, `${BASE}/now`);

export const previewDose = (
	token: string,
	substance: string,
	dose: string | null,
	strain: string | null = null
) =>
	call<MarkerPreview>(
		token,
		`${BASE}/preview?${new URLSearchParams({
			substance,
			...(dose ? { dose } : {}),
			...(strain ? { strain } : {})
		})}`
	);

export const getMarkers = (
	token: string,
	q: { from?: number; to?: number; kind?: string; chat_id?: string; include_void?: boolean } = {}
) =>
	call<any[]>(
		token,
		`${BASE}?${new URLSearchParams(
			Object.entries(q)
				.filter(([, v]) => v !== undefined && v !== null && v !== '')
				.map(([k, v]) => [k, String(v)])
		)}`
	);

export const postMarker = (token: string, body: Record<string, unknown>) =>
	call<{ id: string }>(token, BASE, { method: 'POST', body: JSON.stringify(body) });

// A6 · a new status, past or present, with her real end · dry_run previews the very same lines
export type TripResult = {
	id: string | null;
	timeline: MarkerTimeline;
	due: ('trip' | 'integration')[];
	lines: string[];
	written: boolean;
};
export const postTrip = (token: string, body: Record<string, unknown>) =>
	call<TripResult>(token, `${BASE}/trip`, { method: 'POST', body: JSON.stringify(body) });
