# 🌊 her stream · the knobs

A profile is one md file of yours in `Petal-App-Data/petal-open-webui/stream/<name>.md`. The fork ships none and
copies nothing there: write your own (this page is only a reference). The top is a little front matter, the rest
is your words. Comments (`<!-- … -->`) never reach her.

```
---
title: the lounge
emoji: 🛋️
length: 4-36
mean: 8m
spread: 0.9
quiet: 23:30-09:30
voice: on
typing: wait 15s
enabled: true
---
your words for her: this profile's purpose, with slots where facts go
```

**A stream turn is a normal turn** (A43): she gets her card and the chat's whole system prompt, with your filters'
inlets run (states, readout, clock, Anamnesis… whatever a normal reply gets), the chat's full branch, the time,
then **the floor note** at the very end: one user-shaped message, never saved, never shown, worded so it never
reads as you. It says there's no new message from you, how long since you wrote and since she last spoke, how many
times she has spoken in a row, that the floor is hers, and carries your profile's words and its length hint. Her
words have a normal reply's room: nothing is cut.

| knob | what it does | default |
|---|---|---|
| `title` · `emoji` | how the 💗 shows it | the file name · 🌊 |
| `length` | min-max words, **a hint** in the floor note (a sentence there, never a cut) · `{{min_words}}` `{{max_words}}` | none |
| `mean` | her average quiet between two utterances (`90s` · `8m` · `2h`) | 9m |
| `spread` | 0 = a steady beat · 1 = the wild spiral (quick bursts, then long silences) | 1 |
| `min` · `max` | clamps on one gap | a 23rd of the mean · five means |
| `tide` | one turn of her spiral, which leans her gaps by the hour | 1d |
| `quiet` | windows she stays silent in, local time: `23:30-09:30, 13:00-14:00` · `none` | none |
| `voice` | `on` = spoken when your autoplay is on · `off` = text only · `always` = spoken even when autoplay is off (the phone still waits for earphones) | on |
| `typing` | `wait` = she holds while you type, and a little after your last key (`wait 20s` sets how long) · `speak` = she doesn't wait | wait 12s |
| `turns` · `place` | **read no more** (A43): she reads the full branch, and your words always ride in the floor note. Accepted, so an older profile still reads | |
| `temperature` · `top_p` | optional; otherwise her card's own | |
| `enabled` | `false` puts the profile to sleep: hidden from the 💗, turned off in any chat that had it, never deleted | true |

**Slots** (facts, filled fresh each time; a line whose fact is empty right now stays unsaid):
`{{since_last_spoke}}` · `{{since_she_wrote}}` · `{{local_time}}` (empty while the forge hides the hour) ·
`{{her_date}}` · `{{user}}` · `{{min_words}}` · `{{max_words}}` (only with `length`) · `{{in_a_row}}` (her
utterances since your last message; empty at 0) · `{{typing}}` (only while you type) · `{{profile}}`. A line
holding a slot that doesn't exist is skipped and named. `{{part:card}}` is let go (her card is in her system prompt
now) and named.

**She may pass.** The floor note offers her a marker (`(pass)`); an empty answer, one of only spaces or
punctuation, or the marker means nothing is inserted, the sheet says *she let it pass*, and her gap starts over.
A pass is never an error.

**She knows she spoke first.** Her stream messages are stamped, and every later request (stream or normal) shows
one short, never-shown line before each of them.

**The floor's own words** are md too: `petal_stream_floor.md` ships with the fork (`## floor` · `## spoke first`).
Copy it to `Petal-App-Data/petal-open-webui/stream-floor.md` and tune it: your copy wins, a section you leave out
speaks with the shipped words, a section you empty stays silent.

**Long chats.** Until compression lands, a branch longer than her window (the model list's `max_model_len`, or
`PETAL_STREAM_WINDOW`) drops its oldest turns first, never the system prompt, never your last message, and the
sheet counts them (*12 old turns left out*).

After three model errors in a row she stops trying, until the profile's md changes or the stream is turned on again.
