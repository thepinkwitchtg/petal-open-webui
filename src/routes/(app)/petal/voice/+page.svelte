<script lang="ts">
	// 🎙️ her voice's diary + her controls (slice A48) · /petal/voice?i=<incident> opens one at once
	import { showSidebar } from '$lib/stores';
	import PetalVoiceDiary from '$lib/components/petal/PetalVoiceDiary.svelte';
</script>

<div
	class="flex flex-col w-full h-screen max-h-[100dvh] {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: ''} max-w-full"
>
	<div class="flex-1 max-h-full overflow-y-auto">
		<PetalVoiceDiary />
	</div>
</div>
