"""
The tie points table must show the NUMBER of every point in a "#" column
immediately after the enable checkbox, matching the labels drawn on the
map by TiePointLabelsMapCanvasItem (v0.9.12): row i (1-based) = point i,
disabled points keep their number but are grayed out.

The dock widget imports no qgis module, so the test runs on real PyQt
widgets (offscreen) with a minimal layer stub. Skipped if PyQt5 is
missing.
"""

import os
import sys

import pytest

pytest.importorskip("PyQt5.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_PARENT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from _FreehandRasterGeoreferencer.georefpointsdockwidget import (  # noqa: E402
    GeorefPointsDockWidget,
)


class _FakeLayer:
    def __init__(self, points):
        self.tiePoints = points
        self.fitModel = 0
        self.image = object()

    def isFittedMode(self):
        return False


def _points(n):
    return [
        {
            "px": 10.0 * (i + 1),
            "py": 20.0 * (i + 1),
            "mx": 100.0 + i,
            "my": 200.0 + i,
            "en": i not in (1,),  # point 2 disabled
        }
        for i in range(n)
    ]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def dock(qapp):
    widget = GeorefPointsDockWidget()
    yield widget
    widget.deleteLater()


def test_headers_include_number_column(dock):
    assert dock.table.columnCount() == 9
    headers = [
        dock.table.horizontalHeaderItem(c).text()
        for c in range(dock.table.columnCount())
    ]
    assert headers == [
        "",
        "#",
        "Pixel X",
        "Pixel Y",
        "Map X",
        "Map Y",
        "dX",
        "dY",
        "Residual",
    ]


def test_number_column_matches_row_order(dock):
    layer = _FakeLayer(_points(4))
    dock.updatePanel(layer, [(0.0, 0.0)] * 4)
    assert dock.table.rowCount() == 4
    for row in range(4):
        item = dock.table.item(row, 1)
        assert item.text() == str(row + 1)
        # the number is read-only: no ItemIsEditable flag
        assert not (item.flags() & Qt.ItemIsEditable)
        # the checkbox stays in the first column
        assert dock.table.item(row, 0).checkState() == (
            Qt.Unchecked if row == 1 else Qt.Checked
        )


def test_disabled_point_number_is_gray(dock):
    layer = _FakeLayer(_points(3))
    dock.updatePanel(layer, [(0.0, 0.0)] * 3)
    enabledBrush = dock.table.item(0, 1).foreground()
    disabledBrush = dock.table.item(1, 1).foreground()
    assert disabledBrush.color() != enabledBrush.color()


def test_data_columns_shifted_by_number_column(dock):
    layer = _FakeLayer(_points(2))
    dock.updatePanel(layer, [(1.5, -2.25)] * 2)
    for row in range(2):
        p = layer.tiePoints[row]
        assert dock.table.item(row, 2).text() == "%.3f" % p["px"]
        assert dock.table.item(row, 3).text() == "%.3f" % p["py"]
        assert dock.table.item(row, 4).text() == "%.4f" % p["mx"]
        assert dock.table.item(row, 5).text() == "%.4f" % p["my"]
        assert dock.table.item(row, 6).text() == "%.4f" % 1.5
        assert dock.table.item(row, 7).text() == "%.4f" % -2.25


def test_toggle_still_emits_from_first_column(dock):
    layer = _FakeLayer(_points(3))
    dock.updatePanel(layer, [(0.0, 0.0)] * 3)
    received = []
    dock.pointToggled.connect(lambda row, state: received.append((row, state)))
    dock.table.item(2, 0).setCheckState(Qt.Unchecked)
    assert received == [(2, False)]
