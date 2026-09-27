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

from PyQt5.QtWidgets import QDialog

from .ui_propertiesdialog import Ui_Dialog


class PropertiesDialog(QDialog, Ui_Dialog):
    def __init__(self, layer):
        QDialog.__init__(self)
        # set up the user interface
        self.setupUi(self)
        self.setWindowTitle("%s - %s" % (self.tr("Layer Properties"), layer.name()))

        self.layer = layer
        self.horizontalSlider_Transparency.valueChanged.connect(self.sliderChanged)
        self.spinBox_Transparency.valueChanged.connect(self.spinBoxChanged)

        self.textEdit_Properties.setText(layer.metadataText())
        self.spinBox_Transparency.setValue(layer.transparency)

    def sliderChanged(self, val):
        s = self.spinBox_Transparency
        s.blockSignals(True)
        s.setValue(val)
        s.blockSignals(False)

    def spinBoxChanged(self, val):
        s = self.horizontalSlider_Transparency
        s.blockSignals(True)
        s.setValue(val)
        s.blockSignals(False)
