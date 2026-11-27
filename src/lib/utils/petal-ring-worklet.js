// @ts-nocheck (the audio thread's own globals: AudioWorkletProcessor, sampleRate, registerProcessor)
// 🎧 her playback's ring (A48) · runs on the audio thread: what the one <audio> played, as it came out of it (the
// page's own capture of the element, never the microphone), kept in a ring of the last `seconds` seconds, mono int16 at
// the context's rate. it records only while the page says she's playing; nothing leaves it unless asked (a 🚩): then
// the ring is handed over in order, oldest first, and keeps going.
class PetalRing extends AudioWorkletProcessor {
	constructor(options) {
		super();
		const o = (options && options.processorOptions) || {};
		this.cap = Math.max(1, Math.round((o.seconds || 90) * sampleRate));
		this.buf = new Int16Array(this.cap);
		this.w = 0; // where the next sample goes
		this.n = 0; // how many are kept (≤ cap)
		this.total = 0; // samples ever kept (her played time, at this rate)
		this.rec = false;
		this.port.onmessage = (e) => {
			const d = e.data || {};
			if (typeof d.rec === 'boolean') this.rec = d.rec;
			if (d.snap !== undefined) {
				const out = new Int16Array(this.n);
				const start = (this.w - this.n + this.cap) % this.cap;
				const first = Math.min(this.n, this.cap - start);
				out.set(this.buf.subarray(start, start + first), 0);
				if (first < this.n) out.set(this.buf.subarray(0, this.n - first), first);
				this.port.postMessage({ snap: d.snap, pcm: out.buffer, total: this.total, rate: sampleRate }, [out.buffer]);
			}
			if (d.clear) {
				this.w = 0;
				this.n = 0;
			}
		};
	}

	process(inputs) {
		if (!this.rec) return true;
		const input = inputs[0];
		if (!input || !input.length || !input[0]) return true;
		const a = input[0];
		const b = input.length > 1 && input[1] ? input[1] : null;
		const len = a.length;
		for (let i = 0; i < len; i++) {
			let v = b ? (a[i] + b[i]) * 0.5 : a[i];
			v = v < -1 ? -1 : v > 1 ? 1 : v;
			this.buf[this.w] = v < 0 ? v * 0x8000 : v * 0x7fff;
			this.w = this.w + 1 === this.cap ? 0 : this.w + 1;
		}
		this.n = Math.min(this.cap, this.n + len);
		this.total += len;
		return true;
	}
}

registerProcessor('petal-ring', PetalRing);
