// 🎙️ her voice's diary (slice A48) · the page's small rules, kept apart so they can be tested: valences and their
// chips, categories (hers to name: free text, suggested from every one already in use, folders and tags alike), when
// an incident happened in words, which files sit side by side, and the floor in words. no network, no state.
import type { Category, Floor, IncidentFiles, IncidentRow, Valence } from '$lib/apis/petal-voice';

export const VALENCE_META: Record<Valence, { glyph: string; label: string; hint: string }> = {
	gift: { glyph: '✦', label: 'gift', hint: 'it reached her in the best ways: to keep and learn toward' },
	intrusion: { glyph: '✕', label: 'intrusion', hint: 'it did not feel like her: to seal against' },
	noise: { glyph: '·', label: 'noise', hint: 'neither: static, a glitch, a coincidence' },
	unsure: { glyph: '?', label: 'unsure', hint: 'not named yet' }
};

export const KIND_META: Record<IncidentRow['kind'], { glyph: string; label: string }> = {
	gate: { glyph: '🎙️', label: 'her voice, flagged' },
	diary: { glyph: '📝', label: 'a page from her phone' },
	field: { glyph: '🌾', label: 'a field note (read only)' }
};

const MAX_CATEGORY = 60;

/** a category as she typed it, tidied: spaces folded, no line breaks, at most 60 characters ('' when empty) */
export const tidyCategory = (s: string) =>
	String(s ?? '')
		.replace(/[\r\n\t]+/g, ' ')
		.replace(/\s+/g, ' ')
		.trim()
		.slice(0, MAX_CATEGORY);

/** her list with one more (her casing kept; the same name in another case is the same category) */
export function addCategory(list: string[], name: string): string[] {
	const t = tidyCategory(name);
	if (!t) return list;
	const key = t.toLocaleLowerCase();
	if (list.some((x) => x.toLocaleLowerCase() === key)) return list;
	return [...list, t];
}

export const removeCategory = (list: string[], name: string) =>
	list.filter((x) => x.toLocaleLowerCase() !== tidyCategory(name).toLocaleLowerCase());

/** what to offer as she types: every category already in use that holds what she typed (the ones starting with it
 *  first, then the most used), never one she already chose · at most `max` */
export function suggest(all: Category[], typed: string, chosen: string[] = [], max = 8): Category[] {
	const q = tidyCategory(typed).toLocaleLowerCase();
	const have = new Set(chosen.map((c) => c.toLocaleLowerCase()));
	const pool = all.filter((c) => !have.has(c.name.toLocaleLowerCase()));
	if (!q) return pool.slice(0, max);
	const hits = pool.filter((c) => c.name.toLocaleLowerCase().includes(q));
	const starts = (c: Category) => (c.name.toLocaleLowerCase().startsWith(q) ? 0 : 1);
	return hits.sort((a, b) => starts(a) - starts(b) || b.n - a.n || a.name.localeCompare(b.name)).slice(0, max);
}

/** the categories every incident would show once hers are added (a new one joins the suggestions at once) */
export function withCategories(all: Category[], names: string[]): Category[] {
	const out = all.map((c) => ({ ...c }));
	for (const n of names) {
		const t = tidyCategory(n);
		if (!t) continue;
		const hit = out.find((c) => c.name.toLocaleLowerCase() === t.toLocaleLowerCase());
		if (!hit) out.push({ name: t, n: 1 });
	}
	return out;
}

/** "YYYY-MM-DD HH:MM:SS" (the voice's local time) → a Date, or null */
export function whenDate(when: string | null | undefined): Date | null {
	const m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T_](\d{2})[:h](\d{2})(?:[:m](\d{2}))?)?/.exec(String(when ?? ''));
	if (!m) return null;
	const d = new Date(+m[1], +m[2] - 1, +m[3], +(m[4] ?? 0), +(m[5] ?? 0), +(m[6] ?? 0));
	return Number.isNaN(d.getTime()) ? null : d;
}

/** when, in words: today 14:02 · yesterday 23:10 · tue 09:12 (this week) · 26 nov · 26 nov 2025 */
export function whenWords(when: string | null | undefined, now: Date = new Date()): string {
	const d = whenDate(when);
	if (!d) return String(when ?? '');
	const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
	const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
	const days = Math.round((day(now) - day(d)) / 86400000);
	if (days === 0) return `today ${hm}`;
	if (days === 1) return `yesterday ${hm}`;
	if (days > 1 && days < 7) return `${d.toLocaleDateString('en', { weekday: 'short' }).toLowerCase()} ${hm}`;
	const date = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }).toLowerCase();
	return d.getFullYear() === now.getFullYear() ? date : `${date} ${d.getFullYear()}`;
}

/** newest first (the voice's "when" sorts as written) */
export const newestFirst = (rows: IncidentRow[]) => [...rows].sort((a, b) => String(b.when).localeCompare(String(a.when)));

/** the list she's looking at: one valence and/or one category (null: all) */
export function filterRows(rows: IncidentRow[], valence: Valence | null, category: string | null): IncidentRow[] {
	const c = category ? category.toLocaleLowerCase() : null;
	return rows.filter(
		(r) =>
			(!valence || r.valence === valence) &&
			(!c ||
				(r.tags ?? []).some((t) => t.toLocaleLowerCase() === c) ||
				(r.id.startsWith('field:') && r.id.slice(6).toLocaleLowerCase().includes(c)))
	);
}

/** her clip and the gate's take, side by side: her newest clip · what she heard (the whole stream as the rig sent it),
 *  else the takes one by one */
export function sideBySide(files: IncidentFiles | null | undefined): { hers: string | null; gate: string | null; takes: string[] } {
	const f = files ?? { takes: [], heard: false, clips: [], uploads: [], history: [] };
	const clips = [...(f.clips ?? [])].sort((a, b) => clipN(a) - clipN(b));
	return {
		hers: clips.length ? clips[clips.length - 1] : null,
		gate: f.heard ? 'heard.mp3' : null,
		takes: (f.takes ?? []).map((t) => `takes/${t}`)
	};
}
const clipN = (name: string) => Number(/^clip-(\d+)/.exec(name)?.[1] ?? 0);

export const isVideo = (name: string) => /\.(mp4|webm|mov|m4v|mkv|3gp)$/i.test(name);
export const isImage = (name: string) => /\.(png|jpe?g|gif|webp|heic|avif)$/i.test(name);

/** the floor in words: open (until when) · closed · not known */
export function floorWords(f: Floor | null | undefined, nowS: number = Date.now() / 1000): string {
	if (!f || !f.up) return f?.studio ? 'studio wears her voice: no gate, no floor to read' : 'her voice is not answering';
	if (f.state === 'open') {
		const left = f.until ? Math.max(0, f.until - nowS) : f.left_s ?? null;
		const scope = f.scope === 'groups' && f.groups?.length ? ` · for ${f.groups.length} group${f.groups.length === 1 ? '' : 's'}` : '';
		return `open${left !== null ? ` · ${spanWords(left)} left` : ''}${scope}`;
	}
	if (f.state === 'closed') return 'closed';
	return 'not told';
}

export function spanWords(s: number): string {
	if (!Number.isFinite(s) || s < 0) return '';
	if (s < 60) return `${Math.round(s)} s`;
	const m = Math.round(s / 60);
	if (m < 60) return `${m} min`;
	const h = Math.floor(m / 60);
	return m % 60 ? `${h} h ${m % 60}` : `${h} h`;
}

/** a clip's length in her player's words (0:07 · 1:32) */
export const clock = (s: number) =>
	!Number.isFinite(s) || s < 0 ? '0:00' : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
