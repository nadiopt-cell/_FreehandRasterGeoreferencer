"""
/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainter
from qgis.core import QgsPointXY, QgsRectangle
from qgis.gui import QgsMapCanvasItem

from . import polymesh, transform_math


class RasterShadowMapCanvasItem(QgsMapCanvasItem):
    def __init__(self, canvas):
        QgsMapCanvasItem.__init__(self, canvas)

        self.canvas = canvas
        self.reset()

    def reset(self, layer=None):
        self.layer = layer
        self.setVisible(False)

        self.dx = 0
        self.dy = 0
        self.drotation = 0
        self.fxscale = 1
        self.fyscale = 1

    def setDeltaDisplacement(self, dx, dy, doUpdate):
        self.dx = dx
        self.dy = dy
        if doUpdate:
            self.setVisible(self.layer is None)
            self.updateRect()
            self.update()

    def setDeltaRotation(self, rotation, doUpdate):
        self.drotation = rotation
        if doUpdate:
            self.updateRect()
            self.update()

    def setDeltaRotationFromPoint(self, rotation, startPoint, doUpdate):
        # Rotation around a point other than center of raster
        self.drotation = rotation
        if doUpdate:
            self.updateRectFromPoint(startPoint)
            self.update()

    def setDeltaScale(self, xscale, yscale, doUpdate):
        self.fxscale = xscale
        self.fyscale = yscale
        if doUpdate:
            self.updateRect()
            self.update()

    def updateRect(self):
        if self.layer is None:
            return
        if self._polyActive():
            minX, minY, maxX, maxY = polymesh.warped_bounds(
                self._polyPixelToMap(),
                self.layer.image.width(),
                self.layer.image.height(),
            )
            self.setRect(QgsRectangle(minX, minY, maxX, maxY))
            return

        topLeft, topRight, bottomRight, bottomLeft = self.cornerCoordinates()

        left = min(topLeft.x(), topRight.x(), bottomRight.x(), bottomLeft.x())
        right = max(topLeft.x(), topRight.x(), bottomRight.x(), bottomLeft.x())
        top = max(topLeft.y(), topRight.y(), bottomRight.y(), bottomLeft.y())
        bottom = min(topLeft.y(), topRight.y(), bottomRight.y(), bottomLeft.y())

        self.setRect(QgsRectangle(left, bottom, right, top))

    def updateRectFromPoint(self, startPoint):
        topLeft, topRight, bottomRight, bottomLeft = self.cornerCoordinatesFromPoint(
            startPoint
        )

        left = min(topLeft.x(), topRight.x(), bottomRight.x(), bottomLeft.x())
        right = max(topLeft.x(), topRight.x(), bottomRight.x(), bottomLeft.x())
        top = max(topLeft.y(), topRight.y(), bottomRight.y(), bottomLeft.y())
        bottom = min(topLeft.y(), topRight.y(), bottomRight.y(), bottomLeft.y())

        self.setRect(QgsRectangle(left, bottom, right, top))

    def cornerCoordinates(self):
        center = QgsPointXY(
            self.layer.center.x() + self.dx, self.layer.center.y() + self.dy
        )
        return self.layer.transformedCornerCoordinates(
            center,
            self.layer.rotation + self.drotation,
            self.layer.xScale * self.fxscale,
            self.layer.yScale * self.fyscale,
        )

    # ------------------------------------------------------------------
    # polynomial mode helpers (used by the N-points tool drag preview)
    # ------------------------------------------------------------------

    def _polyActive(self):
        return (
            self.layer is not None
            and self.layer.isPolyMode()
            and self.layer.polyFit() is not None
        )

    def _polyPixelToMap(self):
        """The layer polynomial shifted by the current drag displacement."""
        fit = self.layer.polyFit()
        w = self.layer.image.width()
        h = self.layer.image.height()
        dx = self.dx
        dy = self.dy

        def fn(px, py):
            mx, my = transform_math.poly_pixel_to_map(px, py, fit, w, h)
            return mx + dx, my + dy

        return fn

    def _mapToDeviceLocal(self, mx, my):
        """Map coords to canvas-item local device coords."""
        pt = self.toCanvasCoordinates(QgsPointXY(mx, my))
        pos = self.pos()
        return pt.x() - pos.x(), pt.y() - pos.y()

    def cornerCoordinatesFromPoint(self, startPoint):
        return self.layer.transformedCornerCoordinatesFromPoint(
            startPoint, self.drotation, 1, 1
        )

    def paint(self, painter, options, widget):
        if self.layer is None:
            # nothing to preview (reset state / layer removed)
            return
        painter.save()
        self.prepareStyle(painter)
        try:
            self.drawRaster(painter)
        except Exception:
            # never let an exception escape a paint event: it can take
            # down the whole application
            pass
        painter.restore()

    def drawRaster(self, painter):
        if (
            self.layer is None
            or getattr(self.layer, "image", None) is None
            or self.layer.image.isNull()
        ):
            return

        mapUPerPixel = self.canvas.mapUnitsPerPixel()
        if mapUPerPixel <= 0:
            # degenerate canvas state
            return

        if self._polyActive():
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            polymesh.draw_warped_raster(
                painter,
                self.layer.image,
                self._polyPixelToMap(),
                self._mapToDeviceLocal,
                self.layer.image.width(),
                self.layer.image.height(),
            )
            return

        scaleX = self.layer.xScale * self.fxscale / mapUPerPixel
        scaleY = self.layer.yScale * self.fyscale / mapUPerPixel

        rect = QRectF(
            QPointF(-self.layer.image.width() / 2.0, -self.layer.image.height() / 2.0),
            QPointF(self.layer.image.width() / 2.0, self.layer.image.height() / 2.0),
        )
        targetRect = self.boundingRect()

        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # draw the image on the canvas item rectangle
        # center displacement already taken into account in canvas
        # item rectangle so no update
        painter.translate(targetRect.center())
        painter.rotate(self.layer.rotation + self.drotation)
        painter.scale(scaleX, scaleY)
        painter.drawImage(rect, self.layer.image)

    def prepareStyle(self, painter):
        painter.setOpacity(min(0.5, 1 - self.layer.transparency / 100.0))
