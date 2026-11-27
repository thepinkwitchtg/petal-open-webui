<script lang="ts">
	// 🎙️ her voice's diary + her controls (slice A48) · admin-only, like every petal door
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME, user } from '$lib/stores';

	let loaded = false;
	onMount(() => {
		if ($user?.role !== 'admin') goto('/');
		else loaded = true;
	});
</script>

<svelte:head>
	<!-- LICENSE covers this Open WebUI browser-title identifier.
	Do not alter, remove, obscure, or replace it except as LICENSE permits:
	https://docs.openwebui.com/license. -->
	<title>
		her voice / {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<slot />
{/if}
