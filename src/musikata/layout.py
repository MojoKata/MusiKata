"""What a screen draws outside its box (A1.6): each visible text checked against the card, chip or
panel it sits in. The tour runs it on every screen it saves, and tests run it on views given long
values.

A text's box is the nearest filled Rectangle it is drawn in, or the background of the nearest
control that has one, else the window. A clipping ancestor between a text and its box hides what it
clips (a list's rows inside the list), and that isn't judged; one above the box doesn't, so a card
scrolled out of view is still judged against its own text. From AppKata's, where it caught texts
running out of their chips and dialogs that no test looked at."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, TypeGuard

from PySide6.QtCore import QRectF
from PySide6.QtQuick import QQuickItem, QQuickWindow

SLACK = 2.0  # px: antialiasing and fonts' line heights
TEXTS = ("QQuickText", "QQuickTextEdit", "QQuickTextInput")


def _filled(item: Any) -> TypeGuard[QQuickItem]:
    if not isinstance(item, QQuickItem) or not item.isVisible():
        return False
    if item.width() <= 0 or item.height() <= 0 or not item.inherits("QQuickRectangle"):
        return False
    color = item.property("color")
    return color is not None and color.alpha() > 0


def _box(item: QQuickItem) -> tuple[QRectF | None, QQuickItem | None, QQuickItem | None]:
    """The scene rect of what `item` is drawn in, what that is, and the ancestor it belongs to."""
    p = item.parentItem()
    while p is not None:
        if _filled(p):
            return p.mapRectToScene(p.boundingRect()), p, p
        bg = p.property("background") if p.inherits("QQuickControl") else None
        if _filled(bg):
            return bg.mapRectToScene(bg.boundingRect()), bg, p
        p = p.parentItem()
    return None, None, None


def _drawn(item: QQuickItem) -> QRectF:
    """The scene rect an item paints: for a Text its laid-out text (QQuickText::boundingRect),
    wherever its alignment and padding put it; fields and editors draw inside themselves."""
    if item.inherits("QQuickText"):
        return item.mapRectToScene(item.boundingRect())
    return item.mapRectToScene(QRectF(0, 0, item.width(), item.height()))


def _shown(item: QQuickItem, rect: QRectF, owner: QQuickItem | None) -> QRectF:
    """`rect` less what the clipping ancestors up to `owner` (the box's, itself included) hide."""
    p = item.parentItem()
    while p is not None and not rect.isEmpty():
        if p.clip():
            rect = rect.intersected(p.mapRectToScene(p.boundingRect()))
        if p is owner:
            break
        p = p.parentItem()
    return rect


def _texts(item: QQuickItem) -> Iterator[QQuickItem]:
    if not item.isVisible() or item.opacity() <= 0:
        return
    if any(item.inherits(t) for t in TEXTS) and str(item.property("text") or "").strip():
        yield item
    for child in item.childItems():
        yield from _texts(child)


def faults(window: QQuickWindow) -> list[dict[str, str]]:
    """Each visible text drawn outside its box: {"text": the text, "line": what is wrong}."""
    screen = QRectF(0, 0, window.width(), window.height())
    out = []
    for t in _texts(window.contentItem()):
        box, what, owner = _box(t)
        drawn = _shown(t, _drawn(t), owner)
        if drawn.isEmpty():
            continue
        name = "the window"
        if box is None or what is None:
            box = screen
        else:
            name = what.objectName() or what.metaObject().className()
        past = {
            "left": box.left() - drawn.left(),
            "right": drawn.right() - box.right(),
            "top": box.top() - drawn.top(),
            "bottom": drawn.bottom() - box.bottom(),
        }
        sides = [f"{n} by {v:.0f} px" for n, v in past.items() if v > SLACK]
        if sides:
            text = " ".join(str(t.property("text")).split())
            out.append(
                {"text": text, "line": f"{text[:70]!r} runs past {name}: {', '.join(sides)}"}
            )
    return out
