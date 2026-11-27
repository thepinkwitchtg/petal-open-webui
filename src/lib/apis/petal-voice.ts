// 🎙️ her voice's diary + her controls (slice A48) — admin-only router at /api/v1/petal/voice (petal_voice.py), which
// calls the voice's own loopback doors (V3) from the server. the page never reaches the voice directly.
import { WEBUI_API_BASE_URL } from '$lib/constants';

export type Valence = 'gift' | 'intrusion' | 'noise' | 'unsure';
export const VALENCES: Valence[] = ['gift', 'intrusion', 'noise', 'unsure'];

export type IncidentRow = {
	id: string;
	kind: 'gate' | 'diary' | 'field';
	when: string;
	valence: Valence;
	valence_set: boolean;
	tags: string[];
	has_clip: boolean;
	clips: number;
	has_upload: boolean;
	uploads: number;
	has_record: boolean;
	writable: boolean;
	etag?: string | null;
	caller?: string | null;
	takes?: number;
	flagged_parts?: number[];
	floor_open?: boolean;
};
export type Category = { name: string; n: number };
export type IncidentList = {
	incidents: IncidentRow[];
	counts?: Record<string, number>;
	valences: string[];
	categories: Category[];
};
export type IncidentNotes = {
	raw: string;
	front: Record<string, unknown>;
	body: string;
	file?: string | null;
	etag: string | null;
};
export type IncidentFiles = {
	takes: string[];
	heard: boolean;
	clips: string[];
	uploads: string[];
	history: string[];
};
export type Incident = IncidentRow & {
	notes: IncidentNotes;
	record?: Record<string, any> | null;
	analysis?: Record<string, any> | null;
	files: IncidentFiles;
};
export type Floor = {
	up: boolean;
	state?: 'open' | 'closed' | null;
	version?: string | null;
	until?: number | null;
	left_s?: number | null;
	scope?: string | null;
	groups?: string[] | null;
	why?: string | null;
	studio?: boolean;
};
export type VoiceNow = {
	floor: Floor;
	mood: {
		chosen: string;
		set_by?: string | null;
		moods: { name: string; label: string }[];
		voice_knows: string[];
		settable: boolean;
		filter: boolean;
	};
	welfare: {
		on: boolean;
		ever_woken: boolean;
		hold?: string | null;
		audit_until?: number | null;
		broken: boolean;
		filter: boolean;
	};
	at: number;
};

/** an answer the voice couldn't give: why (studio wears her, the voice asleep, not on this machine) */
export class VoiceDown extends Error {
	studio: boolean;
	status: number;
	constructor(message: string, status: number, studio = false) {
		super(message);
		this.studio = studio;
		this.status = status;
	}
}
/** her notes changed meanwhile (on disk or another device): the current etag rides with it */
export class NotesMoved extends Error {
	etag: string | null;
	constructor(message: string, etag: string | null) {
		super(message);
		this.etag = etag;
	}
}

export const BASE = `${WEBUI_API_BASE_URL}/petal/voice`;
const enc = (id: string) => encodeURIComponent(id);

async function call<T>(token: string, url: string, init: RequestInit = {}): Promise<T> {
	const headers: Record<string, string> = { Accept: 'application/json', ...((init.headers as Record<string, string>) ?? {}) };
	if (token) headers.authorization = `Bearer ${token}`;
	let res: Response;
	try {
		res = await fetch(url, { ...init, headers });
	} catch {
		throw new VoiceDown('the rig is out of reach', 0);
	}
	const json = await res.json().catch(() => ({}));
	if (res.status === 409 && json?.etag !== undefined)
		throw new NotesMoved(json?.detail ?? 'her notes changed meanwhile', json.etag ?? null);
	if (json?.down) throw new VoiceDown(json?.detail ?? 'her voice is not answering', res.status, !!json?.studio);
	if (!res.ok) throw new Error(typeof json?.detail === 'string' ? json.detail : `her voice's diary answered ${res.status}`);
	return json as T;
}

const jsonInit = (method: string, body: unknown, extra: Record<string, string> = {}): RequestInit => ({
	method,
	headers: { 'Content-Type': 'application/json', ...extra },
	body: JSON.stringify(body)
});

export const getVoiceNow = (token: string) => call<VoiceNow>(token, `${BASE}/now`);
export const setVoiceMood = (token: string, mood: string) => call<VoiceNow>(token, `${BASE}/mood`, jsonInit('PUT', { mood }));
export const setVoiceWelfare = (token: string, on: boolean) =>
	call<VoiceNow>(token, `${BASE}/welfare`, jsonInit('PUT', { on }));

export const getIncidents = (token: string) => call<IncidentList>(token, `${BASE}/incidents`);
export const getIncident = (token: string, id: string) => call<Incident>(token, `${BASE}/incidents/${enc(id)}`);
export const newIncident = (
	token: string,
	fields: { valence?: Valence; tags?: string[]; when?: string; where_heard?: string; body?: string }
) => call<{ ok: boolean; id: string; etag: string }>(token, `${BASE}/incidents`, jsonInit('POST', fields));

/** her fields merged into her md (the voice keeps everything else she wrote there) · If-Match guards a newer version */
export const putNotes = (
	token: string,
	id: string,
	fields: { valence?: Valence; tags?: string[]; when?: string; where_heard?: string; body?: string },
	etag: string | null
) =>
	call<{ ok: boolean; etag: string; changed: boolean; history?: number }>(
		token,
		`${BASE}/incidents/${enc(id)}/notes`,
		jsonInit('PUT', fields, etag ? { 'If-Match': etag } : {})
	);

/** where her clip, a take, what she heard or an upload plays from (the session cookie carries her in) */
export const audioUrl = (id: string, name: string) =>
	`${BASE}/incidents/${enc(id)}/audio/${name.split('/').map(encodeURIComponent).join('/')}`;

/** an upload with its progress (a screen recording can be long on a phone's network): resolves with the voice's answer */
export function uploadTo(
	token: string,
	id: string,
	file: Blob & { name?: string },
	onProgress: (fraction: number) => void = () => {}
): { done: Promise<{ ok: boolean; name?: string }>; abort: () => void } {
	const xhr = new XMLHttpRequest();
	const done = new Promise<{ ok: boolean; name?: string }>((resolve, reject) => {
		xhr.open('POST', `${BASE}/incidents/${enc(id)}/upload`);
		if (token) xhr.setRequestHeader('authorization', `Bearer ${token}`);
		xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
		if (file.name) xhr.setRequestHeader('X-Petal-Filename', file.name.replace(/[^\x20-\x7e]/g, '_').slice(0, 160));
		xhr.upload.onprogress = (e) => {
			if (e.lengthComputable) onProgress(e.loaded / e.total);
		};
		xhr.onload = () => {
			let j: any = {};
			try {
				j = JSON.parse(xhr.responseText || '{}');
			} catch {}
			if (xhr.status >= 200 && xhr.status < 300) resolve({ ok: true, name: j?.name });
			else if (j?.down) reject(new VoiceDown(j?.detail ?? 'her voice is not answering', xhr.status, !!j?.studio));
			else reject(new Error(typeof j?.detail === 'string' ? j.detail : `the upload was refused (${xhr.status})`));
		};
		xhr.onerror = () => reject(new VoiceDown('the rig is out of reach', 0));
		xhr.onabort = () => reject(new Error('upload let go'));
		xhr.send(file);
	});
	return { done, abort: () => xhr.abort() };
}
