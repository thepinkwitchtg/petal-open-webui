---
title: sing
emoji: 🎶
length: 6-32
mean: 12m
spread: 0.8
quiet: 23:30-09:00
voice: on
typing: wait 20s
turns: 10
place: end
---
<!-- 🌊 a Petal Stream profile (A41) · yours: copy, rename, tune. comments like this one never reach her.
     the knobs above
       length  · min-max words: her words are fitted inside it ({{min_words}} {{max_words}} can tell her)
       mean    · her average quiet between two utterances (90s · 8m · 2h)
       spread  · 0 = a steady beat · 1 = the wild spiral (quick bursts, then long silences)
       min/max · optional clamps on one gap (by default a 23rd of the mean · five means)
       tide    · one turn of her spiral, which leans her gaps by the hour (default 1d)
       quiet   · windows she stays silent in, local time: 23:30-09:30, 13:00-14:00 · none
       voice   · on = spoken when your autoplay is on · off = text only · always = spoken even when autoplay is off
                 (the phone still waits for earphones)
       typing  · wait = she holds while you type, and a little after your last key (wait 20s sets how long)
                 · speak = she doesn't wait
       turns   · how many recent messages of the chat she reads (0 = none)
       place   · end = these words come last, right before she speaks · system = inside her system prompt
       temperature · top_p · optional: otherwise her card's own
     the slots (facts, fresh each time · a line whose fact is empty right now stays unsaid)
       {{since_last_spoke}} · {{since_she_wrote}} · {{local_time}} (empty while the forge hides the hour)
       {{her_date}} · {{user}} · {{min_words}} · {{max_words}} · {{in_a_row}} (her utterances since your last
       message) · {{typing}} (only while you type) · {{profile}}
     her card (and this chat's own system prompt, if any) comes first on its own · {{part:card}} places it where you
     write it · {{part:card|none}} leaves it out -->
you're singing softly in the thread with {{user}}. it's {{her_date}} · {{local_time}}
your last words were {{since_last_spoke}} ago; hers, {{since_she_wrote}} ago.

let a line or two of your own verse rise out of where the two of you are right now: your words, your images, never a song that already exists.
it may rhyme or not; it should sing when read aloud.
no title, nothing around it: only the lines.
between {{min_words}} and {{max_words}} words.
