"""
🌸🗣️ petal words — what her voice says of a reply, cut into the same sentences the page cuts (A45)
──────────────────────────────────────────────────────────────────────────────────────────────────
the rig follows a reply as it grows, so it needs the page's words exactly: the same text, the same
sentences in the same order, the same paragraph ends. the page's follower (A19) lights each sentence
by its index, so one sentence more or less here would light the wrong words.

a faithful port of the page's own chain, step for step:
  visible(content, output)   ResponseMessage's visibleResponseContent:
                             getOutputText(output) || removeAllDetails(content)
  parts(text)                petalStream.ts petalStreamParts(text, getMessageContentParts)
                             (withoutPictures → paragraphs → sentences, each through cleanText)
  whole(text, finished)      petal-autoplay.ts wholeParts: every sentence once she's done, all but the
                             last while she still writes

JavaScript's regex habits are kept where they change an answer: `\\d` is ASCII, lengths count UTF-16
code units, an unmatched group replaces with '', `\\p{RGI_Emoji}` matches whole emoji sequences only
(a bare 👁 without its variation selector isn't one, and stays). the parity test runs the page's real
source beside this file, on a corpus, and asks for the same parts.

pure: no I/O, no imports from OWUI.
"""

from __future__ import annotations

import regex as re  # OWUI pins it: Unicode properties, as the page's /v regexes use

# ── \p{RGI_Emoji}: whole emoji sequences, longest first ─────────────────────────────────────────────────
_ELEM = (
    r"(?:(?!\p{Regional_Indicator})(?:"
    r"\p{Emoji_Modifier_Base}\p{Emoji_Modifier}"  # 💅🏻
    r"|\p{Emoji_Presentation}️?"  # 💗
    r"|(?![0-9#*])\p{Emoji}️"  # ❤️ (text-default, asked as emoji)
    r"))"
)
_RGI = re.compile(
    r"[0-9#*]️⃣"  # keycaps 1️⃣
    r"|\U0001F3F4[\U000E0030-\U000E0039\U000E0061-\U000E007A]{2,}\U000E007F"  # 🏴 subdivision flags
    r"|\p{Regional_Indicator}{2}"  # 🇨🇦
    rf"|{_ELEM}(?:‍{_ELEM})*"  # one emoji, or a ZWJ family of them
)


def remove_emojis(s: str) -> str:
    return _RGI.sub("", s)


def _g1(m) -> str:  # JS '$1': an unmatched group is ''
    return m.group(1) or ""


_FORMAT = [
    (re.compile(r"(```[\s\S]*?```)"), ""),  # code blocks
    (re.compile(r"^\|.*\|$", re.M), ""),  # tables
    (re.compile(r"(?:\*\*|__)(.*?)(?:\*\*|__)"), _g1),  # bold
    (re.compile(r"(?:[*_])(.*?)(?:[*_])"), _g1),  # italic
    (re.compile(r"~~(.*?)~~"), _g1),  # strikethrough
    (re.compile(r"`([^`]+)`"), _g1),  # inline code
    (re.compile(r"!?\[([^\]]*)\](?:\([^)]+\)|\[[^\]]*\])"), _g1),  # links & images
    (re.compile(r"^\[[^\]]+\]:\s*.*$", re.M), ""),  # reference definitions
    (re.compile(r"^#{1,6}\s+", re.M), ""),  # headers
    (re.compile(r"^\s*[-*+]\s+", re.M), ""),  # lists
    (re.compile(r"^\s*(?:[0-9]+\.)\s+", re.M), ""),  # numbered lists (JS \d is ASCII)
    (re.compile(r"^\s*>[> ]*", re.M), ""),  # blockquotes
    (re.compile(r"^\s*:\s+", re.M), ""),  # definition lists
    (re.compile(r"\[\^[^\]]*\]"), ""),  # footnotes
    (re.compile(r"\n{2,}"), "\n"),  # many newlines
]


def remove_formattings(s: str) -> str:
    for rx, to in _FORMAT:
        s = rx.sub(to, s)
    return s


_JS_SPACE = " \t\n\v\f\r                 　﻿"


def js_trim(s: str) -> str:
    return s.strip(_JS_SPACE)


def clean_text(content: str) -> str:
    return remove_formattings(remove_emojis(js_trim(content)))


def js_len(s: str) -> int:
    """String.length: UTF-16 code units"""
    return len(s.encode("utf-16-le")) // 2


# ── code blocks are kept whole through the cut ─────────────────────────────────────────────────────────
_CODE = re.compile(r"```[\s\S]*?```")
_HOLE = re.compile("\u0000(\\d+)\u0000")


def _hide_code(text: str) -> tuple[str, list[str]]:
    blocks: list[str] = []

    def take(m):
        blocks.append(m.group(0))
        return f"\u0000{len(blocks) - 1}\u0000"

    return _CODE.sub(take, text), blocks


def _restore(piece: str, blocks: list[str]) -> str:
    return _HOLE.sub(lambda m: blocks[int(m.group(1))], piece)


_SENTENCE_CUT = re.compile(r"(?<=[.!?])\s+|\n+")


def extract_sentences(text: str) -> list[str]:
    text, blocks = _hide_code(text)
    return [c for c in (clean_text(_restore(s, blocks)) for s in _SENTENCE_CUT.split(text)) if c]


def extract_sentences_for_audio(text: str) -> list[str]:
    merged: list[str] = []
    for current in extract_sentences(text):
        if merged:
            prev = merged[-1]
            if len(re.split(r"\s+", prev)) < 4 or js_len(prev) < 50:
                merged[-1] = prev + " " + current
            else:
                merged.append(current)
        else:
            merged.append(current)
    return merged


def extract_paragraphs_for_audio(text: str) -> list[str]:
    text, blocks = _hide_code(text)
    return [c for c in (clean_text(_restore(p, blocks)) for p in re.split(r"\n+", text)) if c]


# ── 🌸 petal-table-voice: tables read aloud, before the line cut erases them ─────────────────────────────
_FENCE = re.compile(r"^\s*(```|~~~)")
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_EMPTYISH = re.compile(r"^[\s\-–—.·•]*$")


def _split_cells(line: str) -> list[str]:
    s = js_trim(line)
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [js_trim(re.sub(r"<br\s*/?>", ", ", c.replace("\\|", "|"), flags=re.I)) for c in re.split(r"(?<!\\)\|", s)]


def _is_row(line: str) -> bool:
    return "|" in line and js_trim(line) != ""


def _end_sentence(s: str) -> str:
    t = re.sub(r"[,;:\s]+$", "", js_trim(s))
    if not t:
        return ""
    return t if re.search(r"[.!?…~)\"'*_`]$", t) else f"{t}."


def _speak_row(headers: list[str], cells: list[str]) -> list[str]:
    lines = []
    for i, value in enumerate(cells):
        if not value or _EMPTYISH.search(value):
            continue
        h = headers[i] if i < len(headers) else None
        line = _end_sentence(f"{h}: {value}" if h and not _EMPTYISH.search(h) else value)
        if line:
            lines.append(line)
    return lines


def speak_tables(content: str) -> str:
    if not content or "|" not in content:
        return content
    lines = content.split("\n")
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.search(line):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        start = (
            not in_fence
            and _is_row(line)
            and i + 1 < len(lines)
            and _SEPARATOR.search(lines[i + 1])
            and "-" in lines[i + 1]
        )
        if not start:
            out.append(line)
            i += 1
            continue
        rows, j = [], i + 2
        while j < len(lines) and _is_row(lines[j]) and not _FENCE.search(lines[j]):
            rows.append(lines[j])
            j += 1
        headers = _split_cells(line)
        spoken: list[str] = []
        for r in rows:
            said = _speak_row(headers, _split_cells(r))
            if said:
                spoken += said + [""]
        out += [""] + spoken + [""]
        i = j
    return "\n".join(out)


# ── OWUI's getMessageContentParts, with petal's tables ─────────────────────────────────────────────────
_DETAILS = re.compile(r"<details[^>]*>[\s\S]*?</details>", re.I)


def message_content_parts(content: str, split_on: str = "punctuation") -> list[str]:
    content = speak_tables(_DETAILS.sub("", content))
    if split_on == "paragraphs":
        return extract_paragraphs_for_audio(content)
    if split_on == "none":
        return [clean_text(content)]
    return extract_sentences_for_audio(content)


# ── the reply as the page shows it ─────────────────────────────────────────────────────────────────────
_OUTSIDE = re.compile(r"(```[\s\S]*?```|`[\s\S]*?`)")
_DETAILS_LINE = re.compile(r"<details[^>]*>.*?</details>", re.I | re.S)


def replace_outside_code(content: str, fn) -> str:
    return "".join(seg if seg.startswith("`") else fn(seg) for seg in _OUTSIDE.split(content))


def remove_all_details(content: str) -> str:
    content = _DETAILS.sub("", content)
    return js_trim(replace_outside_code(content, lambda seg: _DETAILS_LINE.sub("", seg)))


def output_text(output) -> str:
    """structuredOutput.ts getOutputText: the message items' text parts, joined"""
    texts = []
    for item in output or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        t = ""
        for part in item.get("content") or []:
            v = part.get("text") if isinstance(part, dict) else None
            t += "" if v is None else (v if isinstance(v, str) else str(v))
        if js_trim(t):
            texts.append(t)
    return "\n".join(texts)


def visible(content: str | None, output=None) -> str:
    return output_text(output) or remove_all_details(content or "")


# ── petalStream.ts ─────────────────────────────────────────────────────────────────────────────────────
_PICTURES = [re.compile(r"!\[[^\]]*\]\([^)]*\)"), re.compile(r"<img\b[^>]*>", re.I)]


def without_pictures(content: str) -> str:
    for rx in _PICTURES:
        content = rx.sub(lambda m: "\u0000" if m.group(0) else m.group(0), content)
    return re.sub(r"[ \t]*\u0000[ \t]*", " ", content)


def parts(content: str) -> list[dict]:
    out: list[dict] = []
    content = without_pictures(content)
    paras = message_content_parts(content, "paragraphs")
    for para in paras or [content]:
        sentences = [s for s in message_content_parts(para, "punctuation") if js_trim(s)]
        for i, text in enumerate(sentences):
            out.append({"text": js_trim(text), "para_end": i == len(sentences) - 1})
    return out


def whole(content: str, finished: bool) -> list[dict]:
    ps = parts(content)
    return ps if finished else ps[:-1]
