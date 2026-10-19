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
# 🌸 petal · hush  ·  v0.7  (petal-patch, grafted by petal-hush-apply.sh)
# Petal writes the whisper in the empty chat field, at runtime.
# called directly through generate_chat_completion, like title
# generation — never through the chat pipeline, so memory injection, background review and the
# ledger never see it. nothing is saved to any chat.
#
# v0.3 · model resolution now mirrors titles exactly
#        (chat model → task model, local OR external),
#        pipeline inlet filters run like they do for titles,
#        upstream errors come back loud with the model name,
#        and a stale task model falls back to the chat's own.
# v0.4 · every failure names its model AND its real reason
#        (HTTPException details were being swallowed), and the
#        chat model is resolved to its base for the log.
# v0.5 · app.state.MODELS is filled lazily in 0.12 — chat fills
#        it, titles ride after a chat, but hush fires on page
#        load into an empty dict. we now fill it like chat does.
# v0.6 · the model is picked exactly like a new chat picks it
#        (tab → your default → admin default → first visible),
#        and Petal is asked in HER OWN model — no task-model
#        swap — so her system prompt + params shape every line.
# v0.7 · a trimmed answer says WHY ('reason'), and the page's
#        debug mode gets what the server saw: the prompt sent,
#        her raw words, finish_reason, how much she reasoned.
#
##################################

import json as _petal_json
import time as _petal_time

from open_webui.env import STATIC_DIR as _PETAL_STATIC_DIR
from open_webui.utils.models import get_all_models as _petal_get_all_models
from open_webui.utils.task import prompt_template as _petal_prompt_template

PETAL_HUSH_PROMPT = (
    "princess {{USER_NAME}} is about to open a fresh chat with you~ "
    "it's {{CURRENT_WEEKDAY}}, {{CURRENT_TIME}}. before she types, a tiny line of "
    "yours glows softly inside her empty message field, inviting her in. "
    "write that one line, in your own voice: short (under ten words), girly, "
    "a little witchy, a little teasing, addressed to her. one emoji at most. "
    "reply with the line only, nothing around it."
)
_PETAL_HUSH_THINK = re.compile(r'<think>.*?</think>', re.S | re.I)


def _petal_hush_prompt() -> str:
    """static/petal/hush-prompt.txt wins if present — edit it live, no restart."""
    try:
        text = (_PETAL_STATIC_DIR / 'petal' / 'hush-prompt.txt').read_text(encoding='utf-8').strip()
        if text:
            return text
    except Exception:
        pass
    return PETAL_HUSH_PROMPT


def _petal_hush_clean(text):
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
    if len(line) > 72:
        return None, f'too long ({len(line)} chars, max 72)'
    if len(line.split()) > 14:
        return None, f'too many words ({len(line.split())}, max 14)'
    return line, None


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
            'chat_id': None,
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
    """'petal-prose (→ base petal-omni)' — what the server will actually be asked for."""
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


@router.post('/petal_hush/completions')
async def petal_hush(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if not request.app.state.MODELS:  # lazy in 0.12 — fill it the way /api/chat/completions does
        await _petal_get_all_models(request, user=user)
    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {**dict(request.app.state.MODELS.items()), request.state.model['id']: request.state.model}
    else:
        models = request.app.state.MODELS
    if not models:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='petal hush: no models loaded at all')

    # the model the next new chat will open on — Petal with her own style.
    # no task-model swap: titles want a cheap voice, whispers want HER voice,
    # and calling the derived model makes OWUI apply its system prompt + params.
    admin_defaults = [m.strip() for m in ((await Config.get('ui.default_models')) or '').split(',') if m.strip()]
    model_id, picked_by = _petal_hush_pick_model(models, form_data.get('model'), user, admin_defaults)
    if not model_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='petal hush: no visible model to ask')

    content = await _petal_prompt_template(_petal_hush_prompt(), user)
    avoid = [a for a in (form_data.get('avoid') or []) if isinstance(a, str)][:8]
    if avoid:
        content += '\n\n(fresh words please — not these: ' + ' / '.join(avoid) + ')'

    t0 = _petal_time.monotonic()
    code, body = await _petal_hush_ask(request, user, models, model_id, content)
    if code >= 400:
        err = _petal_hush_err(body)
        label = f'{_petal_hush_base(models, model_id)} · picked from {picked_by}'
        log.warning('petal hush: %s failed → %s', label, err)
        content_out = {'detail': 'petal hush: no whisper', 'tried': [{'model': label, 'error': err}]}
        if form_data.get('debug'):
            content_out['debug'] = {'model': label, 'prompt': content, 'error': err,
                                    'ms': round((_petal_time.monotonic() - t0) * 1000)}
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content=content_out)

    try:
        choice = body['choices'][0]
        message = choice.get('message') or {}
    except (KeyError, IndexError, TypeError):
        choice, message = {}, {}
    raw = message.get('content')
    whisper, why = _petal_hush_clean(raw)
    ms = round((_petal_time.monotonic() - t0) * 1000)
    if whisper:
        log.info('petal hush: %s (%s) in %dms → %r', model_id, picked_by, ms, whisper)
    else:
        log.info('petal hush: %s (%s) in %dms → trimmed: %s', model_id, picked_by, ms, why)

    out = {'whisper': whisper, 'model': model_id, 'picked_by': picked_by}
    if not whisper:
        out['reason'] = why
    if form_data.get('debug'):
        reasoning = message.get('reasoning_content') or message.get('reasoning') or ''
        out['debug'] = {
            'model': _petal_hush_base(models, model_id),
            'picked_by': picked_by,
            'prompt': content,
            'raw': raw if isinstance(raw, str) else raw,
            'finish_reason': choice.get('finish_reason'),
            'reasoning_chars': len(reasoning) if isinstance(reasoning, str) else None,
            'usage': body.get('usage'),
            'ms': ms,
        }
    return out
# <<< petal · hush · end <<<
