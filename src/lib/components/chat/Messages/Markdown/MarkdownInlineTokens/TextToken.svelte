<script lang="ts">
	import { getContext } from 'svelte';
	import { settings } from '$lib/stores';
	import { dress, quoteSegs } from '$lib/utils/petal-quote';

	export let token;
	export let done = true;

	// 🌸 petal (A17): inside a reply's display quote, its quotation marks wear the accent and emoji
	// keep their colours · display only, the message (and what's copied or spoken) stays as written.
	// its words skip the per-word fade: the quote's gradient ink is cut from the whole line at once,
	// so a fade can't show there (and an arriving emoji would flash as a silhouette)
	const dressed = getContext('petal-quote') === true;

	$: raw = token?.raw ?? '';
</script>

{#if done || dressed || !($settings?.chatFadeStreamingText ?? true)}
	{#if dressed}
		{#each quoteSegs(dress(raw)) as seg}{#if seg.kind === 'mark'}<span class="pq-mark"
					>{seg.text}</span
				>{:else if seg.kind === 'emoji'}<span class="pq-emoji">{seg.text}</span
				>{:else}{seg.text}{/if}{/each}
	{:else}
		{raw}
	{/if}
{:else}
	{#each raw.split(' ') as text}
		<span class="fade-in-token">
			{text}{' '}
		</span>
	{/each}
{/if}
