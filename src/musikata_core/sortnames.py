"""Sort names (R2.13): artists, album artists and albums are shown as tagged and sorted by their
sort names, so "The Beatles" is listed under B. A name's sort tag wins when it has one; without one
a leading article is skipped; and the sort ignores case and leading punctuation and reads numbers
by value, as folder names do (R2.9.2).

What comes out is a key whose plain (binary) order is that order, so the index keeps it in a column
and SQL sorts by it with an index (A1.5): no collation or function of MusiKata's own is needed in a
query."""

from __future__ import annotations

import re
from collections.abc import Sequence

# R2.13's articles. R13.3's Settings list (slice 9) adds to them; until then each function takes
# the list as an argument with this as its default.
ARTICLES: tuple[str, ...] = ("The", "A", "An")

_NUMBER = re.compile(r"[0-9]+")
_WIDTH = 2  # digits of a number's length in its key: numbers of up to 99 digits sort by value


def _leading_punctuation(text: str) -> str:
    """`text` without what leads it that isn't a letter or a digit ("...And Justice", "'74")."""
    for i, ch in enumerate(text):
        if ch.isalnum():
            return text[i:]
    return ""


def skip_article(name: str, articles: Sequence[str] = ARTICLES) -> str:
    """`name` without a leading article and the space after it, any case ("The Beatles" gives
    "Beatles"); a name that is only an article, or "A-ha", is kept whole."""
    for article in articles:
        n = len(article)
        if len(name) > n + 1 and name[:n].casefold() == article.casefold() and name[n] == " ":
            rest = name[n + 1 :].lstrip()
            if rest:
                return rest
    return name


def sort_name(
    name: str | None, sort_tag: str | None = None, articles: Sequence[str] = ARTICLES
) -> str | None:
    """The text a name sorts by: its sort tag when it has one ("Bowie, David"), else the name
    without its leading punctuation and article. None when there is no name."""
    if sort_tag and sort_tag.strip():
        return sort_tag.strip()
    if name is None or not name.strip():
        return None
    text = _leading_punctuation(name.strip())
    if not text:
        return name.strip()  # nothing but punctuation ("!!!"): sorted as written
    return _leading_punctuation(skip_article(text, articles)) or text


def _number(m: re.Match[str]) -> str:
    digits = m.group(0).lstrip("0") or "0"
    return f"{min(len(digits), 10**_WIDTH - 1):0{_WIDTH}d}{digits}"


def key_of(text: str) -> str:
    """The binary-ordered key of a text already made a sort name: case and leading punctuation
    set aside, and each run of digits read as a number, so "Disc 9" comes before "Disc 10"."""
    folded = (_leading_punctuation(text) or text).casefold()
    return _NUMBER.sub(_number, folded)


def sort_key(
    name: str | None, sort_tag: str | None = None, articles: Sequence[str] = ARTICLES
) -> str | None:
    """The key a name sorts by (R2.13), for a column of the index: None when there is no name, so
    it sorts last there."""
    text = sort_name(name, sort_tag, articles)
    return None if text is None else key_of(text)


def article_last(name: str, articles: Sequence[str] = ARTICLES) -> str:
    """`name` with its leading article moved to its end, as R12.1's sort tokens name a folder:
    "The Beatles" gives "Beatles, The"; a name without one, or that is only one, is kept."""
    rest = skip_article(name, articles)
    if rest == name:
        return name
    return f"{rest}, {name[: len(name) - len(rest)].strip()}"
