// 👁 her eyes (slice A10) — the pure side of the raw view: tints, the history as sent, params,
// and the word diff between what Petal wrote raw (petal-wellspring) and what OWUI saved.
// no DOM, no stores: everything here is a function of the record.

import type { EyesPart } from '$lib/apis/petal-eyes';

// src = index into the legend's sources (the tint) · part = which part it is (its hover, A14)
export type Seg = { text: string; src: number | null; part: number | null };
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

/** where `text` first sits in `hay` (−1: nowhere) · a trimmed or re-spaced copy still counts. */
export function firstAt(hay: string, text: string): number {
	if (!hay || !text) return -1;
	const needle = needleOf(text, hay);
	if (needle) return hay.indexOf(needle);
	const nf = fold(text.trim()).out;
	if (nf.length < 3) return -1;
	const { out, map } = fold(hay);
	const i = out.indexOf(nf);
	return i < 0 ? -1 : map[i];
}

/** `text` split into segments, each part's every occurrence tinted by its source.
 * a smaller part inside a bigger one keeps its own tint (painted last). a part whose spacing
 * changed on the way (a newline become a space…) is still found. `found` collects the indexes
 * of the parts that were seen. */
export function tint(text: string, parts: EyesPart[], sources: string[], found?: Set<number>): Seg[] {
	if (!text) return [];
	const owner = ownersOf(text, parts, found);
	if (!owner) return [{ text, src: null, part: null }];
	const srcOf = parts.map((p) => sources.indexOf(p.source));
	const out: Seg[] = [];
	let start = 0;
	for (let i = 1; i <= text.length; i++) {
		if (i === text.length || owner[i] !== owner[start]) {
			const part = owner[start] < 0 ? null : owner[start];
			out.push({ text: text.slice(start, i), src: part === null ? null : srcOf[part], part });
			start = i;
		}
	}
	return out;
}

/** per character: the part that tints it (−1: none) · null when no part is in `text`. */
function ownersOf(text: string, parts: EyesPart[], found?: Set<number>): Int16Array | null {
	const spans: { s: number; e: number; pi: number }[] = [];
	let folded: { out: string; map: number[] } | null = null;
	parts.forEach((p, pi) => {
		const needle = needleOf(p.text, text);
		if (needle) {
			found?.add(pi);
			for (let i = text.indexOf(needle); i !== -1; i = text.indexOf(needle, i + needle.length))
				spans.push({ s: i, e: i + needle.length, pi });
			return;
		}
		const nf = p.text ? fold(p.text.trim()).out : '';
		if (nf.length < 3) return;
		folded ??= fold(text);
		const { out, map } = folded;
		for (let i = out.indexOf(nf); i !== -1; i = out.indexOf(nf, i + nf.length)) {
			found?.add(pi);
			spans.push({ s: map[i], e: map[i + nf.length - 1] + 1, pi });
		}
	});
	if (!spans.length) return null;
	const owner = new Int16Array(text.length).fill(-1);
	spans.sort((a, b) => b.e - b.s - (a.e - a.s)); // biggest first, so the specific ones win
	for (const sp of spans) owner.fill(sp.pi, sp.s, sp.e);
	return owner;
}

// ── A14 · what spoke: the hover (or tap) on a tinted string ──────────────────────
/** the line of `text` around offset `at`, trimmed */
export function lineAt(text: string, at: number): string {
	const i = Math.max(0, Math.min(at, text.length));
	const s = i > 0 ? text.lastIndexOf('\n', text[i] === '\n' ? i - 1 : i) + 1 : 0;
	let e = text.indexOf('\n', i);
	if (e < 0) e = text.length;
	return text.slice(s, Math.max(s, e)).trim();
}

export type Speaker = { what: string; who: string; hit?: boolean }; // hit: an entry that holds her line
const singular = (k: string) => (k.endsWith('ies') ? `${k.slice(0, -3)}y` : k.length > 3 && k.endsWith('s') ? k.slice(0, -1) : k);
const entryWords = (e: unknown): string => {
	if (!e || typeof e !== 'object') return '';
	const o = e as Record<string, unknown>;
	const w = ['text', 'words', 'line', 'content', 'body'].map((k) => o[k]).find((v) => typeof v === 'string');
	return (w as string | undefined) ?? '';
};
const entryName = (e: unknown): string => {
	if (!e || typeof e !== 'object') return '';
	const o = e as Record<string, unknown>;
	const name = ['name', 'label', 'title', 'key', 'id', 'gem'].map((k) => o[k]).find((v) => typeof v === 'string' && v);
	return [typeof o.emoji === 'string' ? o.emoji : '', (name as string | undefined) ?? ''].filter(Boolean).join(' ');
};

/** what spoke where she points, from the part's own extras: the entry of a list (gems, lines…)
 * whose words hold that line (or, a whole phrase, sit inside it), then the part's short plain
 * extras (a gem's id, a mode, a token count). an injector names its speakers by what it puts
 * beside its text. a lone token (an id like "skin") never claims a line it merely appears in. */
export function speakersOf(p: EyesPart, line: string): Speaker[] {
	const out: Speaker[] = [];
	const hit = line.trim();
	const phrase = (w: string) => w.length >= 8 && /\s/.test(w);
	for (const [k, v] of Object.entries(p)) {
		if (k === 'source' || k === 'text') continue;
		if (Array.isArray(v)) {
			if (hit.length < 3) continue;
			for (const e of v) {
				const w = (typeof e === 'string' ? e : entryWords(e)).trim();
				if (!w || !(w.includes(hit) || (phrase(w) && hit.includes(w)))) continue;
				out.push({ what: singular(k), who: (typeof e === 'string' ? '' : entryName(e)) || cut(w, 140), hit: true });
				break;
			}
		} else if ((typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') && String(v).length <= 80) {
			out.push({ what: k, who: String(v) });
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

const isSystem = (role: string) => role === 'system' || role === 'developer';

/** where each message sits, in her words: `system`, `turn N` (her turns and Petal's, counted
 * from 1), or `system · after turn N` for a system turn further down the history. */
export function turnLabels(msgs: Msg[]): string[] {
	let n = 0;
	return msgs.map((m) => (isSystem(m.role) ? (n ? `system · after turn ${n}` : 'system') : `turn ${++n}`));
}

export type Place = { where: string; role: string | null; key: [number, number, number] };

/** each part's first place in the request, in reading order: the instructions, then every
 * message's text, then whatever rides on it. `order` lists the parts as Petal reads them: the ones
 * found in place first, then the ones beside the text (steering, soft tokens), the ones with
 * nothing to tint, and last the ones nowhere in what was sent. */
export function placesOf(payload: Record<string, any>, parts: EyesPart[]): { places: (Place | null)[]; order: number[] } {
	const msgs = historyOf(payload);
	const labels = turnLabels(msgs);
	const slots: { where: string; role: string | null; key: [number, number]; text: string }[] = [];
	if (typeof payload?.instructions === 'string')
		slots.push({ where: 'instructions', role: null, key: [-1, 0], text: payload.instructions });
	msgs.forEach((m, mi) => {
		const text = m.pieces
			.filter((p) => p.kind === 'text')
			.map((p) => p.text)
			.join('\n');
		slots.push({ where: labels[mi], role: m.role, key: [mi, 0], text });
		m.extra.forEach(([k, v], xi) =>
			slots.push({ where: `${labels[mi]} · rides along · ${k}`, role: m.role, key: [mi, 1 + xi], text: v })
		);
	});
	const places = parts.map((p): Place | null => {
		if (partKind(p.source) !== 'text' || !p.text) return null;
		for (const s of slots) {
			const at = firstAt(s.text, p.text);
			if (at >= 0) return { where: s.where, role: s.role, key: [s.key[0], s.key[1], at] };
		}
		return null;
	});
	const rank = (i: number) => {
		const p = parts[i];
		return places[i] ? 0 : partKind(p.source) !== 'text' ? 1 : !p.text ? 2 : 3;
	};
	const cmp = (a: number, b: number) => {
		const ra = rank(a);
		const rb = rank(b);
		if (ra !== rb || ra) return ra - rb || a - b;
		const ka = places[a]!.key;
		const kb = places[b]!.key;
		return ka[0] - kb[0] || ka[1] - kb[1] || ka[2] - kb[2] || a - b;
	};
	return { places, order: parts.map((_, i) => i).sort(cmp) };
}

// ── 🧵 the rendered view (A13): what vLLM's own chat template made of the request ──────────
/** what a chat template writes as markers: <|…|> (ChatML, Qwen-Omni pads, Llama headers), the
 * think and tool tags, <s></s>, [INST], gemma's turns */
export const SPECIAL =
	/<\|[^<>|\s]{1,48}\|>|<\/?(?:think|tool_call|tool_response|tools|answer)>|<\/?s>|\[\/?INST\]|<(?:start|end)_of_turn>|<bos>|<eos>/g;

export type RSeg = { text: string; src: number | null; part: number | null; tpl: boolean; tok: boolean; n: number };

/** the rendered prompt in segments: special tokens (a run of the same one folded into one, ×n),
 * the template's own words (everything that isn't her messages' text), and the parts tinted by
 * source inside her messages. `tail` = what the template writes after the last message: where
 * Petal starts writing. `missed` counts message texts the template reshaped (not found verbatim). */
export function renderedSegs(text: string, payload: Record<string, any>, parts: EyesPart[], sources: string[]) {
	const inMsg = new Uint8Array(text.length);
	let cursor = 0;
	let lastEnd = 0;
	let missed = 0;
	// a turn's text opens right after its header (a newline, a tag's '>', [INST]'s space): a short
	// "hi" is never taken from inside the tool block the template wrote before it
	const opens = (i: number) => i === 0 || /[\n >]/.test(text[i - 1]);
	const locate = (needle: string, from: number, first: boolean) => {
		let i = text.indexOf(needle, from);
		for (let n = 0; first && i >= 0 && !opens(i) && n < 400; n++) i = text.indexOf(needle, i + 1);
		return first && i >= 0 && !opens(i) ? -1 : i;
	};
	for (const m of historyOf(payload)) {
		let first = true;
		for (const p of m.pieces) {
			if (p.kind !== 'text' || !p.text.trim()) continue;
			const t = p.text.trim(); // templates often trim (or lstrip) a turn's text
			// exact after its header, else trimmed after its header, else wherever it first appears
			const tries: [string, boolean][] = [[p.text, first], [t, first], [p.text, false], [t, false]];
			let at = -1;
			let len = 0;
			for (const [needle, strict] of tries) {
				at = locate(needle, cursor, strict);
				len = needle.length;
				if (at >= 0) break;
			}
			if (at < 0) {
				missed++;
				continue;
			}
			inMsg.fill(1, at, at + len);
			cursor = lastEnd = at + len;
			first = false;
		}
	}
	const owner = ownersOf(text, parts);
	const srcOf = parts.map((p) => sources.indexOf(p.source));
	const toks: [number, number][] = [];
	for (const mt of text.matchAll(SPECIAL)) toks.push([mt.index!, mt.index! + mt[0].length]);
	const segs: RSeg[] = [];
	const push = (s: number, e: number) => {
		if (e <= s) return;
		let start = s;
		for (let i = s + 1; i <= e; i++) {
			const cut =
				i === e ||
				inMsg[i] !== inMsg[start] ||
				(owner ? owner[i] : -1) !== (owner ? owner[start] : -1);
			if (!cut) continue;
			const part = owner && inMsg[start] && owner[start] >= 0 ? owner[start] : null;
			segs.push({ text: text.slice(start, i), src: part === null ? null : srcOf[part], part, tpl: !inMsg[start], tok: false, n: 1 });
			start = i;
		}
	};
	let at = 0;
	for (const [s, e] of toks) {
		push(at, s);
		const tok = text.slice(s, e);
		const last = segs[segs.length - 1];
		if (last?.tok && last.text === tok && at === s) last.n++;
		else segs.push({ text: tok, src: null, part: null, tpl: !inMsg[s], tok: true, n: 1 });
		at = e;
	}
	push(at, text.length);
	return { segs, tail: text.slice(lastEnd), lastEnd, missed };
}

/** the thinking switch, read from where she starts writing */
export const thinkingOf = (tail: string): 'closed' | 'open' | null =>
	/<think>\s*<\/think>\s*$/.test(tail) ? 'closed' : /<think>\s*$/.test(tail) ? 'open' : null;

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
