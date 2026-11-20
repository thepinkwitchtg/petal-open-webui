// 📷 A33 · her draft survives a reload: what she typed, the files and images already attached, and a photo the
// page was still sending, are kept in this browser's IndexedDB (private to the browser: never sent, never synced)
// beside OWUI's own copy in sessionStorage, which a phone that closed the page while its camera app was open may
// not bring back. restored when the chat opens again (only what OWUI's copy lost), cleared when she sends.
// temporary chats keep nothing, as OWUI's own drafts don't (contract 0's spirit).
//  · keys are OWUI's own (`chat-input`, `chat-input-<chat id>`, `chat-input-folder-<folder id>`: its getChatInputKey)
//  · keep(key, draft): the same draft OWUI saves (its words, its attached files, its switches), a beat later. an
//    empty composer never erases a kept draft before that chat's draft came back (a page still loading draws it
//    empty first)
//  · photo(key, file): a photo taken in the page, kept from the moment it's taken until it's attached (or sent)
//  · recall(key, owui): when OWUI's copy is gone (or came back empty), the kept draft as OWUI's own draft string ·
//    photos still unsent go back through OWUI's own input, as if the camera had just returned them
//  · drop(key): sent: nothing kept
const DB = 'petal-draft';
const STORE = 'drafts';
const KEEP_DAYS = 14;
const SETTLE_MS = 400;

type Photo = { name: string; type: string; blob: Blob; at: number };
type Kept = { key: string; at: number; draft: string | null; photos: Photo[] };

export const draftKey = (chatId: string | null | undefined) => `chat-input${chatId ? `-${chatId}` : ''}`;

let opening: Promise<IDBDatabase | null> | null = null;
function db(): Promise<IDBDatabase | null> {
	if (typeof indexedDB === 'undefined') return Promise.resolve(null);
	opening ??= new Promise((resolve) => {
		try {
			const req = indexedDB.open(DB, 1);
			req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'key' });
			req.onsuccess = () => resolve(req.result);
			req.onerror = () => resolve(null);
			req.onblocked = () => resolve(null);
		} catch {
			resolve(null);
		}
	});
	return opening;
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T | null> {
	const d = await db();
	if (!d) return null;
	return new Promise((resolve) => {
		try {
			const t = d.transaction(STORE, mode);
			const req = fn(t.objectStore(STORE));
			t.oncomplete = () => resolve(req ? (req.result ?? null) : null);
			t.onerror = t.onabort = () => resolve(null);
		} catch {
			resolve(null);
		}
	});
}

const read = (key: string) => tx<Kept | undefined>('readonly', (s) => s.get(key)).then((k) => k ?? null);
const write = (kept: Kept) => tx('readwrite', (s) => s.put(kept));
const erase = (key: string) => tx('readwrite', (s) => s.delete(key));

// writes for one key wait for each other, so a quick type-then-send never resurrects what was sent
const chains = new Map<string, Promise<unknown>>();
function inTurn(key: string, job: () => Promise<unknown>) {
	const next = (chains.get(key) ?? Promise.resolve()).then(job, job);
	chains.set(key, next);
	return next;
}

const pendingKeep = new Map<string, { draft: string; timer: ReturnType<typeof setTimeout> }>();

const emptyDraft = (d: { prompt?: unknown; files?: unknown[] }) =>
	!String(d?.prompt ?? '').trim() && !(d?.files ?? []).length;

const namesIn = (draft: string | null): Set<string> => {
	try {
		const files = (JSON.parse(draft ?? 'null')?.files ?? []) as { name?: string; status?: string }[];
		return new Set(files.filter((f) => f?.status !== 'uploading').map((f) => String(f?.name ?? '')));
	} catch {
		return new Set();
	}
};

async function store(key: string, draft: string | null) {
	const was = await read(key);
	const attached = namesIn(draft);
	const photos = (was?.photos ?? []).filter((p) => !attached.has(p.name)); // attached now: no longer needed here
	if (!draft && !photos.length) return erase(key);
	return write({ key, at: Date.now(), draft, photos });
}

const recalled = new Set<string>(); // keys whose draft came back this page (only then may an empty one erase)

/** the draft OWUI is keeping (its own shape, as it saves it), kept here too a beat later */
export function keep(key: string, draft: { prompt?: unknown; files?: unknown[] }) {
	if (typeof window === 'undefined') return;
	let text: string | null = null;
	try {
		text = emptyDraft(draft) ? null : JSON.stringify(draft);
	} catch {
		return;
	}
	if (text === null && !recalled.has(key)) return; // drawn empty before its draft came back: nothing erased
	const was = pendingKeep.get(key);
	if (was) clearTimeout(was.timer);
	const timer = setTimeout(() => {
		pendingKeep.delete(key);
		void inTurn(key, () => store(key, text));
	}, SETTLE_MS);
	pendingKeep.set(key, { draft: text ?? '', timer });
}

/** write what's waiting now (the page may be about to leave: the phone's camera app) */
export function flush() {
	for (const [key, p] of pendingKeep) {
		clearTimeout(p.timer);
		pendingKeep.delete(key);
		void inTurn(key, () => store(key, p.draft || null));
	}
}

/** a photo taken in the page, kept from this moment until it's attached (or sent) */
export function photo(key: string, file: File) {
	return inTurn(key, async () => {
		const was = await read(key);
		const photos = [...(was?.photos ?? []).filter((p) => p.name !== file.name)];
		photos.push({ name: file.name, type: file.type, blob: file, at: Date.now() });
		return write({ key, at: Date.now(), draft: was?.draft ?? null, photos });
	});
}

/** sent: nothing kept for this chat */
export function drop(key: string) {
	const was = pendingKeep.get(key);
	if (was) clearTimeout(was.timer);
	pendingKeep.delete(key);
	return inTurn(key, () => erase(key));
}

/** when OWUI's own copy is gone (or came back empty): the kept draft, as OWUI's draft string (else OWUI's own) ·
 *  photos not yet attached go back through OWUI's own input once the composer is there */
export async function recall(key: string, owui: string | null): Promise<string | null> {
	if (typeof window === 'undefined') return owui;
	recalled.add(key);
	await (chains.get(key) ?? Promise.resolve());
	const kept = await read(key);
	if (!kept) return owui;
	if (Date.now() - kept.at > KEEP_DAYS * 86_400_000) {
		void erase(key);
		return owui;
	}
	let lost = !owui;
	try {
		lost ||= emptyDraft(JSON.parse(owui ?? 'null') ?? {});
	} catch {
		lost = true;
	}
	const draft = lost ? (kept.draft ?? owui) : owui;
	const attached = namesIn(draft);
	const unsent = kept.photos.filter((p) => !attached.has(p.name));
	if (unsent.length) refeedSoon(unsent);
	return draft;
}

/** once the composer is drawn (a few tries, then they stay kept for the next visit) */
function refeedSoon(photos: Photo[], tries = 12) {
	setTimeout(() => {
		if (!refeed(photos) && tries > 1) refeedSoon(photos, tries - 1);
	}, 250);
}

/** photos back through OWUI's own input (#camera-input), as if the camera had just returned them */
export function refeed(photos: { name: string; type: string; blob: Blob }[]) {
	const input = document.getElementById('camera-input') as HTMLInputElement | null;
	if (!input || !photos.length || typeof DataTransfer === 'undefined') return false;
	try {
		const dt = new DataTransfer();
		for (const p of photos) dt.items.add(new File([p.blob], p.name, { type: p.type || 'image/jpeg' }));
		input.files = dt.files;
		input.dispatchEvent(new Event('change', { bubbles: true }));
		return true;
	} catch {
		return false;
	}
}

/** long-forgotten drafts let go (once per page) */
let pruned = false;
export function prune() {
	if (pruned || typeof window === 'undefined') return;
	pruned = true;
	void tx('readwrite', (s) => {
		const req = s.openCursor();
		req.onsuccess = () => {
			const c = req.result;
			if (!c) return;
			if (Date.now() - ((c.value as Kept)?.at ?? 0) > KEEP_DAYS * 86_400_000) c.delete();
			c.continue();
		};
		return undefined;
	});
}

/** numbers only, for her console and the tests: how many drafts and photos this browser keeps */
export async function counts(): Promise<{ drafts: number; photos: number }> {
	const all = (await tx<Kept[]>('readonly', (s) => s.getAll() as IDBRequest<Kept[]>)) ?? [];
	return { drafts: all.filter((k) => k.draft).length, photos: all.reduce((n, k) => n + (k.photos?.length ?? 0), 0) };
}

export const petalDraft = { keep, flush, photo, drop, recall, refeed, prune, counts, draftKey };

if (typeof window !== 'undefined') (window as unknown as { petalDraft?: object }).petalDraft = { counts };
