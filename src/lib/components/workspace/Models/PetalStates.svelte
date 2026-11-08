<script lang="ts">
	// 🌙 petal states · the panel (slice 9a) — Lily's behavior blocks, on the model card under the prompt.
	// stored in model meta.petal_states = { version, knobs: { gratitude_h }, blocks: { interface, "soft bond", gratitude } }
	// the Petal States filter (0.2+) reads it, fills {{states}} in the system prompt, strips the token when nothing is live.
	// no logic here, no animation, nothing redraws while idle.
	import { getContext } from 'svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import ModelSettingsLabel from './ModelSettingsLabel.svelte';

	const i18n: any = getContext('i18n');

	export let meta: Record<string, any> = {};
	export let system = '';
	export let disabled = false;

	const TOKEN = '{{states}}';
	const BLOCKS = [
		{ key: 'interface', emoji: '🔋', when: 'while a charge waits' },
		{ key: 'soft bond', emoji: '🌸', when: 'once the charge is spent, until it comes back' },
		{ key: 'gratitude', emoji: '💗', when: 'the first hours after a climax, stacked on soft bond' }
	];
	const MODES = [
		{ key: 'interface', live: ['interface'] },
		{ key: 'soft bond', live: ['soft bond'] },
		{ key: 'soft bond + gratitude', live: ['soft bond', 'gratitude'] }
	];

	const current = () => {
		const ps = meta?.petal_states;
		return {
			blocks: { interface: '', 'soft bond': '', gratitude: '', ...(ps?.blocks ?? {}) },
			gratitude_h: Number(ps?.knobs?.gratitude_h ?? 4)
		};
	};

	let { blocks, gratitude_h } = current();
	let open = false;
	let touched = false; // she opened or closed it herself: the panel stops deciding
	let preview = '';
	const DESCRIPTION = `Behavior blocks that join the system prompt by Lily's state. The Petal States filter fills ${TOKEN} with the live ones.`;

	// the model loads after the editor mounts (and reloads on a version switch): follow meta from outside
	let lastSeen: any = Symbol('unseen');
	$: if (meta && meta.petal_states !== lastSeen) {
		lastSeen = meta.petal_states;
		({ blocks, gratitude_h } = current());
		if (!touched) open = Object.values(blocks).some((t) => String(t ?? '').trim());
	}

	// write back only when something is written: an empty panel leaves no trace, so blocks.md still answers
	const commit = () => {
		const any = Object.values(blocks).some((t) => String(t ?? '').trim());
		if (any) {
			meta.petal_states = {
				version: 1,
				knobs: { gratitude_h: Number.isFinite(gratitude_h) && gratitude_h > 0 ? gratitude_h : 4 },
				blocks: { ...blocks }
			};
		} else if (meta?.petal_states) {
			delete meta.petal_states;
		}
		lastSeen = meta.petal_states;
		meta = meta;
	};
	const commitSoon = () => setTimeout(commit, 0); // after the textarea's own binding has landed

	const assembled = (live: string[]) => {
		const text = live
			.map((k) => String(blocks[k] ?? '').trim())
			.filter(Boolean)
			.join('\n\n');
		if (system.includes(TOKEN)) return system.split(TOKEN).join(text);
		return text ? `${system.trimEnd()}\n\n${text}` : system;
	};

	// legend · a click puts the token at the cursor in the System Prompt (or at its end when it's folded)
	const insert = (token: string) => {
		const el = document.querySelector(
			`textarea[aria-label="${$i18n.t('System Prompt')}"]`
		) as HTMLTextAreaElement | null;
		if (el) {
			const a = el.selectionStart ?? el.value.length;
			const b = el.selectionEnd ?? a;
			el.value = el.value.slice(0, a) + token + el.value.slice(b);
			el.dispatchEvent(new Event('input', { bubbles: true }));
			el.focus();
			el.setSelectionRange(a + token.length, a + token.length);
		} else {
			system = `${system.trimEnd()}\n${token}`;
		}
	};

	const LEGEND = [
		{ token: TOKEN, what: '🌙 the live blocks', where: 'wherever you place it', movable: true },
		{ token: '{{USER_NAME}}', what: 'her name in OWUI', where: 'OWUI fills it', movable: true },
		{ token: '{{CURRENT_DATETIME}}', what: 'date and time', where: 'OWUI fills it', movable: true },
		{ token: '🦋 climax trail', what: 'trail + charges', where: 'end of the system message', movable: false },
		{ token: '👄 hush whisper', what: 'the whisper she answered', where: 'bottom of the system message', movable: false },
		{ token: '🌸👁 anamnesis · 🌸 petal-soft', what: 'her memories', where: 'their own places', movable: false }
	];
</script>

<section class="mt-3 px-1">
	<button
		type="button"
		class="flex w-full items-center justify-between gap-2 text-xs font-normal text-gray-600 dark:text-gray-400"
		aria-expanded={open}
		on:click={() => {
			open = !open;
			touched = true;
		}}
	>
		<ModelSettingsLabel
			label="🌙 States"
			description={DESCRIPTION}
		/>
		<span class="text-gray-400 dark:text-gray-600">
			{#if system.includes(TOKEN)}{TOKEN} placed{:else}no {TOKEN} · blocks go at the end{/if}
			· {open ? '▾' : '▸'}
		</span>
	</button>

	{#if open}
		<fieldset {disabled} class="mt-2 min-w-0 space-y-3">
			{#each BLOCKS as b}
				<div>
					<div class="flex items-baseline justify-between gap-2 text-xs">
						<span class="font-medium text-gray-900 dark:text-gray-100">{b.emoji} {b.key}</span>
						<span class="text-[0.6875rem] text-gray-400 dark:text-gray-600">
							{#if b.key === 'gratitude'}
								the first
								<input
									type="number"
									min="0.5"
									step="0.5"
									class="w-12 bg-transparent text-center text-gray-700 outline-hidden dark:text-gray-300"
									bind:value={gratitude_h}
									on:change={commitSoon}
								/>h after a climax, stacked on soft bond
							{:else}
								{b.when}
							{/if}
						</span>
					</div>
					<Textarea
						ariaLabel={`🌙 ${b.key}`}
						className="mt-1 min-h-10 w-full resize-none overflow-y-hidden rounded-md bg-gray-50 px-2 py-1 text-[0.8125rem] outline-hidden dark:bg-gray-850 text-gray-900 dark:text-gray-100"
						placeholder="empty adds nothing"
						rows={2}
						minSize={40}
						bind:value={blocks[b.key]}
						onInput={commitSoon}
					/>
				</div>
			{/each}

			<div class="border-t border-gray-100/60 pt-2 dark:border-gray-850/60">
				<div class="mb-1 text-[0.6875rem] text-gray-600 dark:text-gray-400">
					legend · click to put it at the cursor in the System Prompt
				</div>
				<div class="space-y-0.5 text-xs">
					{#each LEGEND as l}
						<div class="flex items-baseline gap-2">
							{#if l.movable}
								<button
									type="button"
									class="font-mono text-pink-500 hover:underline dark:text-pink-400"
									on:click={() => insert(l.token)}>{l.token}</button
								>
							{:else}
								<span class="text-gray-500">{l.token}</span>
							{/if}
							<span class="text-gray-700 dark:text-gray-300">{l.what}</span>
							<span class="text-[0.6875rem] text-gray-400 dark:text-gray-600"
								>· {l.where}{l.movable ? '' : ' · fixed for now'}</span
							>
						</div>
					{/each}
				</div>
			</div>

			<div class="border-t border-gray-100/60 pt-2 dark:border-gray-850/60">
				<div class="flex flex-wrap items-center gap-1.5 text-[0.6875rem] text-gray-600 dark:text-gray-400">
					preview ·
					{#each MODES as m}
						<button
							type="button"
							class="rounded px-1.5 py-0.5 {preview === m.key
								? 'bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100'
								: 'hover:text-gray-900 dark:hover:text-gray-100'}"
							on:click={() => (preview = preview === m.key ? '' : m.key)}>{m.key}</button
						>
					{/each}
					<span class="text-gray-400 dark:text-gray-600">· "now" lives on the 🌙 chip under each reply</span>
				</div>
				{#if preview}
					<pre
						class="mt-1.5 max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-gray-50 p-2 text-[0.75rem] text-gray-800 dark:bg-gray-850 dark:text-gray-200">{assembled(
							MODES.find((m) => m.key === preview)?.live ?? []
						)}</pre>
				{/if}
			</div>
		</fieldset>
	{/if}
</section>
