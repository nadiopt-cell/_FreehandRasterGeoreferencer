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

"""
Interactive georeferencing of a raster with an unlimited number of tie
points.

Workflow: click on a feature of the raster, drag it to its correct location
and release. The pair is stored (pixel coordinates of the source + target
map coordinates) and the transform is refitted immediately. Any number of
points can be added; with 2 points a similarity fit is applied, with 3+
points a least-squares anisotropic scaled-rotation fit (the model of the
layer). Right click opens a menu to remove the last point, clear all
points or save/load the points to/from a .points file.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMenu
from qgis.core import QgsPointXY
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand

try:  # scoped enums: PyQt6 style (also available in recent PyQt5)
    _LEFT_BUTTON = Qt.MouseButton.LeftButton
    _RIGHT_BUTTON = Qt.MouseButton.RightButton
except AttributeError:  # pragma: no cover - old PyQt5 fallback
    _LEFT_BUTTON = Qt.LeftButton
    _RIGHT_BUTTON = Qt.RightButton

from .freehandrastergeoreferencer_maptools import (
    isLayerVisible as _isLayerVisible,
    setLayerVisible as _setLayerVisible,
)
from .rastershadowmapcanvasitem import RasterShadowMapCanvasItem


class GeorefRasterByNPointsMapTool(QgsMapToolEmitPoint):
    def __init__(self, iface, plugin):
        self.iface = iface
        self.plugin = plugin
        self.canvas = iface.mapCanvas()
        QgsMapToolEmitPoint.__init__(self, self.canvas)

        self.rasterShadow = RasterShadowMapCanvasItem(self.canvas)

        # circles on the target positions
        self.rubberBandTargets = QgsRubberBand(self.canvas, self._pointGeometry())
        self.rubberBandTargets.setColor(Qt.red)
        self.rubberBandTargets.setIcon(QgsRubberBand.ICON_CIRCLE)
        self.rubberBandTargets.setIconSize(7)
        self.rubberBandTargets.setWidth(2)

        # residual links: predicted position -> target
        self.rubberBandResiduals = QgsRubberBand(self.canvas, self._lineGeometry())
        self.rubberBandResiduals.setColor(Qt.red)
        self.rubberBandResiduals.setWidth(1)

        # current drag line
        self.rubberBandDrag = QgsRubberBand(self.canvas, self._lineGeometry())
        self.rubberBandDrag.setColor(Qt.yellow)
        self.rubberBandDrag.setWidth(1)

        self.isLayerVisible = True

        self.reset()

    @staticmethod
    def _lineGeometry():
        try:
            from qgis.core import Qgis

            return Qgis.LineGeometry
        except (ImportError, AttributeError):
            from qgis.core import QgsWkbTypes

            return QgsWkbTypes.LineGeometry

    def _pointGeometry(self):
        try:
            from qgis.core import Qgis

            return Qgis.PointGeometry
        except (ImportError, AttributeError):
            from qgis.core import QgsWkbTypes

            return QgsWkbTypes.PointGeometry

    def setLayer(self, layer):
        self.layer = layer

    def reset(self):
        self.isDragging = False
        self.startPoint = None
        self.endPoint = None
        self.rubberBandDrag.reset(self._lineGeometry())
        self.rubberBandResiduals.reset(self._lineGeometry())
        self.rubberBandTargets.reset(self._pointGeometry())
        self.rasterShadow.reset()
        self.layer = None

    def deactivate(self):
        QgsMapToolEmitPoint.deactivate(self)
        self.reset()

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    def canvasPressEvent(self, e):
        if e.button() == _RIGHT_BUTTON:
            self._showContextMenu(e)
            return
        if e.button() != _LEFT_BUTTON:
            return
        if self.layer is None:
            return

        self.isDragging = True
        self.startPoint = self.toMapCoordinates(e.pos())
        self.endPoint = self.startPoint

        self.isLayerVisible = _isLayerVisible(self.iface, self.layer)
        _setLayerVisible(self.iface, self.layer, False)

        self._showDrag(self.startPoint, self.endPoint)

    def canvasMoveEvent(self, e):
        if not self.isDragging:
            return
        self.endPoint = self.toMapCoordinates(e.pos())
        self._showDrag(self.startPoint, self.endPoint)

    def canvasReleaseEvent(self, e):
        if e.button() == _RIGHT_BUTTON or not self.isDragging:
            return

        self.isDragging = False
        self.rubberBandDrag.reset(self._lineGeometry())
        self.rasterShadow.reset()

        target = self.toMapCoordinates(e.pos())

        # pixel of the pressed point, computed with the transform in effect
        # BEFORE the refit
        px, py = self.layer.mapToPixel(self.startPoint.x(), self.startPoint.y())

        # undo entry (state before this point moves the raster; the
        # tie points snapshot lets Undo also remove the added point)
        self.layer.pushHistory(
            {
                "action": "npfit",
                "center": self.layer.center,
                "rotation": self.layer.rotation,
                "xScale": self.layer.xScale,
                "yScale": self.layer.yScale,
                "fitModel": self.layer.fitModel,
                "polyCoeffs": list(self.layer.polyCoeffs)
                if self.layer.polyCoeffs
                else None,
                "tiePoints": [dict(p) for p in self.layer.tiePoints],
            }
        )

        points = list(self.layer.tiePoints)
        points.append({"px": px, "py": py, "mx": target.x(), "my": target.y()})
        self.layer.setTiePoints(points)
        self.layer.applyTiePointFit()

        _setLayerVisible(self.iface, self.layer, self.isLayerVisible)
        self.layer.repaint()

        self.refreshPoints()

    # ------------------------------------------------------------------
    # display
    # ------------------------------------------------------------------

    def _showDrag(self, startPoint, endPoint):
        self.rubberBandDrag.reset(self._lineGeometry())
        self.rubberBandDrag.addPoint(QgsPointXY(startPoint), False)
        self.rubberBandDrag.addPoint(QgsPointXY(endPoint), True)
        self.rubberBandDrag.show()

        self.rasterShadow.reset(self.layer)
        self.rasterShadow.setDeltaDisplacement(
            endPoint.x() - startPoint.x(),
            endPoint.y() - startPoint.y(),
            True,
        )
        self.rasterShadow.show()

    def refreshPoints(self):
        """Redraw target markers and residual links for all stored points."""
        self.rubberBandTargets.reset(self._pointGeometry())
        self.rubberBandResiduals.reset(self._lineGeometry())

        if self.layer is None:
            return

        pairs = []
        for point in self.layer.tiePoints:
            if not point.get("en", True):
                # disabled point: excluded from the fit, markers are not
                # drawn on the canvas (it stays visible in the points table)
                continue
            predicted = self.layer.pixelToMap(point["px"], point["py"])
            target = QgsPointXY(point["mx"], point["my"])
            pairs.append((predicted, target))

        count = len(pairs)
        for i, (predicted, target) in enumerate(pairs):
            is_last = i == count - 1
            self.rubberBandResiduals.addPoint(predicted, False)
            # true on the last pair to trigger the rubber band update
            self.rubberBandResiduals.addPoint(target, is_last)
            if not is_last:
                self.rubberBandTargets.addPoint(target, False)
        if count:
            # same for the targets band
            self.rubberBandTargets.addPoint(pairs[-1][1], True)

        self.rubberBandTargets.show()
        self.rubberBandResiduals.show()

    # ------------------------------------------------------------------
    # context menu / point management
    # ------------------------------------------------------------------

    def _showContextMenu(self, e):
        menu = QMenu()
        actionRemove = menu.addAction("Remove last point")
        actionClear = menu.addAction("Clear all points")
        menu.addSeparator()
        actionSave = menu.addAction("Save points to file...")
        actionLoad = menu.addAction("Load points from file...")

        hasPoints = bool(self.layer.tiePoints) if self.layer else False
        actionRemove.setEnabled(hasPoints)
        actionClear.setEnabled(hasPoints)

        action = menu.exec_(e.globalPos())
        if action == actionRemove:
            self.removeLastPoint()
        elif action == actionClear:
            self.clearPoints()
        elif action == actionSave:
            self.plugin.saveTiePoints()
        elif action == actionLoad:
            self.plugin.loadTiePoints()

    def removeLastPoint(self):
        if self.layer is None or not self.layer.tiePoints:
            return
        self.plugin._pushUndoPointsState(self.layer)
        points = list(self.layer.tiePoints)[:-1]
        self.layer.setTiePoints(points)
        # refit (if still possible) + markers + points table refresh
        self.plugin._refitAfterPointsEdit(self.layer)

    def clearPoints(self):
        if self.layer is None:
            return
        self.plugin._pushUndoPointsState(self.layer)
        self.layer.setTiePoints([])
        self.plugin._refitAfterPointsEdit(self.layer)
