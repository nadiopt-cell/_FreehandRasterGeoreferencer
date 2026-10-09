"""
/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or    *
 *   (at your option) any later version.                                  *
 *                                                                         *
 ***************************************************************************/
"""

"""
Canvas item that draws the NUMBER of every tie point next to its target
marker on the map canvas, so that the numbers on the screen match the row
numbers of the tie points table.

The item covers the current canvas extent; label positions are recomputed
from map coordinates on every paint, so pan / zoom keeps the numbers on
their markers. Disabled points are drawn in gray (they keep their table
number).
"""

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from qgis.core import QgsPointXY
from qgis.gui import QgsMapCanvasItem

# colors of the label text: enabled / disabled point
_COLOR_ENABLED = QColor(150, 0, 0)
_COLOR_DISABLED = QColor(128, 128, 128)
# halo color around the digits (readable on any background)
_COLOR_HALO = QColor(255, 255, 255, 220)

# offset of the label from the marker circle center, device pixels
_OFFSET_X = 6.0
_OFFSET_Y = -6.0


class TiePointLabelsMapCanvasItem(QgsMapCanvasItem):
    def __init__(self, canvas):
        QgsMapCanvasItem.__init__(self, canvas)
        self.canvas = canvas
        # list of (QgsPointXY target, number, enabled)
        self._points = []
        self._coverExtent()

    # ------------------------------------------------------------------
    # data
    # ------------------------------------------------------------------

    def setPoints(self, points):
        """points: iterable of (mapPoint QgsPointXY, number int, enabled bool)."""
        self._points = list(points)
        self._coverExtent()
        self.setVisible(bool(self._points))
        self.update()

    def clear(self):
        self.setPoints([])

    # ------------------------------------------------------------------
    # positioning
    # ------------------------------------------------------------------

    def _coverExtent(self):
        # make the item cover the whole visible map: label positions are
        # recomputed in paint() from map coordinates
        try:
            extent = self.canvas.extent()
            if extent is not None and not extent.isEmpty():
                self.setRect(extent)
        except Exception:
            pass

    def updatePosition(self):
        # called by the canvas after pan / zoom: re-cover the new extent
        self._coverExtent()
        self.update()

    def _mapToDeviceLocal(self, mx, my):
        """Map coords to canvas-item local device coords."""
        pt = self.toCanvasCoordinates(QgsPointXY(mx, my))
        pos = self.pos()
        return pt.x() - pos.x(), pt.y() - pos.y()

    # ------------------------------------------------------------------
    # painting
    # ------------------------------------------------------------------

    def paint(self, painter, options, widget):
        if not self._points:
            return
        painter.save()
        try:
            self._drawLabels(painter)
        except Exception:
            # never let an exception escape a paint event
            pass
        painter.restore()

    def _drawLabels(self, painter):
        painter.setRenderHint(QPainter.Antialiasing, True)

        font = QFont(painter.font())
        font.setPointSizeF(9.0)
        font.setBold(True)
        painter.setFont(font)

        haloPen = QPen(_COLOR_HALO)
        haloPen.setWidthF(3.0)
        haloPen.setCapStyle(Qt.RoundCap)
        haloPen.setJoinStyle(Qt.RoundJoin)

        for mapPoint, number, enabled in self._points:
            try:
                x, y = self._mapToDeviceLocal(mapPoint.x(), mapPoint.y())
            except Exception:
                continue

            path = QPainterPath()
            path.addText(QPointF(x + _OFFSET_X, y + _OFFSET_Y), font, str(number))

            painter.setPen(haloPen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            painter.setPen(Qt.NoPen)
            painter.setBrush(_COLOR_ENABLED if enabled else _COLOR_DISABLED)
            painter.drawPath(path)
