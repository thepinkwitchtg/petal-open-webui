// petal-table-voice 🌸 — let Petal's voice read markdown tables instead of skipping them.
//
// OWUI splits a reply into lines before cleaning it, so each `| row |` line used to
// become its own "sentence" that removeFormattings then erased. We rewrite every
// table into spoken prose *before* the split:
//
//   | Name  | Age | Role     |          Name: Alice.
//   |-------|-----|----------|   →      Age: 30.
//   | Alice | 30  | witch    |          Role: witch.
//   | Bob   | 41  | familiar |          Name: Bob.  Age: 41.  Role: familiar.
//
// Fenced code blocks are left untouched (OWUI drops them from speech anyway).
// Pure function, no imports — safe to call from utils/index.ts without cycles.

const FENCE = /^\s*(```|~~~)/;
const SEPARATOR = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
const EMPTYISH = /^[\s\-–—.·•]*$/;

const splitCells = (line: string): string[] => {
	let s = line.trim();
	if (s.startsWith('|')) s = s.slice(1);
	if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1);
	return s
		.split(/(?<!\\)\|/)
		.map((c) =>
			c
				.replace(/\\\|/g, '|')
				.replace(/<br\s*\/?>/gi, ', ')
				.trim()
		);
};

const isRowLine = (line: string) => line.includes('|') && line.trim() !== '';

const endSentence = (s: string) => {
	const t = s.trim().replace(/[,;:\s]+$/, '');
	if (!t) return '';
	return /[.!?…~)"'*_`]$/.test(t) ? t : `${t}.`;
};

// every cell on its own line, always with its column name, so she never has to
// hold the table in her head:  Service: petal-voice / Port: 8100 / GPU: Blackwell
const speakRow = (headers: string[], cells: string[]): string[] => {
	const lines: string[] = [];
	for (let i = 0; i < cells.length; i++) {
		const value = cells[i];
		if (!value || EMPTYISH.test(value)) continue;
		const h = headers[i];
		const line = endSentence(h && !EMPTYISH.test(h) ? `${h}: ${value}` : value);
		if (line) lines.push(line);
	}
	return lines;
};

const speakTable = (headerLine: string, rowLines: string[]): string[] => {
	const headers = splitCells(headerLine);
	const spoken: string[] = [];
	for (const line of rowLines) {
		const row = speakRow(headers, splitCells(line));
		if (row.length) spoken.push(...row, ''); // blank line between rows
	}
	return spoken;
};

export const speakTables = (content: string): string => {
	if (!content || !content.includes('|')) return content;

	const lines = content.split('\n');
	const out: string[] = [];
	let inFence = false;

	for (let i = 0; i < lines.length; i++) {
		const line = lines[i];

		if (FENCE.test(line)) {
			inFence = !inFence;
			out.push(line);
			continue;
		}

		const isTableStart =
			!inFence &&
			isRowLine(line) &&
			i + 1 < lines.length &&
			SEPARATOR.test(lines[i + 1]) &&
			lines[i + 1].includes('-');

		if (!isTableStart) {
			out.push(line);
			continue;
		}

		const rows: string[] = [];
		let j = i + 2;
		while (j < lines.length && isRowLine(lines[j]) && !FENCE.test(lines[j])) {
			rows.push(lines[j]);
			j++;
		}

		// blank lines around the table keep rows from merging with nearby prose
		out.push('', ...speakTable(line, rows), '');
		i = j - 1;
	}

	return out.join('\n');
};
