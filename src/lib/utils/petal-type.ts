// ✍🏻 A33 · nothing of hers appears pre-written: the page's side of petal type (static/petal/type.js, the one
// engine, loaded before the app). her typing speed lives in her settings (synced with every device she signs in
// on) and is mirrored on this device for the static scripts (hush) · toasts type their words in as they appear,
// and stay as long as their typing adds (utils/petal-toast-touch.ts) · no app stores here (a pure util the thumbs
// queue can import as it is): the settings store is handed in by whoever keeps the device copy in step

export const TYPE_SPEEDS = ['natural', 'slow', 'quick', 'instant'] as const;
export type TypeSpeed = (typeof TYPE_SPEEDS)[number];

type Job = { cancel(): void; finish(): void; readonly done: boolean; total: number };
type Engine = {
	run(o: { text: string; write: (part: string, done: boolean) => void; speed?: TypeSpeed }): Job;
	ms(text: string, speed?: TypeSpeed): number;
	speed(set?: TypeSpeed): TypeSpeed;
	readonly active: number;
};

/** her speed, from her settings (natural when unset or unknown) */
export function speedOf(s: unknown): TypeSpeed {
	const v = (s as { petalTyping?: unknown } | null)?.petalTyping;
	return TYPE_SPEEDS.includes(v as TypeSpeed) ? (v as TypeSpeed) : 'natural';
}

const engine = (): Engine | null =>
	typeof window === 'undefined' ? null : ((window as unknown as { petalType?: Engine }).petalType ?? null);

/** how long a text takes to type in (0 with no engine, or at once) */
export function typeMs(text: unknown): number {
	const e = engine();
	return e && typeof text === 'string' && text ? e.ms(text) : 0;
}

/** type a text into a place: write(part, done) on each step · without the engine it's written whole at once */
export function typeIn(text: string, write: (part: string, done: boolean) => void): Job | null {
	const e = engine();
	if (!e) {
		write(text, true);
		return null;
	}
	return e.run({ text, write });
}

type Settings = { subscribe(run: (value: unknown) => void): () => void };

let synced = false;
/** keep this device's copy of her speed in step with her settings (the static scripts read it) */
export function syncTypingSpeed(settings: Settings): () => void {
	if (synced || typeof window === 'undefined') return () => {};
	synced = true;
	const stop = settings.subscribe((s) => {
		if (!s || !Object.keys(s).length) return; // her settings not here yet: the device keeps its last word
		const v = speedOf(s);
		const e = engine();
		try {
			if (e) e.speed(v);
			else localStorage.setItem('petal.type.speed', v);
		} catch {}
	});
	return () => {
		stop();
		synced = false;
	};
}
