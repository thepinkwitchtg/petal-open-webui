<script lang="ts">
	// 📔 the diary (slice A11) · /diary?note opens with the pen in her hand
	import { showSidebar } from '$lib/stores';
	import PetalDiary from '$lib/components/diary/PetalDiary.svelte';
</script>

<div
	class="flex flex-col w-full h-screen max-h-[100dvh] {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: ''} max-w-full"
>
	<div class="flex-1 max-h-full overflow-y-auto">
		<PetalDiary />
	</div>
</div>
