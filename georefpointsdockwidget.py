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

Every row shows the source pixel coordinates, the target map coordinates
and the live residuals (dX, dY, residual) of a tie point. Each point can
be enabled / disabled (a disabled point stays in the table but is excluded
from the fit) and rows can be removed. After every change the raster is
refitted and redrawn immediately by the plugin (signals below).
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
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

try:  # scoped enums: PyQt6 style (also available in recent PyQt5)
    RIGHT_DOCK_AREA = Qt.DockWidgetArea.RightDockWidgetArea
    LEFT_DOCK_AREA = Qt.DockWidgetArea.LeftDockWidgetArea
except AttributeError:  # pragma: no cover - old PyQt5 fallback
    RIGHT_DOCK_AREA = Qt.RightDockWidgetArea
    LEFT_DOCK_AREA = Qt.LeftDockWidgetArea

_HEADERS = ("", "Pixel X", "Pixel Y", "Map X", "Map Y", "dX", "dY", "Residual")
_GRAY = QColor(128, 128, 128)


class GeorefPointsDockWidget(QDockWidget):
    """Table of tie points (enable / disable / remove, live residuals)."""

    pointToggled = pyqtSignal(int, bool)
    pointsDeleted = pyqtSignal(list)
    pointsCleared = pyqtSignal()

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
