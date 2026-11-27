<script lang="ts">
	import EditPencilIcon from '$lib/components/layout/Sidebar/icons/EditPencil.svelte';
	import CopyIcon from '$lib/components/layout/Sidebar/icons/Copy.svelte';
	import TrashIcon from '$lib/components/layout/Sidebar/icons/Trash.svelte';
	import ChevronRightIcon from '$lib/components/layout/Sidebar/icons/ChevronRight.svelte';
	import { resolveLocalizedFunction } from '$lib/utils/localizedContent';
	import { functions as localizedFunctions } from '$lib/stores';
	import { toast } from 'svelte-sonner';

	import { createEventDispatcher, onDestroy } from 'svelte';
	import { onMount, tick, getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType, t } from 'i18next';

	const i18n = getContext<Writable<i18nType>>('i18n');

	const dispatch = createEventDispatcher();

	import { thumbMarks, thumbNote, thumbVerdict } from '$lib/utils/petal-thumbs'; // 👍🏻 instant thumbs (A23) · her thank-you (A27)

	import { config, settings, TTSWorker, user, visibleControls } from '$lib/stores';
	import { synthesizeOpenAISpeech } from '$lib/apis/audio';
	import { flagPetalVoice, spokenMessages, stopVoice, voiceThread } from '$lib/utils/petalStream'; // 🧵 A46 · the one thread
	import { goto as petalGoto } from '$app/navigation'; // 🎧 A48 · a kept incident opens in her voice's diary
	import { setContext as petalSetContext } from 'svelte';
	import { sight as petalSight } from '$lib/utils/petal-sight'; // 🔋 A48 · her words move only while she can see them
	import { imageGenerations } from '$lib/apis/images';
	import { isSavedChatId } from '$lib/utils/chatId';
	import { castOrbit, markMoment, marksFor, markersNow, nowS, vowBrakes } from '$lib/utils/petal-markers'; // 🌙 trip markers · ✧ orbits · 🔥 vows
	import PetalEyes from './PetalEyes.svelte'; // 👁 what Petal received (slice A10)
	import PetalPlayButton from './PetalPlayButton.svelte'; // 🔈 the speaker by her name (slices A19 · A19b)
	import { chosenVoice, registerReply, replyDone, speakReply } from '$lib/utils/petal-voice'; // 🎙️ the voice control and the trail find replies here
	import { grew } from '$lib/utils/petal-autoplay'; // 🔈 A37 · her voice as she writes
	import PetalOrbitMenu from './PetalOrbitMenu.svelte'; // ✧ the menu (slice A11)
	import {
		copyToClipboard as _copyToClipboard,
		approximateToHumanReadable,
		getMessageContentParts,
		sanitizeResponseContent,
		createMessagesList,
		formatMessageTimestamp,
		formatMessageTimestampFull,
		removeDetails,
		removeAllDetails,
		isInternalMessage
	} from '$lib/utils';
	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';
	import { resolveLocalizedModelName } from '$lib/utils/localizedContent';
	import { isTemporaryChatId } from '$lib/utils/chatId';
	import { getCarriedSources } from '$lib/utils/citations';
	import equal from 'fast-deep-equal';

	import Name from './Name.svelte';
	import ProfileImage from './ProfileImage.svelte';
	import Image from '$lib/components/common/Image.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import RateComment from './RateComment.svelte';
	import WebSearchResults from './ResponseMessage/WebSearchResults.svelte';
	import Sparkles from '$lib/components/layout/Sidebar/icons/Sparkles.svelte';

	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	import Error from './Error.svelte';
	import Citations from './Citations.svelte';
	import CodeExecutions from './CodeExecutions.svelte';
	import ContentRenderer from './ContentRenderer.svelte';
	import ContextCompactionLabel from './ContextCompactionLabel.svelte';
	import SubagentResultRow from './SubagentResultRow.svelte';
	import ChatMessageRow from './ChatMessageRow.svelte';
	import TimerRow from './TimerRow.svelte';
	import { KokoroWorker } from '$lib/workers/KokoroWorker';
	import FileItem from '$lib/components/common/FileItem.svelte';
	import FollowUps from './ResponseMessage/FollowUps.svelte';
	import { fade } from 'svelte/transition';
	import { flyAndScale } from '$lib/utils/transitions';
	import RegenerateMenu from './ResponseMessage/RegenerateMenu.svelte';
	import StatusHistory from './ResponseMessage/StatusHistory.svelte';
	import FullHeightIframe from '$lib/components/common/FullHeightIframe.svelte';
	import OutputEditView from './OutputEditView.svelte';
	import { getOutputText, replaceOutputMessageText, type OutputItem } from './structuredOutput';
	import { getChatContext } from '$lib/components/chat/context';

	const { audioQueue, models } = getChatContext();

	interface MessageType {
		user_id?: string;
		id: string;
		model: string;
		modelName?: string;
		content: string;
		output?: OutputItem[];
		contextSummary?: string;
		files?: { type: string; url: string }[];
		timestamp: number;
		role: string;
		statusHistory?: {
			done: boolean;
			action: string;
			description: string;
			urls?: string[];
			query?: string;
		}[];
		status?: {
			done: boolean;
			action: string;
			description: string;
			urls?: string[];
			query?: string;
		};
		done: boolean;
		error?: boolean | { content: string };
		sources?: string[];
		code_executions?: {
			uuid: string;
			name: string;
			code: string;
			language?: string;
			result?: {
				error?: string;
				output?: string;
				files?: { name: string; url: string }[];
			};
		}[];
		info?: {
			openai?: boolean;
			prompt_tokens?: number;
			completion_tokens?: number;
			total_tokens?: number;
			eval_count?: number;
			eval_duration?: number;
			prompt_eval_count?: number;
			prompt_eval_duration?: number;
			total_duration?: number;
			load_duration?: number;
			usage?: unknown;
		};
		annotation?: { type: string; rating: number };
		meta?: { response_ended_at?: number };
	}

	export let chatId = '';
	export let history;
	export let messageId;
	$: compacting =
		!message.done &&
		(message.output ?? []).some(
			(item) => item?.type === 'open_webui:context_compaction' && item.status === 'in_progress'
		);
	export let selectedModels = [];

	let messageSource = history.messages[messageId];
	let message: MessageType = structuredClone(messageSource);
	$: isAgent =
		message.model?.startsWith('agent:') || selectedModels.some((id) => id.startsWith('agent:'));
	// Agents regenerate on a fork of their own conversation; continuing or copying a reply has no turn to fork.
	$: canBranch = !isAgent;
	$: if (history.messages) {
		const source = history.messages[messageId];
		if (source) {
			// Fast path for the fields that change most often while streaming.
			// Responses streams update output even when legacy content is unchanged.
			if (source !== messageSource) {
				messageSource = source;
				message = structuredClone(source);
			} else if (
				message.content !== source.content ||
				message.done !== source.done ||
				message.output?.length !== source.output?.length
			) {
				message = structuredClone(source);
			} else if (!equal(message, source)) {
				// Slow path: full comparison for infrequent changes (sources, annotations, status, etc.)
				message = structuredClone(source);
			}
		}
	}

	// The message's own sources, plus any from earlier turns that it cites.
	const getCitationSources = (message: any) => {
		const sources = message?.sources ?? message?.citations;
		const carriedSources = getCarriedSources(history.messages, message);
		return carriedSources.length > 0 ? [...(sources ?? []), ...carriedSources] : sources;
	};
	$: citationSources = getCitationSources(message);

	export let siblings;

	export let setInputText: Function = () => {};
	export let gotoMessage: Function = () => {};
	export let showPreviousMessage: Function;
	export let showNextMessage: Function;

	export let updateChat: Function;
	export let editMessage: Function;
	export let saveMessage: Function;
	export let rateMessage: Function;
	export let actionMessage: Function;
	export let deleteMessage: Function;

	export let submitMessage: Function;
	export let continueResponse: Function;
	export let regenerateResponse: Function;
	export let forkHandler: Function | null = null;

	export let addMessages: Function;
	export let onToolCallResolved: Function = () => {};

	export let isLastMessage = true;
	export let readOnly = false;
	export let writeAccess = false;
	export let allowDelete = true;
	export let allowToolApproval: boolean = false;
	export let compactPreview = false;
	export let editCodeBlock = true;
	export let topPadding = false;
	export let onInsertToNote: ((content: string) => void) | null = null;
	export let onOpenArtifacts: ((code?: string) => void) | null = null;
	export let pickOpen = false; // 🍒 A29 · shown inside an open pick: no thumbs, no regenerate, no continue

	let citationsElement: HTMLDivElement;

	let contentContainerElement: HTMLDivElement;
	let buttonsContainerElement: HTMLDivElement;
	let showDeleteConfirm = false;

	let model = null;
	$: localizedModelName = model
		? resolveLocalizedModelName(model, $i18n.language)
		: message.modelName || message.model;
	$: model = ($models ?? []).find((m) => m.id === message.model);
	$: selectedModel = message?.selectedModelId
		? ($models ?? []).find((m) => m.id === message.selectedModelId)
		: null;
	$: selectedModelName = selectedModel
		? resolveLocalizedModelName(selectedModel, $i18n.language)
		: message?.selectedModelId;
	$: showSelectedModel = !!message?.selectedModelId && message?.strategy !== 'random';
	// 🍒 A30d · inside an open pick both replies show the moment they were asked (the same on both): when each one
	// ended would tell them apart before her 💗
	$: responseTimestamp = (pickOpen ? null : message?.meta?.response_ended_at) ?? message?.timestamp;

	$: parentMessage = history.messages[message?.parentId];
	$: statusEntries = message?.statusHistory ?? [...(message?.status ? [message?.status] : [])];
	$: hasVisibleStatus =
		(model?.info?.meta?.capabilities?.status_updates ?? true) &&
		statusEntries.length > 0 &&
		!(statusEntries.at(-1)?.hidden ?? false);
	$: visibleResponseContent =
		getOutputText(message.output) || removeAllDetails(message.content ?? '');
	$: hasResponseContent = Boolean((message.content ?? '').trim() || message.output?.length);
	// 🔈 A23: the speaker by her name is her one control in speaker mode, so the action row's Read Aloud steps
	// aside for it there (bubble mode keeps the row's speaker; the bubble already gives way to it)
	$: speakerByName =
		!readOnly &&
		($settings?.voiceControl ?? 'bubble') === 'speaker' &&
		message.done &&
		hasResponseContent &&
		message.error !== true;

	let edit = false;
	let editButtonElement: HTMLButtonElement;
	let editedContent = '';
	let editedOutput: any[] | null = null;
	let editTextAreaElement: HTMLTextAreaElement;

	let messageIndexEdit = false;

	// 🧵 A46 · her voice for this reply lives in the one thread (petalStream.ts): the ✕ reads its store, so it shows
	// whenever this reply's words are sounding, whoever started them (autoplay, a pick, her stream, the bubble, a replay)
	$: voiceMine =
		$voiceThread.message_id === message.id &&
		($voiceThread.state === 'loading' || $voiceThread.state === 'playing' || $voiceThread.state === 'paused');
	$: loadingSpeech = voiceMine && $voiceThread.state === 'loading';
	$: speaking = voiceMine && !loadingSpeech;

	let showRateComment = false;

	// ✧ the orbit (slice A11 · the primary gesture): one tap keeps an orbit on this reply with
	// its outcome open, and opens the ✧ menu (orbit · held · orbit · leaked · 🌊 climax · unflag).
	// a reply that carries a mark opens the menu instead. a temp chat keeps its marks without any
	// link (contract 0). A13: a past day's reply is annotated at its own moment, and while a vow is
	// alive today's reply opens the menu without keeping anything (🔥 the brake).
	$: marksSaved = isSavedChatId(chatId);
	$: marksStore = $user?.role === 'admin' && chatId ? marksFor(chatId) : null;
	$: mark = $marksStore?.[message.id] ?? null;
	let orbitBtn: HTMLButtonElement;
	let orbitMenu = false;
	let orbitBusy = false;
	const tapOrbit = async () => {
		if (orbitBusy) return;
		const moment = markMoment(message.timestamp);
		if (mark?.orbit || mark?.climax || vowBrakes($markersNow?.vow, moment ?? nowS())) {
			orbitMenu = !orbitMenu;
			return;
		}
		orbitBusy = true;
		try {
			await castOrbit(chatId, message.id, moment);
			orbitMenu = true;
		} catch (e) {
			toast.error(`✧ ${e}`);
		} finally {
			orbitBusy = false;
		}
	};

	// 👁 her eyes: the raw view of exactly what Petal received for this reply (temp chats too:
	// the server keeps their last 20 sends in memory)
	let eyesOpen = false;

	// 🔋 A48 · while she writes, this reply is watched (petal-sight): off her screen every css animation inside holds
	// (the shimmer of a status, a word's fade), and its Markdown waits to parse until she can see it again (one parse
	// then, never a frame behind once it's in view). done, nothing is watched
	let petalHeld = false;
	const petalWakers = new Set<() => void>();
	const petalSeen = (on: boolean) => {
		petalHeld = !on;
		if (!on) return;
		for (const fn of [...petalWakers]) {
			petalWakers.delete(fn);
			try {
				fn();
			} catch {}
		}
	};
	petalSetContext('petal-sight', {
		held: () => petalHeld,
		whenSeen: (fn: () => void) => {
			petalWakers.add(fn);
			return () => void petalWakers.delete(fn);
		}
	});
	$: if (message.done && petalHeld) petalSeen(true); // her reply is whole: whatever waited parses now

	// 🚩 flag the voice: plants this reply's stream as an incident on the rig
	let flaggingVoice = false;
	const flagVoice = async () => {
		if (flaggingVoice) return;
		flaggingVoice = true;
		const r = await flagPetalVoice({ token: localStorage.token, message_id: message.id, via: 'button' });
		flaggingVoice = false;
		// 🎧 A48 · her playback rides with it (sent once the flag landed); a kept incident opens in her voice's diary
		const ride = r.playback ? ` · her playback (${Math.round(r.playback.seconds)} s) rides with it` : '';
		const open = r.incident
			? { action: { label: 'open', onClick: () => petalGoto(`/petal/voice?i=${encodeURIComponent(r.incident ?? '')}`) } }
			: {};
		if (!r.ok) toast.error(`🚩 ${r.error ?? 'could not flag the voice'}`);
		else if (r.planted) toast.success(`🚩 voice incident kept · ${r.incident}${ride}`, open);
		else toast.success(`🚩 flagged~ she\'ll be kept once she finishes speaking${ride}`);
		r.playback?.sent.then((p) => {
			if (!p.ok) toast.error(`🎧 ${p.error ?? 'her playback could not be sent'}`);
		});
	};

	const copyToClipboard = async (text) => {
		text = removeAllDetails(text);

		if (($config?.ui?.response_watermark ?? '').trim() !== '') {
			text = `${text}\n\n${$config?.ui?.response_watermark}`;
		}

		const res = await _copyToClipboard(text, null, $settings?.copyFormatted ?? false);
		if (res) {
			toast.success($i18n.t('Copying to clipboard was successful!'));
		}
	};

	// 🧵 A46 · her ✕ on this reply stops the voice speaking it (and only that one)
	const stopAudio = () => {
		if (voiceMine) stopVoice('her ✕ on this reply');
	};

	// Resolve voice: model-specific > her pick > her Petal voice (🧵 A46 · one answer for every way in) · the model's own
	// voice rides in its meta (Workspace → Models), untyped upstream
	const modelVoice = () => (model?.info?.meta as { tts?: { voice?: string } } | undefined)?.tts?.voice;
	const getVoiceId = () => chosenVoice(modelVoice());

	// 🎙️ A19 · A19b: this reply can be spoken from the voice control (the bubble or the speaker by her
	// name, Settings → Interface → Voice control) and the hotkey (petal-voice)
	let unregisterVoice = () => {};
	let registeredVoice = '';
	// 🍒 A38 · inside an open pick, the pair in the order its cards show (autoplay reads them in turn)
	const pickPairOf = (m: unknown): [string, string] | null => {
		const pair = (m as { petal_pick?: { pair?: unknown } } | undefined)?.petal_pick?.pair;
		return Array.isArray(pair) && pair.length === 2 && pair.every((x) => typeof x === 'string')
			? [pair[0], pair[1]]
			: null;
	};
	$: if (message?.id && message.id !== registeredVoice && !readOnly) {
		unregisterVoice();
		const id = message.id;
		registeredVoice = id;
		unregisterVoice = registerReply({
			id,
			root: () => document.getElementById(`message-${id}`),
			words: () => contentContainerElement ?? null,
			done: () => !!message?.done && message.id === id,
			speak: () => speak(),
			voice: () => getVoiceId(),
			content: () => visibleResponseContent ?? '',
			meta: () => ({
				chat_id: chatId,
				model: message?.model,
				title: model?.name ? `${model.name} 💗` : 'Petal 💗',
				artwork: model?.info?.meta?.profile_image_url,
				playbackRate: $settings.audio?.tts?.playbackRate ?? 1
			}),
			pick: () => !!(message as { petal_pick?: unknown } | undefined)?.petal_pick,
			pair: () => (pickOpen ? pickPairOf(message) : null)
		});
	}
	$: if (message?.done && message?.id) replyDone(message.id);
	// 🌊 A41 · words she spoke on her own (Petal Stream): marked by her name, never continued or regenerated as a reply
	$: streamed = (message as { petal_stream?: { profile?: string } } | undefined)?.petal_stream ?? null;
	// 🔈 A37 · each change of her words, for the voice that speaks as she writes (it decides; nothing runs when off)
	const parentOf = (m: unknown) => (m as { parentId?: string | null } | undefined)?.parentId ?? null;
	const parentWords = () => history?.messages?.[parentOf(message) ?? '']?.content; // read only when asked (a queued send of hers)
	$: if (message?.id && !readOnly) grew(message.id, visibleResponseContent ?? '', !!message.done, parentOf(message), parentWords);

	// 🧵 A46 · her voice from this reply's first sentence, through the one thread: her petal stream (its sentence clips
	// when the stream can't open), the in-browser engine's clips, or the browser's own voice (OWUI's engine '')
	const speak = async () => {
		const content = visibleResponseContent;
		if (!content.trim().length) {
			toast.info($i18n.t('No content to speak'));
			return;
		}
		await speakReply({
			id: message.id,
			chat_id: chatId,
			content,
			modelVoice: modelVoice(),
			model: message.model,
			title: model?.name ? `${model.name} 💗` : 'Petal 💗',
			artwork: model?.info?.meta?.profile_image_url,
			playbackRate: $settings.audio?.tts?.playbackRate ?? 1,
			// the browser's own voice reached her last word: OWUI's conversation mode listens again
			onNatural: () => {
				if ($settings.conversationMode) document.getElementById('voice-input-button')?.click();
			},
			kokoro: async (text, voice) => {
				if (!$TTSWorker) {
					await TTSWorker.set(new KokoroWorker({ dtype: $settings.audio?.tts?.engineConfig?.dtype ?? 'fp32' }));
					await $TTSWorker.init();
				}
				return $TTSWorker.generate({ text, voice }).catch((error) => {
					console.error(error);
					return null;
				});
			}
		});
	};

	let preprocessedDetailsCache = [];

	function preprocessForEditing(content: string): string {
		// Replace <details>...</details> with unique ID placeholder
		const detailsBlocks = [];
		let i = 0;

		content = content.replace(/<details[\s\S]*?<\/details>/gi, (match) => {
			detailsBlocks.push(match);
			return `<details id="__DETAIL_${i++}__"/>`;
		});

		// Store original blocks in the editedContent or globally (see merging later)
		preprocessedDetailsCache = detailsBlocks;

		return content;
	}

	function postprocessAfterEditing(content: string): string {
		const restoredContent = content.replace(
			/<details id="__DETAIL_(\d+)__"\/>/g,
			(_, index) => preprocessedDetailsCache[parseInt(index)] || ''
		);

		return restoredContent;
	}

	const editMessageHandler = async () => {
		edit = true;

		if (message.output?.length) {
			// Structured edit: use the block editor
			editedOutput = structuredClone(message.output);
		} else {
			// Legacy text edit: use the textarea
			editedContent = preprocessForEditing(message.content);
		}

		await tick();

		if (!editedOutput && editTextAreaElement) {
			const messagesContainer = document.getElementById('messages-container');
			const savedScrollTop = messagesContainer?.scrollTop ?? 0;

			editTextAreaElement.style.height = '';
			editTextAreaElement.style.height = `${editTextAreaElement.scrollHeight}px`;

			if (messagesContainer) messagesContainer.scrollTop = savedScrollTop;
			editTextAreaElement?.focus({ preventScroll: true });
		}
	};

	const editMessageConfirmHandler = async () => {
		if (editedOutput) {
			editMessage(message.id, { output: editedOutput }, false);
		} else {
			// Legacy text edit
			const messageContent = postprocessAfterEditing(editedContent ?? '');
			editMessage(message.id, { content: messageContent }, false);
		}

		edit = false;
		editedContent = '';
		editedOutput = null;

		await tick();
	};

	const saveAsCopyHandler = async () => {
		if (!canBranch) return;
		if (editedOutput) {
			editMessage(message.id, { output: editedOutput });
		} else {
			const messageContent = postprocessAfterEditing(editedContent ?? '');
			editMessage(message.id, { content: messageContent });
		}

		edit = false;
		editedContent = '';
		editedOutput = null;

		await tick();
	};

	const cancelEditMessage = async () => {
		edit = false;
		editedContent = '';
		editedOutput = null;
		await tick();
		editButtonElement?.focus();
	};

	// 👍🏻 A23 · instant thumbs: the tap's own task does one thing, light the thumb from this reply alone, so
	// the very next frame shows it whatever the phone is doing. the frame after, the note opens and the save
	// leaves (the thumbs queue: petal-thumbs → POST /api/v1/petal/thumbs, the same feedback row as before, one
	// per reply, the latest verdict winning; OWUI's tag step follows on the rig once it landed); the chat's
	// history catches up a frame later still (its update reaches every reply on screen). nothing waits on the
	// network
	let thumbPending: Record<string, unknown> | null = null; // her verdict before the history has it
	const afterFrame = (fn: () => void) => requestAnimationFrame(() => setTimeout(fn, 0));

	const feedbackHandler = (rating: number | null = null, details: object | null = null) => {
		const before = thumbPending ?? message?.annotation ?? {};
		// 🍒 a later thumb that changes a picked reply's verdict is hers, no longer the pick's
		const unpick =
			rating !== null && (before as Record<string, unknown>)?.petal_pick === true && rating !== before?.rating;
		const annotation = {
			...before,
			...(rating !== null ? { rating: rating } : {}),
			...(unpick ? { petal_pick: false } : {}),
			...(rating !== null && rating !== before?.rating ? { reason: null, details: null } : {}),
			...(details ? details : {})
		};
		thumbPending = annotation;
		afterFrame(() => landVerdict(annotation, !details));
	};

	const landVerdict = (annotation: Record<string, unknown>, fromThumb: boolean) => {
		if (thumbPending !== annotation) return; // a newer tap carries its own verdict
		if (fromThumb) showRateComment = true;
		const messages = createMessagesList(history, message.id);
		const siblings = history.messages[message.parentId]?.childrenIds ?? [];
		const model_id = message?.selectedModelId ?? message.model;
		const sibling_model_ids =
			siblings.length > 1
				? siblings
						.filter((id) => id !== message.id)
						.map((id) => history.messages[id]?.selectedModelId ?? history.messages[id].model)
				: null;
		const base_models = [model_id, ...(sibling_model_ids ?? [])].reduce((acc, modelId) => {
			const model = ($models ?? []).find((m) => m.id === modelId);
			if (model) {
				acc[model.id] = model?.info?.base_model_id ?? null;
			} else {
				console.warn(`Model with ID ${modelId} not found`);
			}
			return acc;
		}, {});

		thumbVerdict({
			chat_id: chatId,
			message_id: message.id,
			feedback_id: message?.feedbackId ?? null,
			annotation,
			model_id,
			sibling_model_ids,
			meta: {
				strategy: message?.strategy ?? null,
				model_id: message.model,
				message_id: message.id,
				message_index: messages.length,
				chat_id: chatId,
				base_models
			},
			askTags: fromThumb && !annotation?.tags && (message?.content ?? '') !== '',
			thumb: fromThumb, // 💗 A27 · a tap begins a feedback: her thank-you follows it, once
			note: fromThumb && !!message.done // the note window opens with it: her line waits for its save or close
		});

		const id = message.id;
		afterFrame(() => {
			if (thumbPending !== annotation) return; // a newer tap writes its own
			const source = history.messages?.[id];
			if (source) {
				const settled = { ...(source.annotation ?? {}), ...annotation };
				saveMessage(id, { ...source, annotation: settled }, { local: true });
			}
			thumbPending = null;
		});
	};

	// her verdict as the thumbs show it: the tap's own (until the history has it), one still on its way after
	// a reload, else the reply's. once landed, Messages settles the rig's annotation + row id into the history
	$: thumbMark = $thumbMarks[message?.id];
	$: thumbRating = thumbPending
		? thumbPending.rating
		: thumbMark && thumbMark.state !== 'saved' && thumbMark.rating !== undefined
			? thumbMark.rating
			: message?.annotation?.rating;
	// the note reads the tap's verdict at once too (its reasons follow the thumb)
	$: noteMessage = thumbPending ? { ...message, annotation: thumbPending } : message;

	const deleteMessageHandler = async () => {
		deleteMessage(message.id);
	};

	$: if (!edit) {
		(async () => {
			await tick();
		})();
	}

	const buttonsWheelHandler = (event: WheelEvent) => {
		if (buttonsContainerElement) {
			if (buttonsContainerElement.scrollWidth <= buttonsContainerElement.clientWidth) {
				// If the container is not scrollable, horizontal scroll
				return;
			} else {
				event.preventDefault();

				if (event.deltaY !== 0) {
					// Adjust horizontal scroll position based on vertical scroll
					buttonsContainerElement.scrollLeft += event.deltaY;
				}
			}
		}
	};

	const contentCopyHandler = (e) => {
		if (contentContainerElement) {
			e.preventDefault();
			// Get the selected HTML
			const selection = window.getSelection();
			const range = selection.getRangeAt(0);
			const tempDiv = document.createElement('div');

			// Copy formulas as TeX source, rendered KaTeX pastes garbled
			const katexElements = [...document.querySelectorAll('.katex')].filter((katex) =>
				selection.containsNode(katex, true)
			);
			const texNodes = katexElements.map((katex) => {
				const tex = katex.querySelector('annotation[encoding="application/x-tex"]').textContent;
				const texNode = document.createTextNode(
					katex.closest('.katex-display') ? `$$${tex}$$` : `$${tex}$`
				);
				if (katex.contains(range.startContainer)) range.setStartBefore(katex);
				if (katex.contains(range.endContainer)) range.setEndAfter(katex);
				katex.before(texNode);
				katex.style.display = 'none';
				return texNode;
			});

			// Remove background, color, and font styles
			tempDiv.appendChild(range.cloneContents());
			tempDiv.querySelectorAll('.katex').forEach((katex) => katex.remove());
			// 🌸 a display quote's layers only echo its words: the words are copied once
			tempDiv.querySelectorAll('.pq-copy, .pv-mark').forEach((el) => el.remove());

			tempDiv.querySelectorAll('table').forEach((table) => {
				table.style.borderCollapse = 'collapse';
				table.style.width = 'auto';
				table.style.tableLayout = 'auto';
			});

			tempDiv.querySelectorAll('th').forEach((th) => {
				th.style.whiteSpace = 'nowrap';
				th.style.padding = '4px 8px';
			});

			// Put cleaned HTML + plain text into clipboard
			e.clipboardData.setData('text/html', tempDiv.innerHTML);
			e.clipboardData.setData('text/plain', selection.toString());

			katexElements.forEach((katex) => (katex.style.display = ''));
			texNodes.forEach((texNode) => texNode.remove());
		}
	};

	onMount(async () => {
		// console.log('ResponseMessage mounted');

		await tick();
		if (buttonsContainerElement) {
			buttonsContainerElement.addEventListener('wheel', buttonsWheelHandler);
		}

		if (contentContainerElement) {
			contentContainerElement.addEventListener('copy', contentCopyHandler);
		}
	});

	// 💗 A27 · the note window, open or closed: her thank-you waits while it's open (petal-thumbs)
	$: thumbNote(message?.id, !!(message?.done && showRateComment));

	onDestroy(() => {
		if (showRateComment) thumbNote(message?.id, false); // the reply left the page: the window closed with it
		unregisterVoice();
		if (buttonsContainerElement) {
			buttonsContainerElement.removeEventListener('wheel', buttonsWheelHandler);
		}

		if (contentContainerElement) {
			contentContainerElement.removeEventListener('copy', contentCopyHandler);
		}
	});
</script>

<DeleteConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete message?')}
	on:confirm={() => {
		deleteMessageHandler();
	}}
/>

{#key message.id}
	<div
		class=" flex w-full message-{message.id}"
		id="message-{message.id}"
		dir={$settings.chatDirection}
		style="scroll-margin-top: 3rem;"
		use:petalSight={{ on: !message.done, seen: petalSeen }}
	>
		<div class={`shrink-0 ltr:mr-2 rtl:ml-2 hidden @lg:flex mt-0.5 `}>
			<ProfileImage
				src={`${WEBUI_API_BASE_URL}/models/model/profile/image?id=${model?.id ?? message.model}&lang=${$i18n.language}&v=${model?.info?.updated_at}`}
				className={'size-7 assistant-message-profile-image'}
			/>
		</div>

		<div class="flex-auto w-0 pl-1 relative">
			{#if !compactPreview}
				<div class="flex items-center gap-1.5 min-w-0">
					<Name>
						<Tooltip content={localizedModelName} placement="top-start">
							<span
							id="response-message-model-name"
							class="line-clamp-1 text-base-1000 dark:text-base-0"
						>
								{localizedModelName}
							</span>
						</Tooltip>
					{#if showSelectedModel}
						<span class="truncate text-base-500">{selectedModelName}</span>
					{/if}
					</Name>
					{#if streamed}<span class="text-xs opacity-70 select-none" data-petal-stream-mark
							title={`${$i18n.t('she spoke on her own')} · ${streamed.profile ?? ''}`}>🌊</span>{/if}
					<!-- 🔈 petal (A19b): the speaker by her name, when it's her chosen voice control -->
					{#if speakerByName}
						<PetalPlayButton id={message.id} />
					{/if}
				</div>
			{/if}

			{#if isInternalMessage(parentMessage)}
				{#if parentMessage.meta.type === 'timer'}
					<TimerRow content={parentMessage.content} />
				{:else if parentMessage.meta.type === 'message'}
					<ChatMessageRow content={parentMessage.content} />
				{:else}
					<SubagentResultRow content={parentMessage.content} />
				{/if}
			{/if}

			{#if message.contextSummary}
				<ContextCompactionLabel summary={message.contextSummary} {compactPreview} />
			{/if}

			<div>
				<div class="chat-{message.role} w-full min-w-full">
					<div>
						{#if model?.info?.meta?.capabilities?.status_updates ?? true}
							<StatusHistory statusHistory={message?.statusHistory} />
						{/if}

						{#if message?.files && message.files?.filter( (f) => ['image', 'video', 'file'].includes(f.type) ).length > 0}
							<div
								class="my-1 w-full flex overflow-x-auto gap-2 flex-wrap"
								dir={$settings?.chatDirection ?? 'auto'}
							>
								{#each message.files.filter( (f) => ['image', 'video', 'file'].includes(f.type) ) as file}
									<div>
										{#if file.type === 'image' || (file?.content_type ?? '').startsWith('image/')}
											<Image src={file.url} alt={file.name || $i18n.t('Generated Image')} />
										{:else if file.type === 'video' || (file?.content_type ?? '').startsWith('video/')}
											<!-- svelte-ignore a11y-media-has-caption -->
											<video
												src={file.url}
												controls
												preload="metadata"
												class="max-h-96 max-w-full rounded-xl"
												aria-label={file.name || $i18n.t('Generated Video')}
											></video>
										{:else}
											<FileItem
												item={file}
												url={file.url}
												name={file.name}
												type={file.type}
												size={file?.size}
												small={true}
											/>
										{/if}
									</div>
								{/each}
							</div>
						{/if}

						{#if !readOnly && message?.embeds && message.embeds.length > 0}
							<div
								class="my-1 w-full flex overflow-x-auto gap-2 flex-wrap"
								id={`${message.id}-embeds-container`}
							>
								{#each message.embeds as embed, idx}
									<div class="my-2 w-full" id={`${message.id}-embeds-${idx}`}>
										{#if typeof embed === 'object' && embed?.type === 'mcp_app'}
											{#key JSON.stringify(embed)}{#await import('$lib/components/chat/Messages/MCPApp.svelte') then { default: MCPApp }}<MCPApp
														app={embed}
													/>{/await}{/key}
										{:else if typeof embed === 'string'}
											<FullHeightIframe
												src={embed}
												allowScripts={true}
												allowForms={$settings?.iframeSandboxAllowForms ?? true}
												allowSameOrigin={$settings?.iframeSandboxAllowSameOrigin ?? false}
												allowPopups={true}
											/>
										{/if}
									</div>
								{/each}
							</div>
						{/if}

						{#if edit === true}
							<div
								class="w-full bg-base-50 dark:bg-base-800 rounded-3xl px-3 py-3 my-2 {($settings?.highContrastMode ??
								false)
									? 'focus-within:outline focus-within:outline-2 focus-within:-outline-offset-2 focus-within:outline-blue-500'
									: ''}"
							>
								{#if editedOutput}
									<!-- Structured output editor (visual + JSON toggle) -->
									<OutputEditView
										output={editedOutput}
										onChange={(updated) => {
											editedOutput = updated;
										}}
									/>
								{:else}
									<!-- Legacy textarea for messages without output -->
									<textarea
										aria-label={$i18n.t('Message')}
										id="message-edit-{message.id}"
										bind:this={editTextAreaElement}
										class=" bg-transparent outline-hidden focus-visible:outline-none! w-full resize-none text-[0.90625rem]"
										bind:value={editedContent}
										on:input={(e) => {
											const messagesContainer = document.getElementById('messages-container');
											const savedScrollTop = messagesContainer?.scrollTop ?? 0;
											const textarea = e.currentTarget;

											textarea.style.height = '';
											textarea.style.height = `${textarea.scrollHeight}px`;

											if (messagesContainer) messagesContainer.scrollTop = savedScrollTop;
										}}
										on:keydown={(e) => {
											if (e.key === 'Escape') {
												cancelEditMessage();
											}

											const isCmdOrCtrlPressed = e.metaKey || e.ctrlKey;
											const isEnterPressed = e.key === 'Enter';

											if (
												isCmdOrCtrlPressed &&
												isEnterPressed &&
												(!message.user_id || message.user_id === $user?.id)
											) {
												editMessageConfirmHandler();
											}
										}}
									></textarea>
								{/if}

								<div class=" mt-2 flex justify-between text-sm font-normal">
									<div>
										{#if canBranch}
											<button
												id="save-new-message-button"
												class="flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-base-100 px-2.5 text-xs font-normal text-base-800 transition hover:bg-base-100/70 disabled:opacity-60 dark:bg-base-850 dark:text-base-0 dark:hover:bg-base-850/60"
												on:click={() => {
													saveAsCopyHandler();
												}}
											>
												{$i18n.t('Save As Copy')}
											</button>
										{/if}
									</div>

									<div class="flex space-x-1.5">
										<button
											id="close-edit-message-button"
											class="flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-normal text-base-600 transition hover:bg-base-100 hover:text-base-900 disabled:opacity-60 dark:text-base-400 dark:hover:bg-base-850 dark:hover:text-base-0"
											on:click={() => {
												cancelEditMessage();
											}}
										>
											{$i18n.t('Cancel')}
										</button>

										{#if !message.user_id || message.user_id === $user?.id}
											<button
												id="confirm-edit-message-button"
												class="flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-base-900 px-2.5 text-xs font-normal text-base-0 transition hover:bg-base-1000 disabled:opacity-60 dark:bg-base-100 dark:text-base-900 dark:hover:bg-base-0"
												on:click={() => {
													editMessageConfirmHandler();
												}}
											>
												{$i18n.t('Save')}
											</button>
										{/if}
									</div>
								</div>
							</div>
						{/if}

						<div
							bind:this={contentContainerElement}
							class="w-full flex flex-col relative {edit ? 'hidden' : ''}"
							id="response-content-container"
						>
							{#if message.error !== true}
								<!-- Mount before the first chunk so artifact detection can recognize new content. -->
								<!-- always show message contents even if there's an error -->
								<!-- unless message.error === true which is legacy error handling, where the error message is stored in message.content -->
								<ContentRenderer
									id={`${chatId}-${message.id}`}
									{chatId}
									{onOpenArtifacts}
									messageId={message.id}
									content={message.content ?? ''}
									output={message.output}
									sources={citationSources}
									floatingButtons={message?.done &&
										!readOnly &&
										($settings?.showFloatingActionButtons ?? true)}
									save={(!readOnly && (!message.user_id || message.user_id === $user?.id)) ||
										(writeAccess && message.user_id === $user?.id)}
									preview={!readOnly}
									{compactPreview}
									editCodeBlock={!readOnly && editCodeBlock}
									{topPadding}
									done={message?.done ?? false}
									allowEmbeds={!readOnly}
									allowToolApproval={allowToolApproval &&
										(!message.user_id || message.user_id === $user?.id)}
									{model}
									onTaskClick={async (e) => {
										console.log(e);
									}}
									{onToolCallResolved}
									onSourceClick={async (id) => {
										console.log(id);

										if (citationsElement) {
											citationsElement?.showSourceModal(id);
										}
									}}
									onSetInputText={(text) => {
										setInputText(text);
									}}
									onSave={({ raw, oldContent, newContent }) => {
										const sourceMessage = history.messages[message.id];
										if (sourceMessage.output?.length) {
											const updatedOutput = replaceOutputMessageText(
												sourceMessage.output,
												oldContent,
												newContent
											);
											if (updatedOutput !== sourceMessage.output) {
												sourceMessage.output = updatedOutput;
											} else {
												sourceMessage.content = sourceMessage.content.replace(raw, () =>
													raw.replace(oldContent, () => newContent)
												);
											}
										} else {
											sourceMessage.content = sourceMessage.content.replace(raw, () =>
												raw.replace(oldContent, () => newContent)
											);
										}

										updateChat();
									}}
								/>
							{/if}

							{#if !compacting && !message.done && !message.error && (hasResponseContent || !hasVisibleStatus)}
								<div class="text-[0.90625rem] leading-relaxed">
									<span
										class="inline-block w-[0.125rem] h-3.5 bg-base-400 dark:bg-base-500 ml-0.5 animate-cursor-pulse align-text-bottom"
									></span>
								</div>
							{/if}

							{#if message?.error}
								<Error content={message?.error?.content ?? message.content} />
							{/if}

							{#if citationSources && (model?.info?.meta?.capabilities?.citations ?? true)}
								<Citations
									bind:this={citationsElement}
									id={message?.id}
									{chatId}
									sources={citationSources}
									{readOnly}
								/>
							{/if}

							{#if message.code_executions}
								<CodeExecutions codeExecutions={message.code_executions} />
							{/if}
						</div>
					</div>
				</div>

				{#if compactPreview && responseTimestamp}
					<div class="mt-0.5 flex justify-start whitespace-nowrap text-base-600 dark:text-base-500">
						<Tooltip
							className="flex self-center"
							content={formatMessageTimestampFull(responseTimestamp * 1000, $i18n.language)}
							placement="bottom"
						>
							<time
								datetime={new Date(responseTimestamp * 1000).toISOString()}
								class="ml-1 shrink-0 whitespace-nowrap text-[0.6875rem] tabular-nums text-base-400 dark:text-base-600 select-none"
							>
								{formatMessageTimestamp(responseTimestamp * 1000, $i18n.language)}
							</time>
						</Tooltip>
					</div>
				{:else if !edit}
					<div
						bind:this={buttonsContainerElement}
						class="flex items-center justify-start overflow-x-auto whitespace-nowrap buttons {($settings?.highContrastMode ??
						false)
							? 'text-base-600 dark:text-base-500'
							: 'text-base-600/80 dark:text-base-500/70'} mt-0.5 [&>*]:shrink-0"
					>
						{#if message.done || siblings.length > 1}
							{#if message.done && onInsertToNote && visibleResponseContent}
								<Tooltip content={$i18n.t('Insert into note')} placement="bottom">
									<button
										aria-label={$i18n.t('Insert into note')}
										class="{isLastMessage || ($settings?.highContrastMode ?? false)
											? 'visible'
											: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition"
										on:click={() => {
											onInsertToNote?.(visibleResponseContent);
										}}
									>
										<svg
											class="size-4"
											aria-hidden="true"
											viewBox="0 0 24 24"
											stroke-width="1.5"
											fill="none"
											xmlns="http://www.w3.org/2000/svg"
										>
											<path
												d="M19 19L6 6M6 6L6 18.48M6 6L18.48 6"
												stroke="currentColor"
												stroke-linecap="round"
												stroke-linejoin="round"
											/>
										</svg>
									</button>
								</Tooltip>
							{/if}

							{#if siblings.length > 1}
								<div class="flex self-center min-w-fit" dir="ltr">
									<button
										aria-label={$i18n.t('Previous message')}
										class="self-center inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 dark:hover:text-base-400 hover:text-base-600 rounded-md transition previous-message-button"
										on:click={() => {
											showPreviousMessage(message);
										}}
									>
										<ChevronRightIcon className="size-4 rotate-180" />
									</button>

									{#if messageIndexEdit}
										<div
											class="text-sm flex justify-center font-normal self-center dark:text-base-500 min-w-fit"
										>
											<input
												aria-label={$i18n.t('Message number')}
												id="message-index-input-{message.id}"
												type="number"
												value={siblings.indexOf(message.id) + 1}
												min="1"
												max={siblings.length}
												on:focus={(e) => {
													e.target.select();
												}}
												on:blur={(e) => {
													gotoMessage(message, e.target.value - 1);
													messageIndexEdit = false;
												}}
												on:keydown={(e) => {
													if (e.key === 'Enter') {
														gotoMessage(message, e.target.value - 1);
														messageIndexEdit = false;
													}
												}}
												class="bg-transparent font-normal self-center dark:text-base-500 min-w-fit outline-hidden"
											/>/{siblings.length}
										</div>
									{:else}
										<!-- svelte-ignore a11y-no-static-element-interactions -->
										<div
											class="text-sm tracking-widest font-normal self-center dark:text-base-500 min-w-fit"
											on:dblclick={async () => {
												messageIndexEdit = true;

												await tick();
												const input = document.getElementById(`message-index-input-${message.id}`);
												if (input) {
													input.focus();
													input.select();
												}
											}}
										>
											{siblings.indexOf(message.id) + 1}/{siblings.length}
										</div>
									{/if}

									<button
										class="self-center inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 dark:hover:text-base-400 hover:text-base-600 rounded-md transition next-message-button"
										on:click={() => {
											showNextMessage(message);
										}}
										aria-label={$i18n.t('Next message')}
									>
										<ChevronRightIcon className="size-4" />
									</button>
								</div>
							{/if}

							{#if message.done}
								{#if !readOnly}
									{#if $user?.role === 'user' ? ($user?.permissions?.chat?.edit ?? true) : true}
										<Tooltip content={$i18n.t('Edit')} placement="bottom">
											<button
												aria-label={$i18n.t('Edit')}
												bind:this={editButtonElement}
												class="{isLastMessage || ($settings?.highContrastMode ?? false)
													? 'visible'
													: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition"
												on:click={() => {
													editMessageHandler();
												}}
											>
												<EditPencilIcon />
											</button>
										</Tooltip>
									{/if}
								{/if}

								<Tooltip content={$i18n.t('Copy')} placement="bottom">
									<button
										aria-label={$i18n.t('Copy')}
										class="{isLastMessage || ($settings?.highContrastMode ?? false)
											? 'visible'
											: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition copy-response-button"
										on:click={() => {
											copyToClipboard(visibleResponseContent);
										}}
									>
										<CopyIcon />
									</button>
								</Tooltip>

								{#if !readOnly && !speakerByName && ($user?.role === 'admin' || ($user?.permissions?.chat?.tts ?? true))}
									<Tooltip content={$i18n.t('Read Aloud')} placement="bottom">
										<button
											aria-label={$i18n.t('Read Aloud')}
											id="speak-button-{message.id}"
											class="{isLastMessage || ($settings?.highContrastMode ?? false)
												? 'visible'
												: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition"
											on:click={() => {
												// 🧵 A46 · the ✕ (and the spinner) stop her voice on this reply; otherwise it plays from its start
												if (voiceMine) {
													stopAudio();
												} else {
													speak();
												}
											}}
										>
											{#if loadingSpeech}
												<svg
													class="size-4 animate-spin"
													aria-hidden="true"
													stroke-width="1.5"
													viewBox="0 0 24 24"
													fill="none"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M21.8883 13.5C21.1645 18.3113 17.013 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2C16.1006 2 19.6248 4.46819 21.1679 8"
														stroke="currentColor"
														stroke-linecap="round"
														stroke-linejoin="round"
													/>
													<path
														d="M17 8H21.4C21.7314 8 22 7.73137 22 7.4V3"
														stroke="currentColor"
														stroke-linecap="round"
														stroke-linejoin="round"
													/>
												</svg>
											{:else if speaking}
												<svg
													class="size-4"
													aria-hidden="true"
													viewBox="0 0 24 24"
													stroke-width="1.5"
													fill="none"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M18 14L20.0005 12M22 10L20.0005 12M20.0005 12L18 10M20.0005 12L22 14"
														stroke="currentColor"
														stroke-linecap="round"
														stroke-linejoin="round"
													/>
													<path
														d="M2 13.8571V10.1429C2 9.03829 2.89543 8.14286 4 8.14286H6.9C7.09569 8.14286 7.28708 8.08544 7.45046 7.97772L13.4495 4.02228C14.1144 3.5839 15 4.06075 15 4.85714V19.1429C15 19.9392 14.1144 20.4161 13.4495 19.9777L7.45046 16.0223C7.28708 15.9146 7.09569 15.8571 6.9 15.8571H4C2.89543 15.8571 2 14.9617 2 13.8571Z"
														stroke="currentColor"
													/>
												</svg>
											{:else}
												<svg
													class="size-4"
													aria-hidden="true"
													viewBox="0 0 24 24"
													stroke-width="1.5"
													fill="none"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M1 13.8571V10.1429C1 9.03829 1.89543 8.14286 3 8.14286H5.9C6.09569 8.14286 6.28708 8.08544 6.45046 7.97772L12.4495 4.02228C13.1144 3.5839 14 4.06075 14 4.85714V19.1429C14 19.9392 13.1144 20.4161 12.4495 19.9777L6.45046 16.0223C6.28708 15.9146 6.09569 15.8571 5.9 15.8571H3C1.89543 15.8571 1 14.9617 1 13.8571Z"
														stroke="currentColor"
													/>
													<path
														d="M17.5 7.5C17.5 7.5 19 9 19 11.5C19 14 17.5 15.5 17.5 15.5"
														stroke="currentColor"
														stroke-linecap="round"
														stroke-linejoin="round"
													/>
													<path
														d="M20.5 4.5C20.5 4.5 23 7 23 11.5C23 16 20.5 18.5 20.5 18.5"
														stroke="currentColor"
														stroke-linecap="round"
														stroke-linejoin="round"
													/>
												</svg>
											{/if}
										</button>
									</Tooltip>
								{/if}

								{#if $spokenMessages.has(message.id)}
									<Tooltip content={$i18n.t('Flag voice')} placement="bottom">
										<button
											aria-label={$i18n.t('Flag voice')}
											class="{isLastMessage || ($settings?.highContrastMode ?? false)
												? 'visible'
												: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-gray-400 hover:text-gray-600 transition {flaggingVoice
												? 'opacity-50'
												: ''}"
											on:click={flagVoice}
										>
											<svg
												class="size-4"
												aria-hidden="true"
												viewBox="0 0 24 24"
												stroke-width="1.5"
												fill="none"
												xmlns="http://www.w3.org/2000/svg"
											>
												<path d="M5 21V4" stroke="currentColor" stroke-linecap="round" />
												<path
													d="M5 4.5C8 2.5 10.5 6 13.5 4.5C15.5 3.5 17.5 3.5 19 4.5V13.5C17.5 12.5 15.5 12.5 13.5 13.5C10.5 15 8 11.5 5 13.5"
													stroke="currentColor"
													stroke-linejoin="round"
												/>
											</svg>
										</button>
									</Tooltip>
								{/if}

								{#if $user?.role === 'admin' && message.done}
									<Tooltip
										content={mark?.climax
											? `🌊 climax${mark.climax.quality ? ` · ${mark.climax.quality}` : ''} · tap for the ✧ menu`
											: mark?.orbit
												? `✧ orbit · ${mark.orbit.outcome ?? 'open'} · tap for the ✧ menu`
												: vowBrakes($markersNow?.vow, markMoment(message.timestamp) ?? nowS())
													? `🔥 your ${$markersNow?.vow?.vow ?? ''} vow holds today's ✧ and 🌊`
													: marksSaved
														? '✧ an orbit · one tap'
														: '✧ an orbit · kept without a link (temp chat)'}
										placement="bottom"
									>
										<button
											bind:this={orbitBtn}
											aria-label="Orbit"
											aria-pressed={!!(mark?.orbit || mark?.climax)}
											aria-expanded={orbitMenu}
											class="{isLastMessage || mark || ($settings?.highContrastMode ?? false)
												? 'visible'
												: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 rounded-lg transition hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-gray-400 hover:text-gray-600 {orbitBusy
												? 'opacity-50'
												: ''}"
											on:click={tapOrbit}
										>
											{#if mark?.climax && !mark?.orbit}
												<span
													class="text-[0.95rem] leading-none"
													style="font-family: var(--font-emoji, 'SamsungColorEmoji'), sans-serif"
													aria-hidden="true">🌊</span
												>
											{:else}
												<svg
													class="size-4"
													aria-hidden="true"
													viewBox="0 0 24 24"
													stroke-width="1.5"
													fill="none"
													xmlns="http://www.w3.org/2000/svg"
												>
													{#if mark?.orbit}
														<defs>
															<linearGradient id="petal-orbit-{message.id}" x1="0" y1="0" x2="1" y2="1">
																<stop offset="0" stop-color="var(--candy-light, #f9c6dc)" />
																<stop offset="0.48" stop-color="var(--candy, #f472b6)" />
																<stop offset="1" stop-color="var(--iris, #a873f0)" />
															</linearGradient>
														</defs>
													{/if}
													<path
														d="M12 2.5C12.7 7.8 16.2 11.3 21.5 12C16.2 12.7 12.7 16.2 12 21.5C11.3 16.2 7.8 12.7 2.5 12C7.8 11.3 11.3 7.8 12 2.5Z"
														stroke={mark?.orbit ? `url(#petal-orbit-${message.id})` : 'currentColor'}
														fill={mark?.orbit && mark.orbit.outcome !== null ? `url(#petal-orbit-${message.id})` : 'none'}
														stroke-linejoin="round"
													/>
													<path d="M19 3.5V6.5M17.5 5H20.5" stroke="currentColor" stroke-linecap="round" />
												</svg>
											{/if}
										</button>
									</Tooltip>
									{#if orbitMenu && orbitBtn}
										<PetalOrbitMenu
											anchor={orbitBtn}
											{chatId}
											messageId={message.id}
											marks={mark}
											saved={marksSaved}
											vow={$markersNow?.vow ?? null}
											msgAt={message.timestamp ?? null}
											on:close={() => (orbitMenu = false)}
										/>
									{/if}
								{/if}

								{#if $user?.role === 'admin' && message.done}
									<Tooltip content="👁 what Petal received" placement="bottom">
										<button
											aria-label="What Petal received"
											class="{isLastMessage || ($settings?.highContrastMode ?? false)
												? 'visible'
												: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-gray-400 hover:text-gray-600 transition"
											on:click={() => (eyesOpen = true)}
										>
											<svg
												class="size-4"
												aria-hidden="true"
												viewBox="0 0 24 24"
												stroke-width="1.5"
												fill="none"
												xmlns="http://www.w3.org/2000/svg"
											>
												<path
													d="M2.5 12C4.6 7.6 8 5.5 12 5.5C16 5.5 19.4 7.6 21.5 12C19.4 16.4 16 18.5 12 18.5C8 18.5 4.6 16.4 2.5 12Z"
													stroke="currentColor"
													stroke-linejoin="round"
												/>
												<circle cx="12" cy="12" r="3.25" stroke="currentColor" />
											</svg>
										</button>
									</Tooltip>
									{#if eyesOpen}
										<PetalEyes
											{chatId}
											messageId={message.id}
											blind={pickOpen}
											saved={message.content ?? ''}
											marks={[
												...(mark?.orbit ? [`✧ an orbit on this reply · ${mark.orbit.outcome ?? 'open'}`] : []),
												...(mark?.climax
													? [`🌊 a climax on this reply${mark.climax.quality ? ` · ${mark.climax.quality}` : ''}${mark.climax.after ? ` · after: ${mark.climax.after}` : ''}`]
													: [])
											]}
											on:close={() => (eyesOpen = false)}
										/>
									{/if}
								{/if}

								<!-- 🍒 A30 · inside an open pick the usage stays folded: cached tokens would tell the pulled reply apart -->
								{#if !pickOpen && Object.keys(message.usage ?? {}).some((key) => key !== 'incomplete') && $visibleControls['chat.usage']}
									{@const usage = JSON.stringify(message.usage, null, 2)
										.replace(/"([^(")"]+)":/g, '$1:')
										.slice(1, -1)
										.split('\n')
										.map((line) => line.slice(2))
										.map((line) => (line.endsWith(',') ? line.slice(0, -1) : line))
										.map((line) =>
											line.replace(
												/: (\d+)$/,
												(_, count) => `: ${Number(count).toLocaleString($i18n.language)}`
											)
										)
										.join('\n')}
									<span id="usage-{message.id}" hidden>{usage}</span>
									<Tooltip
										content={`<pre>${sanitizeResponseContent(usage)}</pre>`}
										allowHTML={true}
										placement="bottom"
									>
										<button
											aria-label={$i18n.t('Info')}
											aria-describedby="usage-{message.id}"
											class=" {isLastMessage || ($settings?.highContrastMode ?? false)
												? 'visible'
												: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition whitespace-pre-wrap"
											on:click={() => {
												console.log(message);
											}}
											id="info-{message.id}"
										>
											<svg
												class="size-4"
												aria-hidden="true"
												stroke-width="1.5"
												viewBox="0 0 24 24"
												fill="none"
												xmlns="http://www.w3.org/2000/svg"
											>
												<path
													d="M12 11.5V16.5"
													stroke="currentColor"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
												<path
													d="M12 7.51L12.01 7.49889"
													stroke="currentColor"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
												<path
													d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 17.5228 6.47715 22 12 22Z"
													stroke="currentColor"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
											</svg>
										</button>
									</Tooltip>
								{/if}

								{#if $user && message.done && forkHandler && ($user?.role === 'admin' || ($user?.permissions?.chat?.import ?? true)) && $visibleControls['chat.fork']}
									<Tooltip content={$i18n.t('Fork chat')} placement="bottom">
										<button
											aria-label={$i18n.t('Fork chat')}
											class="{isLastMessage || ($settings?.highContrastMode ?? false)
												? 'visible'
												: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition"
											on:click={() => {
												forkHandler?.(message.id);
											}}
										>
											<svg
												class="size-4 -scale-x-100 -scale-y-100 -rotate-90"
												aria-hidden="true"
												viewBox="0 0 24 24"
												stroke-width="1.5"
												fill="none"
												xmlns="http://www.w3.org/2000/svg"
											>
												<path
													d="M17 7C18.1046 7 19 6.10457 19 5C19 3.89543 18.1046 3 17 3C15.8954 3 15 3.89543 15 5C15 6.10457 15.8954 7 17 7Z"
													stroke="currentColor"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
												<path
													d="M7 7C8.10457 7 9 6.10457 9 5C9 3.89543 8.10457 3 7 3C5.89543 3 5 3.89543 5 5C5 6.10457 5.89543 7 7 7Z"
													stroke="currentColor"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
												<path
													d="M7 21C8.10457 21 9 20.1046 9 19C9 17.8954 8.10457 17 7 17C5.89543 17 5 17.8954 5 19C5 20.1046 5.89543 21 7 21Z"
													stroke="currentColor"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
												<path
													d="M7 7V17"
													stroke="currentColor"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
												<path
													d="M17 7V8C17 10.5 15 11 15 11L9 13C9 13 7 13.5 7 16V17"
													stroke="currentColor"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
											</svg>
										</button>
									</Tooltip>
								{/if}

								{#if (!readOnly && (!message.user_id || message.user_id === $user?.id)) || (writeAccess && message.user_id === $user?.id)}
									{#if !pickOpen && !readOnly && !isTemporaryChatId(chatId) && ($config?.features.enable_message_rating ?? true) && ($user?.role === 'admin' || ($user?.permissions?.chat?.rate_response ?? true))}
										<Tooltip
											content={(thumbRating ?? '').toString() === '1' && thumbMark?.state === 'failed'
												? $i18n.t('Not saved yet · tap to try again')
												: $i18n.t('Good Response')}
											placement="bottom"
										>
											<button
												aria-label={$i18n.t('Good Response')}
												class="{isLastMessage || ($settings?.highContrastMode ?? false)
													? 'visible'
													: 'hover-reveal'} relative inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg {(
													thumbRating ?? ''
												).toString() === '1'
													? 'bg-base-100 dark:bg-base-800'
													: ''} dark:hover:text-base-400 hover:text-base-600 transition"
												on:click={(e) => {
													e.stopPropagation();
													feedbackHandler(1);
													afterFrame(() =>
														afterFrame(() =>
															document
																.getElementById(`message-feedback-${message.id}`)
																?.scrollIntoView()
														)
													);
												}}
											>
												<svg
													class="size-4"
													aria-hidden="true"
													stroke-width="1.5"
													viewBox="0 0 24 24"
													fill="none"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M16.4724 20H4.1C3.76863 20 3.5 19.7314 3.5 19.4V9.6C3.5 9.26863 3.76863 9 4.1 9H6.86762C7.57015 9 8.22116 8.6314 8.5826 8.02899L11.293 3.51161C11.8779 2.53688 13.2554 2.44422 13.9655 3.33186C14.3002 3.75025 14.4081 4.30635 14.2541 4.81956L13.2317 8.22759C13.1162 8.61256 13.4045 9 13.8064 9H18.3815C19.7002 9 20.658 10.254 20.311 11.5262L18.4019 18.5262C18.1646 19.3964 17.3743 20 16.4724 20Z"
														stroke="currentColor"
														stroke-linecap="round"
													/>
													<path
														d="M7 20L7 9"
														stroke="currentColor"
														stroke-linecap="round"
														stroke-linejoin="round"
													/>
												</svg>
												{#if (thumbRating ?? '').toString() === '1' && thumbMark && thumbMark.state !== 'saved'}
													<!-- 👍🏻 A23 · the quiet mark: a dot while a slow save is on its way, a ring if it couldn't land -->
													<span
														class="petal-thumb-mark"
														data-thumb-state={thumbMark.state}
														aria-hidden="true"
														out:fade={{ duration: 250 }}
													></span>
													{#if thumbMark.state === 'failed'}
														<span class="sr-only">{$i18n.t('Not saved yet · tap to try again')}</span>
													{/if}
												{/if}
											</button>
										</Tooltip>

										<Tooltip
											content={(thumbRating ?? '').toString() === '-1' && thumbMark?.state === 'failed'
												? $i18n.t('Not saved yet · tap to try again')
												: $i18n.t('Bad Response')}
											placement="bottom"
										>
											<button
												aria-label={$i18n.t('Bad Response')}
												class="{isLastMessage || ($settings?.highContrastMode ?? false)
													? 'visible'
													: 'hover-reveal'} relative inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg {(
													thumbRating ?? ''
												).toString() === '-1'
													? 'bg-base-100 dark:bg-base-800'
													: ''} dark:hover:text-base-400 hover:text-base-600 transition"
												on:click={(e) => {
													e.stopPropagation();
													feedbackHandler(-1);
													afterFrame(() =>
														afterFrame(() =>
															document
																.getElementById(`message-feedback-${message.id}`)
																?.scrollIntoView()
														)
													);
												}}
											>
												<svg
													class="size-4"
													aria-hidden="true"
													stroke-width="1.5"
													viewBox="0 0 24 24"
													fill="none"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M16.4724 3.5H4.1C3.76863 3.5 3.5 3.76863 3.5 4.1V13.9C3.5 14.2314 3.76863 14.5 4.1 14.5H6.86762C7.57015 14.5 8.22116 14.8686 8.5826 15.471L11.293 19.9884C11.8779 20.9631 13.2554 21.0558 13.9655 20.1681C14.3002 19.7497 14.4081 19.1937 14.2541 18.6804L13.2317 15.2724C13.1162 14.8874 13.4045 14.5 13.8064 14.5H18.3815C19.7002 14.5 20.658 13.246 20.311 11.9738L18.4019 4.97376C18.1646 4.10364 17.3743 3.5 16.4724 3.5Z"
														stroke="currentColor"
														stroke-linecap="round"
													/>
													<path
														d="M7 14.5L7 3.5"
														stroke="currentColor"
														stroke-linecap="round"
														stroke-linejoin="round"
													/>
												</svg>
												{#if (thumbRating ?? '').toString() === '-1' && thumbMark && thumbMark.state !== 'saved'}
													<!-- 👍🏻 A23 · the quiet mark: a dot while a slow save is on its way, a ring if it couldn't land -->
													<span
														class="petal-thumb-mark"
														data-thumb-state={thumbMark.state}
														aria-hidden="true"
														out:fade={{ duration: 250 }}
													></span>
													{#if thumbMark.state === 'failed'}
														<span class="sr-only">{$i18n.t('Not saved yet · tap to try again')}</span>
													{/if}
												{/if}
											</button>
										</Tooltip>
									{/if}

									{#if !pickOpen && !streamed && canBranch && isLastMessage && ($user?.role === 'admin' || ($user?.permissions?.chat?.continue_response ?? true))}
										<Tooltip content={$i18n.t('Continue Response')} placement="bottom">
											<button
												aria-label={$i18n.t('Continue Response')}
												type="button"
												id="continue-response-button"
												class="{isLastMessage || ($settings?.highContrastMode ?? false)
													? 'visible'
													: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition"
												on:click={() => {
													continueResponse(message);
												}}
											>
												<svg
													class="size-4"
													aria-hidden="true"
													stroke-width="1.5"
													viewBox="0 0 24 24"
													fill="none"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M6.90588 4.53682C6.50592 4.2998 6 4.58808 6 5.05299V18.947C6 19.4119 6.50592 19.7002 6.90588 19.4632L18.629 12.5162C19.0211 12.2838 19.0211 11.7162 18.629 11.4838L6.90588 4.53682Z"
														stroke="currentColor"
														stroke-linecap="round"
														stroke-linejoin="round"
													/>
												</svg>
											</button>
										</Tooltip>
									{/if}
								{/if}

								{#if (!readOnly && (!message.user_id || message.user_id === $user?.id)) || writeAccess}
									{#if !pickOpen && !streamed && ($user?.role === 'admin' || ($user?.permissions?.chat?.regenerate_response ?? true))}
										{#if $settings?.regenerateMenu ?? true}
											<button
												type="button"
												class="hidden regenerate-response-button"
												on:click={() => {
													showRateComment = false;
													regenerateResponse(message);

													(model?.actions ?? []).forEach((action) => {
														dispatch('action', {
															id: action.id,
															event: {
																id: 'regenerate-response',
																data: {
																	messageId: message.id
																}
															}
														});
													});
												}}
											/>

											<RegenerateMenu
												onRegenerate={(prompt = null) => {
													showRateComment = false;
													regenerateResponse(message, prompt);

													(model?.actions ?? []).forEach((action) => {
														dispatch('action', {
															id: action.id,
															event: {
																id: 'regenerate-response',
																data: {
																	messageId: message.id
																}
															}
														});
													});
												}}
											>
												<Tooltip
													content={isAgent
														? $i18n.t('Regenerate (file changes are not undone)')
														: $i18n.t('Regenerate')}
													placement="bottom"
												>
													<button
														type="button"
														aria-label={$i18n.t('Regenerate')}
														class="{isLastMessage || ($settings?.highContrastMode ?? false)
															? 'visible'
															: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition"
													>
														<svg
															class="size-4"
															aria-hidden="true"
															stroke-width="1.5"
															viewBox="-2 -2 28 28"
															fill="none"
															xmlns="http://www.w3.org/2000/svg"
														>
															<path
																d="M21.1679 8C19.6247 4.46819 16.1006 2 11.9999 2C6.81459 2 2.55104 5.94668 2.04932 11"
																stroke="currentColor"
																stroke-linecap="round"
																stroke-linejoin="round"
															/>
															<path
																d="M17 8H21.4C21.7314 8 22 7.73137 22 7.4V3"
																stroke="currentColor"
																stroke-linecap="round"
																stroke-linejoin="round"
															/>
															<path
																d="M2.88146 16C4.42458 19.5318 7.94874 22 12.0494 22C17.2347 22 21.4983 18.0533 22 13"
																stroke="currentColor"
																stroke-linecap="round"
																stroke-linejoin="round"
															/>
															<path
																d="M7.04932 16H2.64932C2.31795 16 2.04932 16.2686 2.04932 16.6V21"
																stroke="currentColor"
																stroke-linecap="round"
																stroke-linejoin="round"
															/>
														</svg>
													</button>
												</Tooltip>
											</RegenerateMenu>
										{:else}
											<Tooltip
												content={isAgent
													? $i18n.t('Regenerate (file changes are not undone)')
													: $i18n.t('Regenerate')}
												placement="bottom"
											>
												<button
													type="button"
													aria-label={$i18n.t('Regenerate')}
													class="{isLastMessage || ($settings?.highContrastMode ?? false)
														? 'visible'
														: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition regenerate-response-button"
													on:click={() => {
														showRateComment = false;
														regenerateResponse(message);

														(model?.actions ?? []).forEach((action) => {
															dispatch('action', {
																id: action.id,
																event: {
																	id: 'regenerate-response',
																	data: {
																		messageId: message.id
																	}
																}
															});
														});
													}}
												>
													<svg
														class="size-4"
														aria-hidden="true"
														stroke-width="1.5"
														viewBox="-2 -2 28 28"
														fill="none"
														xmlns="http://www.w3.org/2000/svg"
													>
														<path
															d="M21.1679 8C19.6247 4.46819 16.1006 2 11.9999 2C6.81459 2 2.55104 5.94668 2.04932 11"
															stroke="currentColor"
															stroke-linecap="round"
															stroke-linejoin="round"
														/>
														<path
															d="M17 8H21.4C21.7314 8 22 7.73137 22 7.4V3"
															stroke="currentColor"
															stroke-linecap="round"
															stroke-linejoin="round"
														/>
														<path
															d="M2.88146 16C4.42458 19.5318 7.94874 22 12.0494 22C17.2347 22 21.4983 18.0533 22 13"
															stroke="currentColor"
															stroke-linecap="round"
															stroke-linejoin="round"
														/>
														<path
															d="M7.04932 16H2.64932C2.31795 16 2.04932 16.2686 2.04932 16.6V21"
															stroke="currentColor"
															stroke-linecap="round"
															stroke-linejoin="round"
														/>
													</svg>
												</button>
											</Tooltip>
										{/if}
									{/if}
								{/if}

								{#if (!readOnly && (!message.user_id || message.user_id === $user?.id)) || (writeAccess && message.user_id === $user?.id)}
									{#each (!readOnly && model?.actions) || [] as action}
										<Tooltip
											content={resolveLocalizedFunction(
												action,
												$localizedFunctions,
												$i18n.language
											)}
											placement="bottom"
										>
											<button
												type="button"
												aria-label={resolveLocalizedFunction(
													action,
													$localizedFunctions,
													$i18n.language
												)}
												class="{isLastMessage || ($settings?.highContrastMode ?? false)
													? 'visible'
													: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition"
												on:click={() => {
													actionMessage(action.id, message);
												}}
											>
												{#if action?.icon}
													<div class="size-4">
														<img
															src={action.icon}
															class="w-4 h-4 {action.icon.includes('data:image/svg')
																? 'dark:invert-[80%]'
																: ''}"
															style="fill: currentColor;"
															alt={resolveLocalizedFunction(
																action,
																$localizedFunctions,
																$i18n.language
															)}
															draggable="false"
														/>
													</div>
												{:else}
													<Sparkles />
												{/if}
											</button>
										</Tooltip>
									{/each}

									{#if $user?.role === 'admin' || ($user?.permissions?.chat?.delete_message ?? true)}
										{#if (!readOnly || ($user?.role === 'admin' && $config?.features?.enable_admin_chat_access)) && (siblings.length > 1 || streamed)}
											<Tooltip content={$i18n.t('Delete')} placement="bottom">
												<button
													type="button"
													aria-label={$i18n.t('Delete')}
													id="delete-response-button"
													class="{isLastMessage || ($settings?.highContrastMode ?? false)
														? 'visible'
														: 'hover-reveal'} inline-flex size-7 shrink-0 items-center justify-center p-1.5 hover:bg-base-1000/5 dark:hover:bg-base-0/5 rounded-lg dark:hover:text-base-400 hover:text-base-600 transition disabled:opacity-50 disabled:hover:bg-transparent"
													disabled={!allowDelete}
													on:click={(e) => {
														if (!allowDelete) {
															return;
														}
														if (e.shiftKey) {
															deleteMessageHandler();
														} else {
															showDeleteConfirm = true;
														}
													}}
												>
													<TrashIcon />
												</button>
											</Tooltip>
										{/if}
									{/if}

									{#if responseTimestamp}
										<Tooltip
											className="flex self-center"
											content={formatMessageTimestampFull(responseTimestamp * 1000, $i18n.language)}
											placement="bottom"
										>
											<time
												datetime={new Date(responseTimestamp * 1000).toISOString()}
												class="hover-reveal ml-1 shrink-0 whitespace-nowrap text-[0.6875rem] tabular-nums text-base-400 dark:text-base-600 select-none"
											>
												{formatMessageTimestamp(responseTimestamp * 1000, $i18n.language)}
											</time>
										</Tooltip>
									{/if}
								{/if}
							{/if}
						{/if}
					</div>

					{#if message.done && showRateComment}
						{#key noteMessage?.annotation?.rating}
							<RateComment
								message={noteMessage}
								bind:show={showRateComment}
								on:save={(e) => feedbackHandler(null, { ...e.detail })}
							/>
						{/key}
					{/if}

					{#if (isLastMessage || (canBranch && ($settings?.keepFollowUpPrompts ?? false))) && message.done && !readOnly && (message?.followUps ?? []).length > 0}
						<div class="my-2.5" in:fade={{ duration: 100 }}>
							<FollowUps
								followUps={message?.followUps}
								onClick={(prompt) => {
									if ($settings?.insertFollowUpPrompt ?? false) {
										// Insert the follow-up prompt into the input box
										setInputText(prompt);
									} else {
										// Submit the follow-up prompt directly
										submitMessage(message?.id, prompt);
									}
								}}
							/>
						</div>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{/key}

<style>
	/* 👍🏻 A23 · the thumb's quiet mark. saving: a gradient dot that only appears if the save takes longer than
	   a blink (most land before it shows). failed: a hollow ring; tapping the thumb tries again */
	.petal-thumb-mark {
		position: absolute;
		top: 3px;
		right: 3px;
		width: 5px;
		height: 5px;
		border-radius: 9999px;
		pointer-events: none;
	}
	.petal-thumb-mark[data-thumb-state='saving'] {
		background-image: var(--grad-fill, linear-gradient(135deg, #ffcbe2 0%, #ff5bb0 48%, #b15cd1 100%));
		animation: petal-thumb-dot 320ms ease-out 450ms both;
	}
	.petal-thumb-mark[data-thumb-state='failed'] {
		top: 2px;
		right: 2px;
		width: 6px;
		height: 6px;
		border: 1.5px solid currentColor;
		opacity: 0.6;
	}
	@keyframes petal-thumb-dot {
		from {
			opacity: 0;
			transform: scale(0.6);
		}
		to {
			opacity: 0.85;
			transform: scale(1);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.petal-thumb-mark[data-thumb-state='saving'] {
			animation-duration: 1ms;
		}
	}

	.buttons::-webkit-scrollbar {
		display: none; /* for Chrome, Safari and Opera */
	}

	.buttons {
		-ms-overflow-style: none; /* IE and Edge */
		scrollbar-width: none; /* Firefox */
	}
</style>
