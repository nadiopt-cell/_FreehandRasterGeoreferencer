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

import os.path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAction,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
)
from qgis.core import QgsApplication, QgsMapLayer, QgsPointXY, QgsProject

from . import tiepoints, utils
from .exportgeorefrasterdialog import ExportGeorefRasterDialog
from .freehandrastergeoreferencer_commands import ExportGeorefRasterCommand
from .freehandrastergeoreferencer_layer import (
    FreehandRasterGeoreferencerLayer,
    FreehandRasterGeoreferencerLayerType,
)
from .freehandrastergeoreferencer_maptools import (
    AdjustRasterMapTool,
    GeorefRasterBy2PointsMapTool,
    MoveRasterMapTool,
    RotateRasterMapTool,
    ScaleRasterMapTool,
)
from .freehandrastergeoreferencer_maptools_npoints import GeorefRasterByNPointsMapTool
from .freehandrastergeoreferencerdialog import FreehandRasterGeoreferencerDialog
from .georefpointsdockwidget import GeorefPointsDockWidget, RIGHT_DOCK_AREA


class FreehandRasterGeoreferencer(object):

    PLUGIN_MENU = "&Freehand Raster Georeferencer"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.layers = {}
        self.layer = None
        self._syncing = False
        QgsProject.instance().layerRemoved.connect(self.layerRemoved)
        self.iface.currentLayerChanged.connect(self.currentLayerChanged)

    def _icon(self, name):
        return utils.plugin_icon(self.plugin_dir, name)

    def initGui(self):
        # Create actions
        self.actionAddLayer = QAction(
            self._icon("iconAdd.png"),
            "Add raster for interactive georeferencing",
            self.iface.mainWindow(),
        )
        self.actionAddLayer.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_AddLayer"
        )
        self.actionAddLayer.triggered.connect(self.addLayer)

        self.actionMoveRaster = QAction(
            self._icon("iconMove.png"),
            "Move raster",
            self.iface.mainWindow(),
        )
        self.actionMoveRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_MoveRaster"
        )
        self.actionMoveRaster.triggered.connect(self.moveRaster)
        self.actionMoveRaster.setCheckable(True)

        self.actionRotateRaster = QAction(
            self._icon("iconRotate.png"),
            "Rotate raster",
            self.iface.mainWindow(),
        )
        self.actionRotateRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_RotateRaster"
        )
        self.actionRotateRaster.triggered.connect(self.rotateRaster)
        self.actionRotateRaster.setCheckable(True)

        self.actionScaleRaster = QAction(
            self._icon("iconScale.png"),
            "Scale raster",
            self.iface.mainWindow(),
        )
        self.actionScaleRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_ScaleRaster"
        )
        self.actionScaleRaster.triggered.connect(self.scaleRaster)
        self.actionScaleRaster.setCheckable(True)

        self.actionAdjustRaster = QAction(
            self._icon("iconAdjust.png"),
            "Adjust sides of raster",
            self.iface.mainWindow(),
        )
        self.actionAdjustRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_AdjustRaster"
        )
        self.actionAdjustRaster.triggered.connect(self.adjustRaster)
        self.actionAdjustRaster.setCheckable(True)

        self.actionGeoref2PRaster = QAction(
            self._icon("icon2Points.png"),
            "Georeference raster with 2 points",
            self.iface.mainWindow(),
        )
        self.actionGeoref2PRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_Georef2PRaster"
        )
        self.actionGeoref2PRaster.triggered.connect(self.georef2PRaster)
        self.actionGeoref2PRaster.setCheckable(True)

        self.actionGeorefNPRaster = QAction(
            self._icon("iconNPoints.png"),
            "Georeference raster with N points\n"
            "Drag raster features to their real location. "
            "Right click: remove / save / load points.",
            self.iface.mainWindow(),
        )
        self.actionGeorefNPRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_GeorefNPRaster"
        )
        self.actionGeorefNPRaster.triggered.connect(self.georefNPRaster)
        self.actionGeorefNPRaster.setCheckable(True)

        self.actionSaveTiePoints = QAction(
            "Save tie points...",
            self.iface.mainWindow(),
        )
        self.actionSaveTiePoints.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_SaveTiePoints"
        )
        self.actionSaveTiePoints.triggered.connect(self.saveTiePoints)

        self.actionLoadTiePoints = QAction(
            "Load tie points...",
            self.iface.mainWindow(),
        )
        self.actionLoadTiePoints.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_LoadTiePoints"
        )
        self.actionLoadTiePoints.triggered.connect(self.loadTiePoints)

        self.actionShowPointsDock = QAction(
            self._icon("iconPointsTable.png"),
            "Tie points panel\nShow or hide the panel with the table of "
            "tie points (enable / disable / remove points, live "
            "residuals) and the exact numeric transform controls "
            "(center, pixel sizes, RMS).",
            self.iface.mainWindow(),
        )
        self.actionShowPointsDock.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_ShowPointsDock"
        )
        self.actionShowPointsDock.setCheckable(True)
        self.actionShowPointsDock.triggered.connect(self.showPointsDock)

        self.actionIncreaseTransparency = QAction(
            self._icon("iconTransparencyIncrease.png"),
            "Increase transparency",
            self.iface.mainWindow(),
        )
        self.actionIncreaseTransparency.triggered.connect(self.increaseTransparency)
        self.actionIncreaseTransparency.setShortcut("Alt+Ctrl+N")

        self.actionDecreaseTransparency = QAction(
            self._icon("iconTransparencyDecrease.png"),
            "Decrease transparency",
            self.iface.mainWindow(),
        )
        self.actionDecreaseTransparency.triggered.connect(self.decreaseTransparency)
        self.actionDecreaseTransparency.setShortcut("Alt+Ctrl+B")

        self.actionExport = QAction(
            self._icon("iconExport.png"),
            "Export raster with world file",
            self.iface.mainWindow(),
        )
        self.actionExport.triggered.connect(self.exportGeorefRaster)

        self.actionUndo = QAction(
            self._icon("iconUndo.png"),
            u"Undo\nRevert the last action: move / rotate / scale / "
            u"adjust, adding, enabling, deleting, clearing or loading "
            u"tie points.",
            self.iface.mainWindow(),
        )
        self.actionUndo.triggered.connect(self.undo)

        # Add toolbar button and menu item for AddLayer
        self.iface.layerToolBar().addAction(self.actionAddLayer)
        self.iface.insertAddLayerAction(self.actionAddLayer)
        self.iface.addPluginToRasterMenu(
            FreehandRasterGeoreferencer.PLUGIN_MENU, self.actionAddLayer
        )
        self.iface.addPluginToRasterMenu(
            FreehandRasterGeoreferencer.PLUGIN_MENU, self.actionSaveTiePoints
        )
        self.iface.addPluginToRasterMenu(
            FreehandRasterGeoreferencer.PLUGIN_MENU, self.actionLoadTiePoints
        )
        self.iface.addPluginToRasterMenu(
            FreehandRasterGeoreferencer.PLUGIN_MENU, self.actionShowPointsDock
        )

        self.spinBoxRotate = QDoubleSpinBox(self.iface.mainWindow())
        self.spinBoxRotate.setDecimals(3)
        self.spinBoxRotate.setMinimum(-180)
        self.spinBoxRotate.setMaximum(180)
        self.spinBoxRotate.setSingleStep(0.1)
        self.spinBoxRotate.setValue(0.0)
        self.spinBoxRotate.setToolTip("Rotation value (-180 to 180)")
        self.spinBoxRotate.setObjectName("FreehandRasterGeoreferencer_spinbox")
        self.spinBoxRotate.setKeyboardTracking(False)
        self.spinBoxRotate.valueChanged.connect(self.spinBoxRotateValueChangeEvent)
        self.spinBoxRotate.setFocusPolicy(Qt.ClickFocus)
        self.spinBoxRotate.setFixedWidth(90)
        self.spinBoxRotate.focusInEvent = self.spinBoxRotateFocusInEvent

        # create toolbar for this plugin (kept compact: the exact numeric
        # controls live in the tie points panel, which is always visible
        # when open - a crowded toolbar hides its tail behind the >>
        # extension button)
        self.toolbar = self.iface.addToolBar("Freehand raster georeferencing")
        self.toolbar.addAction(self.actionAddLayer)
        self.toolbar.addAction(self.actionMoveRaster)
        self.toolbar.addAction(self.actionRotateRaster)
        self.toolbar.addWidget(self.spinBoxRotate)
        self.toolbar.addAction(self.actionScaleRaster)
        self.toolbar.addAction(self.actionAdjustRaster)
        self.toolbar.addAction(self.actionGeoref2PRaster)
        self.toolbar.addAction(self.actionGeorefNPRaster)
        self.toolbar.addAction(self.actionShowPointsDock)
        self.toolbar.addAction(self.actionDecreaseTransparency)
        self.toolbar.addAction(self.actionIncreaseTransparency)
        self.toolbar.addAction(self.actionExport)
        self.toolbar.addAction(self.actionUndo)

        # compact "values" toolbar: the exact numeric controls for move and
        # scale, next to the tools like the rotation spinbox. It lives in
        # its own narrow toolbar so it can be repositioned / hidden
        # independently and never pushes the tool buttons behind the >>
        # extension button of a crowded row (the reason why these controls
        # had to leave the main toolbar in 0.9.6)
        self.toolbarValues = self.iface.addToolBar(
            "Freehand raster georeferencing values"
        )
        self.toolbarValues.setObjectName("FreehandRasterGeoreferencingValues")

        def _valueSpin(minimum, maximum, step, objectName):
            spinBox = QDoubleSpinBox(self.iface.mainWindow())
            spinBox.setDecimals(6)
            spinBox.setMinimum(minimum)
            spinBox.setMaximum(maximum)
            spinBox.setSingleStep(step)
            spinBox.setKeyboardTracking(False)
            spinBox.setFocusPolicy(Qt.ClickFocus)
            spinBox.setFixedWidth(90)
            spinBox.setObjectName(objectName)
            return spinBox

        self.spinBoxCenterX = _valueSpin(
            -1e12, 1e12, 1.0, "FreehandRasterGeoreferencer_spinMoveX"
        )
        self.spinBoxCenterY = _valueSpin(
            -1e12, 1e12, 1.0, "FreehandRasterGeoreferencer_spinMoveY"
        )
        self.spinBoxScaleX = _valueSpin(
            1e-9, 1e9, 0.001, "FreehandRasterGeoreferencer_spinScaleX"
        )
        self.spinBoxScaleY = _valueSpin(
            1e-9, 1e9, 0.001, "FreehandRasterGeoreferencer_spinScaleY"
        )
        self.spinBoxCenterX.setToolTip(
            "Move X: X coordinate of the raster center (map units).\n"
            "Type a value for an exact horizontal placement."
        )
        self.spinBoxCenterY.setToolTip(
            "Move Y: Y coordinate of the raster center (map units).\n"
            "Type a value for an exact vertical placement."
        )
        self.spinBoxScaleX.setToolTip(
            "Scale X: pixel size in X, map units per pixel.\n"
            "Type a value for an exact horizontal scale."
        )
        self.spinBoxScaleY.setToolTip(
            "Scale Y: pixel size in Y, map units per pixel.\n"
            "Type a value for an exact vertical scale."
        )
        self.labelMoveX = QLabel("Move X", self.toolbarValues)
        self.labelMoveY = QLabel("Move Y", self.toolbarValues)
        self.labelScaleX = QLabel("Scale X", self.toolbarValues)
        self.labelScaleY = QLabel("Scale Y", self.toolbarValues)
        self.toolbarValues.addWidget(self.labelMoveX)
        self.toolbarValues.addWidget(self.spinBoxCenterX)
        self.toolbarValues.addWidget(self.labelMoveY)
        self.toolbarValues.addWidget(self.spinBoxCenterY)
        self.toolbarValues.addSeparator()
        self.toolbarValues.addWidget(self.labelScaleX)
        self.toolbarValues.addWidget(self.spinBoxScaleX)
        self.toolbarValues.addWidget(self.labelScaleY)
        self.toolbarValues.addWidget(self.spinBoxScaleY)
        self.spinBoxCenterX.valueChanged.connect(self.onToolbarCenterEdited)
        self.spinBoxCenterY.valueChanged.connect(self.onToolbarCenterEdited)
        self.spinBoxScaleX.valueChanged.connect(self.onToolbarPixelSizeEdited)
        self.spinBoxScaleY.valueChanged.connect(self.onToolbarPixelSizeEdited)

        # Register plugin layer type
        self.layerType = FreehandRasterGeoreferencerLayerType(self)
        QgsApplication.pluginLayerRegistry().addPluginLayerType(self.layerType)

        self.dialogAddLayer = FreehandRasterGeoreferencerDialog()
        self.dialogExportGeorefRaster = ExportGeorefRasterDialog()

        self.moveTool = MoveRasterMapTool(self.iface)
        self.moveTool.setAction(self.actionMoveRaster)
        self.rotateTool = RotateRasterMapTool(self.iface)
        self.rotateTool.setAction(self.actionRotateRaster)
        self.scaleTool = ScaleRasterMapTool(self.iface)
        self.scaleTool.setAction(self.actionScaleRaster)
        self.adjustTool = AdjustRasterMapTool(self.iface)
        self.adjustTool.setAction(self.actionAdjustRaster)
        self.georef2PTool = GeorefRasterBy2PointsMapTool(self.iface)
        self.georef2PTool.setAction(self.actionGeoref2PRaster)
        self.georefNPTool = GeorefRasterByNPointsMapTool(self.iface, self)
        self.georefNPTool.setAction(self.actionGeorefNPRaster)
        self.currentTool = None

        # tie points panel (QGIS georeferencer style GCP table + exact
        # numeric transform controls)
        self.dockPoints = GeorefPointsDockWidget(self.iface.mainWindow())
        self.iface.addDockWidget(RIGHT_DOCK_AREA, self.dockPoints)
        self.dockPoints.hide()
        self.dockPoints.visibilityChanged.connect(self._pointsDockVisibilityChanged)
        self.dockPoints.pointToggled.connect(self.dockPointToggled)
        self.dockPoints.pointsDeleted.connect(self.dockPointsDeleted)
        self.dockPoints.pointsCleared.connect(self.dockPointsCleared)
        self.dockPoints.spinBoxCenterX.valueChanged.connect(self.onCenterEdited)
        self.dockPoints.spinBoxCenterY.valueChanged.connect(self.onCenterEdited)
        self.dockPoints.spinBoxPxX.valueChanged.connect(self.onPixelSizeEdited)
        self.dockPoints.spinBoxPxY.valueChanged.connect(self.onPixelSizeEdited)
        self.dockPoints.fitModelChanged.connect(self.onFitModelChanged)

        # default state for toolbar
        self.checkCurrentLayerIsPluginLayer()

    def unload(self):
        # Remove the tie points dock
        if getattr(self, "dockPoints", None) is not None:
            self.iface.mainWindow().removeDockWidget(self.dockPoints)
            self.dockPoints.deleteLater()
            self.dockPoints = None

        # Remove the values toolbar
        if getattr(self, "toolbarValues", None) is not None:
            self.iface.mainWindow().removeToolBar(self.toolbarValues)
            del self.toolbarValues

        # Remove the plugin menu item and icon
        self.iface.layerToolBar().removeAction(self.actionAddLayer)
        self.iface.removeAddLayerAction(self.actionAddLayer)
        self.iface.removePluginRasterMenu(
            FreehandRasterGeoreferencer.PLUGIN_MENU, self.actionAddLayer
        )

        # Unregister plugin layer type
        QgsApplication.pluginLayerRegistry().removePluginLayerType(
            FreehandRasterGeoreferencerLayer.LAYER_TYPE
        )

        self.iface.removePluginRasterMenu(
            FreehandRasterGeoreferencer.PLUGIN_MENU, self.actionSaveTiePoints
        )
        self.iface.removePluginRasterMenu(
            FreehandRasterGeoreferencer.PLUGIN_MENU, self.actionLoadTiePoints
        )
        self.iface.removePluginRasterMenu(
            FreehandRasterGeoreferencer.PLUGIN_MENU, self.actionShowPointsDock
        )
        QgsProject.instance().layerRemoved.disconnect(self.layerRemoved)
        self.iface.currentLayerChanged.disconnect(self.currentLayerChanged)

        del self.toolbar

    def layerRemoved(self, layerId):
        if layerId in self.layers:
            del self.layers[layerId]
            self.checkCurrentLayerIsPluginLayer()

    def currentLayerChanged(self, layer):
        self.checkCurrentLayerIsPluginLayer()

    def checkCurrentLayerIsPluginLayer(self):
        layer = self.iface.activeLayer()
        if (
            layer
            and layer.type() == QgsMapLayer.PluginLayer
            and layer.pluginLayerType() == FreehandRasterGeoreferencerLayer.LAYER_TYPE
        ):
            self.actionMoveRaster.setEnabled(True)
            self.actionRotateRaster.setEnabled(True)
            self.actionScaleRaster.setEnabled(True)
            self.actionAdjustRaster.setEnabled(True)
            self.actionGeoref2PRaster.setEnabled(True)
            self.actionGeorefNPRaster.setEnabled(True)
            self.actionDecreaseTransparency.setEnabled(True)
            self.actionIncreaseTransparency.setEnabled(True)
            self.actionExport.setEnabled(True)
            self.actionSaveTiePoints.setEnabled(True)
            self.actionLoadTiePoints.setEnabled(True)
            self.actionShowPointsDock.setEnabled(True)
            self.spinBoxRotate.setEnabled(True)
            try:
                # self.layer is the previously selected layer
                # in case it was a FRGR layer, disconnect the widgets
                self.layer.transformParametersChanged.disconnect()
            except Exception:
                pass
            layer.transformParametersChanged.connect(self.updateTransformWidgets)
            self.dialogAddLayer.toolButtonAdvanced.setEnabled(True)
            self.actionUndo.setEnabled(True)
            self.layer = layer

            if self.currentTool:
                self.currentTool.reset()
                self.currentTool.setLayer(layer)
                if hasattr(self.currentTool, "refreshPoints"):
                    self.currentTool.refreshPoints()
            self.updateTransformWidgets()
        else:
            self.actionMoveRaster.setEnabled(False)
            self.actionRotateRaster.setEnabled(False)
            self.actionScaleRaster.setEnabled(False)
            self.actionAdjustRaster.setEnabled(False)
            self.actionGeoref2PRaster.setEnabled(False)
            self.actionGeorefNPRaster.setEnabled(False)
            self.actionDecreaseTransparency.setEnabled(False)
            self.actionIncreaseTransparency.setEnabled(False)
            self.actionExport.setEnabled(False)
            self.actionSaveTiePoints.setEnabled(False)
            self.actionLoadTiePoints.setEnabled(False)
            self.actionShowPointsDock.setEnabled(False)
            self.spinBoxRotate.setEnabled(False)
            self._setValueSpinsEnabled(False)
            self._setTransformWidgets(0, 0, 0.0, 1.0, 1.0, None)
            if getattr(self, "dockPoints", None) is not None:
                self.dockPoints.updatePanel(None)
            try:
                self.layer.transformParametersChanged.disconnect()
            except Exception:
                pass
            self.dialogAddLayer.toolButtonAdvanced.setEnabled(False)
            self.actionUndo.setEnabled(False)
            self.layer = None

            if self.currentTool:
                self.currentTool.reset()
                self.currentTool.setLayer(None)
                self._uncheckCurrentTool()

    def addLayer(self):
        self.dialogAddLayer.clear(self.layer)
        self.dialogAddLayer.show()
        result = self.dialogAddLayer.exec_()
        if result == QDialog.Accepted:
            self.createFreehandRasterGeoreferencerLayer()
        elif result == FreehandRasterGeoreferencerDialog.REPLACE:
            self.replaceImage()
        elif result == FreehandRasterGeoreferencerDialog.DUPLICATE:
            self.duplicateLayer()

    def replaceImage(self):
        imagepath = self.dialogAddLayer.lineEditImagePath.text()
        imagename, _ = os.path.splitext(os.path.basename(imagepath))
        self.layer.replaceImage(imagepath, imagename)

    def duplicateLayer(self):
        layer = self.iface.activeLayer().clone()
        QgsProject.instance().addMapLayer(layer)
        self.layers[layer.id()] = layer

    def createFreehandRasterGeoreferencerLayer(self):
        imagePath = self.dialogAddLayer.lineEditImagePath.text()
        imageName, _ = os.path.splitext(os.path.basename(imagePath))
        screenExtent = self.iface.mapCanvas().extent()

        layer = FreehandRasterGeoreferencerLayer(
            self, imagePath, imageName, screenExtent
        )
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            self.layers[layer.id()] = layer
            self.iface.setActiveLayer(layer)

    def _toggleTool(self, tool):
        if self.currentTool is tool:
            # Toggle
            self._uncheckCurrentTool()
        else:
            self.currentTool = tool
            layer = self.iface.activeLayer()
            tool.setLayer(layer)
            if hasattr(tool, "refreshPoints"):
                tool.refreshPoints()
            self.iface.mapCanvas().setMapTool(tool)

    def _uncheckCurrentTool(self):
        # Toggle
        self.iface.mapCanvas().unsetMapTool(self.currentTool)
        # replace tool with Pan
        self.iface.actionPan().trigger()
        self.currentTool = None

    def moveRaster(self):
        if self._manualToolBlockedByPolyMode():
            return
        self._toggleTool(self.moveTool)

    def rotateRaster(self):
        if self._manualToolBlockedByPolyMode():
            return
        self._toggleTool(self.rotateTool)

    def scaleRaster(self):
        if self._manualToolBlockedByPolyMode():
            return
        self._toggleTool(self.scaleTool)

    def adjustRaster(self):
        if self._manualToolBlockedByPolyMode():
            return
        self._toggleTool(self.adjustTool)

    def georef2PRaster(self):
        if self._manualToolBlockedByPolyMode():
            return
        self._toggleTool(self.georef2PTool)

    def _manualToolBlockedByPolyMode(self):
        """Manual transform tools cannot be used with a polynomial fit
        model (they would contradict the fitted polynomial)."""
        layer = getattr(self, "layer", None)
        if isinstance(layer, FreehandRasterGeoreferencerLayer) and layer.isPolyMode():
            self.iface.messageBar().pushMessage(
                "Freehand Raster Georeferencer",
                "Manual transform tools are disabled in polynomial fit mode: "
                "edit the tie points instead (a polynomial is refitted after "
                "every point change).",
                level=2,
                duration=5,
            )
            return True
        return False

    def georefNPRaster(self):
        self._toggleTool(self.georefNPTool)
        if self.actionGeorefNPRaster.isChecked():
            # show the points table together with the N-points tool
            if not self.dockPoints.isVisible():
                self.dockPoints.show()
            self.updateTransformWidgets()

    def showPointsDock(self):
        self.dockPoints.setVisible(self.actionShowPointsDock.isChecked())
        if self.actionShowPointsDock.isChecked():
            self.updateTransformWidgets()

    def _pointsDockVisibilityChanged(self, visible):
        # keep the toolbar action in sync when the user closes the dock
        if self.actionShowPointsDock.isChecked() != visible:
            wasBlocked = self.actionShowPointsDock.blockSignals(True)
            self.actionShowPointsDock.setChecked(visible)
            self.actionShowPointsDock.blockSignals(wasBlocked)

    def _pushUndoPointsState(self, layer):
        """Snapshot the tie points, the fit model and the transform into
        the layer history BEFORE a points edit, so that Undo can restore
        everything."""
        layer.history.append(
            {
                "action": "npfit",
                "center": layer.center,
                "rotation": layer.rotation,
                "xScale": layer.xScale,
                "yScale": layer.yScale,
                "fitModel": layer.fitModel,
                "polyCoeffs": list(layer.polyCoeffs)
                if layer.polyCoeffs
                else None,
                "tiePoints": [dict(p) for p in layer.tiePoints],
            }
        )

    def _refitAfterPointsEdit(self, layer):
        """Refit the transform from the tie points after a points edit
        and redraw everything (the caller pushes the undo entry)."""
        layer.applyTiePointFit()
        if isinstance(self.currentTool, GeorefRasterByNPointsMapTool):
            self.currentTool.refreshPoints()
        self.updateTransformWidgets()

    def onFitModelChanged(self, order):
        """Fit model combo changed in the tie points panel."""
        layer = getattr(self, "layer", None)
        if not isinstance(layer, FreehandRasterGeoreferencerLayer):
            return
        if layer.fitModel == order:
            return
        self._pushUndoPointsState(layer)
        layer.setFitModel(order)
        # the manual tools are meaningless in polynomial mode
        self._deactivateManualToolIfPoly(layer)
        self._refitAfterPointsEdit(layer)

    MANUAL_TOOLS = (
        "moveTool",
        "rotateTool",
        "scaleTool",
        "adjustTool",
        "georef2PTool",
    )

    def _deactivateManualToolIfPoly(self, layer):
        """Leave the current manual tool active when a polynomial fit model
        is selected (manual move / rotate / scale contradict the fitted
        polynomial)."""
        if layer is None or not layer.isPolyMode():
            return
        if self.currentTool is None:
            return
        if isinstance(self.currentTool, GeorefRasterByNPointsMapTool):
            return
        if any(
            self.currentTool is getattr(self, name, None)
            for name in self.MANUAL_TOOLS
        ):
            self._uncheckCurrentTool()

    def dockPointToggled(self, row, enabled):
        layer = getattr(self, "layer", None)
        if not isinstance(layer, FreehandRasterGeoreferencerLayer):
            return
        if not (0 <= row < len(layer.tiePoints)):
            return
        self._pushUndoPointsState(layer)
        layer.setTiePointEnabled(row, enabled)
        self._refitAfterPointsEdit(layer)

    def dockPointsDeleted(self, rows):
        layer = getattr(self, "layer", None)
        if not isinstance(layer, FreehandRasterGeoreferencerLayer):
            return
        valid = [
            row
            for row in sorted(rows)
            if 0 <= row < len(layer.tiePoints)
        ]
        if not valid:
            return
        # one undo step for the whole multi-row deletion
        self._pushUndoPointsState(layer)
        for row in sorted(valid, reverse=True):
            layer.removeTiePoint(row)
        self._refitAfterPointsEdit(layer)

    def dockPointsCleared(self):
        layer = getattr(self, "layer", None)
        if not isinstance(layer, FreehandRasterGeoreferencerLayer):
            return
        if not layer.tiePoints:
            return
        self._pushUndoPointsState(layer)
        layer.setTiePoints([])
        self._refitAfterPointsEdit(layer)

    def increaseTransparency(self):
        layer = self.iface.activeLayer()
        # clamp to 100
        tr = min(layer.transparency + 10, 100)
        layer.transparencyChanged(tr)

    def decreaseTransparency(self):
        layer = self.iface.activeLayer()
        # clamp to 0
        tr = max(layer.transparency - 10, 0)
        layer.transparencyChanged(tr)

    def exportGeorefRaster(self):
        layer = self.iface.activeLayer()
        self.dialogExportGeorefRaster.clear(layer)
        self.dialogExportGeorefRaster.show()
        result = self.dialogExportGeorefRaster.exec_()
        if result == 1:
            exportCommand = ExportGeorefRasterCommand(self.iface)
            exportCommand.exportGeorefRaster(
                layer,
                self.dialogExportGeorefRaster.imagePath,
                self.dialogExportGeorefRaster.isPutRotationInWorldFile,
                self.dialogExportGeorefRaster.isExportOnlyWorldFile,
                isExportCOG=self.dialogExportGeorefRaster.isExportCOG,
                resamplingMethod=self.dialogExportGeorefRaster.resamplingMethod,
                compression=self.dialogExportGeorefRaster.compression,
            )

    # ------------------------------------------------------------------
    # Numeric control widgets (exact input of move / scale / rotation)
    # The rotation spinbox stays in the (compact) main toolbar; the center
    # / pixel size controls live in the dedicated "values" toolbar and,
    # duplicated, in the tie points panel. All of them are kept in sync
    # through _setTransformWidgets (guarded by the _syncing flag).
    # ------------------------------------------------------------------

    def _setTransformWidgets(self, cx, cy, rotation, xScale, yScale, rms):
        self._syncing = True
        try:
            self.spinBoxRotate.setValue(rotation)
            for attr, value in (
                ("spinBoxCenterX", cx),
                ("spinBoxCenterY", cy),
                ("spinBoxScaleX", xScale),
                ("spinBoxScaleY", yScale),
            ):
                spinBox = getattr(self, attr, None)
                if spinBox is not None:
                    spinBox.setValue(value)
            if getattr(self, "dockPoints", None) is not None:
                self.dockPoints.setTransformValues(cx, cy, xScale, yScale, rms)
        finally:
            self._syncing = False

    def _setValueSpinsEnabled(self, enabled):
        """Enable / disable the numeric move & scale controls of the values
        toolbar (they are read-only in polynomial fit mode and without a
        plugin layer, like the transform group of the tie points panel)."""
        for attr in (
            "spinBoxCenterX",
            "spinBoxCenterY",
            "spinBoxScaleX",
            "spinBoxScaleY",
        ):
            spinBox = getattr(self, attr, None)
            if spinBox is not None:
                spinBox.setEnabled(enabled)

    def updateTransformWidgets(self, newParameters=None):
        """
        Sync the toolbar widgets and the tie points table with the active
        layer transform (called when the transform parameters changed).
        """
        layer = getattr(self, "layer", None)
        if not layer or getattr(layer, "image", None) is None:
            self._setValueSpinsEnabled(False)
            if getattr(self, "dockPoints", None) is not None:
                self.dockPoints.updatePanel(None)
            return
        residuals = []
        rms = None
        if len(layer.tiePoints) >= 1:
            residuals, rms = layer.tiePointResiduals()
            if len(layer.tiePoints) < 2:
                rms = None
        self._setValueSpinsEnabled(not layer.isPolyMode())
        self._setTransformWidgets(
            layer.center.x(),
            layer.center.y(),
            layer.rotation,
            layer.xScale,
            layer.yScale,
            rms,
        )
        if getattr(self, "dockPoints", None) is not None:
            self.dockPoints.updatePanel(layer, residuals)

    def onCenterEdited(self):
        """Center edited in the tie points panel."""
        if self._syncing:
            return
        if getattr(self, "dockPoints", None) is None:
            return
        self._applyCenter(
            self.dockPoints.spinBoxCenterX.value(),
            self.dockPoints.spinBoxCenterY.value(),
        )

    def onToolbarCenterEdited(self):
        """Center edited in the values toolbar."""
        if self._syncing:
            return
        self._applyCenter(
            self.spinBoxCenterX.value(), self.spinBoxCenterY.value()
        )

    def _applyCenter(self, centerX, centerY):
        layer = self.layer
        if not layer or getattr(layer, "image", None) is None:
            return
        if layer.isPolyMode():
            # read-only display in polynomial mode (handled by the disabled
            # widgets, this is a belt-and-braces guard)
            return
        layer.history.append({"action": "move", "center": layer.center})
        layer.setCenter(QgsPointXY(centerX, centerY))
        layer.repaint()
        layer.commitTransformParameters()

    def onPixelSizeEdited(self):
        """Pixel size edited in the tie points panel."""
        if self._syncing:
            return
        if getattr(self, "dockPoints", None) is None:
            return
        self._applyScale(
            self.dockPoints.spinBoxPxX.value(),
            self.dockPoints.spinBoxPxY.value(),
        )

    def onToolbarPixelSizeEdited(self):
        """Pixel size edited in the values toolbar."""
        if self._syncing:
            return
        self._applyScale(self.spinBoxScaleX.value(), self.spinBoxScaleY.value())

    def _applyScale(self, scaleX, scaleY):
        layer = self.layer
        if not layer or getattr(layer, "image", None) is None:
            return
        if layer.isPolyMode():
            # read-only display in polynomial mode (handled by the disabled
            # widgets, this is a belt-and-braces guard)
            return
        layer.history.append(
            {
                "action": "scale",
                "xScale": layer.xScale,
                "yScale": layer.yScale,
            }
        )
        layer.setScale(scaleX, scaleY)
        layer.repaint()
        layer.commitTransformParameters()

    def spinBoxRotateValueChangeEvent(self, val):
        if self._syncing:
            return
        layer = self.layer
        if not layer or getattr(layer, "image", None) is None:
            return
        if layer.isPolyMode():
            return
        layer.history.append(
            {"action": "rotation", "rotation": layer.rotation, "center": layer.center}
        )
        layer.setRotation(val)
        layer.repaint()
        layer.commitTransformParameters()

    # ------------------------------------------------------------------
    # Tie points save / load (QGIS georeferencer compatible .points CSV)
    # ------------------------------------------------------------------

    def _tiePointsDefaultPath(self, layer):
        try:
            return os.path.splitext(layer.getAbsoluteFilepath())[0] + ".points"
        except Exception:
            return ""

    def saveTiePoints(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, FreehandRasterGeoreferencerLayer):
            return
        path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save tie points",
            self._tiePointsDefaultPath(layer),
            "Tie points (*.points)",
        )
        if not path:
            return
        if not path.lower().endswith(".points"):
            path += ".points"
        try:
            residuals, _ = layer.tiePointResiduals()
            with open(path, "w") as writer:
                writer.write(tiepoints.to_csv(layer.tiePoints, residuals))
        except Exception as ex:
            self.iface.messageBar().pushMessage(
                "Freehand Raster Georeferencer",
                "Unable to save tie points: %s" % ex,
                level=3,
                duration=5,
            )
            return
        self.iface.messageBar().pushMessage(
            "Freehand Raster Georeferencer",
            "%d tie point(s) saved to %s" % (len(layer.tiePoints), path),
            level=1,
            duration=4,
        )

    def loadTiePoints(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, FreehandRasterGeoreferencerLayer):
            return
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Load tie points",
            self._tiePointsDefaultPath(layer),
            "Tie points (*.points *.csv *.txt)",
        )
        if not path:
            return
        try:
            with open(path) as reader:
                points = tiepoints.from_csv(reader.read())
        except Exception as ex:
            self.iface.messageBar().pushMessage(
                "Freehand Raster Georeferencer",
                "Unable to load tie points: %s" % ex,
                level=3,
                duration=5,
            )
            return
        if not points:
            self.iface.messageBar().pushMessage(
                "Freehand Raster Georeferencer",
                "No valid tie point found in %s" % path,
                level=1,
                duration=5,
            )
            return
        layer.history.append(
            {
                "action": "npfit",
                "center": layer.center,
                "rotation": layer.rotation,
                "xScale": layer.xScale,
                "yScale": layer.yScale,
                "fitModel": layer.fitModel,
                "polyCoeffs": list(layer.polyCoeffs)
                if layer.polyCoeffs
                else None,
                "tiePoints": [dict(p) for p in layer.tiePoints],
            }
        )
        layer.setTiePoints(points)
        fitted = layer.applyTiePointFit()
        if self.currentTool and hasattr(self.currentTool, "refreshPoints"):
            self.currentTool.refreshPoints()
        if fitted:
            _, rms = layer.tiePointResiduals()
            self.iface.messageBar().pushMessage(
                "Freehand Raster Georeferencer",
                "%d tie point(s) loaded, RMS = %.3f map units"
                % (len(points), rms),
                level=1,
                duration=5,
            )
        else:
            self.iface.messageBar().pushMessage(
                "Freehand Raster Georeferencer",
                "%d tie point(s) loaded (2 points minimum needed to "
                "georeference)" % len(points),
                level=1,
                duration=5,
            )
        self.updateTransformWidgets()

    def spinBoxRotateFocusInEvent(self, event):
        # for clear 2point rubberband
        if self.currentTool:
            layer = self.iface.activeLayer()
            self.currentTool.reset()
            self.currentTool.setLayer(layer)

    def undo(self):
        layer = self.iface.activeLayer()
        if self.currentTool:
            self.currentTool.reset()  # for clear 2point rubberband
            self.currentTool.setLayer(layer)
        if layer is None or len(layer.history) == 0:
            return
        act = layer.history.pop()
        if "tiePoints" in act:
            # restore the tie points as they were before the action
            # (add / toggle / delete / clear / load / model change)
            layer.setTiePoints([dict(p) for p in act["tiePoints"]])
        if "fitModel" in act:
            # restore the fit model + polynomial coefficients (if any) as
            # they were before the action
            layer.fitModel = act["fitModel"]
            layer.polyCoeffs = (
                list(act["polyCoeffs"]) if act["polyCoeffs"] else None
            )
        if act["action"] == "move":
            layer.setCenter(act["center"])
        elif act["action"] == "scale":
            layer.setScale(act["xScale"], act["yScale"])
        elif act["action"] == "rotation":
            layer.setRotation(act["rotation"])
            layer.setCenter(act["center"])
        elif act["action"] == "adjust":
            layer.setCenter(act["center"])
            layer.setScale(act["xScale"], act["yScale"])
        elif act["action"] == "2pointsA":
            layer.setCenter(act["center"])
        elif act["action"] == "2pointsB":
            layer.setRotation(act["rotation"])
            layer.setCenter(act["center"])
            layer.setScale(act["xScale"], act["yScale"])
        elif act["action"] == "npfit":
            layer.setCenter(act["center"])
            layer.setRotation(act["rotation"])
            layer.setScale(act["xScale"], act["yScale"])
        layer.repaint()
        layer.commitTransformParameters()
        if self.currentTool and hasattr(self.currentTool, "refreshPoints"):
            # redraw the target markers / residual links at the restored
            # points and transform
            self.currentTool.refreshPoints()
