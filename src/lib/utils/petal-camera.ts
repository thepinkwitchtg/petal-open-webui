// 📷 A33 · the camera stays in the page. on a phone, OWUI's Capture opens the phone's camera app: the page leaves,
// and on a weak network the phone may close it meanwhile (it reloads when she comes back). when this address is a
// secure context (https), the photo is taken right here instead (getUserMedia, PetalCamera.svelte), so the page
// never leaves; the photo is kept in this browser (petal-draft) from the moment it's taken until it's attached,
// and goes through OWUI's own input (#camera-input), as if the camera app had returned it.
// when the camera can't bind in the page (an http address, a refusal, no camera), a gentle note says so, typed in,
// and the camera app is one tap away; what she wrote is written down first, in case the phone closes the page.
// one capture-phase click listener (passive until the camera input is clicked), nothing runs idle.
import { mount, unmount } from 'svelte';

import PetalCamera from '$lib/components/chat/MessageInput/PetalCamera.svelte';
import { draftKey, flush, photo } from '$lib/utils/petal-draft';

export type CameraWhy = 'insecure' | 'unsupported' | 'denied' | 'missing' | 'busy' | 'failed';

/** can the camera open in this page? (an http address never can: browsers keep it for secure contexts) */
export function cameraHere(): { inPage: boolean; why: CameraWhy | null } {
	if (typeof window === 'undefined') return { inPage: false, why: 'unsupported' };
	if (!window.isSecureContext) return { inPage: false, why: 'insecure' };
	if (!navigator.mediaDevices?.getUserMedia) return { inPage: false, why: 'unsupported' };
	return { inPage: true, why: null };
}

const NOTED = 'petal.camera.noted'; // the day the http note was last shown on this device (once a day is gentle)
const chatKey = () => draftKey(location.pathname.match(/^\/c\/([^/?#]+)/)?.[1] ?? null);

let shown: ReturnType<typeof mount> | null = null;
let passing = false; // our own click on the input (the camera app, asked for on purpose): it goes through

function give(input: HTMLInputElement, file: File) {
	const dt = new DataTransfer();
	dt.items.add(file);
	input.files = dt.files;
	input.dispatchEvent(new Event('change', { bubbles: true }));
}

function close() {
	if (!shown) return;
	const was = shown;
	shown = null;
	void unmount(was);
}

function appCamera(input: HTMLInputElement) {
	close();
	flush(); // the phone may close the page while its camera app is open: her words are written down now
	passing = true;
	try {
		input.click();
	} finally {
		passing = false;
	}
}

function open(input: HTMLInputElement, why: CameraWhy | null) {
	if (shown) return;
	const key = chatKey();
	shown = mount(PetalCamera, {
		target: document.body,
		props: {
			why,
			onShot: async (file: File) => {
				await photo(key, file); // kept from this moment until it's attached (or sent)
				give(input, file);
				close();
			},
			onAppCamera: () => appCamera(input),
			onClose: close
		}
	});
}

function today() {
	const d = new Date(); // her own day (local), not the UTC one
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function onClick(e: MouseEvent) {
	const input = e.target as HTMLInputElement | null;
	if (passing || !input || input.id !== 'camera-input' || input.type !== 'file') return;
	const here = cameraHere();
	if (here.inPage) {
		e.preventDefault(); // no camera app: the photo is taken here
		open(input, null);
		return;
	}
	// it can't bind here: a gentle note once a day (the camera app one tap away), else straight to the app
	let noted = '';
	try {
		noted = localStorage.getItem(NOTED) ?? '';
	} catch {}
	flush();
	if (noted === today()) return; // the camera app opens as OWUI asked
	e.preventDefault();
	try {
		localStorage.setItem(NOTED, today());
	} catch {}
	open(input, here.why);
}

let installed = false;
/** listen for OWUI's camera input (one capture-phase click listener, idle until it's clicked) */
export function installPetalCamera() {
	if (installed || typeof window === 'undefined') return;
	installed = true;
	window.addEventListener('click', onClick, true);
	(window as unknown as { petalCamera?: object }).petalCamera = {
		/** numbers and words only: can the camera open here, and why not */
		get here() {
			return cameraHere();
		}
	};
}
