<script lang="ts">
	// 🌷 PetalWindow — an abyssal range picker for the garden harvest.
	// Replaces the browser's datetime-local popup (which only ever paints white + blue).
	// Values stay datetime-local strings ('YYYY-MM-DDTHH:mm') so the harvest logic is untouched.
	//
	// hands-light controls:
	//   tap a pill (from / to) → the calendar unfolds inline with that end active
	//   pick a day on "from" → the cursor glides to "to", so a window is two taps
	//   arrows move the day cursor · PageUp/PageDown change month (Shift = year)
	//   Enter picks the day under the cursor · Esc folds the calendar
	//   hour/minute: wheel or ↑/↓ (Shift = ×10), or type
	// nothing animates while idle.
	import { createEventDispatcher, tick } from 'svelte';

	export let from = '';
	export let to = '';

	const dispatch = createEventDispatcher();

	type End = 'from' | 'to';
	let active: End | null = null;
	let grid: HTMLDivElement;

	const pad = (n: number) => String(n).padStart(2, '0');
	const toInput = (d: Date) =>
		`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
	const parse = (v: string): Date | null => {
		if (!v) return null;
		const d = new Date(v);
		return isNaN(d.getTime()) ? null : d;
	};
	const dayKey = (d: Date) => d.getFullYear() * 10000 + d.getMonth() * 100 + d.getDate();
	const sameDay = (a: Date | null, b: Date | null) => !!a && !!b && dayKey(a) === dayKey(b);

	const MONTHS = ['january','february','march','april','may','june','july','august','september','october','november','december'];
	const WEEK = ['su', 'mo', 'tu', 'we', 'th', 'fr', 'sa'];

	const pretty = (v: string) => {
		const d = parse(v);
		if (!d) return '—';
		return `${MONTHS[d.getMonth()].slice(0, 3)} ${d.getDate()} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
	};

	$: fromD = parse(from);
	$: toD = parse(to);

	// the day cursor (keyboard) and the month on show
	let cursor = new Date();
	$: viewYear = cursor.getFullYear();
	$: viewMonth = cursor.getMonth();

	const valueOf = (end: End) => (end === 'from' ? from : to);

	const setEnd = (end: End, d: Date) => {
		if (end === 'from') from = toInput(d);
		else to = toInput(d);
		dispatch('change');
	};

	const open = async (end: End) => {
		if (active === end) {
			active = null;
			return;
		}
		active = end;
		const d = parse(valueOf(end)) ?? (end === 'to' ? fromD : toD) ?? new Date();
		cursor = new Date(d.getFullYear(), d.getMonth(), d.getDate());
		await tick();
		grid?.focus({ preventScroll: true });
	};

	// six fixed weeks so the panel never jumps in height
	$: cells = (() => {
		const first = new Date(viewYear, viewMonth, 1);
		const start = new Date(viewYear, viewMonth, 1 - first.getDay());
		return Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
	})();

	$: lo = fromD && toD ? Math.min(dayKey(fromD), dayKey(toD)) : 0;
	$: hi = fromD && toD ? Math.max(dayKey(fromD), dayKey(toD)) : 0;
	const today = new Date();

	const pick = async (day: Date) => {
		if (!active) return;
		const prev = parse(valueOf(active));
		// keep the time of day already chosen; a fresh "to" defaults to the end of that day
		const h = prev ? prev.getHours() : active === 'to' ? 23 : 0;
		const m = prev ? prev.getMinutes() : active === 'to' ? 59 : 0;
		setEnd(active, new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, m));
		cursor = new Date(day);
		if (active === 'from') {
			active = 'to';
			await tick();
			grid?.focus({ preventScroll: true });
		}
	};

	const moveCursor = (days = 0, months = 0) => {
		cursor = new Date(cursor.getFullYear(), cursor.getMonth() + months, cursor.getDate() + days);
	};

	const onGridKey = (e: KeyboardEvent) => {
		const k = e.key;
		if (k === 'ArrowLeft') moveCursor(-1);
		else if (k === 'ArrowRight') moveCursor(1);
		else if (k === 'ArrowUp') moveCursor(-7);
		else if (k === 'ArrowDown') moveCursor(7);
		else if (k === 'PageUp') moveCursor(0, e.shiftKey ? -12 : -1);
		else if (k === 'PageDown') moveCursor(0, e.shiftKey ? 12 : 1);
		else if (k === 'Home') cursor = new Date();
		else if (k === 'Enter' || k === ' ') pick(cursor);
		else if (k === 'Escape') active = null;
		else return;
		e.preventDefault();
		e.stopPropagation(); // keep Esc from closing the whole settings modal
	};

	// ── time ──────────────────────────────────────────────────
	$: activeD = active === 'from' ? fromD : active === 'to' ? toD : null;

	const nudgeTime = (unit: 'h' | 'm', delta: number) => {
		if (!active) return;
		const d = parse(valueOf(active)) ?? new Date(cursor);
		if (unit === 'h') d.setHours(d.getHours() + delta);
		else d.setMinutes(d.getMinutes() + delta);
		setEnd(active, d);
		cursor = new Date(d.getFullYear(), d.getMonth(), d.getDate());
	};

	const typeTime = (unit: 'h' | 'm', raw: string) => {
		if (!active) return;
		const n = parseInt(raw, 10);
		if (!Number.isFinite(n)) return;
		const d = parse(valueOf(active)) ?? new Date(cursor);
		if (unit === 'h') d.setHours(Math.max(0, Math.min(23, n)));
		else d.setMinutes(Math.max(0, Math.min(59, n)));
		setEnd(active, d);
	};

	const onTimeKey = (unit: 'h' | 'm') => (e: KeyboardEvent) => {
		const step = e.shiftKey ? 10 : 1;
		if (e.key === 'ArrowUp') nudgeTime(unit, step);
		else if (e.key === 'ArrowDown') nudgeTime(unit, -step);
		else if (e.key === 'Escape') active = null;
		else if (e.key === 'Enter') active = null;
		else return;
		e.preventDefault();
		e.stopPropagation();
	};

	const onTimeWheel = (unit: 'h' | 'm') => (e: WheelEvent) => {
		e.preventDefault();
		nudgeTime(unit, (e.deltaY < 0 ? 1 : -1) * (e.shiftKey ? 10 : 1));
	};

	const now = () => {
		if (!active) return;
		const d = new Date();
		setEnd(active, d);
		cursor = new Date(d.getFullYear(), d.getMonth(), d.getDate());
	};
</script>

<div class="pw">
	<div class="pw-pills">
		<button type="button" class="pw-pill" class:on={active === 'from'} on:click={() => open('from')}>
			<span class="pw-k">from</span>
			<span class="pw-v">{pretty(from)}</span>
		</button>
		<span class="pw-arrow">→</span>
		<button type="button" class="pw-pill" class:on={active === 'to'} on:click={() => open('to')}>
			<span class="pw-k">to</span>
			<span class="pw-v">{pretty(to)}</span>
		</button>
	</div>

	{#if active}
		<div class="pw-panel">
			<div class="pw-head">
				<button type="button" class="pw-nav" title="previous month (PageUp)" on:click={() => moveCursor(0, -1)}>‹</button>
				<div class="pw-month">{MONTHS[viewMonth]} <span class="pw-year">{viewYear}</span></div>
				<button type="button" class="pw-nav" title="next month (PageDown)" on:click={() => moveCursor(0, 1)}>›</button>
			</div>

			<!-- svelte-ignore a11y-no-noninteractive-tabindex -->
			<div
				class="pw-grid"
				role="grid"
				tabindex="0"
				aria-label="choose the {active} day"
				bind:this={grid}
				on:keydown={onGridKey}
			>
				{#each WEEK as w}<div class="pw-wd">{w}</div>{/each}
				{#each cells as day}
					{@const k = dayKey(day)}
					<button
						type="button"
						tabindex="-1"
						class="pw-day"
						class:out={day.getMonth() !== viewMonth}
						class:inside={lo && k >= lo && k <= hi}
						class:edge={sameDay(day, fromD) || sameDay(day, toD)}
						class:today={sameDay(day, today)}
						class:cursor={sameDay(day, cursor)}
						on:click={() => pick(day)}>{day.getDate()}</button
					>
				{/each}
			</div>

			<div class="pw-time">
				<span class="pw-k">{active} time</span>
				<input
					class="pw-num"
					inputmode="numeric"
					aria-label="hour"
					value={activeD ? pad(activeD.getHours()) : '--'}
					on:keydown={onTimeKey('h')}
					on:wheel={onTimeWheel('h')}
					on:change={(e) => typeTime('h', e.currentTarget.value)}
				/>
				<span class="pw-colon">:</span>
				<input
					class="pw-num"
					inputmode="numeric"
					aria-label="minute"
					value={activeD ? pad(activeD.getMinutes()) : '--'}
					on:keydown={onTimeKey('m')}
					on:wheel={onTimeWheel('m')}
					on:change={(e) => typeTime('m', e.currentTarget.value)}
				/>
				<span class="pw-grow"></span>
				<button type="button" class="pw-soft" on:click={now}>now</button>
				<button type="button" class="pw-soft" on:click={() => (active = null)}>done</button>
			</div>
			<div class="pw-hint">arrows · PgUp/PgDn month · Enter pick · wheel or ↑↓ on time (Shift ×10)</div>
		</div>
	{/if}
</div>

<style>
	/* every colour comes from the Abyssal Pink tokens; the fallbacks only
	   matter if the petal theme isn't loaded at all. */
	.pw {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		font-size: 0.75rem;
	}
	.pw-pills {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
	}
	.pw-pill {
		display: inline-flex;
		align-items: baseline;
		gap: 0.45rem;
		padding: 0.3rem 0.7rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		color: var(--mist, #cfc3cc);
		transition: border-color 140ms, background-color 140ms;
	}
	.pw-pill:hover {
		border-color: var(--edge-lit, #463b52);
	}
	.pw-pill.on {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.55);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.08);
	}
	.pw-k {
		color: var(--whisper, #8a7d92);
	}
	.pw-v {
		font-family: var(--font-mono, ui-monospace, monospace);
		color: var(--pearl, #f6eef3);
	}
	.pw-arrow {
		color: var(--whisper, #8a7d92);
	}

	.pw-panel {
		width: min(100%, 19rem);
		padding: 0.7rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		box-shadow: inset 0 1px 0 var(--glass-sheen, rgba(255, 255, 255, 0.03));
	}
	.pw-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 0.4rem;
	}
	.pw-month {
		font-family: var(--font-display, Georgia, serif);
		font-size: 0.95rem;
		background: var(--grad-text, linear-gradient(100deg, #f9c6dc, #f472b6 46%, #a873f0));
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	.pw-year {
		opacity: 0.7;
	}
	.pw-nav {
		width: 1.8rem;
		height: 1.8rem;
		border-radius: 999px;
		color: var(--mist, #cfc3cc);
		font-size: 1rem;
		line-height: 1;
	}
	.pw-nav:hover {
		background: var(--obsidian-lit, #1d1724);
	}

	.pw-grid {
		display: grid;
		grid-template-columns: repeat(7, 1fr);
		gap: 2px;
		outline: none;
		border-radius: var(--radius-sm, 8px);
	}
	.pw-grid:focus-visible {
		box-shadow: 0 0 0 1px oklch(0.711 0.214 var(--p-h-accent, 352) / 0.35);
	}
	.pw-wd {
		text-align: center;
		color: var(--whisper, #8a7d92);
		font-size: 0.65rem;
		padding: 0.15rem 0;
	}
	.pw-day {
		aspect-ratio: 1;
		border-radius: var(--radius-sm, 8px);
		color: var(--mist, #cfc3cc);
		font-variant-numeric: tabular-nums;
		transition: background-color 120ms;
	}
	.pw-day:hover {
		background: var(--obsidian-lit, #1d1724);
	}
	.pw-day.out {
		color: var(--whisper, #8a7d92);
		opacity: 0.45;
	}
	.pw-day.inside {
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.09);
		color: var(--pearl, #f6eef3);
	}
	.pw-day.today {
		box-shadow: inset 0 0 0 1px var(--edge-lit, #463b52);
	}
	.pw-day.cursor {
		box-shadow: inset 0 0 0 1px oklch(0.711 0.214 var(--p-h-accent, 352) / 0.7);
	}
	/* pink lives in the gradient — never a flat fill */
	.pw-day.edge {
		background: var(--grad-fill, linear-gradient(135deg, #f9c6dc, #f472b6 48%, #a873f0));
		color: var(--abyss, #0c0910);
		font-weight: 600;
		opacity: 1;
	}

	.pw-time {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		margin-top: 0.6rem;
		padding-top: 0.55rem;
		border-top: 1px solid var(--edge-soft, #2a2433);
	}
	.pw-time .pw-k {
		margin-right: 0.25rem;
	}
	.pw-num {
		width: 2.4rem;
		text-align: center;
		padding: 0.2rem 0;
		border-radius: var(--radius-sm, 8px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--abyss, #0c0910);
		color: var(--pearl, #f6eef3);
		font-family: var(--font-mono, ui-monospace, monospace);
		outline: none;
	}
	.pw-num:focus {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.55);
	}
	.pw-colon {
		color: var(--whisper, #8a7d92);
	}
	.pw-grow {
		flex: 1;
	}
	.pw-soft {
		padding: 0.2rem 0.6rem;
		border-radius: 999px;
		color: var(--mist, #cfc3cc);
		background: var(--obsidian-lit, #1d1724);
	}
	.pw-soft:hover {
		color: var(--pearl, #f6eef3);
	}
	.pw-hint {
		margin-top: 0.45rem;
		color: var(--whisper, #8a7d92);
		font-size: 0.62rem;
		opacity: 0.8;
	}
</style>
