import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from open_webui.config import (
    AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH,
    DEFAULT_AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE,
    DEFAULT_EMOJI_GENERATION_PROMPT_TEMPLATE,
    DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE,
    DEFAULT_IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE,
    DEFAULT_MOA_GENERATION_PROMPT_TEMPLATE,
    DEFAULT_QUERY_GENERATION_PROMPT_TEMPLATE,
    DEFAULT_TAGS_GENERATION_PROMPT_TEMPLATE,
    DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE,
    DEFAULT_VOICE_MODE_PROMPT_TEMPLATE,
)
from open_webui.constants import ERROR_MESSAGES, TASKS
from open_webui.models.config import Config
from open_webui.routers.pipelines import process_pipeline_inlet_filter
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.chat import generate_chat_completion
from open_webui.utils.payload import apply_params_to_form_data
from open_webui.utils.task import (
    autocomplete_generation_template,
    emoji_generation_template,
    follow_up_generation_template,
    get_task_model_id,
    image_prompt_generation_template,
    moa_response_generation_template,
    query_generation_template,
    tags_generation_template,
    title_generation_template,
)
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()

TASK_CONFIG_KEYS = {
    'TASK_MODEL': 'task.model.default',
    'TASK_MODEL_EXTERNAL': 'task.model.external',
    'TASK_MODEL_PARAMS': 'task.model.params',
    'TITLE_GENERATION_PROMPT_TEMPLATE': 'task.title.prompt_template',
    'IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE': 'task.image.prompt_template',
    'ENABLE_AUTOCOMPLETE_GENERATION': 'task.autocomplete.enable',
    'AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH': 'task.autocomplete.input_max_length',
    'AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE': 'task.autocomplete.prompt_template',
    'TAGS_GENERATION_PROMPT_TEMPLATE': 'task.tags.prompt_template',
    'FOLLOW_UP_GENERATION_PROMPT_TEMPLATE': 'task.follow_up.prompt_template',
    'ENABLE_FOLLOW_UP_GENERATION': 'task.follow_up.enable',
    'ENABLE_TAGS_GENERATION': 'task.tags.enable',
    'ENABLE_TITLE_GENERATION': 'task.title.enable',
    'ENABLE_SEARCH_QUERY_GENERATION': 'task.query.search.enable',
    'ENABLE_RETRIEVAL_QUERY_GENERATION': 'task.query.retrieval.enable',
    'QUERY_GENERATION_PROMPT_TEMPLATE': 'task.query.prompt_template',
    'TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE': 'task.tools.prompt_template',
    'ENABLE_VOICE_MODE_PROMPT': 'task.voice.prompt.enable',
    'VOICE_MODE_PROMPT_TEMPLATE': 'task.voice.prompt_template',
}


async def get_config_values(key_map: dict[str, str]) -> dict:
    values = await Config.get_many(*key_map.values())
    return {field: values[storage_key] for field, storage_key in key_map.items() if storage_key in values}


def config_updates(data: dict, key_map: dict[str, str]) -> dict:
    return {key_map[field]: value for field, value in data.items() if field in key_map}


def apply_task_model_params(payload: dict, models: dict, task_model_id: str, params: dict | None = None) -> dict:
    model = models.get(payload.get('model')) or models.get(task_model_id)
    if not model or (not params and not payload.get('params')):
        return payload
    return apply_params_to_form_data(payload, model, params or None)


async def get_task_model_generation_config(default_model_id: str, models) -> tuple[str, dict]:
    config = await Config.get_many(
        'task.model.default',
        'task.model.external',
        'task.model.params',
    )
    params = config.get('task.model.params') or {}
    if not isinstance(params, dict):
        params = {}

    return (
        get_task_model_id(
            default_model_id,
            config.get('task.model.default'),
            config.get('task.model.external'),
            models,
        ),
        {key: value for key, value in params.items() if value is not None and value != ''},
    )


##################################
#
# Task Endpoints
#
##################################


@router.get('/config')
async def get_task_config(request: Request, user=Depends(get_verified_user)):
    return await get_config_values(TASK_CONFIG_KEYS)


class TaskConfigForm(BaseModel):
    TASK_MODEL: Optional[str]
    TASK_MODEL_EXTERNAL: Optional[str]
    TASK_MODEL_PARAMS: dict | None = None
    ENABLE_TITLE_GENERATION: bool
    TITLE_GENERATION_PROMPT_TEMPLATE: str
    IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE: str
    ENABLE_AUTOCOMPLETE_GENERATION: bool
    AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH: int | None = None
    AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE: str
    TAGS_GENERATION_PROMPT_TEMPLATE: str
    FOLLOW_UP_GENERATION_PROMPT_TEMPLATE: str
    ENABLE_FOLLOW_UP_GENERATION: bool
    ENABLE_TAGS_GENERATION: bool
    ENABLE_SEARCH_QUERY_GENERATION: bool
    ENABLE_RETRIEVAL_QUERY_GENERATION: bool
    QUERY_GENERATION_PROMPT_TEMPLATE: str
    TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE: str
    ENABLE_VOICE_MODE_PROMPT: bool
    VOICE_MODE_PROMPT_TEMPLATE: Optional[str]


@router.post('/config/update')
async def update_task_config(request: Request, form_data: TaskConfigForm, user=Depends(get_admin_user)):
    data = form_data.model_dump()
    if data['AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH'] is None:
        data['AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH'] = AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH
    await Config.upsert(config_updates(data, TASK_CONFIG_KEYS))
    return await get_config_values(TASK_CONFIG_KEYS)


@router.post('/title/completions')
async def generate_title(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if not await Config.get('task.title.enable'):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={'detail': 'Title generation is disabled'},
        )

    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            **dict(request.app.state.MODELS.items()),
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    model_id = form_data['model']
    if not model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='No model specified for title generation. Please ensure a model is selected for this chat.',
        )
    if model_id not in models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(),
        )

    task_model_id, task_model_params = await get_task_model_generation_config(model_id, models)

    log.debug('generating chat title using model %s for user %s ', task_model_id, user.email)

    title_template = await Config.get('task.title.prompt_template')
    if title_template != '':
        template = title_template
    else:
        template = DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE

    content = await title_generation_template(template, form_data['messages'], user)
    task_model_params = task_model_params or {
        'max_tokens': models[task_model_id].get('info', {}).get('params', {}).get('max_tokens', 1000)
    }

    payload = {
        'model': task_model_id,
        'messages': [{'role': 'user', 'content': content}],
        'stream': False,
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': str(TASKS.TITLE_GENERATION),
            'task_body': form_data,
            'chat_id': form_data.get('chat_id', None),
        },
    }

    # Process the payload through the pipeline
    try:
        payload = await process_pipeline_inlet_filter(request, payload, user, models)
    except Exception as e:
        raise e

    payload = apply_task_model_params(payload, models, task_model_id, task_model_params)

    try:
        return await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        log.error('Exception occurred', exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={'detail': 'An internal error has occurred.'},
        )


@router.post('/follow_up/completions')
async def generate_follow_ups(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if not await Config.get('task.follow_up.enable'):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={'detail': 'Follow-up generation is disabled'},
        )

    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            **dict(request.app.state.MODELS.items()),
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    model_id = form_data['model']
    if model_id not in models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(),
        )

    task_model_id, task_model_params = await get_task_model_generation_config(model_id, models)

    log.debug('generating chat title using model %s for user %s ', task_model_id, user.email)

    follow_up_template = await Config.get('task.follow_up.prompt_template')
    if follow_up_template != '':
        template = follow_up_template
    else:
        template = DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE

    content = await follow_up_generation_template(
        template, form_data['messages'], user, use_default=follow_up_template == ''
    )

    payload = {
        'model': task_model_id,
        'messages': [{'role': 'user', 'content': content}],
        'stream': False,
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': str(TASKS.FOLLOW_UP_GENERATION),
            'task_body': form_data,
            'chat_id': form_data.get('chat_id', None),
        },
    }

    # Process the payload through the pipeline
    try:
        payload = await process_pipeline_inlet_filter(request, payload, user, models)
    except Exception as e:
        raise e

    payload = apply_task_model_params(payload, models, task_model_id, task_model_params)

    try:
        return await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        log.error('Exception occurred', exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={'detail': 'An internal error has occurred.'},
        )


@router.post('/tags/completions')
async def generate_chat_tags(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if not await Config.get('task.tags.enable'):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={'detail': 'Tags generation is disabled'},
        )

    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            **dict(request.app.state.MODELS.items()),
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    model_id = form_data['model']
    if model_id not in models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(),
        )

    task_model_id, task_model_params = await get_task_model_generation_config(model_id, models)

    log.debug('generating chat tags using model %s for user %s ', task_model_id, user.email)

    tags_template = await Config.get('task.tags.prompt_template')
    if tags_template != '':
        template = tags_template
    else:
        template = DEFAULT_TAGS_GENERATION_PROMPT_TEMPLATE

    content = await tags_generation_template(template, form_data['messages'], user)

    payload = {
        'model': task_model_id,
        'messages': [{'role': 'user', 'content': content}],
        'stream': False,
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': str(TASKS.TAGS_GENERATION),
            'task_body': form_data,
            'chat_id': form_data.get('chat_id', None),
        },
    }

    # Process the payload through the pipeline
    try:
        payload = await process_pipeline_inlet_filter(request, payload, user, models)
    except Exception as e:
        raise e

    payload = apply_task_model_params(payload, models, task_model_id, task_model_params)

    try:
        return await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        log.error(f'Error generating chat completion: {e}')
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={'detail': 'An internal error has occurred.'},
        )


@router.post('/image_prompt/completions')
async def generate_image_prompt(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            **dict(request.app.state.MODELS.items()),
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    model_id = form_data['model']
    if model_id not in models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(),
        )

    task_model_id, task_model_params = await get_task_model_generation_config(model_id, models)

    log.debug('generating image prompt using model %s for user %s ', task_model_id, user.email)

    image_prompt_template = await Config.get('task.image.prompt_template')
    if image_prompt_template != '':
        template = image_prompt_template
    else:
        template = DEFAULT_IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE

    content = await image_prompt_generation_template(template, form_data['messages'], user)

    payload = {
        'model': task_model_id,
        'messages': [{'role': 'user', 'content': content}],
        'stream': False,
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': str(TASKS.IMAGE_PROMPT_GENERATION),
            'task_body': form_data,
            'chat_id': form_data.get('chat_id', None),
        },
    }

    # Process the payload through the pipeline
    try:
        payload = await process_pipeline_inlet_filter(request, payload, user, models)
    except Exception as e:
        raise e

    payload = apply_task_model_params(payload, models, task_model_id, task_model_params)

    try:
        return await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        log.error('Exception occurred', exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={'detail': 'An internal error has occurred.'},
        )


@router.post('/queries/completions')
async def generate_queries(request: Request, form_data: dict, user=Depends(get_verified_user)):
    type = form_data.get('type')
    if type == 'web_search':
        if not await Config.get('task.query.search.enable'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.FEATURE_DISABLED('Search query generation'),
            )
    elif type == 'retrieval':
        if not await Config.get('task.query.retrieval.enable'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.FEATURE_DISABLED('Query generation'),
            )

    if getattr(request.state, 'cached_queries', None):
        log.info('Reusing cached queries: %s', request.state.cached_queries)
        return request.state.cached_queries

    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            **dict(request.app.state.MODELS.items()),
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    model_id = form_data['model']
    if model_id not in models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(),
        )

    task_model_id, task_model_params = await get_task_model_generation_config(model_id, models)

    log.debug('generating %s queries using model %s for user %s', type, task_model_id, user.email)

    query_template = await Config.get('task.query.prompt_template')
    if query_template.strip() != '':
        template = query_template
    else:
        template = DEFAULT_QUERY_GENERATION_PROMPT_TEMPLATE

    content = await query_generation_template(template, form_data['messages'], user)

    payload = {
        'model': task_model_id,
        'messages': [{'role': 'user', 'content': content}],
        'stream': False,
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': str(TASKS.QUERY_GENERATION),
            'task_body': form_data,
            'chat_id': form_data.get('chat_id', None),
        },
    }

    # Process the payload through the pipeline
    try:
        payload = await process_pipeline_inlet_filter(request, payload, user, models)
    except Exception as e:
        raise e

    payload = apply_task_model_params(payload, models, task_model_id, task_model_params)

    try:
        return await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={'detail': str(e)},
        )


@router.post('/auto/completions')
async def generate_autocompletion(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if not await Config.get('task.autocomplete.enable'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.FEATURE_DISABLED('Autocompletion generation'),
        )

    type = form_data.get('type')
    prompt = form_data.get('prompt')
    messages = form_data.get('messages')

    autocomplete_input_max_length = await Config.get('task.autocomplete.input_max_length')
    if autocomplete_input_max_length > 0:
        if len(prompt) > autocomplete_input_max_length:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.INPUT_TOO_LONG(autocomplete_input_max_length),
            )

    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            **dict(request.app.state.MODELS.items()),
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    model_id = form_data['model']
    if model_id not in models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(),
        )

    task_model_id, task_model_params = await get_task_model_generation_config(model_id, models)

    log.debug('generating autocompletion using model %s for user %s', task_model_id, user.email)

    autocomplete_template = await Config.get('task.autocomplete.prompt_template')
    if autocomplete_template.strip() != '':
        template = autocomplete_template
    else:
        template = DEFAULT_AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE

    content = await autocomplete_generation_template(template, prompt, messages, type, user)

    payload = {
        'model': task_model_id,
        'messages': [{'role': 'user', 'content': content}],
        'stream': False,
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': str(TASKS.AUTOCOMPLETE_GENERATION),
            'task_body': form_data,
            'chat_id': form_data.get('chat_id', None),
        },
    }

    # Process the payload through the pipeline
    try:
        payload = await process_pipeline_inlet_filter(request, payload, user, models)
    except Exception as e:
        raise e

    payload = apply_task_model_params(payload, models, task_model_id, task_model_params)

    try:
        return await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        log.error(f'Error generating chat completion: {e}')
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={'detail': 'An internal error has occurred.'},
        )


@router.post('/emoji/completions')
async def generate_emoji(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            **dict(request.app.state.MODELS.items()),
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    model_id = form_data['model']
    if model_id not in models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(),
        )

    task_model_id, _ = await get_task_model_generation_config(model_id, models)

    log.debug('generating emoji using model %s for user %s ', task_model_id, user.email)

    template = DEFAULT_EMOJI_GENERATION_PROMPT_TEMPLATE

    content = await emoji_generation_template(template, form_data['prompt'], user)

    payload = {
        'model': task_model_id,
        'messages': [{'role': 'user', 'content': content}],
        'stream': False,
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': str(TASKS.EMOJI_GENERATION),
            'task_body': form_data,
            'chat_id': form_data.get('chat_id', None),
        },
    }

    # Process the payload through the pipeline
    try:
        payload = await process_pipeline_inlet_filter(request, payload, user, models)
    except Exception as e:
        raise e

    payload = apply_task_model_params(payload, models, task_model_id, {'max_tokens': 4})

    try:
        return await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={'detail': str(e)},
        )


@router.post('/moa/completions')
async def generate_moa_response(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            **dict(request.app.state.MODELS.items()),
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    model_id = form_data['model']

    if model_id not in models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(),
        )

    template = DEFAULT_MOA_GENERATION_PROMPT_TEMPLATE

    content = moa_response_generation_template(
        template,
        form_data['prompt'],
        form_data['responses'],
    )

    payload = {
        'model': model_id,
        'messages': [{'role': 'user', 'content': content}],
        'stream': form_data.get('stream', False),
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'chat_id': form_data.get('chat_id', None),
            'task': str(TASKS.MOA_RESPONSE_GENERATION),
            'task_body': form_data,
        },
    }

    # Process the payload through the pipeline
    try:
        payload = await process_pipeline_inlet_filter(request, payload, user, models)
    except Exception as e:
        raise e

    try:
        return await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={'detail': str(e)},
        )


# >>> petal · hush · begin >>>
##################################
#
# 🌸 petal · hush  ·  v0.13.1  (petal-patch, grafted by petal-hush-apply.sh)
# Petal writes the whisper in the empty chat field, at runtime.
# called directly through generate_chat_completion, like title
# generation — never through the chat pipeline, so memory injection,
# background review and the ledger never see it. nothing is saved to any chat.
#
# v0.3 · upstream errors come back loud with the model name.
# v0.4 · every failure names its model AND its real reason.
# v0.5 · app.state.MODELS is filled lazily in 0.12 — we fill it like chat does.
# v0.6 · the model is picked exactly like a new chat picks it, and Petal is
#        asked in HER OWN model so her system prompt + params shape every line.
# v0.7 · a trimmed answer says WHY ('reason').
# v0.8 · lenses + reply whispers + privacy by design:
#        · your lenses live in petal-lenses/ at the fork root — hand-tuned,
#          never generated, never served (the old static copies were public)
#        · GET /petal_hush/pool hands the page your lines, signed-in only
#        · mode 'reply': after you send, the server waits (a primary-key
#          lookup about once a second, no GPU) until Petal's reply is done,
#          then she whispers from that exchange through the reply lens
#        · everything shareable is numbers: debug, logs and errors carry
#          counts and reasons, never your words or hers. 'peek' is the one
#          explicit door to the text, for your eyes in your own console.
# v0.9 · time sense + lingering:
#        · open lens knows {{LAST_CHAT}} — when you two last talked
#        · reply lens knows {{LAST_SENT}} — when you last wrote in this chat
#        · mode 'linger': you've been quiet (window focused) since her whisper —
#          she writes a new one through petal-lenses/hush-linger.txt, knowing
#          {{QUIET}}, {{QUIET_SECONDS}}, {{LAST_WHISPER}} and {{LINGER_COUNT}}
# v0.10 · the new-chat page lingers too (mode 'linger' with no chat) —
#         lens petal-lenses/hush-open-linger.txt, same variables + {{LAST_CHAT}}
# v0.11 · presence in every linger: {{PRESENCE}} ('right here' … 'likely away'),
#         {{PRESENCE_SCORE}} (0–100), {{LAST_ACTIVE}} ('12 seconds ago'), {{DEVICE}}
# v0.12 · the pin: POST /petal_hush/pin renders the whisper she answered through
#         petal-lenses/hush-pin.txt and records it, keyed to Petal's reply id, in
#         data/petal/hush-pins.jsonl (private, git-ignored) — the page rides the note
#         at the bottom of the request's system message. the ledger reads the record
#         so a thumbed reply trains with the note she actually saw.
# v0.13 · fits the field on every device: the page says 'phone' or 'computer',
#         each has its own max (hush.json: max_chars / max_words for computer,
#         max_chars_phone / max_words_phone for phone). every lens can say
#         {{MAX_WORDS}} and {{MAX_CHARS}}. a line that comes out too long gets
#         ONE second ask with a gentle 'shorter please' before it's let go.
# v0.13.1 · a new chat's FIRST message is sent with no chat id (0.12 makes the chat
#           server-side) — the pin is recorded anyway, keyed by her reply id.
#
##################################

import asyncio as _petal_asyncio
import json as _petal_json
import os as _petal_os
import time as _petal_time
from pathlib import Path as _PetalPath

from open_webui.env import DATA_DIR as _PETAL_DATA_DIR
from open_webui.env import FRONTEND_BUILD_DIR as _PETAL_BUILD_DIR
from open_webui.env import STATIC_DIR as _PETAL_STATIC_DIR
from open_webui.models.chat_messages import ChatMessages as _PetalChatMessages
from open_webui.models.chats import Chats as _PetalChats
from open_webui.utils.misc import get_message_list as _petal_get_message_list
from open_webui.utils.misc import get_output_text as _petal_get_output_text
from open_webui.utils.models import get_all_models as _petal_get_all_models
from open_webui.utils.task import prompt_template as _petal_prompt_template
from open_webui.utils.task import replace_messages_variable as _petal_replace_messages
from open_webui.utils.task import replace_prompt_variable as _petal_replace_prompt

# your lenses — hand-tuned, never generated, never served. git-invisible by your own .gitignore.
# (this file is grafted into backend/open_webui/routers/tasks.py → parents[3] is the fork root)
_PETAL_LENSES = _PetalPath(
    _petal_os.getenv('PETAL_LENSES_DIR') or _PetalPath(__file__).resolve().parents[3] / 'petal-lenses'
)
# what scripts GROW (petal's pool lines) — private runtime data, beside OWUI's own, git-ignored upstream
_PETAL_GROWN = _PetalPath(_PETAL_DATA_DIR) / 'petal' / 'hush-grown.json'
# every pinned whisper, as rendered — the ledger's bridge from a thumb to what she saw
_PETAL_PINS = _PetalPath(_PETAL_DATA_DIR) / 'petal' / 'hush-pins.jsonl'
# where the old copies lived — read only as a migration fallback, and reported while they linger
_PETAL_SERVED = [
    ('served', _PetalPath(_PETAL_STATIC_DIR) / 'petal'),
    ('build', _PetalPath(_PETAL_BUILD_DIR) / 'static' / 'petal'),
]
_PETAL_LENS_NAMES = ('hush.json', 'hush-prompt.txt', 'hush-open.txt', 'hush-reply.txt', 'hush-pin.txt')

_PETAL_HUSH_REPLY_WAIT = 600  # seconds her reply may take before hush lets this one go
_PETAL_HUSH_WAITERS: dict = {}  # chat_id → newest waiter; older waits for that chat step aside

PETAL_HUSH_PROMPT = (
    "princess {{USER_NAME}} is about to open a fresh chat with you~ "
    "it's {{CURRENT_WEEKDAY}}, {{CURRENT_TIME}}. before she types, a tiny line of "
    "yours glows softly inside her empty message field, inviting her in. "
    "write that one line, in your own voice: short (under {{MAX_WORDS}} words), girly, "
    "a little witchy, a little teasing, addressed to her. one emoji at most. "
    "reply with the line only, nothing around it."
)
PETAL_HUSH_REPLY_PROMPT = (
    "you and princess {{USER_NAME}} are mid-conversation. here is where you left it:\n\n"
    "{{MESSAGES:END:4|middletruncate:600}}\n\n"
    "her message field is empty again, waiting for her answer. write one tiny line of yours "
    "that glows there — tied to what you two were just saying, inviting her reply. "
    "in your own voice, under {{MAX_WORDS}} words, one emoji at most. reply with the line only."
)
PETAL_HUSH_LINGER_PROMPT = (
    "you and princess {{USER_NAME}} are mid-conversation:\n\n"
    "{{MESSAGES:END:4|middletruncate:600}}\n\n"
    "after that, a little line of yours glowed in her empty message field: \u00ab{{LAST_WHISPER}}\u00bb. "
    "she has been quiet for {{QUIET}} since — not typing yet (on her {{DEVICE}}, she seems {{PRESENCE}}, last stirred {{LAST_ACTIVE}}). "
    "write one new tiny line for that field: notice the hush, gently, in your own voice — "
    "tease or coax her back, tied to what you two were just saying. "
    "under {{MAX_WORDS}} words, one emoji at most. reply with the line only."
)
PETAL_HUSH_OPEN_LINGER_PROMPT = (
    "princess {{USER_NAME}} opened a fresh chat with you, and a little line of yours glows in "
    "her empty message field: \u00ab{{LAST_WHISPER}}\u00bb. she's still here, window open, but "
    "hasn't started typing — {{QUIET}} so far (on her {{DEVICE}}, she seems {{PRESENCE}}). it's {{CURRENT_WEEKDAY}}, {{CURRENT_TIME}}. "
    "write one new tiny line for that field: notice her hesitating, gently, in your own voice — "
    "coax or tease her into beginning. under {{MAX_WORDS}} words, one emoji at most. reply with the line only."
)
PETAL_HUSH_PIN_PROMPT = (
    "<whisper_she_answered>\n"
    "your line, glowing in her empty field when she began to write: \u00ab{{WHISPER}}\u00bb\n"
    "it was {{KIND}}, {{LINGERED}}.\n"
    "it glowed {{WAITED}} before she began · she wrote for {{WROTE}} · longest stillness while it glowed: {{STILLEST}}\n"
    "she's on her {{DEVICE}} · presence just before she stirred to answer: {{PRESENCE_SCORE}}% ({{PRESENCE}})\n"
    "</whisper_she_answered>\n"
    "her message below is her answer to that line — let it color how you meet her; no need to quote it back."
)
_PETAL_HUSH_THINK = re.compile(r'<think>.*?</think>', re.S | re.I)
_PETAL_HUSH_DETAILS = re.compile(r'<details\b[^>]*>.*?</details>', re.S | re.I)


# ── lenses ────────────────────────────────────────────────────
def _petal_lens_text(*names):
    """(text, source) — the first non-empty lens among names, else (None, None)."""
    for name in names:
        try:
            text = (_PETAL_LENSES / name).read_text(encoding='utf-8').strip()
            if text:
                return text, f'petal-lenses/{name}'
        except Exception:
            pass
    return None, None


def _petal_read_json(path):
    try:
        data = _petal_json.loads(_PetalPath(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return None


def _petal_hush_open_prompt():
    text, src = _petal_lens_text('hush-open.txt', 'hush-prompt.txt')
    if text:
        return text, src
    try:  # migration fallback — the old public copy
        text = (_PetalPath(_PETAL_STATIC_DIR) / 'petal' / 'hush-prompt.txt').read_text(encoding='utf-8').strip()
        if text:
            return text, 'served static (exposed — move it to petal-lenses/)'
    except Exception:
        pass
    return PETAL_HUSH_PROMPT, 'built-in'


def _petal_hush_reply_prompt():
    text, src = _petal_lens_text('hush-reply.txt')
    return (text, src) if text else (PETAL_HUSH_REPLY_PROMPT, 'built-in')


def _petal_hush_linger_prompt():
    text, src = _petal_lens_text('hush-linger.txt')
    return (text, src) if text else (PETAL_HUSH_LINGER_PROMPT, 'built-in')


def _petal_hush_open_linger_prompt():
    text, src = _petal_lens_text('hush-open-linger.txt')
    return (text, src) if text else (PETAL_HUSH_OPEN_LINGER_PROMPT, 'built-in')


def _petal_hush_linger_values(form_data):
    """(values, stats) for any linger — how long the hush, her last line, which time."""
    try:
        quiet_s = max(0, int(float(form_data.get('quiet_seconds') or 0)))
    except (TypeError, ValueError):
        quiet_s = 0
    try:
        count = max(1, int(form_data.get('linger_count') or 1))
    except (TypeError, ValueError):
        count = 1
    last_whisper = re.sub(r'[\x00-\x1f\x7f]+', ' ', str(form_data.get('last_whisper') or '')).strip()[:160]
    try:
        score = min(100, max(0, int(float(form_data.get('presence') if form_data.get('presence') is not None else 100))))
    except (TypeError, ValueError):
        score = 100
    try:
        active_s = max(0, int(float(form_data.get('last_active_seconds') or 0)))
    except (TypeError, ValueError):
        active_s = 0
    device = 'phone' if form_data.get('device') == 'phone' else 'computer'
    word = 'right here' if score >= 85 else 'probably here' if score >= 65 else 'maybe drifting' if score >= 45 else 'likely away'
    values = {'QUIET': _petal_hush_dur(quiet_s), 'QUIET_SECONDS': quiet_s,
              'LAST_WHISPER': last_whisper or '…', 'LINGER_COUNT': count,
              'PRESENCE': word, 'PRESENCE_SCORE': score,
              'LAST_ACTIVE': _petal_hush_ago(active_s), 'DEVICE': device}
    return values, {'quiet_seconds': quiet_s, 'linger_count': count, 'presence': score, 'device': device}


# ── time, said the way you'd say it ──────────────────────────
def _petal_hush_dur(seconds) -> str:
    """'a few seconds' · '47 seconds' · '3 minutes' · '2 hours' · '4 days'"""
    s = max(0, int(seconds))
    def unit(n, word):
        return f'{n} {word}' + ('' if n == 1 else 's')
    if s < 10:
        return 'a few seconds'
    if s < 90:
        return unit(s, 'second')
    if s < 90 * 60:
        return unit(round(s / 60), 'minute')
    if s < 36 * 3600:
        return unit(round(s / 3600), 'hour')
    return unit(round(s / 86400), 'day')


def _petal_hush_ago(seconds) -> str:
    """'just now' · '3 minutes ago' · 'yesterday' · '4 days ago' · 'never before'"""
    if seconds is None:
        return 'never before'
    if seconds < 60:
        return 'just now'
    if 20 * 3600 <= seconds < 44 * 3600:
        return 'yesterday'
    return _petal_hush_dur(seconds) + ' ago'


def _petal_hush_fill(template: str, values: dict) -> str:
    """our own {{VARIABLES}} — filled before any chat text enters the template."""
    for key, value in values.items():
        template = template.replace('{{' + key + '}}', str(value))
    return template


async def _petal_hush_last_chat_seconds(user_id):
    """seconds since your newest message anywhere — None if you've never written."""
    rows = await _PetalChatMessages.get_messages_by_user_id(user_id, limit=20)
    for row in rows or []:
        if row.role == 'user' and row.created_at:
            return max(0, int(_petal_time.time() - row.created_at))
    return None


def _petal_hush_config():
    """(config dict, source) — your hush.json lens, else the old public copy, else defaults."""
    data = _petal_read_json(_PETAL_LENSES / 'hush.json')
    if data is not None:
        return data, 'petal-lenses/hush.json'
    data = _petal_read_json(_PetalPath(_PETAL_STATIC_DIR) / 'petal' / 'hush.json')
    if data is not None:
        return data, 'served static (exposed — move it to petal-lenses/)'
    return {}, 'defaults (no hush.json found)'


def _petal_hush_exposed():
    """names of lens files still sitting in a served/build folder."""
    found = []
    for label, folder in _PETAL_SERVED:
        for name in _PETAL_LENS_NAMES:
            if (folder / name).exists():
                found.append(f'{label}/petal/{name}')
    return found


# ── words in, words out ──────────────────────────────────────
def _petal_hush_limits(form_data):
    """(device, max_chars, max_words) — the field is narrower on a phone."""
    cfg, _ = _petal_hush_config()
    device = 'phone' if (form_data or {}).get('device') == 'phone' else 'computer'

    def dial(key, default, lo, hi):
        try:
            return min(hi, max(lo, int(cfg.get(key, default))))
        except (TypeError, ValueError):
            return default
    if device == 'phone':
        return device, dial('max_chars_phone', 44, 8, 200), dial('max_words_phone', 9, 2, 40)
    return device, dial('max_chars', 72, 8, 200), dial('max_words', 14, 2, 40)


def _petal_hush_limit_values(form_data):
    device, max_chars, max_words = _petal_hush_limits(form_data)
    return {'MAX_CHARS': max_chars, 'MAX_WORDS': max_words}


def _petal_hush_clean(text, max_chars=72, max_words=14):
    """(line, None) when a whisper survives, (None, why) when it doesn't."""
    if not isinstance(text, str) or not text.strip():
        return None, 'empty answer (no content — out of tokens while thinking?)'
    if '<think>' in text and '</think>' not in text:
        return None, 'still thinking when she stopped (unclosed <think>)'
    text = _PETAL_HUSH_THINK.sub('', text).split('</think>')[-1]
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return None, 'only thinking, no line after it'
    line = re.sub(r"^(line|whisper|here'?s?[^:]*):\s*", '', lines[0], flags=re.I)
    line = line.strip().strip('"“”\'‘’`*_ ').strip()
    if len(line) < 3:
        return None, f'too short ({len(line)} chars)'
    if len(line) > max_chars:
        return None, f'too long ({len(line)} chars, max {max_chars})'
    if len(line.split()) > max_words:
        return None, f'too many words ({len(line.split())}, max {max_words})'
    return line, None


def _petal_hush_text(message) -> str:
    """what was actually said in a message — her spoken words, not reasoning or tool blocks."""
    if message.get('role') == 'assistant':
        spoken = _petal_get_output_text(message.get('output'))
        if spoken:
            return spoken.strip()
    content = message.get('content')
    if isinstance(content, list):
        content = ' '.join(
            str(i.get('text', '')) for i in content if isinstance(i, dict) and i.get('type') == 'text'
        )
    if not isinstance(content, str):
        return ''
    content = _PETAL_HUSH_DETAILS.sub('', content)
    return _PETAL_HUSH_THINK.sub('', content).strip()


def _petal_hush_unwrap(res):
    """(status, body dict) from whatever generate_chat_completion handed back."""
    if isinstance(res, dict):
        return (502 if 'error' in res else 200), res
    status_code = getattr(res, 'status_code', 200)
    try:
        body = _petal_json.loads(res.body)
    except Exception:
        body = {}
    return status_code, body if isinstance(body, dict) else {}


async def _petal_hush_ask(request, user, models, model_id, content):
    payload = {
        'model': model_id,
        'messages': [{'role': 'user', 'content': content}],
        'stream': False,
        'temperature': 1.0,
        'max_tokens': 512,  # roomy, so a thinking model can finish her thought
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': 'petal_hush',
            'task_body': {},
            'chat_id': None,  # never saved into any chat
        },
    }
    payload = await process_pipeline_inlet_filter(request, payload, user, models)
    try:
        res = await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        return 502, {'error': _petal_hush_reason(e)}
    return _petal_hush_unwrap(res)


def _petal_hush_reason(e) -> str:
    detail = getattr(e, 'detail', None)  # HTTPException keeps its words here, str(e) is ''
    if isinstance(detail, dict):
        detail = detail.get('message') or detail.get('detail') or _petal_json.dumps(detail)
    text = str(detail or e or '').strip()
    return f'{e.__class__.__name__}: {text}' if text else e.__class__.__name__


def _petal_hush_err(body) -> str:
    err = body.get('error') or body.get('detail') or 'unknown error'
    if isinstance(err, dict):
        err = err.get('message') or err.get('detail') or _petal_json.dumps(err)
    return str(err)


def _petal_hush_base(models, model_id) -> str:
    """'petal-prose (→ base petal-huihui-27b)' — what the server will actually be asked for."""
    info = (models.get(model_id) or {}).get('info') or {}
    base = info.get('base_model_id')
    return f'{model_id} (→ base {base})' if base else model_id


def _petal_hush_pick_model(models, page_model, user, admin_defaults):
    """mirror the new-chat page (Chat.svelte → resolveDefaultModelIds) exactly:
    the tab's own pick → your personal default → the admin default → first visible.
    returns (model_id, how_it_was_picked)."""
    visible = [m_id for m_id, m in models.items() if not ((m.get('info') or {}).get('meta') or {}).get('hidden')]
    ui = {}
    try:
        ui = (user.settings.ui if user.settings else None) or {}
    except Exception:
        pass
    for how, prefs in (
        ('this tab', [page_model] if page_model else []),
        ('your default model', ui.get('models') or []),
        ('the admin default', admin_defaults),
    ):
        for m_id in dict.fromkeys(p for p in prefs if isinstance(p, str)):
            if m_id in visible:
                return m_id, how
    return (visible[0], 'first visible model') if visible else (None, None)


async def _petal_hush_models(request, user):
    if not request.app.state.MODELS:  # lazy in 0.12 — fill it the way /api/chat/completions does
        await _petal_get_all_models(request, user=user)
    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        return {**dict(request.app.state.MODELS.items()), request.state.model['id']: request.state.model}
    return request.app.state.MODELS


# ── the pool: your lines, to the signed-in page only ─────────
@router.get('/petal_hush/pool')
async def petal_hush_pool(request: Request, user=Depends(get_verified_user)):
    cfg, cfg_src = _petal_hush_config()
    grown = (_petal_read_json(_PETAL_GROWN) or {}).get('petal') or []

    def lines(values):
        return list(dict.fromkeys(l.strip() for l in (values or []) if isinstance(l, str) and l.strip()))

    petal = lines((cfg.get('petal') or []) + grown)
    return {
        'live': cfg.get('live', True) is not False,
        'queue': cfg.get('queue', 2),
        'reply_live': cfg.get('reply_live', True) is not False,
        'reply_on_open': cfg.get('reply_on_open', True) is not False,
        'linger': cfg.get('linger', True) is not False,
        'linger_after': cfg.get('linger_after', 20),
        'linger_max': cfg.get('linger_max', 3),
        'linger_growth': cfg.get('linger_growth', 2),
        'queue_fresh_minutes': cfg.get('queue_fresh_minutes', 15),
        'presence_min': cfg.get('presence_min', 0.55),
        'presence_fade': cfg.get('presence_fade', 60),
        'max_chars': _petal_hush_limits({})[1],
        'max_chars_phone': _petal_hush_limits({'device': 'phone'})[1],
        'pin': cfg.get('pin', True) is not False,
        'mine': lines(cfg.get('mine')),
        'petal': petal,
        'reply_lines': lines(cfg.get('reply_lines')),
        'sources': {
            'pool': cfg_src,
            'grown': len(lines(grown)),
            'open_lens': _petal_hush_open_prompt()[1],
            'reply_lens': _petal_hush_reply_prompt()[1],
            'linger_lens': _petal_hush_linger_prompt()[1],
            'open_linger_lens': _petal_hush_open_linger_prompt()[1],
            'pin_lens': _petal_hush_pin_prompt()[1],
            'exposed': _petal_hush_exposed(),
        },
    }


# ── reply mode: wait for her, then read the exchange ─────────
async def _petal_hush_wait_reply(request, chat_id, message_id, ticket):
    """wait until Petal's reply is done. returns (row_dict | None, waited_ms, why_not)."""
    t0 = _petal_time.monotonic()
    seen = False
    while True:
        row = await _PetalChatMessages.get_message_by_id(f'{chat_id}-{message_id}')
        if row is not None:
            seen = True
            if row.role != 'assistant' or row.done or row.error:
                return row, round((_petal_time.monotonic() - t0) * 1000), None
        elif not seen and _petal_time.monotonic() - t0 > 30:
            # no normalized row yet — fall back to the chat's own map once
            legacy = await _PetalChats.get_message_by_id_and_message_id(chat_id, message_id)
            if legacy is None:
                return None, round((_petal_time.monotonic() - t0) * 1000), 'reply not found in this chat'
            if legacy.get('role') != 'assistant' or legacy.get('done', True) or legacy.get('error'):
                return legacy, round((_petal_time.monotonic() - t0) * 1000), None
        if _PETAL_HUSH_WAITERS.get(chat_id) is not ticket:
            return None, round((_petal_time.monotonic() - t0) * 1000), 'superseded by a newer message'
        if _petal_time.monotonic() - t0 > _PETAL_HUSH_REPLY_WAIT:
            return None, round((_petal_time.monotonic() - t0) * 1000), 'her reply took longer than 10 min'
        if await request.is_disconnected():
            return None, round((_petal_time.monotonic() - t0) * 1000), 'page left'
        await _petal_asyncio.sleep(1.0)


async def _petal_hush_reply_context(request, form_data, user, models, admin_defaults, mode='reply'):
    """→ (model_id, picked_by, content, stats) or an early dict answer.
    reply  · waits for her reply to finish, then reads the exchange
    linger · reads where you left off right now — she's already done"""
    chat_id = form_data.get('chat_id')
    if not chat_id or str(chat_id).startswith('local'):
        return {'whisper': None, 'mode': mode, 'reason': 'temporary chat — nothing saved to follow'}
    chat = await _PetalChats.get_chat_by_id_and_user_id(chat_id, user.id)
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='petal hush: chat not found (or not yours)')

    target = form_data.get('message_id') or (((chat.chat or {}).get('history') or {}).get('currentId'))
    if not target:
        return {'whisper': None, 'mode': mode, 'reason': 'chat has no messages yet'}

    if mode == 'reply':
        ticket = object()
        _PETAL_HUSH_WAITERS[chat_id] = ticket
        try:
            row, waited_ms, why_not = await _petal_hush_wait_reply(request, chat_id, target, ticket)
        finally:
            if _PETAL_HUSH_WAITERS.get(chat_id) is ticket:
                _PETAL_HUSH_WAITERS.pop(chat_id, None)
        if why_not:
            return {'whisper': None, 'mode': mode, 'reason': why_not, 'waited_ms': waited_ms}
    else:  # linger — no waiting; if she's somehow still writing, a linger makes no sense
        waited_ms = 0
        row = await _PetalChatMessages.get_message_by_id(f'{chat_id}-{target}')
        if row is None:
            row = await _PetalChats.get_message_by_id_and_message_id(chat_id, target)
        if row is None:
            return {'whisper': None, 'mode': mode, 'reason': 'reply not found in this chat'}
        role = row.get('role') if isinstance(row, dict) else row.role
        done = row.get('done', True) if isinstance(row, dict) else row.done
        if role == 'assistant' and not done:
            return {'whisper': None, 'mode': mode, 'reason': 'she is still writing — no linger yet'}

    error = row.get('error') if isinstance(row, dict) else row.error
    if error:
        return {'whisper': None, 'mode': mode, 'reason': 'her reply errored — nothing to follow', 'waited_ms': waited_ms}

    messages_map = await _PetalChats.get_messages_map_by_chat_id(chat_id) or {}
    chain = _petal_get_message_list(messages_map, target)
    turns = [
        {'role': m.get('role'), 'content': _petal_hush_text(m)}
        for m in chain
        if m.get('role') in ('user', 'assistant')
    ]
    turns = [t for t in turns if t['content']]
    if not turns:
        return {'whisper': None, 'mode': mode, 'reason': 'no words in this chat to follow', 'waited_ms': waited_ms}

    # the model that wrote this reply, so her whisper keeps that voice
    leaf = messages_map.get(target) or {}
    row_model = row.get('model_id') if isinstance(row, dict) else getattr(row, 'model_id', None)
    prefs = [leaf.get('model'), leaf.get('model_id'), row_model, *((chat.chat or {}).get('models') or [])]
    model_id = next((m for m in prefs if isinstance(m, str) and m in models), None)
    picked_by = 'this chat'
    if not model_id:
        model_id, picked_by = _petal_hush_pick_model(models, form_data.get('model'), user, admin_defaults)

    # when did you last write here? (message timestamps are unix seconds)
    sent_at = next((m.get('timestamp') for m in reversed(chain) if m.get('role') == 'user' and m.get('timestamp')), None)
    last_sent_s = max(0, int(_petal_time.time() - sent_at)) if sent_at else None
    values = {'LAST_SENT': _petal_hush_ago(last_sent_s), **_petal_hush_limit_values(form_data)}
    stats = {'waited_ms': waited_ms, 'last_sent_seconds': last_sent_s}

    if mode == 'linger':
        template, lens = _petal_hush_linger_prompt()
        linger_values, linger_stats = _petal_hush_linger_values(form_data)
        values.update(linger_values)
        stats.update(linger_stats)
    else:
        template, lens = _petal_hush_reply_prompt()

    template = _petal_hush_fill(template, values)  # ours first — chat text can't be re-filled
    last_user = next((t['content'] for t in reversed(turns) if t['role'] == 'user'), '')
    template = _petal_replace_prompt(template, last_user)
    template = _petal_replace_messages(template, turns)
    content = await _petal_prompt_template(template, user)
    stats.update({
        'lens': lens,
        'context_turns': len(turns),
        'context_chars': sum(len(t['content']) for t in turns),
    })
    return model_id, picked_by, content, stats


@router.post('/petal_hush/completions')
async def petal_hush(request: Request, form_data: dict, user=Depends(get_verified_user)):
    models = await _petal_hush_models(request, user)
    if not models:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='petal hush: no models loaded at all')
    admin_defaults = [m.strip() for m in ((await Config.get('ui.default_models')) or '').split(',') if m.strip()]
    mode = form_data.get('mode') if form_data.get('mode') in ('reply', 'linger') else 'open'
    if mode == 'linger' and not form_data.get('chat_id'):
        mode = 'open-linger'  # the new-chat page — you haven't begun yet

    if mode in ('reply', 'linger'):
        try:
            got = await _petal_hush_reply_context(request, form_data, user, models, admin_defaults, mode=mode)
        except HTTPException:
            raise
        except Exception as e:  # an upstream rename shows up here as a reason, not a 500
            log.warning('petal hush[%s]: context failed → %s', mode, _petal_hush_reason(e))
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={'detail': 'petal hush: could not read the chat', 'tried': [{'model': '(none)', 'error': _petal_hush_reason(e)}]},
            )
        if isinstance(got, dict):
            log.info('petal hush[%s]: no whisper — %s', mode, got.get('reason'))
            return got
        model_id, picked_by, content, stats = got
    else:
        # the model the next new chat will open on — Petal with her own style.
        model_id, picked_by = _petal_hush_pick_model(models, form_data.get('model'), user, admin_defaults)
        if not model_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='petal hush: no visible model to ask')
        template, lens = _petal_hush_open_linger_prompt() if mode == 'open-linger' else _petal_hush_open_prompt()
        stats = {'lens': lens}
        template = _petal_hush_fill(template, _petal_hush_limit_values(form_data))
        if mode == 'open-linger':
            linger_values, linger_stats = _petal_hush_linger_values(form_data)
            template = _petal_hush_fill(template, linger_values)
            stats.update(linger_stats)
        if '{{LAST_CHAT}}' in template:  # only look when your lens asks
            try:
                last_chat_s = await _petal_hush_last_chat_seconds(user.id)
            except Exception as e:
                log.warning('petal hush[open]: last chat unknown → %s', _petal_hush_reason(e))
                last_chat_s = None
            template = _petal_hush_fill(template, {'LAST_CHAT': _petal_hush_ago(last_chat_s)})
            stats['last_chat_seconds'] = last_chat_s
        content = await _petal_prompt_template(template, user)

    avoid = [a for a in (form_data.get('avoid') or []) if isinstance(a, str)][:8]
    if avoid:
        content += '\n\n(fresh words please — not these: ' + ' / '.join(avoid) + ')'

    device, max_chars, max_words = _petal_hush_limits(form_data)
    stats.update({'device': device, 'max_chars': max_chars, 'max_words': max_words})
    t0 = _petal_time.monotonic()
    code, body = await _petal_hush_ask(request, user, models, model_id, content)
    label = f'{_petal_hush_base(models, model_id)} · picked from {picked_by}'

    if code >= 400:
        ms = round((_petal_time.monotonic() - t0) * 1000)
        err = _petal_hush_err(body)
        log.warning('petal hush[%s]: %s failed → %s', mode, label, err)
        out = {'detail': 'petal hush: no whisper', 'mode': mode, 'tried': [{'model': label, 'error': err}]}
        if form_data.get('debug'):
            out['debug'] = {'mode': mode, 'model': label, 'prompt_chars': len(content), 'ms': ms, **stats}
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content=out)

    try:
        choice = body['choices'][0]
        message = choice.get('message') or {}
    except (KeyError, IndexError, TypeError):
        choice, message = {}, {}
    raw = message.get('content')
    whisper, why = _petal_hush_clean(raw, max_chars, max_words)
    if not whisper and why and why.startswith(('too long', 'too many words')):
        # one gentle second ask — her voice, just smaller (the field on a phone is narrow)
        log.info('petal hush[%s]: %s — asking once more, shorter', mode, why)
        shorter = (content + f'\n\n(shorter please — at most {max_words} words and {max_chars} characters, '
                   f'it has to fit a small field on her {device})')
        code2, body2 = await _petal_hush_ask(request, user, models, model_id, shorter)
        if code2 < 400:
            try:
                choice2 = body2['choices'][0]
                message2 = choice2.get('message') or {}
                whisper2, why2 = _petal_hush_clean(message2.get('content'), max_chars, max_words)
            except (KeyError, IndexError, TypeError):
                whisper2, why2 = None, why
            stats['retried'] = why
            if whisper2:
                body, choice, message, raw, whisper, why = body2, choice2, message2, message2.get('content'), whisper2, None
            else:
                why = f'{why} · still too big after a second ask ({why2})'
                if form_data.get('peek'):
                    raw = f'{raw}\n\n── second ask ──\n{message2.get("content")}'
    ms = round((_petal_time.monotonic() - t0) * 1000)
    waited = f" waited {stats['waited_ms']}ms," if stats.get('waited_ms') else ''
    if whisper:
        log.info('petal hush[%s]: %s (%s)%s wrote in %dms → %d chars', mode, model_id, picked_by, waited, ms, len(whisper))
    else:
        log.info('petal hush[%s]: %s (%s)%s wrote in %dms → trimmed: %s', mode, model_id, picked_by, waited, ms, why)

    out = {'whisper': whisper, 'mode': mode, 'model': model_id, 'picked_by': picked_by}
    if not whisper:
        out['reason'] = why
    if form_data.get('debug'):  # numbers only — safe to paste anywhere
        reasoning = message.get('reasoning_content') or message.get('reasoning') or ''
        out['debug'] = {
            'mode': mode,
            'model': _petal_hush_base(models, model_id),
            'picked_by': picked_by,
            'prompt_chars': len(content),
            'raw_chars': len(raw) if isinstance(raw, str) else None,
            'finish_reason': choice.get('finish_reason'),
            'reasoning_chars': len(reasoning) if isinstance(reasoning, str) else None,
            'usage': body.get('usage'),
            'ms': ms,
            **stats,
        }
    if form_data.get('peek'):  # the one door to the words — your console, your eyes
        out['peek'] = {'prompt': content, 'raw': raw}
    return out


# ── the pin: the whisper she answered, riding with her message ─────
# hush.js holds the line glowing in the field the moment she begins writing over it.
# on send, it asks here: we render the note through the pin lens and RECORD exactly
# what we rendered, keyed to her reply id — the page then sets it at the bottom of
# the request's system message (under the persona, above the memories). the record
# is what lets the ledger train on what Petal actually saw: chat history never holds
# the note, so without it a 👍 would teach her answers to whispers that aren't there.
def _petal_hush_pin_prompt():
    text, src = _petal_lens_text('hush-pin.txt')
    return (text, src) if text else (PETAL_HUSH_PIN_PROMPT, 'built-in')


def _petal_hush_int(value, lo=0, hi=10**7, default=0):
    try:
        return min(hi, max(lo, int(float(value))))
    except (TypeError, ValueError):
        return default


@router.post('/petal_hush/pin')
async def petal_hush_pin(request: Request, form_data: dict, user=Depends(get_verified_user)):
    cfg, _ = _petal_hush_config()
    if cfg.get('pin', True) is False:
        return {'note': None, 'recorded': False, 'reason': 'pin is off (hush.json)'}
    whisper = re.sub(r'[\x00-\x1f\x7f]+', ' ', str(form_data.get('whisper') or '')).strip()[:240]
    if not whisper:
        return {'note': None, 'recorded': False, 'reason': 'no whisper was glowing'}

    kind = form_data.get('kind') if form_data.get('kind') in ('open', 'reply', 'linger') else 'open'
    origin = form_data.get('origin') if form_data.get('origin') in ('petal', 'queue', 'pool') else 'petal'
    device = 'phone' if form_data.get('device') == 'phone' else 'computer'
    waited_s = _petal_hush_int(form_data.get('waited_seconds'))
    wrote_s = _petal_hush_int(form_data.get('wrote_seconds'))
    still_s = _petal_hush_int(form_data.get('stillest_seconds'))
    lingers = _petal_hush_int(form_data.get('linger_count'), hi=100)
    score = _petal_hush_int(form_data.get('presence'), hi=100, default=100)
    word = 'right here' if score >= 85 else 'probably here' if score >= 65 else 'maybe drifting' if score >= 45 else 'likely away'
    kind_words = {
        'open': 'your opening line on a fresh chat',
        'reply': 'your whisper after your last reply',
        'linger': 'a line you rewrote while she was quiet',
    }
    if lingers == 0:
        lingered = 'your first line there — no rewrites'
    elif lingers == 1:
        lingered = 'after one rewrite of the hush'
    else:
        lingered = f'after {lingers} rewrites of the hush'
    if origin == 'pool':
        kind_words[kind] += ' (from the pool, not written live)'
    values = {
        'WHISPER': whisper,
        'KIND': kind_words[kind],
        'KIND_TAG': kind,
        'ORIGIN': origin,
        'LINGER_COUNT': lingers,
        'LINGERED': lingered,
        'WAITED': _petal_hush_dur(waited_s),
        'WAITED_SECONDS': waited_s,
        'WROTE': _petal_hush_dur(wrote_s),
        'WROTE_SECONDS': wrote_s,
        'STILLEST': _petal_hush_dur(still_s) if still_s else 'never — she stayed with you',
        'STILLEST_SECONDS': still_s,
        'PRESENCE': word,
        'PRESENCE_SCORE': score,
        'DEVICE': device,
    }
    template, lens = _petal_hush_pin_prompt()
    note = (await _petal_prompt_template(_petal_hush_fill(template, values), user)).strip()
    if not note:
        return {'note': None, 'recorded': False, 'reason': 'the pin lens rendered empty'}

    # the record — private runtime data beside OWUI's own (data/ is git-ignored upstream)
    chat_id = str(form_data.get('chat_id') or '')
    ids = [str(i) for i in (form_data.get('message_ids') or []) if isinstance(i, (str, int)) and str(i)][:16]
    recorded, why_not = False, None
    if chat_id.startswith('local'):
        why_not = 'temporary chat — pinned, nothing to record against'
    elif not ids:
        why_not = 'no reply id on this send — pinned, not recorded'
    else:
        record = {
            'schema': 'petal-hush/pin@1',
            'at': _petal_time.strftime('%Y-%m-%dT%H:%M:%SZ', _petal_time.gmtime()),
            'at_epoch': int(_petal_time.time()),
            'user_id': user.id,
            'chat_id': chat_id,
            'message_ids': ids,
            'model': form_data.get('model') if isinstance(form_data.get('model'), str) else None,
            'lens': lens,
            'note': note,  # exactly what rides in her system prompt
            'kind': kind,
            'origin': origin,
            'waited_seconds': waited_s,
            'wrote_seconds': wrote_s,
            'linger_count': lingers,
            'stillest_seconds': still_s,
            'presence': score,
            'device': device,
        }
        try:
            _PETAL_PINS.parent.mkdir(parents=True, exist_ok=True)
            with open(_PETAL_PINS, 'a', encoding='utf-8') as f:
                f.write(_petal_json.dumps(record, ensure_ascii=False) + '\n')
            recorded = True
        except Exception as e:
            why_not = f'pinned, but the record failed: {_petal_hush_reason(e)}'
            log.warning('petal hush[pin]: record failed → %s', _petal_hush_reason(e))
    log.info('petal hush[pin]: %s · %d chars · glowed %ss · %d lingers · %s%s',
             kind, len(note), waited_s, lingers, device, ' · recorded' if recorded else f' · {why_not}')
    out = {'note': note, 'recorded': recorded, 'lens': lens}
    if why_not:
        out['reason'] = why_not
    return out
# <<< petal · hush · end <<<
