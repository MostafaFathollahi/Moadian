"""Folding Persian text into one spelling, so that searching it works.

The organization's catalogue is written by thousands of different filers, and
the same word arrives spelled several ways that look identical on screen:

* **Yeh and kaf.** ``ي`` U+064A (Arabic) and ``ی`` U+06CC (Farsi) render the
  same in most fonts, as do ``ك`` U+0643 and ``ک`` U+06A9. Arabic keyboards and
  older Windows layouts produce the first of each pair, Persian ones the second.
* **ZWNJ.** ``می‌شود`` and ``می شود`` and ``میشود`` are the same word. The zero
  width non-joiner is invisible, and a tokenizer that treats it as part of the
  word will not match a query that used a space.
* **Digits.** ``۱۲۳`` (Persian), ``١٢٣`` (Arabic-Indic) and ``123`` are the same
  number. A شناسه کالا/خدمت pasted from a PDF often arrives in the first form.
* **Alef and hamza.** ``آ إ أ ٱ`` all normalise to ``ا`` for search purposes,
  and filers use them interchangeably.

None of this is cosmetic: without it a search for ``آشپزی`` misses every row
that happens to have been typed with an Arabic yeh, and the operator concludes
the code is not in the catalogue.

This is a *search* normalisation, deliberately lossy. It is applied to the
indexed text and to the query, never to anything that goes on an invoice — the
شرح کالا/خدمت is sent exactly as the catalogue spells it.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["fold", "fold_digits", "is_digits"]

#: Characters that differ only by keyboard layout or orthographic convention.
_CHARACTERS = {
    # yeh
    "ي": "ی",  # ي ARABIC YEH
    "ى": "ی",  # ى ALEF MAKSURA
    "ے": "ی",  # ے YEH BARREE
    "ئ": "ی",  # ئ YEH WITH HAMZA
    # kaf
    "ك": "ک",  # ك ARABIC KAF
    # alef
    "آ": "ا",  # آ
    "أ": "ا",  # أ
    "إ": "ا",  # إ
    "ٱ": "ا",  # ٱ
    # heh
    "ة": "ه",  # ة TEH MARBUTA
    # waw
    "ؤ": "و",  # ؤ
    # joiners: word separators in Persian compounds, so they become spaces
    "‌": " ",  # ZWNJ
    "‍": " ",  # ZWJ
    "‎": " ",  # LRM
    "‏": " ",  # RLM
    "ـ": "",  # ـ TATWEEL, pure decoration
}

#: Persian ۰-۹ and Arabic-Indic ٠-٩ onto ASCII.
_DIGITS = {
    **{chr(0x06F0 + n): str(n) for n in range(10)},
    **{chr(0x0660 + n): str(n) for n in range(10)},
}

_TRANSLATION = str.maketrans({**_CHARACTERS, **_DIGITS})

#: Harakat, and the superscript alef. Invisible in most rendering, never typed
#: in a search box, and present in a small fraction of catalogue rows.
_MARKS = re.compile("[ً-ٰٕ]")

_WHITESPACE = re.compile(r"\s+")


def fold(text: str) -> str:
    """One spelling for text that is to be indexed or searched.

    Idempotent: folding an already folded string changes nothing, which matters
    because the query passes through here on every keystroke while the index
    passed through once at import.
    """
    if not text:
        return ""
    # NFC first: a yeh written as a base letter plus a combining mark has to
    # become one code point before the table below can recognise it.
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_TRANSLATION)
    text = _MARKS.sub("", text)
    # Latin creeps into the catalogue constantly — brand and software names.
    text = text.casefold()
    return _WHITESPACE.sub(" ", text).strip()


def fold_digits(text: str) -> str:
    """Only the digit mapping, for an identifier rather than a description.

    A شناسه کالا/خدمت pasted out of a PDF or a Persian spreadsheet arrives as
    ``۲۳۳۰۰۰۳۲۴۶۸۷۶``. It is the same code, and refusing it would be a lookup
    failure the operator cannot diagnose by looking at the screen.
    """
    if not text:
        return ""
    return unicodedata.normalize("NFC", text).translate(str.maketrans(_DIGITS)).strip()


def is_digits(text: str) -> bool:
    """Whether the text is a bare number once Persian digits are folded."""
    folded = fold_digits(text).replace(" ", "")
    return bool(folded) and folded.isdigit()
