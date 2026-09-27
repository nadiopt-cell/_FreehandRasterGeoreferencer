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

from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox

from .ui_exportgeorefrasterdialog import Ui_ExportGeorefRasterDialog


class ExportGeorefRasterDialog(QDialog, Ui_ExportGeorefRasterDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.setupUi(self)

        self.pushButtonBrowse.clicked.connect(self.showBrowserDialog)
        self.checkBoxOnlyWorldFile.stateChanged.connect(self.setupOnlyWorldFile)
        self.checkBoxExportCOG.stateChanged.connect(self.setupCogMode)

    def clear(self, layer):
        self.lineEditImagePath.setText("")
        self.checkBoxRotationMode.setChecked(False)
        self.checkBoxRotationMode.setEnabled(True)
        self.checkBoxOnlyWorldFile.setChecked(False)
        self.checkBoxExportCOG.setChecked(False)
        self.comboBoxResampling.setCurrentIndex(0)

        defaultPath, _ = os.path.splitext(layer.filepath)
        self.defaultPath = defaultPath + "_georeferenced.png"

    def setupOnlyWorldFile(self):
        if self.checkBoxOnlyWorldFile.isChecked():
            self._originalCheckBoxRotationModeChecked = (
                self.checkBoxRotationMode.isChecked()
            )
            self.checkBoxRotationMode.setChecked(True)
            self.checkBoxRotationMode.setEnabled(False)
        else:
            self.checkBoxRotationMode.setChecked(
                self._originalCheckBoxRotationModeChecked
            )
            self.checkBoxRotationMode.setEnabled(True)

    def setupCogMode(self):
        isCog = self.checkBoxExportCOG.isChecked()
        # a COG embeds the georeferencing: "only world file" makes no sense
        self.checkBoxOnlyWorldFile.setEnabled(not isCog)
        if isCog:
            self.checkBoxOnlyWorldFile.setChecked(False)
        self.comboBoxResampling.setEnabled(isCog)

    def showBrowserDialog(self):
        isCog = self.checkBoxExportCOG.isChecked()
        if self.lineEditImagePath.text():
            filepathDialog = self.lineEditImagePath.text()
        else:
            filepathDialog = self.defaultPath
            if isCog:
                filepathDialog = os.path.splitext(filepathDialog)[0] + ".tif"

        if isCog:
            filepath, _ = QFileDialog.getSaveFileName(
                None,
                "Export Cloud Optimized GeoTIFF",
                filepathDialog,
                "GeoTIFF (*.tif *.tiff)",
            )
        elif not self.checkBoxOnlyWorldFile.isChecked():
            filepath, _ = QFileDialog.getSaveFileName(
                None,
                "Export georeferenced raster",
                filepathDialog,
                "Images (*.png *.bmp *.jpg *.tif *.tiff)",
            )
        else:
            filepath, _ = QFileDialog.getOpenFileName(
                None,
                "Export world file for raster",
                filepathDialog,
                "Images (*.png *.bmp *.jpg *.tif *.tiff)",
            )

        if filepath:
            self.lineEditImagePath.setText(filepath)

    def accept(self):
        result, message, details = self.validate()
        if result:
            self.done(QDialog.Accepted)
        else:
            msgBox = QMessageBox()
            msgBox.setWindowTitle("Error")
            msgBox.setText(message)
            msgBox.setDetailedText(details)
            msgBox.setStandardButtons(QMessageBox.Ok)
            msgBox.exec_()

    def validate(self):
        result = True
        message = ""
        details = ""

        self.isPutRotationInWorldFile = self.checkBoxRotationMode.isChecked()
        self.isExportOnlyWorldFile = self.checkBoxOnlyWorldFile.isChecked()
        self.isExportCOG = self.checkBoxExportCOG.isChecked()
        self.resamplingMethod = self.comboBoxResampling.currentData()
        if self.resamplingMethod is None:
            # fallback when the combo was built from the .ui file (no data)
            self.resamplingMethod = ("near", "bilinear", "cubic")[
                max(0, self.comboBoxResampling.currentIndex())
            ]

        self.imagePath = self.lineEditImagePath.text()
        if not self.imagePath:
            result = False
            details += "A file must be selected"

        if result:
            _, extension = os.path.splitext(self.imagePath)
            extension = extension.lower()
            allowed = [".tif", ".tiff"] if self.isExportCOG else [
                ".jpg",
                ".bmp",
                ".png",
                ".tif",
                ".tiff",
            ]
            if extension not in allowed:
                result = False
                if len(details) > 0:
                    details += "\n"
                if self.isExportCOG:
                    details += "A COG must be exported as a .tif/.tiff file"
                else:
                    details += "The file must be an image"

        if not result:
            message = "There were errors in the form"

        return result, message, details
