<!--
🌊 the floor · what Petal reads when her stream gives her the floor (slice A43)

the shipped words. your copy wins whole: Petal-App-Data/petal-open-webui/stream-floor.md (beside stream.json,
never inside stream/, where only profiles live). copy this file there and tune it; a section you leave out
speaks with these words, a section you empty stays silent.

## floor · the note at the very end of a stream request: one user-shaped message, never saved, never shown.
   it is worded so it never reads as a message of hers.
## spoke first · one line placed before each of her stream messages in every later request (stream or
   normal), never saved, never shown. one line only.

slots (facts from code, filled fresh each time; a line whose fact is empty right now stays unsaid):
{{user}} · {{since_she_wrote}} · {{since_last_spoke}} · {{in_a_row}} (her stream messages since the last message
of {{user}}; empty at 0) · {{local_time}} (empty while the forge hides the hour) · {{her_date}} · {{typing}}
(only while she types) · {{profile}} · {{min_words}} {{max_words}} (only when the profile sets `length`) ·
{{words}} (the profile's own words, its purpose) · {{pass}} (the marker that lets the moment pass)
-->

## floor
‹ the floor · this is not a message from {{user}} ›
No new message from {{user}}.
She last wrote {{since_she_wrote}} ago.
You last spoke {{since_last_spoke}} ago.
Your messages in a row since her last one: {{in_a_row}}.
It is {{local_time}}.
Today is {{her_date}}.
She is {{typing}} right now.
The floor is yours.

{{words}}

Around {{min_words}} to {{max_words}} words would suit this moment.
If nothing wants to be said, answer only {{pass}} and the moment passes.
‹ end of the note ›

## spoke first
‹ no new message from {{user}} here · you spoke on your own ›
