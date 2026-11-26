"""The layout check (src/musikata/layout.py; A1.6): a text past the card or control it sits in is
found, one inside isn't, and what its card clips isn't judged, while a clip above the card doesn't
excuse it (a card scrolled out of view is still judged)."""

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

from musikata import layout

QML = """
import QtQuick
import QtQuick.Controls.Basic
Window {
    width: 400; height: 300
    Rectangle {
        objectName: "card"; x: 10; y: 10; width: 120; height: 40; color: "#171a21"
        Text { objectName: "long"; text: "%(long)s"; font.pixelSize: 13 }
        Text {
            y: 20; width: 120; elide: Text.ElideRight; font.pixelSize: 13
            text: "elided, however long it runs"
        }
        Text { text: "   "; width: 900 }
        Text { visible: false; text: "hidden, so not judged at all"; width: 900 }
    }
    Rectangle {
        x: 10; y: 100; width: 120; height: 40; color: "#00000000"     // not filled: not a box
        Text { x: 395; text: "past the window"; font.pixelSize: 13 }
    }
    Item {
        x: 10; y: 160; width: 100; height: 40; clip: true
        Rectangle { width: 100; height: 40; color: "#171a21"
            Text { x: 60; text: "past its card, a clip above it hiding it"; font.pixelSize: 13 }
        }
    }
    Rectangle {
        x: 10; y: 220; width: 100; height: 40; color: "#171a21"; clip: true
        Text { x: 60; text: "clipped by its own card, so not judged"; font.pixelSize: 13 }
    }
    Control {
        x: 200; y: 220; width: 60; height: 30
        background: Rectangle { objectName: "chip"; color: "#1e222b" }
        contentItem: Text { text: "%(button)s"; font.pixelSize: 13 }
    }
}
"""


@pytest.fixture
def engine():
    e = QQmlEngine()
    yield e
    e.deleteLater()


HELD = []  # each window's component: one collected takes its window with it


def window(engine, long="fits", button="OK"):
    c = QQmlComponent(engine)
    HELD.append(c)
    c.setData((QML % {"long": long, "button": button}).encode(), QUrl())
    w = c.create()
    assert w is not None, c.errorString()
    w.show()
    return w


def test_texts_inside_their_boxes_pass_and_those_past_them_say_how_far(engine, qtbot):
    w = window(engine)
    qtbot.waitExposed(w)
    found = layout.faults(w)
    assert [f["text"] for f in found] == [
        "past the window", "past its card, a clip above it hiding it"
    ]  # fmt: skip
    assert "runs past the window: right by" in found[0]["line"]
    assert "runs past QQuickRectangle: right by" in found[1]["line"]
    w.close()


def test_a_long_text_in_a_card_and_in_a_controls_background_is_found(engine, qtbot):
    w = window(engine, long="a title much longer than its card can hold", button="Save to 4 files")
    qtbot.waitExposed(w)
    found = {f["text"]: f["line"] for f in layout.faults(w)}
    assert "runs past card: right by" in found["a title much longer than its card can hold"]
    assert "runs past chip: right by" in found["Save to 4 files"]
    w.close()


def test_filled_means_a_visible_rectangle_with_size_and_colour():
    assert not layout._filled(None) and not layout._filled("not an item")
