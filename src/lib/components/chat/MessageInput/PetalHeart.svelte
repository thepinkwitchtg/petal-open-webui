<script context="module" lang="ts">
	let seq = 0; // one heart per bar (a split view holds two): each opens its own picker
</script>

<script lang="ts">
	// 💗 the heart by send (slice A39) — one tap opens the picker where every Petal control lives: 🌀 the mode,
	// 🍒 the next reply's pick, 🎧 her voice, 🌊 her stream (A41: Petal speaks on her own in this chat, the way a
	// profile of hers says), 🌙 the trip window (🔥 her vow), 🌕 the fusion check and her pinned filters (💗
	// heartstrings: on or off in this chat, and its sliders). deeper menus where a control has more
	// to it (the modes, the voice's three ways). 📌 keeps one or two of them on the bar beside the heart (her
	// choice, per device · utils/petal-heart.ts). a tiny dot on the heart when a non-default mode or a pick is on.
	//  · the phone: a sheet the screen's width, above the keyboard, rows a thumb can reach (44 px)
	//  · the desktop: a panel above the heart; ↑ ↓ move between rows, Esc steps back then closes, and the keys of
	//    the controls work as ever (Ctrl+Space, Ctrl+Alt+P) whether their chips are pinned or not
	//  · nothing moves at rest: the sheet settles in once when it opens (none with reduced motion), then rests
	import { getContext, onDestroy, tick } from 'svelte';
	import { get, type Writable } from 'svelte/store';

	import { updateUserSettings } from '$lib/apis/users';
	import { formatChord, keybindings, Shortcut } from '$lib/shortcuts';
	import { settings, showSettings } from '$lib/stores';
	import { audioRoute, autoMode, earphones, followRoute, isPhone, setAutoMode, setEarphones, type AutoMode } from '$lib/utils/petal-autoplay';
	import { fusionRules } from '$lib/utils/petal-fusion';
	import { heartOpen, heartPins, placeSheet, togglePin, type HeartPin, type Place } from '$lib/utils/petal-heart';
	import { keepMode, leadOf, modeOf, modes, modeTick } from '$lib/utils/petal-mode';
	import { askPick, pickAsked, pickAskWhy } from '$lib/utils/petal-pick';
	import {
		lastOf,
		loadLoungeKnobs,
		loadLoungeShelf,
		loungeOn,
		loungeSheet,
		loungeShelf,
		loungeShelfError,
		loungeStatus,
		loungeTurnOff,
		loungeTurnOn,
		type LoungeProfile,
		type LoungeStatus
	} from '$lib/utils/petal-lounge';
	import { stopAllVoice, voiceUI } from '$lib/utils/petal-voice';

	type PinnedFilter = { id: string; emoji: string; name: string; on: boolean; valves: boolean };

	export let chatId: string | null = null;
	export let admin = false;
	export let filters: PinnedFilter[] = [];
	export let onFilter: (id: string, what: 'toggle' | 'valves') => void = () => {};
	export let trip: { emoji: string; text: string } | null = null; // the trip chip's words (null: no markers here)
	export let vow: { text: string } | null = null;
	export let onTrip: (which: 'trip' | 'vow', anchor: HTMLElement) => void = () => {};

	const i18n: Writable<any> = getContext('i18n');
	const me = `heart-${++seq}`;
	const phone = isPhone();

	let btn: HTMLButtonElement;
	let sheet: HTMLDivElement;
	let view: 'main' | 'mode' | 'voice' | 'stream' | 'knobs' = 'main';
	let place: Place = { phone: false, left: 8, width: 320, bottom: 64, maxH: 480 };

	$: open = $heartOpen === me;
	$: current = $modeTick >= 0 ? modeOf($modes, chatId) : null;
	$: lead = leadOf($modes);
	$: offMode = !!(current && lead && current.key !== lead.key);
	$: stream = chatId ? ($loungeOn[chatId] ?? null) : null; // 🌊 A41 · this chat's stream, when it's open to her
	$: dot = offMode || $pickAsked || !!stream?.on;
	$: shelf = $loungeShelf;
	$: shelfError = $loungeShelfError;
	$: line = chatId && stream?.on ? ($loungeStatus[chatId] ?? null) : null;
	// 🌊 A42 · the sheet keeps this chat's looks going while it's open (and visible), and a clock for "next in 42s"
	$: sheetFor = open && (view === 'stream' || view === 'knobs') && chatId ? chatId : null;
	$: if (sheetFor) loungeSheet.set(sheetFor);
	else if (chatId && get(loungeSheet) === chatId) loungeSheet.set(null);
	let nowS = Date.now() / 1000;
	let clock: ReturnType<typeof setInterval> | null = null;
	$: if (open && view === 'stream' && line?.kind === 'next') {
		if (!clock) clock = setInterval(() => (nowS = Date.now() / 1000), 1000);
	} else if (clock) {
		clearInterval(clock);
		clock = null;
	}
	const hhmm = (s: number) => new Date(s * 1000).toTimeString().slice(0, 5);
	const lineOf = (l: LoungeStatus | null, now: number): string => {
		if (!l) return '';
		const last = lastOf(l.last); // A43 · spoke · she let it pass · old turns left out
		if (l.kind === 'next') {
			const s = Math.max(0, Math.round((l.at ?? now) - now));
			const next = s ? `${$i18n.t('next in')} ${s < 120 ? `${s}s` : `${Math.round(s / 60)} min`}` : $i18n.t('any moment now');
			return last ? `${$i18n.t(last)} · ${next}` : next;
		}
		if (l.kind === 'waiting' && last) return `${$i18n.t(last)} · ${$i18n.t('waiting for a reply')}`;
		if (l.kind === 'held') return `${$i18n.t('held')}: ${l.why ?? ''}`;
		if (l.kind === 'writing') return $i18n.t('she is writing…');
		if (l.kind === 'resting') return $i18n.t('resting');
		if (l.kind === 'waiting') return $i18n.t('waiting for a reply');
		if (l.kind === 'quiet') return `${$i18n.t('quiet until')} ${hhmm(l.at ?? now)}`;
		if (l.kind === 'lead') return $i18n.t('another page leads');
		if (l.kind === 'stopped') return `${$i18n.t('stopped after 3 model errors')} · ${l.why ?? ''} · ${$i18n.t('she tries again once the profile changes or you turn it on again')}`;
		return l.why ?? '';
	};
	let knobs: string | null = null;
	const openKnobs = async () => {
		knobs = null;
		void go('knobs');
		knobs = (await loadLoungeKnobs()) ?? $i18n.t("couldn't reach the rig");
		await tick();
		replace();
	};
	$: routed = $followRoute && ($audioRoute === 'earphones' || $audioRoute === 'speaker');
	$: inEars = routed ? $audioRoute === 'earphones' : $earphones;
	$: speaking = $voiceUI.state !== 'idle';
	$: fusionOn = fusionRules($settings).on;
	$: pickKey = formatChord($keybindings[Shortcut.ASK_PICK] ?? '');
	$: modeKey = formatChord($keybindings[Shortcut.CYCLE_MODE] ?? '');
	$: ways = [
		{ value: 'off' as AutoMode, label: $i18n.t('off · only when I tap') },
		{ value: 'finished' as AutoMode, label: $i18n.t('after she finishes') },
		{ value: 'writing' as AutoMode, label: $i18n.t('as she writes') }
	];
	$: wayNow = ways.find((w) => w.value === $autoMode)?.label ?? '';
	$: title = [
		$i18n.t('Petal'),
		offMode && current ? `${current.emoji} ${current.name}`.trim() : '',
		$pickAsked ? $i18n.t('next reply: a pick') : '',
		stream?.on ? `🌊 ${stream.title ?? stream.profile ?? ''}`.trim() : ''
	]
		.filter(Boolean)
		.join(' · ');

	const pinned = (k: HeartPin, pins: HeartPin[]) => pins.includes(k);

	// ── open · place · close ──
	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	}
	const replace = () => btn && (place = placeSheet(btn, 320));
	const rows = () => [...(sheet?.querySelectorAll<HTMLElement>('[data-petal-heart-go]') ?? [])];

	const show = async () => {
		view = 'main';
		replace();
		heartOpen.set(me);
		listen();
		await tick();
		rows()[0]?.focus({ preventScroll: true });
	};
	const close = (back = false) => {
		if ($heartOpen === me) heartOpen.set(null);
		unlisten();
		if (back) btn?.focus({ preventScroll: true });
	};
	const toggle = () => (open ? close() : show());
	const go = async (v: typeof view) => {
		view = v;
		await tick();
		replace();
		rows()[0]?.focus({ preventScroll: true });
	};

	const onOutside = (e: PointerEvent) => {
		const t = e.target as Node;
		if (sheet?.contains(t) || btn?.contains(t)) return;
		close();
	};
	const onKey = (e: KeyboardEvent) => {
		if (!open) return;
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			if (view !== 'main') void go('main');
			else close(true);
			return;
		}
		if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
		if (!sheet?.contains(document.activeElement)) return;
		const all = rows();
		const i = all.indexOf(document.activeElement as HTMLElement);
		e.preventDefault();
		all[(i + (e.key === 'ArrowDown' ? 1 : all.length - 1)) % all.length]?.focus({ preventScroll: true });
	};
	let listening = false;
	function listen() {
		if (listening) return;
		listening = true;
		document.addEventListener('pointerdown', onOutside, true);
		document.addEventListener('keydown', onKey, true);
		window.addEventListener('resize', replace);
		window.visualViewport?.addEventListener('resize', replace);
		window.visualViewport?.addEventListener('scroll', replace);
	}
	function unlisten() {
		if (!listening) return;
		listening = false;
		document.removeEventListener('pointerdown', onOutside, true);
		document.removeEventListener('keydown', onKey, true);
		window.removeEventListener('resize', replace);
		window.visualViewport?.removeEventListener('resize', replace);
		window.visualViewport?.removeEventListener('scroll', replace);
	}
	$: if (!open && listening) unlisten(); // another heart opened
	onDestroy(() => {
		if (clock) clearInterval(clock);
		if ($loungeSheet === chatId) loungeSheet.set(null);
		unlisten();
		if ($heartOpen === me) heartOpen.set(null);
	});

	// ── the controls ──
	const pickMode = (key: string) => {
		keepMode(chatId, key);
		void go('main');
	};
	const setFusion = async (on: boolean) => {
		const rules = { ...fusionRules($settings), on };
		settings.set({ ...$settings, petalFusion: rules } as unknown as typeof $settings);
		await updateUserSettings(localStorage.token, { ui: { petalFusion: rules } }).catch(() => null);
	};
	const toTrip = (which: 'trip' | 'vow') => {
		close();
		onTrip(which, btn);
	};
	// 🌊 A41 · her stream: a profile of hers turns it on for this chat only · off here, or Esc
	const openStream = () => {
		void loadLoungeShelf();
		void go('stream');
	};
	const streamOn = async (name: string) => {
		if (!chatId) return;
		await loungeTurnOn(chatId, name);
		void go('main');
	};
	const streamOff = async () => {
		if (chatId && stream?.on) await loungeTurnOff(chatId);
		void go('main');
	};
	const retryShelf = async () => {
		await loadLoungeShelf();
		await tick();
		replace();
	};
	const every = (min: number | undefined) =>
		min === undefined ? '' : min < 1 ? `${Math.round(min * 60)} s` : min < 90 ? `${Math.round(min)} min` : `${Math.round(min / 6) / 10} h`;
	const subOf = (p: LoungeProfile) =>
		p.problems?.length
			? `⚠ ${p.problems[0]}`
			: [
					`≈ ${every(p.mean_min)}`,
					p.voice === 'off' ? $i18n.t('text only') : p.voice === 'always' ? $i18n.t('voice, always') : $i18n.t('voice'),
					p.quiet ? `${$i18n.t('quiet')} ${p.quiet}` : ''
				]
					.filter(Boolean)
					.join(' · ');

	const toSettings = () => {
		close();
		showSettings.set('petal');
	};
</script>

<button
	type="button"
	bind:this={btn}
	class="phh"
	class:phh-open={open}
	data-petal-heart
	data-petal-heart-dot={dot ? '' : undefined}
	{title}
	aria-label={title}
	aria-haspopup="dialog"
	aria-expanded={open}
	on:click|preventDefault={toggle}
>
	<span class="phh-glyph" aria-hidden="true">💗</span>
	{#if dot}<span class="phh-dot" aria-hidden="true"></span>{/if}
</button>

{#if open}
	<div
		use:portal
		bind:this={sheet}
		class="phh-sheet"
		class:phh-phone={place.phone}
		data-petal-heart-sheet={view}
		role="dialog"
		aria-label={$i18n.t('Petal')}
		style="left:{place.left}px; bottom:{place.bottom}px; width:{place.width}px; max-height:{place.maxH}px"
	>
		{#if place.phone}<span class="phh-handle" aria-hidden="true"></span>{/if}

		{#if view === 'main'}
			{#if admin && current}
				<div class="phh-row" data-petal-heart-row="mode">
					<button type="button" class="phh-go" data-petal-heart-go on:click={() => go('mode')}>
						<span class="phh-ico" aria-hidden="true">{current.emoji || '🌀'}</span>
						<span class="phh-main">
							<span class="phh-name">{current.name}</span>
							<span class="phh-sub">{$i18n.t('the mode')}{!phone && modeKey ? ` · ${modeKey}` : ''}</span>
						</span>
						<span class="phh-more" aria-hidden="true">›</span>
					</button>
					<button type="button" class="phh-pin" class:on={pinned('mode', $heartPins)} data-petal-heart-pin="mode"
						aria-pressed={pinned('mode', $heartPins)} aria-label={$i18n.t('Keep on the bar')} title={$i18n.t('Keep on the bar')}
						on:click={() => togglePin('mode')}>📌</button>
				</div>
			{/if}

			<div class="phh-row" data-petal-heart-row="pick">
				<button type="button" class="phh-go" data-petal-heart-go aria-pressed={$pickAsked} on:click={() => askPick()}>
					<span class="phh-ico" aria-hidden="true">🍒</span>
					<span class="phh-main">
						<span class="phh-name">{$i18n.t('next reply: a pick')}</span>
						<span class="phh-sub"
							>{$pickAsked
								? $pickAskWhy
									? `${$i18n.t('Petal asked')}: ${$pickAskWhy}`
									: $i18n.t('on · tap to take it back')
								: $i18n.t('two replies to choose from')}{!phone && pickKey ? ` · ${pickKey}` : ''}</span
						>
					</span>
					<span class="phh-switch" class:on={$pickAsked} aria-hidden="true"></span>
				</button>
				<button type="button" class="phh-pin" class:on={pinned('pick', $heartPins)} data-petal-heart-pin="pick"
					aria-pressed={pinned('pick', $heartPins)} aria-label={$i18n.t('Keep on the bar')} title={$i18n.t('Keep on the bar')}
					on:click={() => togglePin('pick')}>📌</button>
			</div>

			<div class="phh-row" data-petal-heart-row="ear">
				<button type="button" class="phh-go" data-petal-heart-go on:click={() => go('voice')}>
					<span class="phh-ico" aria-hidden="true">🎧</span>
					<span class="phh-main">
						<span class="phh-name">{$i18n.t('her voice')}</span>
						<span class="phh-sub">{wayNow}{phone && $autoMode !== 'off' ? ` · ${inEars ? $i18n.t('earphones in') : $i18n.t('no earphones')}` : ''}</span>
					</span>
					<span class="phh-more" aria-hidden="true">›</span>
				</button>
				{#if phone}
					<button type="button" class="phh-pin" class:on={pinned('ear', $heartPins)} data-petal-heart-pin="ear"
						aria-pressed={pinned('ear', $heartPins)} aria-label={$i18n.t('Keep on the bar')} title={$i18n.t('Keep on the bar')}
						on:click={() => togglePin('ear')}>📌</button>
				{:else}
					<span class="phh-pin-gap" aria-hidden="true"></span>
				{/if}
			</div>

			{#if admin}
				<div class="phh-row" data-petal-heart-row="stream">
					<button type="button" class="phh-go" data-petal-heart-go aria-pressed={!!stream?.on} on:click={openStream}>
						<span class="phh-ico" aria-hidden="true">🌊</span>
						<span class="phh-main">
							<span class="phh-name"
								>{stream?.on ? `${stream.emoji ?? ''} ${stream.title ?? stream.profile ?? ''}`.trim() : $i18n.t('her stream')}</span
							>
							<span class="phh-sub"
								>{stream?.on
									? $i18n.t('she speaks on her own here')
									: chatId
										? $i18n.t('off in this chat')
										: $i18n.t('opens once this chat exists')}</span
							>
						</span>
						<span class="phh-more" aria-hidden="true">›</span>
					</button>
					<span class="phh-pin-gap" aria-hidden="true"></span>
				</div>
			{/if}

			{#if admin && trip}
				<div class="phh-row" data-petal-heart-row="trip">
					<button type="button" class="phh-go" data-petal-heart-go on:click={() => toTrip('trip')}>
						<span class="phh-ico" aria-hidden="true">{trip.emoji}</span>
						<span class="phh-main">
							<span class="phh-name">{trip.text}</span>
							<span class="phh-sub">{$i18n.t('what I’m on')}</span>
						</span>
						<span class="phh-more" aria-hidden="true">›</span>
					</button>
					<button type="button" class="phh-pin" class:on={pinned('trip', $heartPins)} data-petal-heart-pin="trip"
						aria-pressed={pinned('trip', $heartPins)} aria-label={$i18n.t('Keep on the bar')} title={$i18n.t('Keep on the bar')}
						on:click={() => togglePin('trip')}>📌</button>
				</div>
				{#if vow}
					<div class="phh-row" data-petal-heart-row="vow">
						<button type="button" class="phh-go" data-petal-heart-go on:click={() => toTrip('vow')}>
							<span class="phh-ico" aria-hidden="true">🔥</span>
							<span class="phh-main">
								<span class="phh-name">{vow.text}</span>
								<span class="phh-sub">{$i18n.t('my vow')}</span>
							</span>
							<span class="phh-more" aria-hidden="true">›</span>
						</button>
						<span class="phh-pin-gap" aria-hidden="true"></span>
					</div>
				{/if}
			{/if}

			<div class="phh-row" data-petal-heart-row="fusion">
				<button type="button" class="phh-go" data-petal-heart-go aria-pressed={fusionOn} on:click={() => setFusion(!fusionOn)}>
					<span class="phh-ico" aria-hidden="true">🌕</span>
					<span class="phh-main">
						<span class="phh-name">{$i18n.t('the fusion check')}</span>
						<span class="phh-sub">{fusionOn ? $i18n.t('asks now and then, under a reply') : $i18n.t('off')}</span>
					</span>
					<span class="phh-switch" class:on={fusionOn} aria-hidden="true"></span>
				</button>
				<span class="phh-pin-gap" aria-hidden="true"></span>
			</div>

			{#each filters as f (f.id)}
				<div class="phh-row" data-petal-heart-row="filter:{f.id}">
					<button type="button" class="phh-go" data-petal-heart-go aria-pressed={f.on} on:click={() => onFilter(f.id, 'toggle')}>
						<span class="phh-ico phh-emoji" aria-hidden="true">{f.emoji}</span>
						<span class="phh-main">
							<span class="phh-name">{f.name}</span>
							<span class="phh-sub">{f.on ? $i18n.t('on in this chat') : $i18n.t('off in this chat')}</span>
						</span>
						<span class="phh-switch" class:on={f.on} aria-hidden="true"></span>
					</button>
					{#if f.valves}
						<button type="button" class="phh-pin phh-knob" data-petal-heart-go data-petal-heart-valves={f.id}
							aria-label={$i18n.t('its sliders')} title={$i18n.t('its sliders')} on:click={() => (close(), onFilter(f.id, 'valves'))}>⋯</button>
					{/if}
					<button type="button" class="phh-pin" class:on={pinned(`filter:${f.id}`, $heartPins)} data-petal-heart-pin="filter:{f.id}"
						aria-pressed={pinned(`filter:${f.id}`, $heartPins)} aria-label={$i18n.t('Keep on the bar')} title={$i18n.t('Keep on the bar')}
						on:click={() => togglePin(`filter:${f.id}`)}>📌</button>
				</div>
			{/each}

			<button type="button" class="phh-foot" data-petal-heart-go on:click={toSettings}>
				{$i18n.t('more in Settings → 🌸 Petal')} · 📌 {$i18n.t('keeps two on the bar')}
			</button>
		{:else if view === 'mode'}
			<button type="button" class="phh-back" data-petal-heart-go on:click={() => go('main')}>‹ {$i18n.t('the mode')}</button>
			{#each $modes as m (m.key)}
				<div class="phh-row" data-petal-heart-row="mode:{m.key}">
					<button type="button" class="phh-go" data-petal-heart-go aria-pressed={current?.key === m.key} on:click={() => pickMode(m.key)}>
						<span class="phh-ico" aria-hidden="true">{m.emoji || '·'}</span>
						<span class="phh-main"><span class="phh-name">{m.name}</span>
							{#if lead?.key === m.key}<span class="phh-sub">{$i18n.t('where a chat begins')}</span>{/if}</span>
						<span class="phh-check" aria-hidden="true">{current?.key === m.key ? '✓' : ''}</span>
					</button>
				</div>
			{/each}
		{:else if view === 'stream'}
			<button type="button" class="phh-back" data-petal-heart-go on:click={() => go('main')}>‹ {$i18n.t('her stream')}</button>
			<div class="phh-row" data-petal-heart-row="stream:off">
				<button type="button" class="phh-go" data-petal-heart-go aria-pressed={!stream?.on} on:click={streamOff}>
					<span class="phh-ico" aria-hidden="true">·</span>
					<span class="phh-main">
						<span class="phh-name">{$i18n.t('off')}</span>
						<span class="phh-sub">{$i18n.t('she speaks when you write')}</span>
					</span>
					<span class="phh-check" aria-hidden="true">{!stream?.on ? '✓' : ''}</span>
				</button>
			</div>
			{#if line}
				<div class="phh-note phh-status" data-petal-lounge-status={line.kind}>{lineOf(line, nowS)}</div>
			{/if}
			{#if shelfError}
				<div class="phh-row" data-petal-heart-row="stream:retry">
					<button type="button" class="phh-go" data-petal-heart-go on:click={retryShelf}>
						<span class="phh-ico" aria-hidden="true">↻</span>
						<span class="phh-main">
							<span class="phh-name" data-petal-lounge-error>{shelfError}</span>
							<span class="phh-sub">{$i18n.t('try again')}</span>
						</span>
					</button>
				</div>
			{:else if shelf === null}
				<div class="phh-note">{$i18n.t('reading your folder…')}</div>
			{/if}
			{#each shelf?.profiles ?? [] as p (p.name)}
				<div class="phh-row" data-petal-heart-row="stream:{p.name}">
					<button type="button" class="phh-go" data-petal-heart-go aria-pressed={stream?.profile === p.name}
						disabled={!chatId || !p.ok} on:click={() => streamOn(p.name)}>
						<span class="phh-ico phh-emoji" aria-hidden="true">{p.emoji}</span>
						<span class="phh-main">
							<span class="phh-name">{p.title}</span>
							<span class="phh-sub">{subOf(p)}</span>
						</span>
						<span class="phh-check" aria-hidden="true">{stream?.profile === p.name ? '✓' : ''}</span>
					</button>
				</div>
			{/each}
			{#if shelf}
				<div class="phh-note" data-petal-lounge-folder>
					{shelf.profiles.length ? '' : `${$i18n.t('your folder holds no profile yet')} · `}{shelf.folder}{shelf.asleep
						? ` · ${shelf.asleep} ${$i18n.t('asleep')} (enabled: false)`
						: ''}{shelf.profiles.some((p) => p.ignored?.length) ? ` · ${$i18n.t('place and turns are read no more: she reads the whole chat, your words ride in the floor note')}` : ''} · {$i18n.t('Esc turns it off')}
				</div>
				<div class="phh-row" data-petal-heart-row="stream:knobs">
					<button type="button" class="phh-go" data-petal-heart-go on:click={openKnobs}>
						<span class="phh-ico" aria-hidden="true">📖</span>
						<span class="phh-main">
							<span class="phh-name">{$i18n.t('the knobs')}</span>
							<span class="phh-sub">{$i18n.t('what a profile can say')}</span>
						</span>
						<span class="phh-more" aria-hidden="true">›</span>
					</button>
				</div>
			{/if}
		{:else if view === 'knobs'}
			<button type="button" class="phh-back" data-petal-heart-go on:click={() => go('stream')}>‹ {$i18n.t('the knobs')}</button>
			<pre class="phh-knobs" data-petal-lounge-knobs>{knobs ?? $i18n.t('reading…')}</pre>
		{:else}
			<button type="button" class="phh-back" data-petal-heart-go on:click={() => go('main')}>‹ {$i18n.t('her voice')}</button>
			{#each ways as w (w.value)}
				<div class="phh-row" data-petal-heart-row="voice:{w.value}">
					<button type="button" class="phh-go" data-petal-heart-go aria-pressed={$autoMode === w.value} on:click={() => setAutoMode(w.value)}>
						<span class="phh-main"><span class="phh-name">{w.label}</span></span>
						<span class="phh-check" aria-hidden="true">{$autoMode === w.value ? '✓' : ''}</span>
					</button>
				</div>
			{/each}
			{#if phone && $autoMode !== 'off'}
				<div class="phh-row" data-petal-heart-row="voice:ear">
					<button type="button" class="phh-go" data-petal-heart-go aria-pressed={inEars} disabled={routed} on:click={() => setEarphones(!$earphones)}>
						<span class="phh-ico" aria-hidden="true">🎧</span>
						<span class="phh-main">
							<span class="phh-name">{$i18n.t('earphones in')}</span>
							<span class="phh-sub">{routed ? $i18n.t('the rig says so') : $i18n.t('remembered on this phone')}</span>
						</span>
						<span class="phh-switch" class:on={inEars} aria-hidden="true"></span>
					</button>
				</div>
			{/if}
			{#if speaking}
				<div class="phh-row" data-petal-heart-row="voice:stop">
					<button type="button" class="phh-go" data-petal-heart-go on:click={() => (stopAllVoice('her ⏹ (the heart)'), close())}>
						<span class="phh-ico" aria-hidden="true">⏹</span>
						<span class="phh-main"><span class="phh-name">{$i18n.t('Stop her voice')}</span></span>
					</button>
				</div>
			{/if}
		{/if}
	</div>
{/if}

<style>
	/* the cherry's size and manners: one size in every state, so opening it never moves anything beside it */
	.phh {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		align-self: center;
		flex-shrink: 0;
		height: 1.875rem;
		width: 1.875rem;
		padding: 0;
		margin-right: 0.15rem;
		border-radius: 999px;
		border: 1px solid transparent;
		background: transparent;
		touch-action: manipulation;
		transition:
			border-color 140ms,
			background-color 140ms;
	}
	.phh:hover,
	.phh-open {
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.4);
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.1);
	}
	.phh:focus-visible {
		outline: 2px solid oklch(0.711 0.214 var(--p-h-accent, 352) / 0.7);
		outline-offset: 2px;
	}
	.phh-glyph {
		font-family: var(--font-emoji, 'SamsungColorEmoji'), sans-serif;
		font-size: 0.98rem;
		line-height: 1;
	}
	/* the quiet state: a still dot, never a pulse */
	.phh-dot {
		position: absolute;
		top: 0.2rem;
		right: 0.2rem;
		width: 0.36rem;
		height: 0.36rem;
		border-radius: 999px;
		background: oklch(0.78 0.16 var(--p-h-accent, 352));
		box-shadow: 0 0 0 1.5px var(--obsidian, #15111b);
	}

	.phh-sheet {
		position: fixed;
		z-index: 9999;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		overflow-y: auto;
		overscroll-behavior: contain;
		padding: 0.45rem;
		border-radius: var(--radius, 14px);
		border: 1px solid var(--edge-soft, #2a2433);
		background: var(--obsidian, #15111b);
		box-shadow:
			inset 0 1px 0 var(--glass-sheen, rgba(255, 255, 255, 0.03)),
			0 18px 40px -18px oklch(0 0 0 / 0.7);
		color: var(--mist, #cfc3cc);
		font-size: 0.8rem;
		animation: phh-in 160ms cubic-bezier(0.2, 0.8, 0.2, 1) 1;
	}
	.phh-phone {
		padding: 0.35rem 0.5rem 0.6rem;
		font-size: 0.9rem;
		border-radius: 18px;
	}
	@keyframes phh-in {
		from {
			opacity: 0;
			transform: translateY(6px);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.phh-sheet {
			animation: none;
		}
	}
	.phh-handle {
		align-self: center;
		width: 2.2rem;
		height: 0.22rem;
		margin: 0.15rem 0 0.35rem;
		border-radius: 999px;
		background: var(--edge-soft, #2a2433);
	}

	.phh-row {
		display: flex;
		align-items: stretch;
		gap: 0.2rem;
	}
	.phh-go,
	.phh-back,
	.phh-foot {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex: 1;
		min-width: 0;
		min-height: 2.5rem;
		padding: 0.35rem 0.55rem;
		border-radius: 10px;
		border: 1px solid transparent;
		background: transparent;
		color: inherit;
		text-align: left;
		transition:
			background-color 120ms,
			border-color 120ms;
	}
	.phh-phone .phh-go,
	.phh-phone .phh-back,
	.phh-phone .phh-foot {
		min-height: 2.75rem; /* 44 px: a thumb's reach */
	}
	.phh-go:hover,
	.phh-go:focus-visible,
	.phh-back:hover,
	.phh-back:focus-visible,
	.phh-foot:hover,
	.phh-foot:focus-visible {
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.08);
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.22);
		outline: none;
	}
	.phh-go[aria-pressed='true'] .phh-name {
		color: var(--blush, oklch(0.86 0.09 var(--p-h-accent, 352)));
	}
	.phh-go:disabled {
		opacity: 0.6;
	}
	.phh-ico {
		width: 1.4rem;
		flex-shrink: 0;
		text-align: center;
		font-size: 1.05em;
		font-family: var(--font-emoji, 'SamsungColorEmoji'), sans-serif;
	}
	.phh-main {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
	}
	.phh-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.phh-sub {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.82em;
		opacity: 0.6;
	}
	.phh-more,
	.phh-check {
		flex-shrink: 0;
		opacity: 0.55;
		min-width: 0.8rem;
		text-align: right;
	}
	.phh-check {
		opacity: 0.9;
		color: oklch(0.8 0.14 var(--p-h-accent, 352));
	}
	/* a switch drawn with borders and colour alone: it changes on a tap, never on a timer */
	.phh-switch {
		flex-shrink: 0;
		position: relative;
		width: 1.9rem;
		height: 1.05rem;
		border-radius: 999px;
		border: 1px solid var(--edge-soft, #2a2433);
		background: oklch(0 0 0 / 0.25);
		transition:
			background-color 140ms,
			border-color 140ms;
	}
	.phh-switch::after {
		content: '';
		position: absolute;
		top: 0.12rem;
		left: 0.14rem;
		width: 0.7rem;
		height: 0.7rem;
		border-radius: 999px;
		background: var(--mist, #cfc3cc);
		opacity: 0.6;
		transition: transform 140ms;
	}
	.phh-switch.on {
		background: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.45);
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.6);
	}
	.phh-switch.on::after {
		transform: translateX(0.82rem);
		opacity: 1;
	}
	@media (prefers-reduced-motion: reduce) {
		.phh-switch::after {
			transition: none;
		}
	}
	.phh-pin,
	.phh-pin-gap {
		flex-shrink: 0;
		width: 2.25rem;
	}
	.phh-pin {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border-radius: 10px;
		border: 1px solid transparent;
		background: transparent;
		font-size: 0.85em;
		filter: grayscale(1);
		opacity: 0.35;
		transition:
			opacity 120ms,
			filter 120ms;
	}
	.phh-phone .phh-pin,
	.phh-phone .phh-pin-gap {
		width: 2.75rem;
	}
	.phh-pin:hover,
	.phh-pin:focus-visible {
		opacity: 0.7;
		outline: none;
		border-color: oklch(0.711 0.214 var(--p-h-accent, 352) / 0.22);
	}
	.phh-pin.on {
		filter: none;
		opacity: 1;
	}
	.phh-knob {
		filter: none;
		opacity: 0.7;
		font-size: 1.1em;
	}
	.phh-back {
		flex: none;
		opacity: 0.75;
		font-size: 0.92em;
	}
	.phh-knobs {
		margin: 0;
		padding: 0.4rem 0.55rem 0.6rem;
		font-size: 0.72em;
		line-height: 1.45;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		opacity: 0.85;
	}
	.phh-status {
		opacity: 0.8;
	}
	.phh-note {
		padding: 0.35rem 0.55rem 0.15rem;
		font-size: 0.74em;
		line-height: 1.35;
		opacity: 0.5;
		overflow-wrap: anywhere;
	}
	.phh-foot {
		flex: none;
		justify-content: center;
		margin-top: 0.15rem;
		font-size: 0.78em;
		opacity: 0.5;
	}
</style>
