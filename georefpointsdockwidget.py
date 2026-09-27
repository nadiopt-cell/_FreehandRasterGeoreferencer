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
Dock widget with the table of tie points of the active Freehand Raster
Georeferencer layer, similar to the GCP table of the QGIS built-in
georeferencer.

The top section holds the exact numeric transform controls (center X/Y,
pixel sizes X/Y, RMS of the residuals): type a value for an exact
placement of the raster. Every row of the table shows the source pixel
coordinates, the target map coordinates and the live residuals (dX, dY,
residual) of a tie point. Each point can be enabled / disabled (a
disabled point stays in the table but is excluded from the fit) and rows
can be removed. After every change the raster is refitted and redrawn
immediately by the plugin (signals below).
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import transform_math

try:  # scoped enums: PyQt6 style (also available in recent PyQt5)
    RIGHT_DOCK_AREA = Qt.DockWidgetArea.RightDockWidgetArea
    LEFT_DOCK_AREA = Qt.DockWidgetArea.LeftDockWidgetArea
except AttributeError:  # pragma: no cover - old PyQt5 fallback
    RIGHT_DOCK_AREA = Qt.RightDockWidgetArea
    LEFT_DOCK_AREA = Qt.LeftDockWidgetArea

_HEADERS = ("", "Pixel X", "Pixel Y", "Map X", "Map Y", "dX", "dY", "Residual")
_GRAY = QColor(128, 128, 128)

# (order, label, tooltip)
_FIT_MODELS = (
    (
        0,
        "Similarity / Anisotropic",
        "Default model of the layer: rotation + translation + uniform or"
        " separate X/Y scales (no shear). Exact with 2 points.",
    ),
    (
        1,
        "Polynomial 1 (affine)",
        "Affine transform: rotation, translation, X/Y scales AND shear"
        " (6 parameters, 3 points minimum). Rendered and exported"
        " exactly.",
    ),
    (
        2,
        "Polynomial 2 (quadratic)",
        "Second order polynomial (12 parameters, 6 points minimum)."
        " Can bend the raster; keep points spread over the image and"
        " expect extrapolation artifacts outside their hull.",
    ),
    (
        3,
        "Polynomial 3 (cubic)",
        "Third order polynomial (20 parameters, 10 points minimum)."
        " Most flexible, least stable: use only with many well spread"
        " points.",
    ),
)


class GeorefPointsDockWidget(QDockWidget):
    """Table of tie points (enable / disable / remove, live residuals)."""

    pointToggled = pyqtSignal(int, bool)
    pointsDeleted = pyqtSignal(list)
    pointsCleared = pyqtSignal()
    fitModelChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        QDockWidget.__init__(self, "Georeference points", parent)
        self.setObjectName("FreehandRasterGeoreferencerPointsDock")
        self.setAllowedAreas(LEFT_DOCK_AREA | RIGHT_DOCK_AREA)

        # guard against reacting to our own table rebuilds
        self._updating = False

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # exact numeric transform controls (center / pixel sizes / RMS)
        self.groupTransform = QGroupBox("Transform (exact values)", content)
        self.groupTransform.setToolTip(
            "Exact placement of the raster: center in map units, pixel"
            " sizes in map units per pixel. Editing a value moves /"
            " scales the raster immediately (undoable with the Undo"
            " toolbar button)."
        )
        grid = QGridLayout(self.groupTransform)
        grid.setContentsMargins(6, 6, 6, 6)

        def _paramSpinBox(minimum, maximum, step):
            sb = QDoubleSpinBox(self.groupTransform)
            sb.setDecimals(6)
            sb.setMinimum(minimum)
            sb.setMaximum(maximum)
            sb.setSingleStep(step)
            sb.setKeyboardTracking(False)
            sb.setFocusPolicy(Qt.ClickFocus)
            sb.setFixedWidth(110)
            return sb

        self.spinBoxCenterX = _paramSpinBox(-1e12, 1e12, 1.0)
        self.spinBoxCenterY = _paramSpinBox(-1e12, 1e12, 1.0)
        self.spinBoxPxX = _paramSpinBox(1e-9, 1e9, 0.001)
        self.spinBoxPxY = _paramSpinBox(1e-9, 1e9, 0.001)
        self.spinBoxCenterX.setToolTip(
            "X coordinate of the raster center (map units)"
        )
        self.spinBoxCenterY.setToolTip(
            "Y coordinate of the raster center (map units)"
        )
        self.spinBoxPxX.setToolTip(
            "Pixel size in X: map units per pixel of the raster (xScale)"
        )
        self.spinBoxPxY.setToolTip(
            "Pixel size in Y: map units per pixel of the raster (yScale)"
        )

        grid.addWidget(QLabel("Center X"), 0, 0)
        grid.addWidget(self.spinBoxCenterX, 0, 1)
        grid.addWidget(QLabel("Center Y"), 0, 2)
        grid.addWidget(self.spinBoxCenterY, 0, 3)
        grid.addWidget(QLabel("Pixel size X"), 1, 0)
        grid.addWidget(self.spinBoxPxX, 1, 1)
        grid.addWidget(QLabel("Pixel size Y"), 1, 2)
        grid.addWidget(self.spinBoxPxY, 1, 3)
        self.labelRms = QLabel("", self.groupTransform)
        self.labelRms.setToolTip(
            "Root mean square residual of the tie points, in map units "
            "(shown when 2 or more tie points are set)"
        )
        grid.addWidget(self.labelRms, 2, 0, 1, 4)

        layout.addWidget(self.groupTransform)

        # fit model selector (kept OUTSIDE groupTransform: it stays active
        # in polynomial mode when the exact numeric controls are read-only)
        modelRow = QHBoxLayout()
        modelRow.setContentsMargins(6, 0, 6, 0)
        modelRow.addWidget(QLabel("Fit model"))
        self.comboFitModel = QComboBox(content)
        for order, label, tooltip in _FIT_MODELS:
            self.comboFitModel.addItem(label, order)
            self.comboFitModel.setItemData(
                self.comboFitModel.count() - 1, tooltip, Qt.ToolTipRole
            )
        self.comboFitModel.setToolTip(
            "Mathematical model used to fit the transform from the tie"
            " points (like the QGIS georeferencer transformation type)."
        )
        self.comboFitModel.currentIndexChanged.connect(self._fitModelSelected)
        self.labelFitModelHint = QLabel("", content)
        self.labelFitModelHint.setStyleSheet("color: gray;")
        modelRow.addWidget(self.comboFitModel, 1)
        modelRow.addWidget(self.labelFitModelHint)
        layout.addLayout(modelRow)

        buttons = QHBoxLayout()
        self.buttonDelete = QPushButton("Delete selected", content)
        self.buttonDelete.setToolTip("Remove the selected tie point(s)")
        self.buttonClear = QPushButton("Clear all", content)
        self.buttonClear.setToolTip("Remove all tie points of this raster")
        self.labelStatus = QLabel("", content)
        buttons.addWidget(self.buttonDelete)
        buttons.addWidget(self.buttonClear)
        buttons.addStretch(1)
        buttons.addWidget(self.labelStatus)
        layout.addLayout(buttons)

        self.table = QTableWidget(0, len(_HEADERS), content)
        self.table.setHorizontalHeaderLabels(list(_HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._showContextMenu)
        header = self.table.horizontalHeader()
        try:
            header.setSectionResizeMode(QHeaderView.ResizeToContents)
        except AttributeError:  # pragma: no cover - very old PyQt5
            header.setResizeMode(QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._itemChanged)
        layout.addWidget(self.table)
        self.setWidget(content)

        self.buttonDelete.clicked.connect(self._deleteSelected)
        self.buttonClear.clicked.connect(self._clearAll)

    # ------------------------------------------------------------------
    # public API (called by the plugin)
    # ------------------------------------------------------------------

    def setTransformValues(self, cx, cy, xScale, yScale, rms):
        """Sync the numeric transform widgets with the layer (the plugin
        guards its handlers with the _syncing flag while updating)."""
        self.spinBoxCenterX.setValue(cx)
        self.spinBoxCenterY.setValue(cy)
        self.spinBoxPxX.setValue(xScale)
        self.spinBoxPxY.setValue(yScale)
        if rms is None:
            self.labelRms.setText("")
        else:
            self.labelRms.setText("RMS: %.3f" % rms)

    # ------------------------------------------------------------------
    # fit model selector
    # ------------------------------------------------------------------

    def _fitModelSelected(self, index):
        if self._updating:
            return
        self.fitModelChanged.emit(self.comboFitModel.itemData(index))

    def setFitModelValue(self, order):
        """Sync the combo with the layer (without emitting)."""
        index = self.comboFitModel.findData(int(order))
        if index < 0:
            index = 0
        if self.comboFitModel.currentIndex() != index:
            self.comboFitModel.setCurrentIndex(index)
        self._updateFitModelHint(order)

    def _updateFitModelHint(self, order):
        if order == 0:
            self.labelFitModelHint.setText("")
        else:
            self.labelFitModelHint.setText(
                "min %d points" % transform_math.poly_min_points(order)
            )

    def updatePanel(self, layer, residuals=None):
        """
        Rebuild the table from the layer tie points. layer may be None
        (no plugin layer selected) to clear the table. residuals is the
        optional list of (dx, dy) tuples in the same order as the points.
        """
        self._updating = True
        try:
            points = layer.tiePoints if layer is not None else []
            self.table.clearContents()
            self.table.setRowCount(len(points))
            for i, p in enumerate(points):
                enabled = p.get("en", True)
                if residuals is not None and i < len(residuals):
                    dx, dy = residuals[i]
                else:
                    dx, dy = 0.0, 0.0
                residual = (dx * dx + dy * dy) ** 0.5

                check = QTableWidgetItem()
                check.setFlags(
                    Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
                )
                check.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
                check.setToolTip("Enabled: the point is used for the fit")
                self.table.setItem(i, 0, check)
                if not enabled:
                    check.setForeground(_GRAY)

                values = (
                    "%.3f" % p["px"],
                    "%.3f" % p["py"],
                    "%.4f" % p["mx"],
                    "%.4f" % p["my"],
                    "%.4f" % dx,
                    "%.4f" % dy,
                    "%.4f" % residual,
                )
                for col, text in enumerate(values, start=1):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if not enabled:
                        item.setForeground(_GRAY)
                    self.table.setItem(i, col, item)

            enabledCount = sum(1 for p in points if p.get("en", True))
            self.labelStatus.setText(
                "%d point(s), %d enabled" % (len(points), enabledCount)
            )
            self.buttonDelete.setEnabled(bool(points))
            self.buttonClear.setEnabled(bool(points))
            # the numeric transform controls follow the layer presence and
            # are read-only in polynomial mode (they only DISPLAY the local
            # equivalent values there)
            polyMode = layer is not None and layer.isPolyMode()
            self.groupTransform.setEnabled(layer is not None and not polyMode)
            self.comboFitModel.setEnabled(layer is not None)
            if layer is not None:
                self.setFitModelValue(layer.fitModel)
            else:
                self.setFitModelValue(0)
        finally:
            self._updating = False

    # ------------------------------------------------------------------
    # internal slots
    # ------------------------------------------------------------------

    def _selectedRows(self):
        rows = set()
        selection = self.table.selectionModel()
        if selection is not None:
            for index in selection.selectedRows():
                rows.add(index.row())
        return sorted(rows)

    def _deleteSelected(self):
        if self._updating:
            return
        rows = self._selectedRows()
        if rows:
            self.pointsDeleted.emit(rows)

    def _clearAll(self):
        if self._updating:
            return
        self.pointsCleared.emit()

    def _itemChanged(self, item):
        if self._updating:
            return
        if item.column() == 0:
            self.pointToggled.emit(item.row(), item.checkState() == Qt.Checked)

    def _showContextMenu(self, pos):
        rows = self._selectedRows()
        menu = QMenu(self.table)
        actionDelete = menu.addAction("Delete selected point(s)")
        actionDelete.setEnabled(bool(rows))
        chosen = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if chosen == actionDelete and rows:
            self.pointsDeleted.emit(rows)
