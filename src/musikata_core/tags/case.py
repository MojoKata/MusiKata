"""Tidy case (R3.6.1): a value typed all in lower case or all in upper case becomes Title Case, the
small words (a, an, and, of, the, …) kept lower inside it; a value that already mixes cases is
left as it is. The Edit tags panel's Tidy case uses it (R4.5.3), and Infer from path will (R3).

What counts as a word, and so what is capitalized: a run of letters, digits and apostrophes
(`don't`, `'til`), so the parts of `jay-z`, `ac/dc` and `r.e.m.` are each a word. A word's first
letter becomes upper case and the rest lower; one that starts with a digit (`1st`, `80s`) keeps
its letters lower, and a digit inside one (`deadmau5`) changes nothing. A small word is lower case
unless it is the title's first or last word or starts a part of it (after `:`, `(`, `[`, ` - ` or
`/`). A Roman numeral of I, V and X from 2 to 39 (`ii`, `xiv`) is upper case; those with M, D, C or
L are left as words, as `mix`, `dim` and `civil` are far more often. A value all in capitals is an
acronym as often as a shout, and is tidied either way (`AC/DC` becomes `Ac/Dc`): the preview
(R3.7) is where such a file is unchecked. Spaces and every mark are kept as they are."""

from __future__ import annotations

import re

SMALL = frozenset(("a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor",
                   "of", "on", "onto", "or", "the", "to", "vs", "via", "with", "n"))  # fmt: skip
# a letter or digit, then letters, digits and the marks that combine with them (an accent typed as
# its own character), joined by apostrophes
_L = r"(?:[^\W_]|[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f])"
_WORD = re.compile(rf"[^\W_]{_L}*(?:['’]{_L}+)*")
_ROMAN = re.compile(r"x{0,3}(?:ix|iv|v?i{0,3})", re.I)
_OPENS = re.compile(r"(?:[:(\[/]|\s[-–—]\s)\W*$")  # what starts a part of a title, before a word


def has_mixed_case(value: str) -> bool:
    """Whether `value` has both upper- and lower-case letters (R3.6.1 leaves it alone)."""
    return any(c.isupper() for c in value) and any(c.islower() for c in value)


def tidy_case(value: str) -> str:
    """`value` in Title Case when it is all lower or all upper case (R3.6.1); else as it is,
    as is a value with no letters that have a case."""
    if has_mixed_case(value) or not any(c.isupper() or c.islower() for c in value):
        return value
    words = list(_WORD.finditer(value))
    out: list[str] = []
    at = 0
    for i, m in enumerate(words):
        before = value[at : m.start()]
        out.append(before)
        first, last = i == 0, i == len(words) - 1
        opens = bool(_OPENS.search(before))  # the marks between it and the word before
        out.append(_word(m.group(), inner=not (first or last or opens)))
        at = m.end()
    out.append(value[at:])
    return "".join(out)


def _word(word: str, inner: bool) -> str:
    lower = word.lower()
    if inner and lower in SMALL:
        return lower
    if len(word) > 1 and _ROMAN.fullmatch(word):
        return word.upper()
    if not word[0].isalpha():
        return lower
    head = word[0].upper()
    return (head if len(head) == 1 else word[0]) + lower[1:]  # "ß" has no one-letter upper case
