# 🌸 reading OWUI's database after 0.13.5

For anything **outside the fork** that reads OWUI's database (training exports, memory summarizers, backups and
restores, resolvers): where each thing we read lived up to 0.13.4, where it lives from 0.13.5 on, and a tiny
read-only query for each. Inside the fork, read through upstream's model functions (`Chats.get_chat_by_id` and its
siblings still hand back `chat['history']`, rebuilt from rows); outside, read the rows.

## what moved

Upstream's migration `5e7a2c9d4b13` (*keep chat messages only in chat_message rows*) moves every chat's
`history.messages` into `chat_message` rows, one row per message, and the chat blob keeps no history at all. A row's
id is `{chat_id}-{message_id}`. Keys that have a column of their own live in it; **every other key the message had
(all of our top-level stamps) lives in the new JSON column `chat_message.data`**. A message as OWUI rebuilds it is
its columns (renamed back) plus `data`, and `data` wins.

The migration took the chat's JSON as the truth: each row's columns were rewritten from it, except `output` and
`usage` of rows that already existed (kept as stored). A flag that only a 0.13.4 row held and the JSON didn't is gone:
`meta.petal_spoke_first` on stream messages written before the migration (their stamp, `data.petal_stream`, stays).
Rows whose message was no longer in the JSON were deleted.

Detecting the shape (a reader that also opens older backups needs both):

```sql
SELECT version_num FROM alembic_version;                                     -- '5e7a2c9d4b13' (or later): new shape
SELECT count(*) FROM pragma_table_info('chat_message') WHERE name = 'data';  -- 1: new shape · 0: old
```

## old path → new path

| what we read | up to 0.13.4 | from 0.13.5 |
|---|---|---|
| a chat's messages | `chat.chat` → `history.messages` (by id) | `chat_message` rows `WHERE chat_id = :chat_id`; message id = row id minus `{chat_id}-` |
| the current leaf | `history.currentId` | `chat.current_message_id` |
| the branch's order | `parentId` up from the leaf | column `parent_id` up from the leaf (a root's is NULL) |
| children | `childrenIds` | `data.childrenIds` (or the rows whose `parent_id` is it) |
| role · content · files · sources · meta · done · error | same keys | same-named columns (`content` is JSON: a string or a list of blocks) |
| model · status history | `model` · `statusHistory` | `model_id` · `status_history` (`modelName`, `modelIdx` in `data`) |
| when it was written | `timestamp` | `created_at` (seconds); `data.timestamp` keeps the original when it wasn't plain seconds |
| usage | `usage` | `data.usage` as written; the `usage` column is OWUI's normalized copy (adds `input_tokens`/`output_tokens`) |
| **the stamps** `system` · `petal_state` · `petal_footnote` · `petal_mode` · `petal_pick` | top level on the reply | `data.system` · `data.petal_state` · … |
| **fusion** | `petal_fusion` on the asked reply + feedback rows `type = 'petal_fusion'` | `data.petal_fusion` + the same feedback rows (unchanged) |
| **stream messages** | `petal_stream` on the message (+ `meta.petal_spoke_first` on its 0.13.4 row) | `data.petal_stream` on every one · `meta.petal_spoke_first` only on those written since the rebase |
| a thumb on a reply | `annotation` · `feedbackId` | `data.annotation` · `data.feedbackId` |
| **feedback rows** | `feedback` table · page meta `arena` (bool) | the same table and rows · new rows carry `meta.strategy` (text or null) instead of `meta.arena`; old rows keep `arena` |
| chat tags | `chat.meta.tags` | `resource_tag` rows (`resource_type = 'chat'`) |
| a legacy chat (a `messages` list, no history) | `chat.chat.messages` | rows chained in list order (an entry without an id took its index) |
| the flattened `messages` list beside history | `chat.chat.messages` | gone (walk the rows) |

## tiny queries (SQLite, read-only)

Open the live db read-only, WAL and all: `file:webui.db?mode=ro` (`immutable=1` only on a cold copy: it skips the
WAL). JSON objects come back as JSON text; parse them on your side.

**History: the current branch, oldest first**

```sql
WITH RECURSIVE branch(row_id, depth) AS (
  SELECT c.id || '-' || c.current_message_id, 0 FROM chat c WHERE c.id = :chat_id
  UNION ALL
  SELECT m.chat_id || '-' || m.parent_id, b.depth + 1
  FROM branch b JOIN chat_message m ON m.id = b.row_id
  WHERE m.parent_id IS NOT NULL
)
SELECT substr(m.id, length(m.chat_id) + 2) AS message_id, m.role,
       json_extract(m.content, '$') AS content, m.created_at
FROM branch b JOIN chat_message m ON m.id = b.row_id
ORDER BY b.depth DESC;
```

**The stamps on one reply**

```sql
SELECT json_extract(data, '$.system')         AS system,
       json_extract(data, '$.petal_state')    AS petal_state,
       json_extract(data, '$.petal_footnote') AS petal_footnote,
       json_extract(data, '$.petal_mode')     AS petal_mode,
       json_extract(data, '$.petal_pick')     AS petal_pick
FROM chat_message WHERE id = :chat_id || '-' || :message_id;
```

**Fusion: the asked replies, and their rows**

```sql
SELECT chat_id, substr(id, length(chat_id) + 2) AS message_id,
       json_extract(data, '$.petal_fusion.score') AS score,
       json_extract(data, '$.petal_fusion.feedback_id') AS feedback_id
FROM chat_message WHERE json_extract(data, '$.petal_fusion') IS NOT NULL;

SELECT id, json_extract(data, '$.score') AS score, json_extract(meta, '$.message_id') AS message_id
FROM feedback WHERE type = 'petal_fusion';
```

**Stream messages**

```sql
SELECT chat_id, substr(id, length(chat_id) + 2) AS message_id,
       json_extract(data, '$.petal_stream.profile') AS profile,
       json_extract(data, '$.petal_stream.at') AS at,
       json_extract(meta, '$.petal_spoke_first') AS spoke_first_flag   -- NULL on the older ones: read the stamp
FROM chat_message WHERE json_extract(data, '$.petal_stream') IS NOT NULL;
```

**Feedback: thumbs, and the reply each one rated**

```sql
SELECT f.id, json_extract(f.data, '$.rating') AS rating,
       coalesce(json_extract(f.meta, '$.strategy'), json_extract(f.meta, '$.arena')) AS strategy_or_arena,
       json_extract(m.data, '$.annotation') AS annotation,
       json_extract(m.data, '$.system') AS system
FROM feedback f
LEFT JOIN chat_message m
  ON m.id = json_extract(f.meta, '$.chat_id') || '-' || json_extract(f.meta, '$.message_id')
WHERE f.type = 'rating';
```

**Usage, as it was written**

```sql
SELECT coalesce(json_extract(data, '$.usage'), usage) AS usage
FROM chat_message WHERE id = :chat_id || '-' || :message_id;
```

**A chat's tags**

```sql
SELECT tag_id FROM resource_tag
WHERE resource_type = 'chat' AND resource_id = :chat_id ORDER BY created_at;
```

## copying one chat back from a backup

A chat now lives in four tables: its `chat` row, its `chat_message` rows (`chat_id = :chat_id`), its `resource_tag`
rows (`resource_id = :chat_id`) and the `feedback` rows that name it (`meta.chat_id`). A restore copies all four
(`INSERT OR IGNORE`, OWUI stopped, a safety copy first). **A backup taken before the migration holds the old shape**
(history in the blob, no `data` column): copied as is into a migrated db, the chat opens empty. Convert it first with
the migration's own rules (`_move_chat_history` in `5e7a2c9d4b13`), or restore into a copy of the old backup and let
OWUI migrate that copy.
