// 👁 her eyes (slice A10) — the pure side of the raw view: tints, the history as sent, params,
// and the word diff between what Petal wrote raw (petal-wellspring) and what OWUI saved.
// no DOM, no stores: everything here is a function of the record.

import type { EyesPart } from '$lib/apis/petal-eyes';

export type Seg = { text: string; src: number | null }; // src = index into the legend's sources
export type Piece = { kind: 'text' | 'image' | 'other'; text: string };
export type Msg = { i: number; role: string; pieces: Piece[]; extra: [string, string][] };
export type Op = { op: '=' | '-' | '+'; text: string };

export const TINTS = 8; // palette slots in PetalEyes.svelte (.pe-c0 … .pe-c7)

/** the legend: every distinct source, in the order the injectors spoke. */
export const sourcesOf = (parts: EyesPart[]): string[] => [...new Set(parts.map((p) => p.source))];

/** what a part is: text that rides in the request, or something that never was text
 * (Heartstrings steers the activations, petal-soft speaks in soft tokens). A11.1 */
export const partKind = (source: string): 'steering' | 'soft' | 'text' =>
	/heartstring|💗|\bstrings\b/i.test(source)
		? 'steering'
		: /petal-soft|soft.?tokens?|\bscent\b/i.test(source)
			? 'soft'
			: 'text';

const needleOf = (text: string, hay: string): string | null => {
	if (!text) return null;
	if (text.trim().length >= 3 && hay.includes(text)) return text;
	const t = text.trim(); // an injector's trailing newline may have been trimmed on the way
	return t.length >= 3 && hay.includes(t) ? t : null;
};

/** whitespace runs folded to one space, with the way back to the original offsets */
const fold = (s: string) => {
	let out = '';
	const map: number[] = [];
	let gap = false;
	for (let i = 0; i < s.length; i++) {
		if (/\s/.test(s[i])) {
			if (!gap) {
				out += ' ';
				map.push(i);
			}
			gap = true;
		} else {
			out += s[i];
			map.push(i);
			gap = false;
		}
	}
	return { out, map };
};

/** `text` split into segments, each part's every occurrence tinted by its source.
 * a smaller part inside a bigger one keeps its own tint (painted last). a part whose spacing
 * changed on the way (a newline become a space…) is still found. `found` collects the indexes
 * of the parts that were seen. */
export function tint(text: string, parts: EyesPart[], sources: string[], found?: Set<number>): Seg[] {
	if (!text) return [];
	const spans: { s: number; e: number; src: number }[] = [];
	let folded: { out: string; map: number[] } | null = null;
	parts.forEach((p, pi) => {
		const src = sources.indexOf(p.source);
		const needle = needleOf(p.text, text);
		if (needle) {
			found?.add(pi);
			for (let i = text.indexOf(needle); i !== -1; i = text.indexOf(needle, i + needle.length))
				spans.push({ s: i, e: i + needle.length, src });
			return;
		}
		const nf = p.text ? fold(p.text.trim()).out : '';
		if (nf.length < 3) return;
		folded ??= fold(text);
		const { out, map } = folded;
		for (let i = out.indexOf(nf); i !== -1; i = out.indexOf(nf, i + nf.length)) {
			found?.add(pi);
			spans.push({ s: map[i], e: map[i + nf.length - 1] + 1, src });
		}
	});
	if (!spans.length) return [{ text, src: null }];
	const owner = new Int16Array(text.length).fill(-1);
	spans.sort((a, b) => b.e - b.s - (a.e - a.s)); // biggest first, so the specific ones win
	for (const sp of spans) owner.fill(sp.src, sp.s, sp.e);
	const out: Seg[] = [];
	let start = 0;
	for (let i = 1; i <= text.length; i++) {
		if (i === text.length || owner[i] !== owner[start]) {
			out.push({ text: text.slice(start, i), src: owner[start] < 0 ? null : owner[start] });
			start = i;
		}
	}
	return out;
}

const kb = (n: number) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`);

function piecesOf(content: unknown): Piece[] {
	if (content == null) return [];
	if (typeof content === 'string') return [{ kind: 'text', text: content }];
	if (!Array.isArray(content)) return [{ kind: 'other', text: JSON.stringify(content, null, 1) }];
	return content.map((c: any): Piece => {
		if (c && (c.type === 'text' || c.type === 'input_text') && typeof c.text === 'string')
			return { kind: 'text', text: c.text };
		const url = c?.image_url?.url ?? c?.image_url ?? c?.url;
		if (c && (c.type === 'image_url' || c.type === 'input_image') && typeof url === 'string')
			return {
				kind: 'image',
				text: url.startsWith('data:') ? `${url.slice(5, url.indexOf(';'))} · ${kb(url.length)}` : url
			};
		return { kind: 'other', text: JSON.stringify(c, null, 1) };
	});
}

const flat = (v: unknown): string =>
	typeof v === 'string' ? v : JSON.stringify(v, null, 1) ?? String(v);

/** every message as sent, in order · `extra` = whatever rides on it beside role + content. */
export function historyOf(payload: Record<string, any>): Msg[] {
	const list = Array.isArray(payload?.messages)
		? payload.messages
		: Array.isArray(payload?.input)
			? payload.input // the responses API
			: [];
	return list.map((m: any, i: number) => ({
		i,
		role: String(m?.role ?? m?.type ?? '?'),
		pieces: piecesOf(m?.content),
		extra: Object.entries(m ?? {})
			.filter(([k]) => k !== 'role' && k !== 'content')
			.map(([k, v]) => [k, flat(v)] as [string, string])
	}));
}

/** her system context: every system/developer turn (or the responses API's instructions). */
export function systemOf(payload: Record<string, any>): { at: number | null; text: string }[] {
	const out: { at: number | null; text: string }[] = [];
	if (typeof payload?.instructions === 'string') out.push({ at: null, text: payload.instructions });
	historyOf(payload).forEach((m) => {
		if (m.role === 'system' || m.role === 'developer')
			out.push({ at: m.i, text: m.pieces.map((p) => p.text).join('\n') });
	});
	return out;
}

const TEXT_KEYS = new Set(['messages', 'input', 'instructions', 'prompt']);

/** everything else in the payload (temperature, a steering field, …), values as JSON text. */
export const paramsOf = (payload: Record<string, any>): [string, string][] =>
	Object.entries(payload ?? {})
		.filter(([k]) => !TEXT_KEYS.has(k))
		.map(([k, v]) => [k, typeof v === 'string' ? JSON.stringify(v) : JSON.stringify(v, null, 1)]);

/** the saved side without OWUI's folded blocks (reasoning, tool calls): those are shown apart. */
export function stripDetails(saved: string): { text: string; folded: number } {
	let folded = 0;
	const text = (saved ?? '').replace(/<details\b[^>]*>[\s\S]*?<\/details>\s*/g, () => {
		folded++;
		return '';
	});
	return { text, folded };
}

// ── the word diff (Myers, with a ceiling so a total rewrite never freezes the page) ──
const tokens = (s: string): string[] => s.match(/\s+|[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu) ?? [];

function myersCore(A: string[], B: string[], maxD: number): Op[] | null {
	const N = A.length;
	const M = B.length;
	const snaps: Int32Array[] = [];
	let found = -1;
	outer: for (let d = 0; d <= Math.min(N + M, maxD); d++) {
		const cur = new Int32Array(2 * d + 1);
		const prev = d > 0 ? snaps[d - 1] : null;
		for (let k = -d; k <= d; k += 2) {
			let x: number;
			if (!prev) x = 0;
			else {
				const down = k === -d || (k !== d && prev[k - 1 + d - 1] < prev[k + 1 + d - 1]);
				x = down ? prev[k + 1 + d - 1] : prev[k - 1 + d - 1] + 1;
			}
			let y = x - k;
			while (x < N && y < M && A[x] === B[y]) {
				x++;
				y++;
			}
			cur[k + d] = x;
			if (x >= N && y >= M) {
				snaps.push(cur);
				found = d;
				break outer;
			}
		}
		snaps.push(cur);
	}
	if (found < 0) return null;
	const out: Op[] = [];
	let x = N;
	let y = M;
	for (let d = found; d > 0; d--) {
		const prev = snaps[d - 1];
		const k = x - y;
		const down = k === -d || (k !== d && prev[k - 1 + d - 1] < prev[k + 1 + d - 1]);
		const pk = down ? k + 1 : k - 1;
		const px = prev[pk + d - 1];
		const py = px - pk;
		while (x > px && y > py) {
			out.push({ op: '=', text: A[--x] });
			y--;
		}
		if (x === px) out.push({ op: '+', text: B[--y] });
		else out.push({ op: '-', text: A[--x] });
	}
	while (x > 0 && y > 0) {
		out.push({ op: '=', text: A[--x] });
		y--;
	}
	return out.reverse();
}

const merge = (ops: Op[]): Op[] =>
	ops.reduce<Op[]>((acc, o) => {
		if (!o.text) return acc;
		const last = acc[acc.length - 1];
		if (last && last.op === o.op) last.text += o.text;
		else acc.push({ ...o });
		return acc;
	}, []);

function diffOf(a: string[], b: string[], maxD: number): Op[] | null {
	let pre = 0;
	while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
	let suf = 0;
	while (suf < a.length - pre && suf < b.length - pre && a[a.length - 1 - suf] === b[b.length - 1 - suf])
		suf++;
	const core = myersCore(a.slice(pre, a.length - suf), b.slice(pre, b.length - suf), maxD);
	if (!core) return null;
	return merge([
		{ op: '=', text: a.slice(0, pre).join('') },
		...core,
		{ op: '=', text: a.slice(a.length - suf).join('') }
	]);
}

/** raw → saved: '-' only in what she wrote raw, '+' only in what OWUI saved. */
export function diffWords(raw: string, saved: string, maxD = 1500): Op[] {
	if (raw === saved) return raw ? [{ op: '=', text: raw }] : [];
	return (
		diffOf(tokens(raw), tokens(saved), maxD) ??
		diffOf(raw.split(/(?<=\n)/), saved.split(/(?<=\n)/), maxD) ?? [
			{ op: '-', text: raw },
			{ op: '+', text: saved }
		]
	);
}

export type Shown = Op | { op: '…'; text: string };

/** long unchanged stretches folded to their ends, so the changes stay in view. */
export const foldSame = (ops: Op[], keep = 160): Shown[] =>
	ops.flatMap((o): Shown[] =>
		o.op === '=' && o.text.length > keep * 2 + 40
			? [
					{ op: '=', text: o.text.slice(0, keep) },
					{ op: '…', text: `${(o.text.length - keep * 2).toLocaleString()} chars the same` },
					{ op: '=', text: o.text.slice(-keep) }
				]
			: [o]
	);

export const changed = (ops: Op[]) =>
	ops.reduce((n, o) => n + (o.op === '=' ? 0 : o.text.length), 0);

/** a change made only of whitespace, made visible (· space, → tab, ↵ newline). */
export const visible = (s: string) =>
	/^\s+$/.test(s) ? s.replace(/ /g, '·').replace(/\t/g, '→').replace(/\n/g, '↵\n') : s;

/** a value too long to read at a glance (a soft-token blob, an image) is shown cut. */
export const cut = (s: string, n = 600) =>
	s.length > n ? `${s.slice(0, n)}… (${(s.length - n).toLocaleString()} more chars)` : s;
