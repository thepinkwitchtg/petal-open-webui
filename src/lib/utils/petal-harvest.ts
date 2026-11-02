// petal-harvest 🌷 — gather every chat from a precise time range into md + json,
// so Lily can tend Petal's growth (keep what was growth, release what was drift).
// Pure helpers: filtering, branch walking, rendering. No network, no DOM.

export type HarvestMode = 'alive' | 'born' | 'touched';

export interface HarvestOptions {
	start: number; // epoch seconds, inclusive
	end: number; // epoch seconds, inclusive
	mode: HarvestMode;
	trimToRange: boolean; // md only keeps messages whose timestamp falls in range
	userName: string;
}

export interface HarvestFile {
	name: string;
	content: string;
}

export interface HarvestBundle {
	folder: string;
	files: HarvestFile[];
	chats: number;
	messages: number;
	combined: string; // one long md, for the clipboard
}

// ── time ────────────────────────────────────────────────────────────────

const pad = (n: number) => String(n).padStart(2, '0');

// OWUI stores seconds; a few old imports carry ms or ns — fold them back to seconds.
export const toSeconds = (t: unknown): number => {
	const n = Number(t ?? 0);
	if (!Number.isFinite(n) || n <= 0) return 0;
	if (n > 1e17) return Math.floor(n / 1e9);
	if (n > 1e12) return Math.floor(n / 1e3);
	return Math.floor(n);
};

export const stamp = (sec: number, withTime = true) => {
	if (!sec) return '—';
	const d = new Date(sec * 1000);
	const day = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
	return withTime ? `${day} ${pad(d.getHours())}:${pad(d.getMinutes())}` : day;
};

const isMidnight = (sec: number) => {
	const d = new Date(sec * 1000);
	return d.getHours() === 0 && d.getMinutes() === 0;
};

// ── names ───────────────────────────────────────────────────────────────

export const safeName = (s: string, max = 80) =>
	(s || 'untitled')
		.replace(/[\/\\:*?"<>|\u0000-\u001f]/g, ' ')
		.replace(/\s+/g, ' ')
		.trim()
		.slice(0, max)
		.trim() || 'untitled';

// ── chat shape ──────────────────────────────────────────────────────────

const chatCreated = (c: any) => toSeconds(c?.created_at ?? c?.chat?.timestamp);
const chatUpdated = (c: any) => toSeconds(c?.updated_at) || chatCreated(c);

// current branch, root → leaf (what Lily actually saw on screen)
export const branchMessages = (c: any): any[] => {
	const history = c?.chat?.history;
	if (history?.messages && history?.currentId) {
		const out: any[] = [];
		const seen = new Set<string>();
		let id: string | null = history.currentId;
		while (id && history.messages[id] && !seen.has(id)) {
			seen.add(id);
			out.unshift(history.messages[id]);
			id = history.messages[id].parentId ?? null;
		}
		return out;
	}
	return Array.isArray(c?.chat?.messages) ? c.chat.messages : [];
};

const messageText = (m: any): string => {
	if (typeof m?.content === 'string' && m.content.trim()) return m.content;
	if (Array.isArray(m?.content)) {
		return m.content
			.map((p: any) => (typeof p === 'string' ? p : (p?.text ?? '')))
			.filter(Boolean)
			.join('\n');
	}
	if (Array.isArray(m?.output)) {
		return m.output
			.flatMap((o: any) => (Array.isArray(o?.content) ? o.content : []))
			.map((p: any) => p?.text ?? '')
			.filter(Boolean)
			.join('\n');
	}
	return '';
};

export const inRange = (c: any, o: Pick<HarvestOptions, 'start' | 'end' | 'mode'>) => {
	const born = chatCreated(c);
	const touched = chatUpdated(c);
	switch (o.mode) {
		case 'born':
			return born >= o.start && born <= o.end;
		case 'touched':
			return touched >= o.start && touched <= o.end;
		case 'alive':
		default:
			// lived at any moment inside the window
			return born <= o.end && touched >= o.start;
	}
};

const keptMessages = (c: any, o: HarvestOptions) => {
	const all = branchMessages(c);
	if (!o.trimToRange) return all;
	return all.filter((m) => {
		const t = toSeconds(m?.timestamp);
		return !t || (t >= o.start && t <= o.end); // keep untimed messages, never guess
	});
};

// ── render ──────────────────────────────────────────────────────────────

const yamlStr = (s: string) => JSON.stringify(s ?? '');

const renderAnnotation = (m: any): string => {
	const a = m?.annotation;
	if (!a) return '';
	const bits: string[] = [];
	if (a.rating === 1) bits.push('👍');
	if (a.rating === -1) bits.push('👎');
	if (a.reason) bits.push(`reason: ${a.reason}`);
	if (Array.isArray(a.tags) && a.tags.length) bits.push(`tags: ${a.tags.join(', ')}`);
	if (a.comment) bits.push(`note: ${String(a.comment).replace(/\n+/g, ' ')}`);
	return bits.length ? `\n\n> ${bits.join(' · ')}` : '';
};

export const renderChatMd = (c: any, o: HarvestOptions) => {
	const msgs = keptMessages(c, o);
	const models = Array.isArray(c?.chat?.models) ? c.chat.models : [];
	const tags = Array.isArray(c?.meta?.tags) ? c.meta.tags : [];

	const front = [
		'---',
		`id: ${c?.id ?? ''}`,
		`title: ${yamlStr(c?.title ?? '')}`,
		`created: ${stamp(chatCreated(c))}`,
		`updated: ${stamp(chatUpdated(c))}`,
		`models: ${JSON.stringify(models)}`,
		tags.length ? `tags: ${JSON.stringify(tags)}` : null,
		c?.folder_id ? `folder_id: ${c.folder_id}` : null,
		c?.archived ? 'archived: true' : null,
		c?.pinned ? 'pinned: true' : null,
		`messages: ${msgs.length}`,
		o.trimToRange ? `trimmed_to: ${stamp(o.start)} → ${stamp(o.end)}` : null,
		'---'
	]
		.filter((l) => l !== null)
		.join('\n');

	const body = msgs
		.map((m) => {
			const who =
				m?.role === 'user'
					? `🌸 ${o.userName || 'Lily'}`
					: m?.role === 'assistant'
						? `🦋 ${m?.modelName || m?.model || 'Petal'}`
						: `✦ ${m?.role ?? 'note'}`;
			return `### ${who} · ${stamp(toSeconds(m?.timestamp))}\n\n${messageText(m).trim()}${renderAnnotation(m)}`;
		})
		.join('\n\n');

	return { md: `${front}\n\n# ${c?.title || 'untitled'}\n\n${body}\n`, count: msgs.length };
};

export const harvest = (chats: any[], o: HarvestOptions): HarvestBundle => {
	const picked = chats
		.filter((c) => inRange(c, o))
		.sort((a, b) => chatCreated(a) - chatCreated(b));

	const withTime = !(isMidnight(o.start) && isMidnight(o.end + 1));
	const folder = safeName(
		`harvest ${stamp(o.start, withTime).replace(':', 'h')} → ${stamp(o.end, withTime).replace(':', 'h')} · ${o.mode}`,
		120
	);

	const files: HarvestFile[] = [];
	const index: string[] = [];
	const combined: string[] = [];
	let messages = 0;

	for (const c of picked) {
		const { md, count } = renderChatMd(c, o);
		messages += count;
		const base = safeName(
			`${stamp(chatCreated(c)).replace(':', '')} · ${c?.title || 'untitled'} · ${String(c?.id ?? '').slice(0, 8)}`,
			110
		);
		files.push({ name: `${base}.md`, content: md });
		files.push({ name: `json/${base}.json`, content: JSON.stringify(c, null, 2) });
		index.push(
			`- ${stamp(chatCreated(c))} → ${stamp(chatUpdated(c))} · **${c?.title || 'untitled'}** · ${count} msgs · \`${c?.id}\``
		);
		combined.push(md);
	}

	const meta = {
		range: { start: o.start, end: o.end, start_local: stamp(o.start), end_local: stamp(o.end) },
		mode: o.mode,
		trim_to_range: o.trimToRange,
		chats: picked.length,
		messages,
		harvested_at: stamp(Math.floor(Date.now() / 1000)),
		ids: picked.map((c) => c?.id)
	};

	files.unshift(
		{
			name: '_index.md',
			content: `# 🌷 ${folder}\n\n${picked.length} chats · ${messages} messages\n\n${index.join('\n')}\n`
		},
		{ name: '_harvest.json', content: JSON.stringify(meta, null, 2) }
	);

	return {
		folder,
		files,
		chats: picked.length,
		messages,
		combined: combined.join('\n\n---\n\n')
	};
};
