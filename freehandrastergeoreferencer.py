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
from PyQt5.QtWidgets import QAction, QDialog, QDoubleSpinBox, QFileDialog, QLabel
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
            "Tie points table\nShow or hide the table of tie points "
            "(enable / disable / remove points, live residuals).",
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
            u"Undo",
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
        self.spinBoxRotate.focusInEvent = self.spinBoxRotateFocusInEvent

        # numeric control widgets (exact input of move / scale)
        self.spinBoxCenterX = self._createParamSpinBox(-1e12, 1e12, 6, 1.0)
        self.spinBoxCenterY = self._createParamSpinBox(-1e12, 1e12, 6, 1.0)
        self.spinBoxPxX = self._createParamSpinBox(1e-9, 1e9, 6, 0.001)
        self.spinBoxPxY = self._createParamSpinBox(1e-9, 1e9, 6, 0.001)

        self.spinBoxCenterX.setToolTip("X coordinate of the raster center (map units)")
        self.spinBoxCenterY.setToolTip("Y coordinate of the raster center (map units)")
        self.spinBoxPxX.setToolTip(
            "Pixel size in X: map units per pixel of the raster (xScale)"
        )
        self.spinBoxPxY.setToolTip(
            "Pixel size in Y: map units per pixel of the raster (yScale)"
        )

        self.spinBoxCenterX.valueChanged.connect(self.onCenterEdited)
        self.spinBoxCenterY.valueChanged.connect(self.onCenterEdited)
        self.spinBoxPxX.valueChanged.connect(self.onPixelSizeEdited)
        self.spinBoxPxY.valueChanged.connect(self.onPixelSizeEdited)

        self.labelCenterX = QLabel("X:", self.iface.mainWindow())
        self.labelCenterY = QLabel("Y:", self.iface.mainWindow())
        self.labelPxX = QLabel("Px X:", self.iface.mainWindow())
        self.labelPxY = QLabel("Px Y:", self.iface.mainWindow())
        self.labelRms = QLabel("", self.iface.mainWindow())
        self.labelRms.setToolTip(
            "Root mean square residual of the tie points, in map units "
            "(shown when 2 or more tie points are set)"
        )

        # create toolbar for this plugin
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
        self.toolbar.addWidget(self.labelCenterX)
        self.toolbar.addWidget(self.spinBoxCenterX)
        self.toolbar.addWidget(self.labelCenterY)
        self.toolbar.addWidget(self.spinBoxCenterY)
        self.toolbar.addWidget(self.labelPxX)
        self.toolbar.addWidget(self.spinBoxPxX)
        self.toolbar.addWidget(self.labelPxY)
        self.toolbar.addWidget(self.spinBoxPxY)
        self.toolbar.addAction(self.actionDecreaseTransparency)
        self.toolbar.addAction(self.actionIncreaseTransparency)
        self.toolbar.addAction(self.actionExport)
        self.toolbar.addAction(self.actionUndo)
        self.toolbar.addWidget(self.labelRms)

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

        # tie points table dock (QGIS georeferencer style GCP table)
        self.dockPoints = GeorefPointsDockWidget(self.iface.mainWindow())
        self.iface.addDockWidget(RIGHT_DOCK_AREA, self.dockPoints)
        self.dockPoints.hide()
        self.dockPoints.visibilityChanged.connect(self._pointsDockVisibilityChanged)
        self.dockPoints.pointToggled.connect(self.dockPointToggled)
        self.dockPoints.pointsDeleted.connect(self.dockPointsDeleted)
        self.dockPoints.pointsCleared.connect(self.dockPointsCleared)

        # default state for toolbar
        self.checkCurrentLayerIsPluginLayer()

    def unload(self):
        # Remove the tie points dock
        if getattr(self, "dockPoints", None) is not None:
            self.iface.mainWindow().removeDockWidget(self.dockPoints)
            self.dockPoints.deleteLater()
            self.dockPoints = None

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
            self.spinBoxCenterX.setEnabled(True)
            self.spinBoxCenterY.setEnabled(True)
            self.spinBoxPxX.setEnabled(True)
            self.spinBoxPxY.setEnabled(True)
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
            self.spinBoxCenterX.setEnabled(False)
            self.spinBoxCenterY.setEnabled(False)
            self.spinBoxPxX.setEnabled(False)
            self.spinBoxPxY.setEnabled(False)
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
        self._toggleTool(self.moveTool)

    def rotateRaster(self):
        self._toggleTool(self.rotateTool)

    def scaleRaster(self):
        self._toggleTool(self.scaleTool)

    def adjustRaster(self):
        self._toggleTool(self.adjustTool)

    def georef2PRaster(self):
        self._toggleTool(self.georef2PTool)

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

    def _refitAfterPointsEdit(self, layer):
        """Refit the transform from the tie points after a table edit and
        redraw everything (undo entry is pushed only if the fit changed
        the transform)."""
        params = (layer.center, layer.rotation, layer.xScale, layer.yScale)
        if layer.applyTiePointFit():
            layer.history.append(
                {
                    "action": "npfit",
                    "center": params[0],
                    "rotation": params[1],
                    "xScale": params[2],
                    "yScale": params[3],
                }
            )
        if isinstance(self.currentTool, GeorefRasterByNPointsMapTool):
            self.currentTool.refreshPoints()
        self.updateTransformWidgets()

    def dockPointToggled(self, row, enabled):
        layer = getattr(self, "layer", None)
        if not isinstance(layer, FreehandRasterGeoreferencerLayer):
            return
        if not (0 <= row < len(layer.tiePoints)):
            return
        layer.setTiePointEnabled(row, enabled)
        self._refitAfterPointsEdit(layer)

    def dockPointsDeleted(self, rows):
        layer = getattr(self, "layer", None)
        if not isinstance(layer, FreehandRasterGeoreferencerLayer):
            return
        deleted = False
        for row in sorted(rows, reverse=True):
            if 0 <= row < len(layer.tiePoints):
                layer.removeTiePoint(row)
                deleted = True
        if deleted:
            self._refitAfterPointsEdit(layer)

    def dockPointsCleared(self):
        layer = getattr(self, "layer", None)
        if not isinstance(layer, FreehandRasterGeoreferencerLayer):
            return
        layer.setTiePoints([])
        if isinstance(self.currentTool, GeorefRasterByNPointsMapTool):
            self.currentTool.refreshPoints()
        self.updateTransformWidgets()

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
            )

    # ------------------------------------------------------------------
    # Numeric control widgets (exact input of move / scale / rotation)
    # ------------------------------------------------------------------

    def _createParamSpinBox(self, minimum, maximum, decimals, step):
        sb = QDoubleSpinBox(self.iface.mainWindow())
        sb.setDecimals(decimals)
        sb.setMinimum(minimum)
        sb.setMaximum(maximum)
        sb.setSingleStep(step)
        sb.setKeyboardTracking(False)
        sb.setFocusPolicy(Qt.ClickFocus)
        return sb

    def _setTransformWidgets(self, cx, cy, rotation, xScale, yScale, rms):
        self._syncing = True
        try:
            self.spinBoxRotate.setValue(rotation)
            self.spinBoxCenterX.setValue(cx)
            self.spinBoxCenterY.setValue(cy)
            self.spinBoxPxX.setValue(xScale)
            self.spinBoxPxY.setValue(yScale)
            if rms is None:
                self.labelRms.setText("")
            else:
                self.labelRms.setText("RMS: %.3f" % rms)
        finally:
            self._syncing = False

    def updateTransformWidgets(self, newParameters=None):
        """
        Sync the toolbar widgets and the tie points table with the active
        layer transform (called when the transform parameters changed).
        """
        layer = getattr(self, "layer", None)
        if not layer or getattr(layer, "image", None) is None:
            if getattr(self, "dockPoints", None) is not None:
                self.dockPoints.updatePanel(None)
            return
        residuals = []
        rms = None
        if len(layer.tiePoints) >= 1:
            residuals, rms = layer.tiePointResiduals()
            if len(layer.tiePoints) < 2:
                rms = None
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
        if self._syncing:
            return
        layer = self.layer
        if not layer or getattr(layer, "image", None) is None:
            return
        layer.history.append({"action": "move", "center": layer.center})
        layer.setCenter(
            QgsPointXY(self.spinBoxCenterX.value(), self.spinBoxCenterY.value())
        )
        layer.repaint()
        layer.commitTransformParameters()

    def onPixelSizeEdited(self):
        if self._syncing:
            return
        layer = self.layer
        if not layer or getattr(layer, "image", None) is None:
            return
        layer.history.append(
            {
                "action": "scale",
                "xScale": layer.xScale,
                "yScale": layer.yScale,
            }
        )
        layer.setScale(self.spinBoxPxX.value(), self.spinBoxPxY.value())
        layer.repaint()
        layer.commitTransformParameters()

    def spinBoxRotateValueChangeEvent(self, val):
        if self._syncing:
            return
        layer = self.layer
        if not layer or getattr(layer, "image", None) is None:
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
        if len(layer.history) > 0:
            act = layer.history.pop()
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
