// 🌸 a display quote's words, dressed (slice A17). in a reply, a blockquote is usually the heart of the
// message (identity lines, vows, words to repeat), so it's set as display type in the accent gradient.
// its own quotation marks are kept and wear the accent (a straight " turns curly), and emoji keep
// their own colours inside the gradient. display only: the message itself, what the copy button
// takes and what the voice reads stay exactly as written.

export type QuoteSeg = { kind: 'text' | 'mark' | 'emoji'; text: string };

const OPENS_AFTER = /[\s([{—–«“„/-]/; // a straight " right after these opens
const CLOSES_BEFORE = /[\s.,;:!?)\]}]/; // at the very start, a " right before these closes

/** straight double quotes made curly by where they stand: after a space or an opening bracket (or
 * at the start, before a word) they open, otherwise they close */
export function curl(text: string): string {
	return text.replace(/"/g, (_m: string, i: number) => {
		const before = text[i - 1];
		const after = text[i + 1];
		const opens =
			before === undefined
				? after !== undefined && !CLOSES_BEFORE.test(after)
				: OPENS_AFTER.test(before);
		return opens ? '“' : '”';
	});
}

/** french guillemets hold their words: the space just inside « » turns no-break, so a line never
 * starts with a lone » */
export function tie(text: string): string {
	return text.replace(/«[ \t]+/g, '« ').replace(/[ \t]+»/g, ' »');
}

/** what a display quote shows of a run of text: curly marks, tied guillemets */
export const dress = (text: string): string => tie(curl(text));

/** a quote's lines: its inline tokens split at the line breaks (each line becomes its own block, so a
 * line that wraps on a narrow screen can wrap evenly instead of leaving one word alone) */
export function quoteLines<T extends { type: string }>(tokens: T[]): T[][] {
	const lines: T[][] = [[]];
	for (const t of tokens) {
		if (t.type === 'br') lines.push([]);
		else lines[lines.length - 1].push(t);
	}
	return lines;
}

// double marks only: a single ’ is an apostrophe as often as it is a quote
const MARKS = '“”„«»';

// an emoji drawn in colour: one shown as emoji by default, or a symbol asked to be one (VS16), with
// its skin tone and any ZWJ sequence it joins · flags and keycaps too. a text-style symbol (✧, ©)
// stays text, so it takes the gradient like the words around it
const EMOJI =
	/\p{Regional_Indicator}{2}|[#*0-9]️?⃣|(?:\p{Emoji_Presentation}|\p{Extended_Pictographic}️)(?:\p{Emoji_Modifier}|️)*(?:‍\p{Extended_Pictographic}️?(?:\p{Emoji_Modifier}|️)*)*/gu;

/** the words in runs: plain text, quotation marks and emoji, in order (joined, they give back the text) */
export function quoteSegs(text: string): QuoteSeg[] {
	const out: QuoteSeg[] = [];
	const push = (kind: QuoteSeg['kind'], t: string) => {
		if (!t) return;
		const last = out[out.length - 1];
		if (kind === 'text' && last?.kind === 'text') last.text += t;
		else out.push({ kind, text: t });
	};
	const marks = (t: string) => {
		let run = '';
		for (const c of t) {
			if (MARKS.includes(c)) {
				push('text', run);
				push('mark', c);
				run = '';
			} else run += c;
		}
		push('text', run);
	};
	let at = 0;
	for (const m of text.matchAll(EMOJI)) {
		const i = m.index ?? 0;
		marks(text.slice(at, i));
		push('emoji', m[0]);
		at = i + m[0].length;
	}
	marks(text.slice(at));
	return out;
}
