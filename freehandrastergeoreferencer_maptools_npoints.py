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

Workflow (like the classic QGIS georeferencer "add point" tool, but live):
1. Left click on a feature of the raster: the source pixel is picked and
   the raster is hidden so the map underneath is visible.
2. Left click on the correct location on the map: the pair (source
   pixel, target map position) is added to the tie points table and the
   transform is refitted immediately - the raster moves to its newly
   calculated position. The tool is then ready for the next pair.

The drag gesture is also supported: press on a raster feature, drag it
to its real location and release to create the pair in one gesture.
A simple click (press + release without moving) never creates a point
by itself: it only advances the two-click sequence.

Esc cancels the pending source point. Right click opens a menu to remove
the last point, clear all points or save/load the points to/from a
.points file. Any number of points can be added; with 2 points a
similarity fit is applied, with 3+ points a least-squares anisotropic
scaled-rotation fit (the model of the layer).
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMenu
from qgis.core import QgsPointXY
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand

try:  # scoped enums: PyQt6 style (also available in recent PyQt5)
    _LEFT_BUTTON = Qt.MouseButton.LeftButton
    _RIGHT_BUTTON = Qt.MouseButton.RightButton
    _ESC_KEY = Qt.Key.Key_Escape
except AttributeError:  # pragma: no cover - old PyQt5 fallback
    _LEFT_BUTTON = Qt.LeftButton
    _RIGHT_BUTTON = Qt.RightButton
    _ESC_KEY = Qt.Key_Escape

# drag shorter than this (canvas pixels) is a simple click, not a drag
_DRAG_THRESHOLD_PX = 4


def _isLayerVisible(iface, layer):
    vl = iface.layerTreeView().layerTreeModel().rootGroup().findLayer(layer)
    return vl.itemVisibilityChecked()


def _setLayerVisible(iface, layer, visible):
    vl = iface.layerTreeView().layerTreeModel().rootGroup().findLayer(layer)
    vl.setItemVisibilityChecked(visible)


class GeorefRasterByNPointsMapTool(QgsMapToolEmitPoint):
    """Two-click tie point picking: first click on the raster (source
    pixel), second click on the map (target). The raster is refitted and
    moved immediately after every pair. Drag press-move-release works
    too; a plain click never adds a point on its own."""

    _STATE_PICK_SOURCE = 0
    _STATE_PICK_TARGET = 1

    def __init__(self, iface, plugin):
        self.iface = iface
        self.plugin = plugin
        self.canvas = iface.mapCanvas()
        QgsMapToolEmitPoint.__init__(self, self.canvas)

        # pending source point (picked on the raster, waiting for target)
        self.rubberBandPending = QgsRubberBand(self.canvas, self._pointGeometry())
        self.rubberBandPending.setColor(Qt.yellow)
        self.rubberBandPending.setIcon(QgsRubberBand.ICON_CIRCLE)
        self.rubberBandPending.setIconSize(9)
        self.rubberBandPending.setWidth(2)

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

        # source -> cursor line while picking the target
        self.rubberBandDrag = QgsRubberBand(self.canvas, self._lineGeometry())
        self.rubberBandDrag.setColor(Qt.yellow)
        self.rubberBandDrag.setWidth(1)

        self._wasLayerVisible = True
        self._layerHidden = False
        self._dragOngoing = False
        self._dragStartScreenPos = None
        self.pickState = self._STATE_PICK_SOURCE
        self.pendingPixel = None

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
        """Cancel the pending point and clear the canvas decorations."""
        self._cancelPending()
        self.rubberBandResiduals.reset(self._lineGeometry())
        self.rubberBandTargets.reset(self._pointGeometry())
        self.layer = None

    def deactivate(self):
        QgsMapToolEmitPoint.deactivate(self)
        self.reset()

    def activate(self):
        QgsMapToolEmitPoint.activate(self)
        self._showHint(
            "Click a point on the raster, then click its correct location "
            "on the map. Right click: menu. Esc: cancel the current point.",
            6,
        )

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    def canvasPressEvent(self, e):
        if e.button() == _RIGHT_BUTTON:
            self._cancelPending()
            self._showContextMenu(e)
            return
        if e.button() != _LEFT_BUTTON:
            return
        layer = self.layer
        if layer is None or getattr(layer, "image", None) is None:
            return

        if self.pickState == self._STATE_PICK_SOURCE:
            self._pickSource(e)
        else:
            self._pickTarget(e)

    def canvasMoveEvent(self, e):
        if self.pickState != self._STATE_PICK_TARGET or self.pendingPixel is None:
            return
        layer = self.layer
        if layer is None:
            return
        pos = self.toMapCoordinates(e.pos())
        self.rubberBandDrag.reset(self._lineGeometry())
        self.rubberBandDrag.addPoint(layer.pixelToMap(*self.pendingPixel), False)
        self.rubberBandDrag.addPoint(QgsPointXY(pos), True)
        self.rubberBandDrag.show()

    def canvasReleaseEvent(self, e):
        if e.button() != _LEFT_BUTTON or not self._dragOngoing:
            return
        self._dragOngoing = False
        if self.pickState != self._STATE_PICK_TARGET or self.layer is None:
            return
        # if the cursor barely moved since the source press, this was a
        # simple click: keep waiting for the target click (a plain click
        # never creates a pair by itself)
        delta = e.pos() - self._dragStartScreenPos
        if delta.manhattanLength() < _DRAG_THRESHOLD_PX:
            return
        self._createPair(self.toMapCoordinates(e.pos()))

    def keyPressEvent(self, e):
        if e.key() == _ESC_KEY and self.pickState == self._STATE_PICK_TARGET:
            self._cancelPending()
            self._showHint("Current tie point cancelled.", 3)
            return
        QgsMapToolEmitPoint.keyPressEvent(self, e)

    # ------------------------------------------------------------------
    # picking (two-click workflow)
    # ------------------------------------------------------------------

    def _pickSource(self, e):
        layer = self.layer
        pos = self.toMapCoordinates(e.pos())
        px, py = layer.mapToPixel(pos.x(), pos.y())
        # accept any click on the raster (pixel-center convention: the
        # centers of the first/last pixels are 0 and size - 1)
        if not (
            -0.5 <= px <= layer.image.width() - 0.5
            and -0.5 <= py <= layer.image.height() - 0.5
        ):
            self._showHint("Click on the raster layer to pick the source point.", 3)
            return

        self.pendingPixel = (px, py)
        self.pickState = self._STATE_PICK_TARGET
        self._dragOngoing = True
        self._dragStartScreenPos = e.pos()

        # hide the raster so the map underneath (the target area) is
        # visible; the source point stays marked on the canvas
        self._wasLayerVisible = _isLayerVisible(self.iface, layer)
        _setLayerVisible(self.iface, layer, False)
        self._layerHidden = True

        self.rubberBandPending.reset(self._pointGeometry())
        self.rubberBandPending.addPoint(layer.pixelToMap(px, py), True)
        self.rubberBandPending.show()

    def _pickTarget(self, e):
        self._dragOngoing = False
        self._createPair(self.toMapCoordinates(e.pos()))

    def _createPair(self, target):
        """Store the pair (pending source pixel, target map position),
        refit the transform from all the points and move the raster."""
        layer = self.layer
        if layer is None or self.pendingPixel is None:
            return
        px, py = self.pendingPixel
        points = list(layer.tiePoints)
        points.append({"px": px, "py": py, "mx": target.x(), "my": target.y()})
        layer.setTiePoints(points)
        # refit + undo entry + canvas markers + points table refresh
        self.plugin._refitAfterPointsEdit(layer)

        self._cancelPending()

        message = "Tie point %d added" % len(points)
        if len(points) >= 2:
            _, rms = layer.tiePointResiduals()
            message += " (RMS = %.3f map units)" % rms
        else:
            message += " - add one more point to place the raster"
        self._showHint(message, 4)

    def _cancelPending(self):
        """Abort the current two-click sequence and restore the raster."""
        layer = getattr(self, "layer", None)
        if layer is not None and getattr(self, "_layerHidden", False):
            _setLayerVisible(self.iface, layer, self._wasLayerVisible)
        self._layerHidden = False
        self._dragOngoing = False
        self._dragStartScreenPos = None
        self.pickState = self._STATE_PICK_SOURCE
        self.pendingPixel = None
        self.rubberBandDrag.reset(self._lineGeometry())
        self.rubberBandPending.reset(self._pointGeometry())

    def _showHint(self, text, duration):
        self.iface.messageBar().pushMessage(
            "Freehand Raster Georeferencer", text, level=0, duration=duration
        )

    # ------------------------------------------------------------------
    # display
    # ------------------------------------------------------------------

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
        points = list(self.layer.tiePoints)[:-1]
        self.layer.setTiePoints(points)
        # refit (if still possible) + markers + points table refresh
        self.plugin._refitAfterPointsEdit(self.layer)

    def clearPoints(self):
        if self.layer is None:
            return
        self.layer.setTiePoints([])
        self.plugin._refitAfterPointsEdit(self.layer)
