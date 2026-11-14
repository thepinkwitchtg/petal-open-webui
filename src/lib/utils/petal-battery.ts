// 🔋 the device's battery, where the browser offers it (navigator.getBattery: Chrome, Chrome on Android,
// Edge · never Firefox or Safari, where nothing is read and nothing is sent).
//  · auto quotes read it: low and not charging, the gloss becomes a rare glint and her voice's follower
//    goes simpler (petal-quote-fx, petal-voice)
//  · OWUI tells petal-live what it reads ({level, charging, device}), through its own signed-in route
//    (POST /api/v1/petal/observe → petal-live's /v1/observe on 127.0.0.1), at most once a minute and only
//    when the reading changes · nothing goes to any other host
import { writable } from 'svelte/store';
import { WEBUI_API_BASE_URL } from '$lib/constants';

export type BatteryReading = { level: number | null; charging: boolean | null; supported: boolean };
export type DeviceKind = 'phone' | 'pc';

export const LOW_LEVEL = 0.2; // at or under this, not charging: low
export const SEND_EVERY_MS = 60_000; // petal-live hears at most one reading a minute

type BatteryManagerLike = EventTarget & { level: number; charging: boolean };

let latest: BatteryReading = { level: null, charging: null, supported: false };
export const battery = writable<BatteryReading>(latest);

/** low and not charging (unknown counts as fine) */
export const batteryLow = () =>
	latest.level !== null && latest.level <= LOW_LEVEL && latest.charging === false;

export const batteryNow = () => latest;

/** phone or pc, as the browser says (a tablet counts as a phone) */
export function deviceKind(): DeviceKind {
	if (typeof navigator === 'undefined') return 'pc';
	const mobile = (navigator as Navigator & { userAgentData?: { mobile?: boolean } }).userAgentData
		?.mobile;
	if (typeof mobile === 'boolean') return mobile ? 'phone' : 'pc';
	return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent) ? 'phone' : 'pc';
}

let watching: Promise<void> | null = null;
const listeners = new Set<() => void>();

/** start reading the battery (once per page; a browser without the API just stays unsupported) */
export function watchBattery(): Promise<void> {
	if (watching) return watching;
	const nav =
		typeof navigator !== 'undefined'
			? (navigator as Navigator & { getBattery?: () => Promise<BatteryManagerLike> })
			: null;
	if (!nav?.getBattery) return (watching = Promise.resolve());
	watching = nav
		.getBattery()
		.then((b) => {
			const read = () => {
				latest = { level: b.level, charging: b.charging, supported: true };
				battery.set(latest);
				for (const fn of listeners) fn();
			};
			b.addEventListener('levelchange', read);
			b.addEventListener('chargingchange', read);
			read();
		})
		.catch(() => {});
	return watching;
}

// ── petal-live hears it ─────────────────────────────────────────────────────────────────────────────
let reporting = false;
let lastSent: string | null = null;
let lastSentAt = 0;
let pending: ReturnType<typeof setTimeout> | null = null;

function reading() {
	if (!latest.supported || latest.level === null) return null;
	return {
		level: Math.round(latest.level * 100),
		charging: !!latest.charging,
		device: deviceKind()
	};
}

async function send() {
	const r = reading();
	if (!r) return;
	const key = JSON.stringify(r);
	if (key === lastSent) return;
	const wait = lastSentAt + SEND_EVERY_MS - Date.now();
	if (wait > 0) {
		// a change inside the minute waits for it to end, and only the newest reading goes
		if (!pending)
			pending = setTimeout(() => {
				pending = null;
				send();
			}, wait);
		return;
	}
	let token = '';
	try {
		token = localStorage.token ?? '';
	} catch {}
	if (!token) return;
	lastSent = key;
	lastSentAt = Date.now();
	const heard = await fetch(`${WEBUI_API_BASE_URL}/petal/observe`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
		body: key,
		keepalive: true
	})
		.then((res) => (res.ok ? res.json() : null))
		.then((j) => j?.heard === true)
		.catch(() => false);
	if (!heard && lastSent === key) {
		// unheard (the rig away, petal-live asleep, a hiccup): this reading tries again after its minute
		lastSent = null;
		if (!pending)
			pending = setTimeout(() => {
				pending = null;
				send();
			}, SEND_EVERY_MS);
	}
}

/** start telling petal-live the battery's readings (once per page, when she's signed in) */
export function reportBattery() {
	if (reporting) return;
	reporting = true;
	listeners.add(() => {
		send();
	});
	watchBattery().then(() => send());
}
