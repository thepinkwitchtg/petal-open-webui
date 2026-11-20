<script lang="ts">
	// 📷 A33 · the camera, in the page (utils/petal-camera.ts opens it): her phone's camera shows here, one tap takes
	// the photo, and it goes to the chat as if the camera app had returned it, so the page never leaves. when the
	// camera can't bind here (an http address, a refusal, no camera), a gentle note says why, typed in, and the
	// camera app is one tap away. the camera is let go the moment it closes or the page is hidden (and taken up
	// again if she comes back to it); nothing moves at rest but the camera's own picture.
	import { onDestroy, onMount, tick } from 'svelte';

	import i18n from '$lib/i18n';
	import type { CameraWhy } from '$lib/utils/petal-camera';
	import { typeIn } from '$lib/utils/petal-type';

	export let why: CameraWhy | null = null; // set: it can't bind here (the note) · null: open the camera
	export let onShot: (file: File) => void = () => {};
	export let onAppCamera: () => void = () => {};
	export let onClose: () => void = () => {};

	let video: HTMLVideoElement;
	let stream: MediaStream | null = null;
	let facing: 'environment' | 'user' = 'environment';
	let ready = false;
	let taking = false;
	let note = ''; // the note as it types in
	let typing: { cancel(): void } | null = null;

	const NOTES: Record<CameraWhy, string> = {
		insecure: 'This address isn’t https, so the camera can’t open in the page here. Its own app can take the photo, and what you wrote stays kept.',
		unsupported: 'This browser can’t open the camera in the page. Its own app can take the photo, and what you wrote stays kept.',
		denied: 'The camera wasn’t allowed here. Its own app can still take the photo.',
		missing: 'No camera answered. Its own app can still take the photo.',
		busy: 'The camera is busy elsewhere. Its own app can still take the photo.',
		failed: 'The camera couldn’t open in the page. Its own app can still take the photo.'
	};

	const whyOf = (e: unknown): CameraWhy => {
		const name = (e as { name?: string })?.name ?? '';
		if (name === 'NotAllowedError' || name === 'SecurityError') return 'denied';
		if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'missing';
		if (name === 'NotReadableError' || name === 'AbortError') return 'busy';
		return 'failed';
	};

	const say = (w: CameraWhy) => {
		why = w;
		typing?.cancel();
		typing = typeIn($i18n.t(NOTES[w]), (part) => (note = part));
	};

	const letGo = () => {
		stream?.getTracks().forEach((t) => t.stop());
		stream = null;
		ready = false;
		if (video) video.srcObject = null;
	};

	const start = async () => {
		letGo();
		try {
			stream = await navigator.mediaDevices.getUserMedia({
				video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1080 } },
				audio: false
			});
			if (document.visibilityState === 'hidden' || why) return letGo(); // she left meanwhile
			await tick();
			video.srcObject = stream;
			await video.play().catch(() => {});
			ready = true;
		} catch (e) {
			letGo();
			say(whyOf(e));
		}
	};

	const shoot = async () => {
		if (!ready || taking || !video?.videoWidth) return;
		taking = true;
		const canvas = document.createElement('canvas');
		canvas.width = video.videoWidth;
		canvas.height = video.videoHeight;
		canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
		const blob: Blob | null = await new Promise((r) => canvas.toBlob(r, 'image/jpeg', 0.92));
		if (!blob) return void (taking = false);
		const at = new Date();
		const p = (n: number) => String(n).padStart(2, '0');
		const name = `petal-photo-${at.getFullYear()}${p(at.getMonth() + 1)}${p(at.getDate())}-${p(at.getHours())}${p(at.getMinutes())}${p(at.getSeconds())}.jpg`;
		letGo();
		onShot(new File([blob], name, { type: 'image/jpeg', lastModified: at.getTime() }));
	};

	const flip = () => {
		facing = facing === 'environment' ? 'user' : 'environment';
		void start();
	};

	const close = () => {
		letGo();
		onClose();
	};

	// hidden: the camera is let go at once · back: taken up again if the camera is still what she's looking at
	const onVisibility = () => {
		if (document.visibilityState === 'hidden') letGo();
		else if (!why && !stream && !taking) void start();
	};
	const onKey = (e: KeyboardEvent) => {
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	};

	onMount(() => {
		document.addEventListener('visibilitychange', onVisibility);
		window.addEventListener('keydown', onKey, true);
		if (why) say(why);
		else void start();
	});
	onDestroy(() => {
		typing?.cancel();
		letGo();
		document.removeEventListener('visibilitychange', onVisibility);
		window.removeEventListener('keydown', onKey, true);
	});
</script>

<div class="petal-camera" role="dialog" aria-modal="true" aria-label={$i18n.t('Camera')} data-petal-camera={why ?? 'open'}>
	{#if why}
		<div class="pc-note">
			<p class="pc-words" aria-live="polite">{note}</p>
			<div class="pc-row">
				<button type="button" class="pc-app" on:click={onAppCamera}>📷 {$i18n.t('Open the camera app')}</button>
				<button type="button" class="pc-quiet" on:click={close}>{$i18n.t('Not now')}</button>
			</div>
		</div>
	{:else}
		<!-- svelte-ignore a11y-media-has-caption -->
		<video bind:this={video} class="pc-view" class:pc-ready={ready} playsinline muted autoplay></video>
		<div class="pc-bar">
			<button type="button" class="pc-side" aria-label={$i18n.t('Close')} on:click={close}>✕</button>
			<button
				type="button"
				class="pc-shutter"
				aria-label={$i18n.t('Take the photo')}
				disabled={!ready || taking}
				on:click={shoot}
			></button>
			<button type="button" class="pc-side" aria-label={$i18n.t('Turn the camera')} on:click={flip}>⟲</button>
		</div>
	{/if}
</div>

<style>
	.petal-camera {
		position: fixed;
		inset: 0;
		z-index: 9999;
		display: flex;
		flex-direction: column;
		background: var(--abyss, #0b0610);
		color: var(--pearl, #f6ecf3);
	}
	.pc-view {
		flex: 1;
		min-height: 0;
		width: 100%;
		object-fit: cover;
		opacity: 0;
		transition: opacity 0.2s ease;
	}
	.pc-view.pc-ready {
		opacity: 1;
	}
	.pc-bar {
		display: flex;
		align-items: center;
		justify-content: space-around;
		padding: 18px 24px calc(18px + env(safe-area-inset-bottom));
	}
	.pc-side {
		width: 44px;
		height: 44px;
		border-radius: 50%;
		font-size: 18px;
		color: var(--mist, #d8c6d4);
		background: rgb(255 255 255 / 0.06);
	}
	.pc-shutter {
		width: 68px;
		height: 68px;
		border-radius: 50%;
		background: var(--grad-fill, linear-gradient(140deg, #ff8ccd, #e05aa8));
		box-shadow:
			0 0 0 4px var(--abyss, #0b0610),
			0 0 0 6px var(--candy, #ff5bb0);
	}
	.pc-shutter:disabled {
		opacity: 0.45;
	}
	.pc-note {
		margin: auto;
		max-width: 26rem;
		padding: 28px 24px;
		text-align: center;
	}
	.pc-words {
		min-height: 4.5em;
		font-size: 15px;
		line-height: 1.5;
		color: var(--mist, #d8c6d4);
	}
	.pc-row {
		display: flex;
		flex-direction: column;
		gap: 10px;
		margin-top: 18px;
	}
	.pc-app {
		padding: 12px 18px;
		border-radius: 999px;
		color: var(--abyss, #0b0610);
		font-weight: 600;
		background: var(--grad-fill, linear-gradient(140deg, #ff8ccd, #e05aa8));
	}
	.pc-quiet {
		padding: 10px 18px;
		border-radius: 999px;
		color: var(--whisper, #b9a2b4);
	}
</style>
