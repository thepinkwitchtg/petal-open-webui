<script lang="ts">
	// 🌙 PetalStatusChip — "what i'm on", always beside the chat input (sprint contract 1).
	//
	// the chip:  🌈 peak · 2h 10m   ·   🌙 integration · 2d 4h   ·   ✧ (nothing set)
	// one tap opens the panel. setting a status is: tap the chip → (last substance is
	// already chosen) → type the dose or tap "again" → enter. the time defaults to now
	// and follows now until you nudge it.
	//
	// lily only ever sets the start. the end, the integration window and its closing
	// arrive by themselves (the server derives them and writes the auto lines).
	// edits write an `amend`, never rewrite a line. Petal sees none of this yet.
	//
	// nothing animates, ever: the label re-reads once a minute while the page is
	// visible and something is counting down; a hidden page holds no timer at all.
	import { onDestroy, onMount, tick } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { previewDose, type MarkerPreview, type MarkerTimeline } from '$lib/apis/petal-markers';
	import {
		clock,
		doseText,
		markersError,
		markersNow,
		nextEdge,
		nowS,
		phaseAt,
		offerGatherUndo,
		refreshMarkers,
		setOutcome,
		span,
		writeMarker,
		writeTrip
	} from '$lib/utils/petal-markers';
	import type { TripResult } from '$lib/apis/petal-markers';

	export let temporary = false;

	let t = nowS();
	let timer: ReturnType<typeof setTimeout> | undefined;

	// ── the minute hand (only while visible and counting) ───────
	const schedule = () => {
		clearTimeout(timer);
		timer = undefined;
		if (typeof document === 'undefined' || document.visibilityState !== 'visible') return;
		const n = $markersNow;
		if (!n?.status && !n?.integration) return; // nothing counts down → no timer
		const edge = nextEdge(n, t);
		const minute = (Math.floor(nowS() / 60) + 1) * 60;
		const at = edge !== null ? Math.min(edge, minute) : minute;
		timer = setTimeout(
			async () => {
				t = nowS();
				if (edge !== null && t >= edge) await refreshMarkers(); // the server writes the auto line
				schedule();
			},
			Math.max(1000, (at - nowS()) * 1000 + 300)
		);
	};
	$: $markersNow, schedule();

	const onVisible = () => {
		if (document.visibilityState === 'visible') {
			t = nowS();
			refreshMarkers();
		} else {
			clearTimeout(timer);
			timer = undefined;
		}
	};

	onMount(() => {
		refreshMarkers();
		offerGatherUndo(); // 🌷 the ledger gathered a trip while she was away → one quiet undo
		document.addEventListener('visibilitychange', onVisible);
	});
	onDestroy(() => {
		clearTimeout(timer);
		clearTimeout(previewTimer);
		clearTimeout(voidTimer);
		clearTimeout(purgeTimer);
		clearTimeout(tripTimer);
		if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible);
		unlisten();
	});

	// ── what the chip says ──────────────────────────────────────
	$: n = $markersNow;
	$: current = [n?.status, ...(n?.also ?? [])].filter(
		(s): s is MarkerTimeline => !!s && ['upcoming', 'peak', 'active'].includes(phaseAt(s, t))
	);
	$: s = current[0] ?? null;
	$: phase = s ? phaseAt(s, t) : null;
	$: ig = n?.integration && n.integration.opens_at <= t && t < n.integration.closes_at ? n.integration : null;

	$: chip = s
		? {
				emoji: s.emoji,
				word: phase === 'upcoming' ? 'soon' : phase,
				left: s.end !== null ? span(s.end - t) : 'no end',
				tier: s.tier?.label ?? null
			}
		: ig
			? { emoji: ig.source === 'orbit' ? '✧' : '🌙', word: 'integration', left: span(ig.closes_at - t), tier: null }
			: null;

	$: chipTitle = s
		? `${s.label}${s.dose ? ` · ${doseText(s.dose, s.dose_unit)}` : ''} · ${chip?.word}${
				s.end !== null ? ` · ends ${clock(s.end, t)}` : ''
			}${ig ? ' · integration open' : ''}`
		: ig
			? `${ig.source === 'orbit' ? `✧ orbit · ${ig.outcome ?? 'open'} · ` : ''}integration · closes ${clock(ig.closes_at, t)}`
			: $markersError
				? `trip markers: ${$markersError}`
				: 'what are you on? ✧';

	// ── the panel ───────────────────────────────────────────────
	let chipEl: HTMLButtonElement;
	let panelEl: HTMLDivElement;
	let doseEl: HTMLInputElement;
	let open = false;
	let mode: 'view' | 'form' = 'view';
	let busy = false;
	let pos = { left: 8, bottom: 64, width: 352, maxH: 480 };

	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	}

	const place = () => {
		if (!chipEl) return;
		const r = chipEl.getBoundingClientRect();
		const vh = window.visualViewport?.height ?? window.innerHeight;
		const vw = window.innerWidth;
		// a mouse on a wide screen gets the compact panel; a phone keeps the thumb-sized one
		const compact = window.matchMedia?.('(pointer: fine) and (min-width: 641px)').matches;
		const width = Math.min(compact ? 296 : 352, vw - 16);
		pos = {
			width,
			left: Math.min(Math.max(8, r.left), vw - width - 8),
			bottom: Math.max(8, window.innerHeight - r.top + 8),
			maxH: Math.max(220, r.top - 16 - (window.innerHeight - vh))
		};
	};

	const onOutside = (e: PointerEvent) => {
		const el = e.target as Node;
		if (panelEl?.contains(el) || chipEl?.contains(el)) return;
		close();
	};
	const onKey = (e: KeyboardEvent) => {
		if (e.key === 'Escape') {
			e.stopPropagation();
			close();
		}
	};
	let listening = false;
	const listen = () => {
		if (listening) return;
		listening = true;
		document.addEventListener('pointerdown', onOutside, true);
		document.addEventListener('keydown', onKey, true);
		window.addEventListener('resize', place);
		window.visualViewport?.addEventListener('resize', place);
	};
	function unlisten() {
		if (!listening) return;
		listening = false;
		document.removeEventListener('pointerdown', onOutside, true);
		document.removeEventListener('keydown', onKey, true);
		window.removeEventListener('resize', place);
		window.visualViewport?.removeEventListener('resize', place);
	}

	const close = () => {
		open = false;
		voidArm = null;
		unlisten();
	};

	const toggle = async () => {
		if (open) return close();
		t = nowS();
		place();
		open = true;
		listen();
		if (current.length || ig) {
			mode = 'view';
		} else {
			newForm();
			await tick();
			focusDose();
		}
		refreshMarkers();
	};

	const focusDose = () => doseEl?.focus({ preventScroll: true });

	// ── the form (new status · or edit = amend) ─────────────────
	let editing: MarkerTimeline | null = null;
	let fSub: string | null = null; // a table key, or '__other'
	let fDose = '';
	let fTaken = nowS();
	let followNow = true;
	let fNote = '';
	let showNote = false;
	let fOtherName = '';
	let fOtherHours = '';
	let fStrain: string | null = null;

	$: table = n?.table ?? [];
	$: subOf = (key: string | null) => table.find((x) => x.key === key) ?? null;
	$: fEntry = subOf(fSub);
	$: lastAgain = fSub && fSub !== '__other' && !editing ? (n?.last_dose?.[fSub] ?? null) : null;
	// 1.2 · strains: potency/duration_x null = not tuned yet, so the strain is a note and changes nothing
	$: strainsOf = fEntry?.strains ?? [];
	$: fStrainRow = strainsOf.find((x) => x.key === fStrain) ?? null;
	const defaultStrain = (key: string | null) => subOf(key)?.strain_default ?? null;

	const newForm = () => {
		editing = null;
		const recent = Object.keys(n?.last_dose ?? {});
		fSub = recent.length ? recent[recent.length - 1] : (table[0]?.key ?? '__other');
		if (fSub !== '__other' && !subOf(fSub)) fSub = table[0]?.key ?? '__other';
		fStrain = defaultStrain(fSub);
		fDose = '';
		fTaken = nowS();
		followNow = true;
		fNote = '';
		showNote = false;
		fOtherName = '';
		fOtherHours = '';
		fEndOn = false;
		trip = null;
		tripErr = null;
		mode = 'form';
	};

	const editForm = async (st: MarkerTimeline) => {
		editing = st;
		const known = !!subOf(st.substance);
		fSub = known ? st.substance : '__other';
		fOtherName = known ? '' : st.substance;
		fOtherHours = '';
		fStrain = st.strain?.key ?? defaultStrain(st.substance);
		fDose = st.dose ?? '';
		fTaken = st.taken_at;
		followNow = false;
		fEndOn = false;
		trip = null;
		fNote = st.note ?? '';
		showNote = !!st.note;
		mode = 'form';
		await tick();
		focusDose();
	};

	const pickSub = async (key: string) => {
		if (fSub !== key) fStrain = defaultStrain(key);
		fSub = key;
		await tick();
		focusDose();
	};

	// preview: what this dose means (tier · duration · integration), asked gently
	let preview: MarkerPreview | null = null;
	let previewTimer: ReturnType<typeof setTimeout> | undefined;
	$: if (open && mode === 'form') schedulePreview(fSub, fDose, fStrain);
	function schedulePreview(sub: string | null, dose: string, strain: string | null) {
		clearTimeout(previewTimer);
		if (!sub || sub === '__other') {
			preview = null;
			return;
		}
		previewTimer = setTimeout(async () => {
			try {
				preview = await previewDose(localStorage.token, sub, dose.trim() || null, strain);
			} catch {
				preview = null;
			}
		}, 220);
	}

	// time: follows now until nudged · typed times later than now mean yesterday
	// A6 · a date too (‹ day ›, or type it), and for a trip that's over, her real end
	type When = 'taken' | 'end';
	const DAY = 86400;
	let fEndOn = false;
	let fEnd = nowS();
	$: takenShown = followNow ? t : fTaken;
	const baseOf = (w: When) => (w === 'end' ? fEnd : followNow ? nowS() : fTaken);
	const setWhen = (w: When, s2: number) => {
		if (w === 'end') {
			fEnd = Math.max((followNow ? nowS() : fTaken) + 60, Math.min(nowS(), s2));
		} else {
			followNow = false;
			fTaken = Math.min(nowS(), s2);
			if (fEndOn && fEnd <= fTaken) fEnd = Math.min(nowS(), fTaken + 3600);
		}
	};
	const nudge = (minutes: number, w: When = 'taken') => setWhen(w, baseOf(w) + minutes * 60);
	const setNow = () => {
		followNow = true;
		fEndOn = false; // a trip that starts now hasn't ended
		fTaken = nowS();
		t = nowS();
	};
	const pad = (x: number) => String(x).padStart(2, '0');
	const isoDay = (s2: number) => {
		const d = new Date(s2 * 1000);
		return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
	};
	const dayWord = (s2: number) => {
		const k = isoDay(s2);
		if (k === isoDay(t)) return 'today';
		if (k === isoDay(t - DAY)) return 'yesterday';
		return clock(s2, t).split(' ').slice(0, -1).join(' ') || k;
	};
	const shiftDay = (w: When, days: number) => setWhen(w, baseOf(w) + days * DAY);
	const typeDay = (w: When, raw: string) => {
		const m = raw.replace(/[\u2010-\u2015]/g, '-').trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
		if (!m) return;
		const d = new Date(baseOf(w) * 1000);
		d.setFullYear(+m[1], +m[2] - 1, +m[3]);
		setWhen(w, Math.floor(d.getTime() / 1000));
	};
	const typeTime = (unit: 'h' | 'm', raw: string, w: When = 'taken') => {
		const v = parseInt(raw, 10);
		if (!Number.isFinite(v)) return;
		const d = new Date(baseOf(w) * 1000);
		if (unit === 'h') d.setHours(Math.max(0, Math.min(23, v)));
		else d.setMinutes(Math.max(0, Math.min(59, v)));
		let s2 = Math.floor(d.getTime() / 1000);
		if (s2 > nowS() + 60) s2 -= DAY; // 23:30 typed at 00:10 → last night
		setWhen(w, s2);
	};
	const timeKey = (unit: 'h' | 'm', w: When = 'taken') => (e: KeyboardEvent) => {
		const step = (e.shiftKey ? 10 : 1) * (unit === 'h' ? 60 : 1);
		if (e.key === 'ArrowUp') nudge(step, w);
		else if (e.key === 'ArrowDown') nudge(-step, w);
		else if (e.key === 'Enter') submit();
		else return;
		e.preventDefault();
	};
	const timeWheel = (unit: 'h' | 'm', w: When = 'taken') => (e: WheelEvent) => {
		e.preventDefault();
		nudge((e.deltaY < 0 ? 1 : -1) * (e.shiftKey ? 10 : 1) * (unit === 'h' ? 60 : 1), w);
	};

	// the whole timeline, previewed by the server's own dry run (it can't disagree with the write)
	let trip: TripResult | null = null;
	let tripErr: string | null = null;
	let tripTimer: ReturnType<typeof setTimeout> | undefined;
	$: past = !editing && !followNow;
	$: if (open && mode === 'form') scheduleTrip(past, fSub, fDose, fStrain, fTaken, fEndOn, fEnd, fOtherName, fOtherHours);
	function tripBody(dry: boolean) {
		const hours = parseFloat(fOtherHours.replace(',', '.'));
		return {
			substance: fSub === '__other' ? fOtherName.trim() : fSub,
			dose: fDose.trim() || null,
			taken_at: followNow ? nowS() : fTaken,
			ended_at: fEndOn && !followNow ? fEnd : null,
			note: fNote.trim() || null,
			temp: temporary,
			dry_run: dry,
			...(strainsOf.length && fStrain ? { strain: fStrain } : {}),
			...(fSub === '__other' && Number.isFinite(hours) && hours > 0 ? { duration_h: hours } : {})
		};
	}
	function scheduleTrip(..._deps: unknown[]) {
		clearTimeout(tripTimer);
		if (!past || !fSub || doseMissing || (fSub === '__other' && !fOtherName.trim())) {
			trip = null;
			tripErr = null;
			return;
		}
		tripTimer = setTimeout(async () => {
			try {
				trip = await writeTrip(tripBody(true));
				tripErr = null;
			} catch (e) {
				trip = null;
				tripErr = `${e}`;
			}
		}, 260);
	}
	const enableEnd = () => {
		// start from the table's end (the dry run's, else the dose preview's), she nudges from there
		const dur = preview?.duration_h;
		const table = trip?.timeline?.expected_end ?? (dur != null ? Math.round(fTaken + dur * 3600) : null);
		fEnd = Math.max(fTaken + 60, Math.min(nowS(), table ?? nowS()));
		fEndOn = true;
	};

	// a curve substance scales with its dose: without a number it would never end
	$: doseMissing = !!fEntry?.needs_dose && !/\d/.test(fDose);
	$: canSubmit =
		!busy &&
		!!fSub &&
		(fSub !== '__other' || fOtherName.trim().length > 0) &&
		!doseMissing &&
		!(past && tripErr);

	const submit = async () => {
		if (!canSubmit) return;
		busy = true;
		try {
			const substance = fSub === '__other' ? fOtherName.trim() : (fSub as string);
			const dose = fDose.trim() || null;
			const taken_at = followNow ? nowS() : fTaken;
			const note = fNote.trim() || null;
			if (editing) {
				const fields: Record<string, unknown> = {};
				if (substance !== editing.substance) fields.substance = substance;
				if (dose !== (editing.dose ?? null)) fields.dose = dose;
				if (taken_at !== editing.taken_at) fields.taken_at = taken_at;
				if (strainsOf.length && fStrain !== (editing.strain?.key ?? null)) fields.strain = fStrain;
				if (note !== (editing.note ?? null)) fields.note = note;
				if (!Object.keys(fields).length) {
					mode = 'view';
					return;
				}
				await writeMarker({ kind: 'amend', ref: editing.id, fields, temp: temporary });
				toast.success('🌙 amended — the first line stays, the correction rides beside it');
			} else {
				// one lock on the server: the start line, then her real end (an amend or an end)
				const r = await writeTrip(tripBody(false));
				if (past) {
					const due = r.due.length ? ` · ${r.due.join(' + ')} due for the ledger` : '';
					const tl = r.timeline;
					toast.success(`${tl.emoji} locked in · ${clock(tl.taken_at, nowS())} → ${clock(tl.end ?? nowS(), nowS())}${due}`);
				}
			}
			t = nowS();
			close();
		} catch (e) {
			toast.error(`🌙 ${e}`);
		} finally {
			busy = false;
		}
	};

	// ── view actions ────────────────────────────────────────────
	const undoable = (msg: string, id: string) =>
		toast.success(msg, {
			action: {
				label: 'undo',
				onClick: () =>
					writeMarker({ kind: 'void', ref: id, reason: 'undo', temp: temporary }).catch((e) =>
						toast.error(`🌙 ${e}`)
					)
			}
		});

	const act = async (fn: () => Promise<void>) => {
		if (busy) return;
		busy = true;
		try {
			await fn();
			t = nowS();
		} catch (e) {
			toast.error(`🌙 ${e}`);
		} finally {
			busy = false;
		}
	};

	const endNow = (st: MarkerTimeline) =>
		act(async () => {
			const { id } = await writeMarker({ kind: 'status.end', ref: st.id, temp: temporary });
			undoable(`${st.emoji} ended · integration opens now`, id);
		});

	const closeIntegration = (id: string) =>
		act(async () => {
			const r = await writeMarker({ kind: 'integration.end', ref: id, temp: temporary });
			undoable('🌙 integration closed', r.id);
		});

	// A11 · ✧ an orbit's window: its outcome is one tap here too (tap the lit one again → open)
	const OUTCOMES = ['held', 'leaked'] as const;
	const pickOutcome = (id: string, outcome: 'held' | 'leaked' | null) =>
		act(async () => {
			await setOutcome(id, outcome);
		});

	const openIntegration = () =>
		act(async () => {
			const r = await writeMarker({ kind: 'integration.start', temp: temporary });
			undoable('🌙 integration open · it closes itself after the window in settings.json', r.id);
		});

	// 1.2 · 👽 the monsters are declared: on until taken + mutation_h, never shorter (one tap, undoable)
	const mutate = (st: MarkerTimeline) =>
		act(async () => {
			const h = subOf(st.substance)?.mutation_h;
			const r = await writeMarker({ kind: 'mutation', ref: st.id, temp: temporary });
			undoable(`👽 the monsters are declared${h ? ` · on until ${clock(st.taken_at + h * 3600, nowS())}` : ''}`, r.id);
		});
	$: mutationOpen = (st: MarkerTimeline | undefined | null) => {
		const h = st ? subOf(st.substance)?.mutation_h : null;
		return !!st && st.can_mutate && !!h && t < st.taken_at + h * 3600;
	};

	// purge shortens the trip, so it asks twice (stay on longer when unsure)
	let purgeArm: string | null = null;
	let purgeTimer: ReturnType<typeof setTimeout> | undefined;
	const purgeStatus = (st: MarkerTimeline) => {
		if (purgeArm !== st.id) {
			purgeArm = st.id;
			clearTimeout(purgeTimer);
			purgeTimer = setTimeout(() => (purgeArm = null), 4000);
			return;
		}
		purgeArm = null;
		act(async () => {
			const h = subOf(st.substance)?.purge_after_h;
			const r = await writeMarker({ kind: 'purge', ref: st.id, temp: temporary });
			undoable(`purge noted${h ? ` · integration within ~${h}h` : ''}`, r.id);
		});
	};

	const effText = (st: { dose: string | null; dose_eff: number | null; dose_unit: string | null }) => {
		const raw = st.dose ? parseFloat(st.dose.replace(',', '.').replace(/[^\d.]/g, '')) : NaN;
		if (st.dose_eff === null || !Number.isFinite(raw) || Math.abs(st.dose_eff - raw) < 1e-9) return '';
		return `≈\u00a0${Math.round(st.dose_eff * 100) / 100}${st.dose_unit ? `\u00a0${st.dose_unit}` : ''}`;
	};

	let voidArm: string | null = null;
	let voidTimer: ReturnType<typeof setTimeout> | undefined;
	const voidStatus = (st: MarkerTimeline) => {
		if (voidArm !== st.id) {
			voidArm = st.id;
			clearTimeout(voidTimer);
			voidTimer = setTimeout(() => (voidArm = null), 4000);
			return;
		}
		voidArm = null;
		act(async () => {
			const r = await writeMarker({ kind: 'void', ref: st.id, reason: 'never happened', temp: temporary });
			undoable(`${st.emoji} voided — kept in the log, gone from the view`, r.id);
		});
	};

	// the timeline bar: taken → end → integration close, as percentages
	const bar = (st: MarkerTimeline) => {
		const a = st.taken_at;
		const z = st.integration?.closes_at ?? st.end ?? Math.max(t, a + 3600);
		const span_ = Math.max(1, z - a);
		const pct = (x: number) => `${Math.max(0, Math.min(100, ((x - a) / span_) * 100))}%`;
		const w = (x: number, y: number) => `${Math.max(0, Math.min(100, ((y - x) / span_) * 100))}%`;
		return {
			active: st.end !== null ? { left: '0%', width: w(a, st.end) } : { left: '0%', width: '100%' },
			peak: st.peak ? { left: pct(st.peak[0]), width: w(st.peak[0], st.peak[1]) } : null,
			integ:
				st.integration && !st.integration.empty
					? { left: pct(st.integration.opens_at), width: w(st.integration.opens_at, st.integration.closes_at) }
					: null,
			now: pct(t)
		};
	};
</script>

{#if n || $markersError}
	<button
		type="button"
		bind:this={chipEl}
		class="pmk-chip"
		class:quiet={!chip}
		class:open
		data-phase={s ? phase : ig ? 'integration' : 'none'}
		title={chipTitle}
		aria-label={chipTitle}
		aria-expanded={open}
		on:click|preventDefault={toggle}
	>
		<span class="pmk-emoji" aria-hidden="true">{chip?.emoji ?? '✧'}</span>
		{#if chip}
			<span class="pmk-word">{chip.word}</span>
			<span class="pmk-left">{chip.left}</span>
			{#if s && ig}<span class="pmk-soft">·</span><span class="pmk-moon" aria-label="integration open">🌙</span>{/if}
			{#if current.length > 1}<span class="pmk-plus">+{current.length - 1}</span>{/if}
			{#if chip.tier}<span class="pmk-tier">{chip.tier}</span>{/if}
		{/if}
	</button>
{/if}

{#if open}
	<div
		use:portal
		bind:this={panelEl}
		class="pmk-panel"
		role="dialog"
		aria-label="trip markers"
		style="left:{pos.left}px; bottom:{pos.bottom}px; width:{pos.width}px; max-height:{pos.maxH}px"
	>
		{#if mode === 'view'}
			{#each current as st (st.id)}
				{@const b = bar(st)}
				{@const ph = phaseAt(st, t)}
				<section class="pmk-card">
					<header class="pmk-head">
						<span class="pmk-big" aria-hidden="true">{st.emoji}</span>
						<div class="pmk-title">
							<div class="pmk-name">
								{st.label}{#if st.dose}<span class="pmk-dose"
										>{'\u00a0· '}{doseText(st.dose, st.dose_unit)}{#if st.strain}{' '}{st.strain.label}{/if}{#if effText(st)}{' '}<span
												class="pmk-eff">{effText(st)}</span
											>{/if}</span
									>{/if}
								{#if st.mutated}<span class="pmk-mini" title="the monsters are declared">👽</span>{/if}
								{#if st.amended}<span class="pmk-mini" title="corrected by an amend">✎</span>{/if}
							</div>
							{#if st.tier}<div class="pmk-tiername">{st.tier.label}</div>{/if}
						</div>
						<span class="pmk-phase" data-phase={ph}>{ph === 'upcoming' ? 'soon' : ph}</span>
					</header>

					<div class="pmk-bar" aria-hidden="true">
						<i class="pmk-seg active" style="left:{b.active.left}; width:{b.active.width}"></i>
						{#if b.peak}<i class="pmk-seg peak" style="left:{b.peak.left}; width:{b.peak.width}"></i>{/if}
						{#if b.integ}<i class="pmk-seg integ" style="left:{b.integ.left}; width:{b.integ.width}"></i>{/if}
						<i class="pmk-now" style="left:{b.now}"></i>
					</div>

					<dl class="pmk-facts">
						<dt>taken</dt>
						<dd>{clock(st.taken_at, t)} <span class="pmk-soft">· {span(t - st.taken_at)} ago</span></dd>
						{#if st.peak && t < st.peak[1]}
							<dt>peak</dt>
							<dd>until {clock(st.peak[1], t)} <span class="pmk-soft">· {span(st.peak[1] - t)}</span></dd>
						{/if}
						<dt>ends</dt>
						{#if st.end !== null}
							<dd>
								~{clock(st.end, t)} <span class="pmk-soft">· in {span(st.end - t)}</span>
							</dd>
						{:else}
							<dd class="pmk-soft">no end known — {st.why_no_end ?? 'end it by hand'}</dd>
						{/if}
						{#if st.mutated}
							<dt>👽</dt>
							<dd>declared {clock(st.mutated.at, t)}</dd>
						{/if}
						{#if st.purged}
							<dt>purge</dt>
							<dd>{clock(st.purged.at, t)}</dd>
						{/if}
						{#if st.integration && !st.integration.empty}
							<dt>integration</dt>
							<dd>{clock(st.integration.opens_at, t)} → {clock(st.integration.closes_at, t)}</dd>
						{/if}
						{#if st.temp}
							<dt></dt>
							<dd class="pmk-soft">set from a temp chat · kept without a chat link</dd>
						{/if}
					</dl>

					{#if mutationOpen(st) || st.can_purge}
						<div class="pmk-actions">
							{#if mutationOpen(st)}
								<button
									type="button"
									class="pmk-soft-btn"
									disabled={busy}
									title="the monsters are declared · stays on until {subOf(st.substance)?.mutation_h} h after ingestion, never shorter"
									on:click={() => mutate(st)}>👽 monsters</button
								>
							{/if}
							{#if st.can_purge}
								<button
									type="button"
									class="pmk-soft-btn"
									class:armed={purgeArm === st.id}
									disabled={busy}
									title="the trip may close early: integration within ~{subOf(st.substance)?.purge_after_h} h"
									on:click={() => purgeStatus(st)}>{purgeArm === st.id ? 'sure? purged' : 'purge'}</button
								>
							{/if}
						</div>
					{/if}
					<div class="pmk-actions">
						<button type="button" class="pmk-soft-btn" disabled={busy} on:click={() => editForm(st)}>✎ edit</button>
						<button type="button" class="pmk-soft-btn" disabled={busy} on:click={() => endNow(st)}>end now</button>
						<button
							type="button"
							class="pmk-soft-btn ghost"
							class:armed={voidArm === st.id}
							disabled={busy}
							title="it never happened — kept in the log, gone from the view"
							on:click={() => voidStatus(st)}>{voidArm === st.id ? 'sure? never happened' : 'void'}</button
						>
					</div>
				</section>
			{/each}

			{#if ig}
				<section class="pmk-card integ">
					<header class="pmk-head">
						<span class="pmk-big" aria-hidden="true">{ig.source === 'orbit' ? '✧' : '🌙'}</span>
						<div class="pmk-title">
							<div class="pmk-name">integration</div>
							<div class="pmk-soft">
								{ig.label ?? 'opened by hand'}{ig.source === 'orbit' ? ` · ${clock(ig.opens_at, t)}` : ''} · closes {clock(
									ig.closes_at,
									t
								)} · {span(ig.closes_at - t)}
							</div>
						</div>
					</header>
					{#if ig.source === 'orbit'}
						<div class="pmk-outcome" role="group" aria-label="the orbit's outcome">
							{#each OUTCOMES as o (o)}
								<button
									type="button"
									class="pmk-pill"
									class:on={ig.outcome === o}
									disabled={busy}
									on:click={() => ig && pickOutcome(ig.id, ig.outcome === o ? null : o)}>{o}</button
								>
							{/each}
							{#if !ig.outcome}<span class="pmk-soft">open</span>{/if}
						</div>
					{/if}
					<div class="pmk-actions">
						{#if ig.status && mutationOpen(ig.status)}
							<button
								type="button"
								class="pmk-soft-btn"
								disabled={busy}
								title="still deep? the monsters are declared · the trip comes back on until {subOf(ig.status.substance)
									?.mutation_h} h after ingestion"
								on:click={() => ig?.status && mutate(ig.status)}>👽 still deep</button
							>
						{/if}
						<button type="button" class="pmk-soft-btn" disabled={busy} on:click={() => closeIntegration(ig.id)}
							>close integration</button
						>
					</div>
				</section>
			{/if}

			<div class="pmk-actions foot">
				<button type="button" class="pmk-go" disabled={busy} on:click={async () => { newForm(); await tick(); focusDose(); }}
					>＋ status</button
				>
				{#if !ig}
					<button type="button" class="pmk-soft-btn" disabled={busy} on:click={openIntegration}>🌙 open integration</button>
				{/if}
			</div>
		{:else}
			<form class="pmk-form" on:submit|preventDefault={submit}>
				<div class="pmk-k">{editing ? 'correct this status' : 'what are you on?'}</div>
				<div class="pmk-subs">
					{#each table as sub (sub.key)}
						<button
							type="button"
							class="pmk-sub"
							class:on={fSub === sub.key}
							on:click={() => pickSub(sub.key)}
						>
							<span class="pmk-sub-emoji" aria-hidden="true">{sub.emoji}</span>{sub.label}
						</button>
					{/each}
					<button type="button" class="pmk-sub" class:on={fSub === '__other'} on:click={() => pickSub('__other')}>
						<span class="pmk-sub-emoji" aria-hidden="true">✧</span>other
					</button>
				</div>

				{#if strainsOf.length}
					<div class="pmk-subs">
						{#each strainsOf as sv (sv.key)}
							<button type="button" class="pmk-strain" class:on={fStrain === sv.key} on:click={() => (fStrain = sv.key)}
								>{sv.label}</button
							>
						{/each}
					</div>
					{#if fStrainRow?.note}
						<div class="pmk-warn">
							⚠ {fStrainRow.label} · {fStrainRow.note}{#if fStrainRow.potency === null && fStrainRow.duration_x === null}<span
									class="pmk-soft"
								>{'\u00a0· not tuned yet, so it changes nothing'}</span
								>{/if}
						</div>
					{/if}
				{/if}

				{#if fSub === '__other'}
					<div class="pmk-row">
						<input class="pmk-field grow" placeholder="what" bind:value={fOtherName} maxlength="64" />
						<input
							class="pmk-field narrow"
							placeholder="hours"
							inputmode="decimal"
							bind:value={fOtherHours}
							title="how long it lasts — leave empty and end it by hand"
						/>
					</div>
				{/if}

				<div class="pmk-row">
					<input
						bind:this={doseEl}
						class="pmk-field grow mono"
						placeholder={fEntry ? `dose${fEntry.dose_unit ? ` (${fEntry.dose_unit})` : ''}` : 'dose (if known)'}
						inputmode="decimal"
						maxlength="32"
						bind:value={fDose}
						on:keydown={(e) => e.key === 'Enter' && (e.preventDefault(), submit())}
					/>
					{#if fEntry?.dose_unit}<span class="pmk-unit">{fEntry.dose_unit}</span>{/if}
					{#if lastAgain && !fDose}
						<button type="button" class="pmk-soft-btn" on:click={() => (fDose = String(lastAgain))}
							>↺ {lastAgain} again</button
						>
					{/if}
				</div>
				{#if doseMissing}
					<div class="pmk-soft small">
						{fEntry?.label} scales with its dose — the end, the tier and the record all need the number
					</div>
				{/if}
				{#if preview && !doseMissing}
					<div class="pmk-preview">
						{#if effText({ dose: fDose, dose_eff: preview.dose_eff, dose_unit: preview.dose_unit })}
							<span class="pmk-eff">{effText({ dose: fDose, dose_eff: preview.dose_eff, dose_unit: preview.dose_unit })}</span>
						{/if}
						{#if preview.tier}<span class="pmk-tiername">{preview.tier.label}</span>{/if}
						{#if preview.duration_h !== null}
							<span>~{Math.round(preview.duration_h * 10) / 10}h</span>
							<span class="pmk-soft"
								>· integration from {Math.round(preview.duration_h * preview.integration_from * 10) / 10}h</span
							>
						{:else if preview.why_no_end && fDose.trim()}
							<span class="pmk-soft">{preview.why_no_end}</span>
						{/if}
					</div>
				{/if}

				<div class="pmk-k">
					taken · {followNow ? 'now' : `${dayWord(fTaken)} · ${span(nowS() - fTaken)} ago`}
				</div>
				<div class="pmk-row">
					<button type="button" class="pmk-step" aria-label="a day earlier" on:click={() => shiftDay('taken', -1)}>‹</button>
					<input
						class="pmk-day"
						inputmode="numeric"
						aria-label="day taken"
						value={isoDay(takenShown)}
						on:change={(e) => typeDay('taken', e.currentTarget.value)}
						on:keydown={(e) => e.key === 'Enter' && (e.preventDefault(), typeDay('taken', e.currentTarget.value))}
					/>
					<button
						type="button"
						class="pmk-step"
						aria-label="a day later"
						disabled={isoDay(takenShown) === isoDay(t)}
						on:click={() => shiftDay('taken', 1)}>›</button
					>
					<span class="pmk-gap"></span>
					<input
						class="pmk-num"
						inputmode="numeric"
						aria-label="hour taken"
						value={pad(new Date(takenShown * 1000).getHours())}
						on:keydown={timeKey('h')}
						on:wheel={timeWheel('h')}
						on:change={(e) => typeTime('h', e.currentTarget.value)}
					/>
					<span class="pmk-soft">:</span>
					<input
						class="pmk-num"
						inputmode="numeric"
						aria-label="minute taken"
						value={pad(new Date(takenShown * 1000).getMinutes())}
						on:keydown={timeKey('m')}
						on:wheel={timeWheel('m')}
						on:change={(e) => typeTime('m', e.currentTarget.value)}
					/>
				</div>
				<div class="pmk-row">
					<button type="button" class="pmk-soft-btn tight" class:lit={followNow} on:click={setNow}>now</button>
					<button type="button" class="pmk-soft-btn tight" on:click={() => nudge(-5)}>−5m</button>
					<button type="button" class="pmk-soft-btn tight" on:click={() => nudge(-15)}>−15m</button>
					<button type="button" class="pmk-soft-btn tight" on:click={() => nudge(-60)}>−1h</button>
				</div>

				{#if past}
					{#if fEndOn}
						<div class="pmk-k">
							ended · {dayWord(fEnd)} · {span(fEnd - fTaken)} after
							<button type="button" class="pmk-link" on:click={() => (fEndOn = false)}>let the table decide</button>
						</div>
						<div class="pmk-row">
							<button type="button" class="pmk-step" aria-label="a day earlier" on:click={() => shiftDay('end', -1)}>‹</button>
							<input
								class="pmk-day"
								inputmode="numeric"
								aria-label="day it ended"
								value={isoDay(fEnd)}
								on:change={(e) => typeDay('end', e.currentTarget.value)}
								on:keydown={(e) => e.key === 'Enter' && (e.preventDefault(), typeDay('end', e.currentTarget.value))}
							/>
							<button
								type="button"
								class="pmk-step"
								aria-label="a day later"
								disabled={isoDay(fEnd) === isoDay(t)}
								on:click={() => shiftDay('end', 1)}>›</button
							>
							<span class="pmk-gap"></span>
							<input
								class="pmk-num"
								inputmode="numeric"
								aria-label="hour it ended"
								value={pad(new Date(fEnd * 1000).getHours())}
								on:keydown={timeKey('h', 'end')}
								on:wheel={timeWheel('h', 'end')}
								on:change={(e) => typeTime('h', e.currentTarget.value, 'end')}
							/>
							<span class="pmk-soft">:</span>
							<input
								class="pmk-num"
								inputmode="numeric"
								aria-label="minute it ended"
								value={pad(new Date(fEnd * 1000).getMinutes())}
								on:keydown={timeKey('m', 'end')}
								on:wheel={timeWheel('m', 'end')}
								on:change={(e) => typeTime('m', e.currentTarget.value, 'end')}
							/>
						</div>
					{:else}
						<button type="button" class="pmk-link start" on:click={enableEnd}>＋ it already ended at…</button>
					{/if}

					{#if tripErr}
						<div class="pmk-warn">{tripErr}</div>
					{:else if trip}
						{@const tl = trip.timeline}
						{@const b = bar(tl)}
						<div class="pmk-tripview">
							<div class="pmk-bar" aria-hidden="true">
								<i class="pmk-seg active" style="left:{b.active.left}; width:{b.active.width}"></i>
								{#if b.peak}<i class="pmk-seg peak" style="left:{b.peak.left}; width:{b.peak.width}"></i>{/if}
								{#if b.integ}<i class="pmk-seg integ" style="left:{b.integ.left}; width:{b.integ.width}"></i>{/if}
								<i class="pmk-now" style="left:{b.now}"></i>
							</div>
							<dl class="pmk-facts">
								<dt>ends</dt>
								<dd>
									{#if tl.end !== null}~{clock(tl.end, t)}
										<span class="pmk-soft">· {fEndOn ? 'your end' : 'from the table'}</span>
									{:else}<span class="pmk-soft">no end known — {tl.why_no_end ?? 'end it by hand'}</span>{/if}
								</dd>
								{#if tl.integration && !tl.integration.empty}
									<dt>integration</dt>
									<dd>{clock(tl.integration.opens_at, t)} → {clock(tl.integration.closes_at, t)}</dd>
								{/if}
								<dt>harvests</dt>
								<dd>
									{#if trip.due.length}{trip.due.join(' + ')} <span class="pmk-soft">· due once locked in</span>
									{:else}<span class="pmk-soft">when it ends</span>{/if}
								</dd>
							</dl>
						</div>
					{/if}
				{/if}

				{#if showNote}
					<textarea class="pmk-field note" rows="2" placeholder="note (only for you)" bind:value={fNote}></textarea>
				{/if}

				<div class="pmk-actions foot">
					<button type="submit" class="pmk-go" disabled={!canSubmit}>
						{editing ? 'save the correction' : past ? `lock it in ${fEntry?.emoji ?? '✧'}` : `set ${fEntry?.emoji ?? '✧'}`}
					</button>
					{#if !showNote}
						<button type="button" class="pmk-soft-btn ghost" on:click={() => (showNote = true)}>＋ note</button>
					{/if}
					{#if current.length || ig}
						<button type="button" class="pmk-soft-btn ghost" on:click={() => (mode = 'view')}>back</button>
					{/if}
				</div>
				{#if temporary && !editing}
					<div class="pmk-soft small">temp chat · your status still counts (it's about you, not the chat)</div>
				{/if}
			</form>
		{/if}
	</div>
{/if}

<style>
	/* every colour comes from the Abyssal Pink tokens; the fallbacks only matter
	   if the petal theme isn't loaded. pink lives in gradients, never a flat fill.
	   no keyframes anywhere — nothing moves on its own. */
	.pmk-chip {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		flex-shrink: 0;
		max-width: 100%;
		height: 1.875rem;
		padding: 0 0.6rem 0 0.45rem;
		border-radius: 999px;
		border: 1px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.3);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.08);
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
		line-height: 1;
		white-space: nowrap;
		transition:
			border-color 140ms,
			background-color 140ms,
			opacity 140ms;
	}
	.pmk-chip:hover,
	.pmk-chip.open {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.55);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.14);
	}
	.pmk-chip.quiet {
		width: 1.875rem;
		padding: 0;
		justify-content: center;
		border-color: transparent;
		background: transparent;
		opacity: 0.55;
	}
	.pmk-chip.quiet:hover {
		opacity: 1;
		background: var(--obsidian-lit, #1d1724);
	}
	/* peak: the gradient hairline (static) */
	.pmk-chip[data-phase='peak'] {
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian, #15111b), var(--obsidian, #15111b)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
	}
	/* integration: purple-up */
	.pmk-chip[data-phase='integration'] {
		border-color: oklch(0.622 0.186 calc(var(--p-h-accent, 352) - 36) / 0.4);
		background: oklch(0.622 0.186 calc(var(--p-h-accent, 352) - 36) / 0.1);
	}
	.pmk-emoji,
	.pmk-big,
	.pmk-moon,
	.pmk-sub-emoji {
		font-family: var(--font-emoji, 'SamsungColorEmoji'), sans-serif;
	}
	.pmk-emoji {
		font-size: 0.95rem;
	}
	.pmk-word {
		color: var(--pearl, #f6eef3);
	}
	.pmk-left {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.72rem;
		color: var(--mist, #cfc3cc);
		font-variant-numeric: tabular-nums;
	}
	.pmk-moon {
		font-size: 0.75rem;
	}
	.pmk-plus {
		font-size: 0.65rem;
		color: var(--whisper, #8a7d92);
	}
	.pmk-tier {
		max-width: 9rem;
		overflow: hidden;
		text-overflow: ellipsis;
		font-size: 0.7rem;
		background: var(--grad-text, linear-gradient(100deg, #f9c6dc, #f472b6 46%, #a873f0));
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	@media (max-width: 640px) {
		.pmk-tier {
			display: none; /* the panel always names the tier; the phone row stays short */
		}
	}

	.pmk-panel,
	.pmk-panel * {
		box-sizing: border-box;
	}
	.pmk-panel {
		position: fixed;
		z-index: 9999;
		overflow-y: auto;
		overscroll-behavior: contain;
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		padding: 0.75rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		box-shadow:
			inset 0 1px 0 var(--glass-sheen, rgba(255, 255, 255, 0.03)),
			0 18px 40px -18px oklch(0 0 0 / 0.7);
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
	}
	.pmk-card {
		display: flex;
		flex-direction: column;
		gap: 0.55rem;
	}
	.pmk-card + .pmk-card {
		padding-top: 0.6rem;
		border-top: 1px solid var(--edge-soft, #2a2433);
	}
	.pmk-head {
		display: flex;
		align-items: center;
		gap: 0.55rem;
	}
	.pmk-big {
		font-size: 1.5rem;
		line-height: 1;
	}
	.pmk-title {
		flex: 1;
		min-width: 0;
	}
	.pmk-name {
		font-family: var(--font-display, Georgia, serif);
		font-size: 1rem;
		color: var(--pearl, #f6eef3);
	}
	.pmk-dose {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.8rem;
		color: var(--mist, #cfc3cc);
	}
	.pmk-mini {
		margin-left: 0.25rem;
		font-size: 0.7rem;
		color: var(--whisper, #8a7d92);
	}
	.pmk-tiername {
		font-size: 0.75rem;
		background: var(--grad-text, linear-gradient(100deg, #f9c6dc, #f472b6 46%, #a873f0));
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
	}
	.pmk-phase {
		padding: 0.15rem 0.55rem;
		border-radius: 999px;
		font-size: 0.7rem;
		border: 1px solid var(--edge-lit, #463b52);
		color: var(--pearl, #f6eef3);
	}
	.pmk-phase[data-phase='peak'] {
		border-color: transparent;
		background: var(--grad-fill, linear-gradient(135deg, #f9c6dc, #f472b6 48%, #a873f0));
		color: var(--abyss, #0c0910);
		font-weight: 600;
	}

	.pmk-bar {
		position: relative;
		height: 0.4rem;
		border-radius: 999px;
		background: var(--abyss, #0c0910);
		overflow: hidden;
	}
	.pmk-seg {
		position: absolute;
		top: 0;
		bottom: 0;
	}
	.pmk-seg.active {
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.28);
	}
	.pmk-seg.peak {
		background: var(--grad-fill, linear-gradient(135deg, #f9c6dc, #f472b6 48%, #a873f0));
		opacity: 0.85;
	}
	.pmk-seg.integ {
		background: oklch(0.622 0.186 calc(var(--p-h-accent, 352) - 36) / 0.35);
	}
	.pmk-now {
		position: absolute;
		top: -2px;
		bottom: -2px;
		width: 2px;
		margin-left: -1px;
		background: var(--pearl, #f6eef3);
	}

	.pmk-facts {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.2rem 0.7rem;
		margin: 0;
		font-size: 0.75rem;
	}
	.pmk-facts dt {
		color: var(--whisper, #8a7d92);
	}
	.pmk-facts dd {
		margin: 0;
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.72rem;
		color: var(--pearl, #f6eef3);
	}
	.pmk-soft {
		color: var(--whisper, #8a7d92);
	}
	.small {
		font-size: 0.68rem;
	}

	.pmk-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.pmk-actions.foot {
		padding-top: 0.15rem;
	}
	.pmk-outcome {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}
	.pmk-pill {
		min-height: 2.25rem;
		min-width: 4.5rem;
		padding: 0 0.85rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--abyss, #0c0910);
		color: var(--mist, #cfc3cc);
		font-size: 0.78rem;
	}
	.pmk-pill.on {
		border-color: transparent;
		background:
			linear-gradient(var(--obsidian-lit, #1d1724), var(--obsidian-lit, #1d1724)) padding-box,
			var(--grad-hairline, linear-gradient(135deg, #f9c6dc, #f472b6 45%, #a873f0)) border-box;
		color: var(--pearl, #f6eef3);
	}
	.pmk-soft-btn,
	.pmk-go,
	.pmk-sub {
		min-height: 2.25rem; /* thumb-sized on the phone */
		padding: 0 0.8rem;
		border-radius: 999px;
		font-size: 0.78rem;
		transition:
			background-color 140ms,
			color 140ms,
			border-color 140ms;
	}
	.pmk-soft-btn {
		color: var(--mist, #cfc3cc);
		background: var(--obsidian-lit, #1d1724);
		border: 1px solid transparent;
	}
	.pmk-soft-btn:hover {
		color: var(--pearl, #f6eef3);
		border-color: var(--edge-lit, #463b52);
	}
	.pmk-soft-btn.lit {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.55);
		color: var(--pearl, #f6eef3);
	}
	.pmk-soft-btn.tight {
		flex: 1;
		padding: 0 0.4rem;
	}
	.pmk-soft-btn.ghost {
		background: transparent;
		color: var(--whisper, #8a7d92);
	}
	.pmk-soft-btn.armed {
		color: var(--pearl, #f6eef3);
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.55);
	}
	.pmk-soft-btn:disabled,
	.pmk-go:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.pmk-go {
		background: var(--grad-fill, linear-gradient(135deg, #f9c6dc, #f472b6 48%, #a873f0));
		color: var(--abyss, #0c0910);
		font-weight: 600;
	}

	.pmk-form {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.pmk-k {
		color: var(--whisper, #8a7d92);
		font-size: 0.72rem;
	}
	.pmk-subs {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.pmk-sub {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--abyss, #0c0910);
		color: var(--mist, #cfc3cc);
	}
	.pmk-sub-emoji {
		font-size: 1.05rem;
	}
	.pmk-sub.on {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.55);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.1);
		color: var(--pearl, #f6eef3);
	}
	.pmk-step {
		width: 2.25rem;
		min-height: 2.25rem;
		flex-shrink: 0;
		border-radius: var(--radius-sm, 8px);
		background: var(--obsidian-lit, #1d1724);
		color: var(--mist, #cfc3cc);
		font-size: 1rem;
		line-height: 1;
	}
	.pmk-step:disabled {
		opacity: 0.35;
		cursor: default;
	}
	.pmk-day {
		width: 6.6rem;
		min-height: 2.25rem;
		padding: 0;
		border-radius: var(--radius-sm, 8px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--abyss, #0c0910);
		color: var(--pearl, #f6eef3);
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.8rem;
		text-align: center;
		outline: none;
	}
	.pmk-day:focus {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.55);
	}
	.pmk-gap {
		flex: 1;
		min-width: 0.25rem;
	}
	.pmk-link {
		color: var(--candy-light, #f9c6dc);
		font-size: 0.72rem;
		text-decoration: underline;
		text-decoration-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.35);
		text-underline-offset: 2px;
	}
	.pmk-k .pmk-link {
		margin-left: 0.35rem;
	}
	.pmk-link.start {
		align-self: flex-start;
		min-height: 1.9rem;
	}
	.pmk-tripview {
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
		padding: 0.55rem 0.6rem;
		border-radius: var(--radius-sm, 8px);
		background: var(--abyss, #0c0910);
	}
	.pmk-strain {
		min-height: 1.9rem;
		padding: 0 0.7rem;
		border-radius: 999px;
		font-size: 0.74rem;
		border: 1px solid var(--edge-soft, #2a2433);
		color: var(--mist, #cfc3cc);
		transition:
			border-color 140ms,
			color 140ms;
	}
	.pmk-strain.on {
		border-color: oklch(0.622 0.186 calc(var(--p-h-accent, 352) - 36) / 0.55);
		color: var(--pearl, #f6eef3);
	}
	.pmk-warn {
		font-size: 0.72rem;
		color: var(--candy-light, #f9c6dc);
	}
	.pmk-eff {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.72rem;
		color: var(--candy-light, #f9c6dc);
	}
	.pmk-row {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}
	.pmk-field,
	.pmk-num {
		min-height: 2.25rem;
		padding: 0 0.7rem;
		border-radius: var(--radius-sm, 8px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--abyss, #0c0910);
		color: var(--pearl, #f6eef3);
		outline: none;
		font-size: 0.85rem;
	}
	.pmk-field:focus,
	.pmk-num:focus {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.55);
	}
	.pmk-field.grow {
		flex: 1;
		min-width: 0;
	}
	.pmk-field.narrow {
		width: 5rem;
	}
	.pmk-field.mono,
	.pmk-num {
		font-family: var(--font-mono, ui-monospace, monospace);
	}
	.pmk-field.note {
		padding: 0.5rem 0.7rem;
		resize: vertical;
	}
	.pmk-num {
		width: 2.8rem;
		padding: 0;
		text-align: center;
	}
	.pmk-unit {
		color: var(--whisper, #8a7d92);
		font-family: var(--font-mono, ui-monospace, monospace);
	}
	/* desktop · a mouse needs less room than a thumb (the phone layout above stays as is) */
	@media (pointer: fine) and (min-width: 641px) {
		.pmk-panel {
			gap: 0.45rem;
			padding: 0.6rem;
			font-size: 0.74rem;
		}
		.pmk-card,
		.pmk-form {
			gap: 0.4rem;
		}
		.pmk-head {
			gap: 0.45rem;
		}
		.pmk-big {
			font-size: 1.15rem;
		}
		.pmk-name {
			font-size: 0.88rem;
		}
		.pmk-soft-btn,
		.pmk-go,
		.pmk-sub,
		.pmk-pill {
			min-height: 1.7rem;
			padding: 0 0.6rem;
			font-size: 0.71rem;
		}
		.pmk-pill {
			min-width: 3.6rem;
		}
		.pmk-soft-btn.tight {
			padding: 0 0.3rem;
		}
		.pmk-strain {
			min-height: 1.5rem;
			padding: 0 0.5rem;
			font-size: 0.68rem;
		}
		.pmk-sub-emoji {
			font-size: 0.9rem;
		}
		.pmk-field,
		.pmk-num {
			min-height: 1.8rem;
			font-size: 0.78rem;
		}
		.pmk-field {
			padding: 0 0.55rem;
		}
		.pmk-num {
			width: 2.3rem;
		}
		.pmk-step {
			width: 1.7rem;
			min-height: 1.7rem;
			font-size: 0.85rem;
		}
		.pmk-day {
			width: 5.6rem;
			min-height: 1.8rem;
			font-size: 0.74rem;
		}
		.pmk-tripview {
			gap: 0.35rem;
			padding: 0.45rem 0.5rem;
		}
		.pmk-actions,
		.pmk-subs {
			gap: 0.3rem;
		}
		.pmk-facts {
			gap: 0.12rem 0.6rem;
			font-size: 0.7rem;
		}
		.pmk-facts dd {
			font-size: 0.68rem;
		}
		.pmk-bar {
			height: 0.3rem;
		}
	}
	.pmk-preview {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
		align-items: baseline;
		font-size: 0.75rem;
		color: var(--pearl, #f6eef3);
	}
</style>
