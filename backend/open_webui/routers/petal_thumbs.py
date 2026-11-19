"""
petal_thumbs 👍🏻 — one verdict per reply, in one small request (slice A23 · instant thumbs).

The page lights the thumb on the tap's frame and queues the verdict (src/lib/utils/petal-thumbs.ts). This
door lands it with the same effect as OWUI's two-step thumb (GET the chat → POST /evaluations/feedback with
the chat as its snapshot → POST the whole chat back), without the page carrying the chat both ways:

    POST /api/v1/petal/thumbs  { chat_id, message_id, feedback_id?, annotation, model_id,
                                 sibling_model_ids?, meta }
         → { feedback_id, created, annotation, updated_at }

- **one row per reply.** the row is found by `feedback_id`, else by the reply (`meta.message_id`, newest
  first, the order petal_state reads), else created. double taps, flips, retries and replays all land on it
- **the row reads exactly as before:** `data` = the reply's annotation + `model_id` (+ `sibling_model_ids`),
  `meta` as the page computed it, `snapshot.chat` = OWUI's own GET /chats/{id} answer (the same route
  function, through its response model), taken before the annotation is saved, as the page did. the
  resolved system stamp rides inside it untouched (`system` on the reply, guarded by merge_history)
- **a tags-only follow-up keeps the snapshot** (OWUI's tag step re-sent the tap's snapshot)
- **the chat keeps only what the thumb changed:** `annotation` + `feedbackId` merged into that one reply
  (owner only, as POST /chats/{id} was), never a whole history sent back
- the annotation merges over the stored one, key by key: the page sends what it knows (after a reload,
  only the verdict: ids, rating, reason, the 1–10), the stored note and tags stay
- contract 0: temporary chats record nothing (the page shows no thumbs there either)
- events as before: feedback.created | feedback.updated, then chat.updated

    POST /api/v1/petal/thumbs/tags  { chat_id, message_id }  → { tags, annotation, feedback_id }

- OWUI's tag step (her first thumb of a reply), run here instead of from the page: the same task
  (routers/tasks.generate_chat_tags: her tag template, the task model) over the same messages (root → this
  reply), read from the chat on the rig, so the phone never uploads the conversation. its answer is read the
  way the page read it (the JSON block's `tags`, [] on any failure, as the page saved). the tags land in the
  row's `data` and the reply's annotation, the snapshot kept (as OWUI's tag step re-sent the tap's)

💗 A26 · her thank-yous (utils/petal_thanks.py): a landed verdict also answers `thanks`, the next line Petal wrote
ahead of time (shown once, then retired; null when none is ready). the take is a file read, never a model call;
it wakes one refill in the background, written when vLLM is quiet. it is handed only the reply's model id: never
the verdict, never the note
💗 A27 · one line per feedback: the page asks (`"thanks": true`) only on a feedback's first landing (the thumb),
never on the note that follows it or a flip while the note is open; unasked, `thanks` is null and nothing is taken

🍒 A30b · her 💗 on an arm (the chosen reply of a pick whose replies differ only in pull) teaches the strength
search (utils/petal_arms.py): the reply's arm as the server recorded it says whether the pulled one won. once per
arm: a verdict sent again teaches nothing more

    GET  /api/v1/petal/thumbs/thanks         (admin) → { ready, target, recent, written, shown, writing, last }
    POST /api/v1/petal/thumbs/thanks/refill  (admin) → the same, after waking a refill
"""

import asyncio
import json
import logging
import re
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from open_webui.constants import ERROR_MESSAGES
from open_webui.events import EVENTS, publish_event
from open_webui.internal.db import get_async_db_context, get_async_session
from open_webui.models.chats import ChatResponse, Chats
from open_webui.models.feedbacks import Feedback, FeedbackForm, Feedbacks
from open_webui.routers.chats import get_chat_by_id as read_chat_as_the_page_did
from open_webui.routers.tasks import generate_chat_tags
from open_webui.utils import petal_arms, petal_thanks
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.chat_id import is_saved_chat_id
from open_webui.utils.misc import get_message_list

log = logging.getLogger(__name__)
router = APIRouter()

MAX_ANNOTATION_BYTES = 64 * 1024
_locks: dict = defaultdict(asyncio.Lock)  # one verdict at a time per (user, reply): two tabs never mint two rows


class ThumbForm(BaseModel):
    chat_id: str
    message_id: str
    feedback_id: Optional[str] = None
    annotation: dict
    model_id: Optional[str] = None
    sibling_model_ids: Optional[list[str]] = None
    meta: dict = {}
    thanks: bool = False  # 💗 A27 · this landing begins a feedback: hand back her next line (once per feedback)
    model_config = ConfigDict(extra='ignore', protected_namespaces=())


async def _row_for(user, form: ThumbForm, db: AsyncSession):
    """the reply's row: by id when it's hers and this reply's, else the newest for the reply"""
    if form.feedback_id:
        row = await Feedbacks.get_feedback_by_id(id=form.feedback_id, db=db)
        if row and (row.user_id == user.id) and (row.meta or {}).get('message_id') == form.message_id:
            return row
    async with get_async_db_context(db) as session:
        result = await session.execute(
            select(Feedback)
            .filter(
                Feedback.user_id == user.id,
                Feedback.type == 'rating',
                Feedback.meta['message_id'].as_string() == form.message_id,
            )
            .order_by(Feedback.created_at.desc())
            .limit(1)
        )
        found = result.scalars().first()
    return await Feedbacks.get_feedback_by_id(id=found.id, db=db) if found else None


@router.post('/thumbs')
async def land_thumb(
    request: Request,
    form: ThumbForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    if not is_saved_chat_id(form.chat_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='temporary chats keep no thumbs')
    if len(repr(form.annotation)) > MAX_ANNOTATION_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MESSAGES.DEFAULT('too large'))

    if len(_locks) > 256:  # forget the quiet ones now and then
        for k in [k for k, lock in _locks.items() if not lock.locked()]:
            _locks.pop(k, None)
    async with _locks[(user.id, form.message_id)]:
        # the snapshot, read the way the page read it (GET /chats/{id}), before anything is saved
        page_view = await read_chat_as_the_page_did(form.chat_id, request, user=user, db=db)
        chat_json = ChatResponse.model_validate(page_view).model_dump(mode='json')
        stored = ((chat_json.get('chat') or {}).get('history') or {}).get('messages', {}).get(form.message_id)
        if not isinstance(stored, dict):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)

        stored_annotation = stored.get('annotation') if isinstance(stored.get('annotation'), dict) else {}
        annotation = {**stored_annotation, **form.annotation}
        data = {
            **annotation,
            'model_id': form.model_id,
            **({'sibling_model_ids': form.sibling_model_ids} if form.sibling_model_ids else {}),
        }

        row = await _row_for(user, form, db)
        tags_only = set(form.annotation) <= {'tags'}
        feedback_form = FeedbackForm(
            type='rating',
            data=data,
            meta=form.meta,
            snapshot=None if (row and tags_only) else {'chat': chat_json},
        )
        if row:
            if user.role == 'admin':
                landed = await Feedbacks.update_feedback_by_id(id=row.id, form_data=feedback_form, db=db)
            else:
                landed = await Feedbacks.update_feedback_by_id_and_user_id(
                    id=row.id, user_id=user.id, form_data=feedback_form, db=db
                )
            created = False
        else:
            landed = await Feedbacks.insert_new_feedback(user_id=user.id, form_data=feedback_form, db=db)
            created = True
        if not landed:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MESSAGES.DEFAULT())

        await publish_event(
            request,
            EVENTS.FEEDBACK_CREATED if created else EVENTS.FEEDBACK_UPDATED,
            actor=user,
            subject_id=landed.id,
            data={'rating': (landed.data or {}).get('rating')},
        )

        # the chat keeps the thumb: annotation + feedbackId on that one reply (owner only, like POST /chats/{id})
        if chat_json.get('user_id') == user.id:
            saved = await Chats.upsert_message_to_chat_by_id_and_message_id(
                form.chat_id, form.message_id, {'annotation': annotation, 'feedbackId': landed.id}
            )
            if saved:
                await publish_event(
                    request,
                    EVENTS.CHAT_UPDATED,
                    actor=user,
                    subject_id=form.chat_id,
                    data={'title': saved.title},
                )

        # 🍒 A30b · her 💗 on an arm teaches the strength search: the arm as the server recorded it, learned once
        if annotation.get('petal_pick') is True and annotation.get('rating') == 1:
            record = stored.get('petal_pick') if isinstance(stored.get('petal_pick'), dict) else {}
            arm = record.get('arm') if isinstance(record.get('arm'), dict) else None
            if arm is not None and isinstance(arm.get('steered'), bool):
                try:
                    await asyncio.to_thread(petal_arms.learn, form.message_id, arm['steered'])
                except Exception as e:  # the search never costs her the verdict
                    log.warning(f'🍒 the strength search did not learn ({e!r})')

        return {
            'feedback_id': landed.id,
            'created': created,
            'annotation': annotation,
            'updated_at': landed.updated_at,
            # 💗 A26 · the next line she wrote ahead of time · verdict-blind: only the model id goes along
            # 💗 A27 · taken only when the page asks (a feedback's first landing): one line per feedback
            'thanks': await petal_thanks.take(request, user, model_id=form.model_id) if form.thanks else None,
        }


@router.get('/thumbs/thanks')
async def thanks_status(user=Depends(get_admin_user)):
    """numbers only: how many lines wait, how many were shown, how the last refill went"""
    return await petal_thanks.status()


@router.post('/thumbs/thanks/refill')
async def thanks_refill(request: Request, user=Depends(get_admin_user)):
    """top the pool up now (one line at a time, when vLLM is quiet), e.g. right after installing"""
    petal_thanks.wake(request.app, user)
    return await petal_thanks.status()


class TagsForm(BaseModel):
    chat_id: str
    message_id: str


def _truthy(value) -> bool:
    """the page's `!annotation?.tags` test: an empty list counts as tags already there"""
    return value is not None and value is not False and value != '' and not (isinstance(value, (int, float)) and value == 0)


def _tags_from(answer) -> list:
    """the page's parse of the tag task's answer: the JSON block's `tags` list, else []"""
    try:
        if not isinstance(answer, dict):
            return []  # tags switched off, a refused model, an error: the page saved [] for these
        content = ((answer.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
        text = re.sub(r"['‘’`]", '"', content)
        start, end = text.find('{'), text.rfind('}')
        if start == -1 or end == -1:
            return []
        parsed = json.loads(text[start : end + 1])
        tags = parsed.get('tags') if isinstance(parsed, dict) else None
        return tags if isinstance(tags, list) else []
    except Exception:
        return []


@router.post('/thumbs/tags')
async def tag_thumb(
    request: Request,
    form: TagsForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    if not is_saved_chat_id(form.chat_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='temporary chats keep no thumbs')
    chat = await Chats.get_accessible_chat_by_id(form.chat_id, user, db=db)
    messages_map = (((chat.chat or {}).get('history') or {}).get('messages') or {}) if chat else {}
    reply = messages_map.get(form.message_id)
    if not isinstance(reply, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    if _truthy((reply.get('annotation') or {}).get('tags')):
        return {'tags': None, 'annotation': None, 'feedback_id': None, 'skipped': True}

    # the task itself, outside the reply's lock: a flip never waits on a model
    try:
        answer = await generate_chat_tags(
            request,
            {'model': reply.get('model'), 'messages': get_message_list(messages_map, form.message_id), 'chat_id': form.chat_id},
            user=user,
        )
        tags = _tags_from(answer)
    except Exception as e:
        log.debug(f'thumb tags: {e}')
        tags = []

    async with _locks[(user.id, form.message_id)]:
        row = await _row_for(user, ThumbForm(chat_id=form.chat_id, message_id=form.message_id, annotation={}), db)
        if not row:
            return {'tags': tags, 'annotation': None, 'feedback_id': None}
        fresh = await Chats.get_chat_by_id(form.chat_id, db=db)
        stored = ((((fresh.chat or {}).get('history') or {}).get('messages') or {}).get(form.message_id) or {}) if fresh else {}
        annotation = {**(stored.get('annotation') if isinstance(stored.get('annotation'), dict) else {}), 'tags': tags}
        feedback_form = FeedbackForm(type='rating', data={**(row.data or {}), 'tags': tags}, meta=row.meta, snapshot=None)
        if user.role == 'admin':
            landed = await Feedbacks.update_feedback_by_id(id=row.id, form_data=feedback_form, db=db)
        else:
            landed = await Feedbacks.update_feedback_by_id_and_user_id(
                id=row.id, user_id=user.id, form_data=feedback_form, db=db
            )
        if landed:
            await publish_event(
                request,
                EVENTS.FEEDBACK_UPDATED,
                actor=user,
                subject_id=landed.id,
                data={'rating': (landed.data or {}).get('rating')},
            )
        if fresh and fresh.user_id == user.id:
            saved = await Chats.upsert_message_to_chat_by_id_and_message_id(
                form.chat_id, form.message_id, {'annotation': annotation, 'feedbackId': row.id}
            )
            if saved:
                await publish_event(
                    request, EVENTS.CHAT_UPDATED, actor=user, subject_id=form.chat_id, data={'title': saved.title}
                )
        return {'tags': tags, 'annotation': annotation, 'feedback_id': row.id}
