"""
Offscreen rendering tests of the mesh drawing (polymesh.draw_warped_raster):
the per-cell transforms must be applied on top of the painter BASE
transform, not combined with each other. Regression test for the
"image disappears, only the outline remains" bug of v0.9.7 (the
combine=True variant made the cell transforms accumulate across the
loop, so only the first mesh cell was painted).

Requires PyQt5 (skipped automatically when it is missing) and runs on
the offscreen platform, so it works headlessly.
"""

import importlib
import os
import sys

import pytest

pytest.importorskip("osgeo.gdal")
QtGui = pytest.importorskip("PyQt5.QtGui")

# import polymesh as a package member (it uses relative imports); skip
# cleanly when the checkout directory name is not importable
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PKG = os.path.basename(_REPO)
try:
    if _PKG not in sys.path and os.path.dirname(_REPO) not in sys.path:
        sys.path.insert(0, os.path.dirname(_REPO))
    polymesh = importlib.import_module("%s.polymesh" % _PKG)
except (ImportError, ValueError) as ex:  # pragma: no cover
    pytest.skip("cannot import the polymesh package: %s" % ex, allow_module_level=True)

if not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from PyQt5.QtCore import QPointF  # noqa: E402
from PyQt5.QtGui import QColor, QImage, QPainter, QPen  # noqa: E402

W = H = 100
DEV_DX, DEV_DY, DEV_SCALE = 5.0, 7.0, 2.0


def _gradient_image():
    """Color encodes the pixel position: (2x, 2y, 0)."""
    img = QImage(W, H, QImage.Format_ARGB32)
    for y in range(H):
        for x in range(W):
            img.setPixel(x, y, QColor(x * 2, y * 2, 0).rgba())
    return img


def _identity_base():
    canvas = QImage(4 * W, 4 * H, QImage.Format_ARGB32)
    canvas.fill(QColor(255, 0, 255))
    return canvas, QPainter(canvas)


def _translated_base(offx, offy):
    """A canvas-item painter: the base transform translates the item."""
    canvas = QImage(4 * W + offx + 10, 4 * H + offy + 10, QImage.Format_ARGB32)
    canvas.fill(QColor(255, 0, 255))
    painter = QPainter(canvas)
    painter.translate(QPointF(offx, offy))
    return canvas, painter


def _draw(canvas, painter, image):
    polymesh.draw_warped_raster(
        painter,
        image,
        lambda px, py: (float(px), float(py)),  # map coords == image px
        lambda mx, my: (
            DEV_SCALE * mx + DEV_DX,
            DEV_SCALE * my + DEV_DY,
        ),
        W,
        H,
    )
    painter.end()
    return canvas


def _assert_pixel(canvas, px, py):
    """The device pixel for image (px, py) must show the source color."""
    dx = int(DEV_SCALE * px + DEV_DX)
    dy = int(DEV_SCALE * py + DEV_DY)
    got = canvas.pixelColor(dx, dy)
    expected = QColor(px * 2, py * 2, 0)
    assert abs(got.red() - expected.red()) <= 6, (
        "src(%d,%d)->dev(%d,%d): got rgb(%d,%d,%d), expected rgb(%d,%d,0)"
        % (px, py, dx, dy, got.red(), got.green(), got.blue(),
           expected.red(), expected.green())
    )
    assert abs(got.green() - expected.green()) <= 6


class TestMeshRendering:
    def test_all_cells_drawn_identity_base(self):
        """Map-job case (identity painter base): every mesh cell is drawn
        at its affine position, not only the first one."""
        canvas = _draw(*(_identity_base() + (_gradient_image(),)))
        for px, py in (
            (20, 20),  # cell (0, 0)
            (60, 20),  # cell (1, 0)
            (20, 60),  # cell (0, 1)
            (60, 60),  # cell (1, 1)
        ):
            _assert_pixel(canvas, px, py)

    def test_all_cells_drawn_translated_base(self):
        """Canvas-item case (painter pre-translated by the item position):
        the cell affine is composed with the base, not replaced by it."""
        canvas = _draw(*(_translated_base(30, 40) + (_gradient_image(),)))
        for px, py in ((20, 20), (60, 60)):
            dx = int(30 + DEV_SCALE * px + DEV_DX)
            dy = int(40 + DEV_SCALE * py + DEV_DY)
            got = canvas.pixelColor(dx, dy)
            expected = QColor(px * 2, py * 2, 0)
            assert abs(got.red() - expected.red()) <= 6
            assert abs(got.green() - expected.green()) <= 6

    def test_outline_drawn_in_device_coords(self):
        """draw_warped_outline strokes the warped border through the same
        map->device function (identity base)."""
        canvas = QImage(4 * W, 4 * H, QImage.Format_ARGB32)
        canvas.fill(QColor(255, 0, 255))
        painter = QPainter(canvas)
        pen = QPen()
        pen.setColor(QColor(0, 0, 0))
        pen.setWidth(1)
        painter.setPen(pen)
        polymesh.draw_warped_outline(
            painter,
            lambda px, py: (float(px), float(py)),
            lambda mx, my: (DEV_SCALE * mx + DEV_DX, DEV_SCALE * my + DEV_DY),
            W,
            H,
        )
        painter.end()
        # a point on the top border: image (50, 0) -> device (105, 7)
        c = canvas.pixelColor(105, 7)
        assert c.value() < 128  # dark stroke pixel on the border
        # the interior stays background
        c = canvas.pixelColor(107, 12)
        assert c.red() == 255 and c.green() == 0  # magenta background
