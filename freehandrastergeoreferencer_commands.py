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

import math
import os

from osgeo import gdal
from PyQt5.QtCore import qDebug, QPointF, QRectF, QSize
from PyQt5.QtGui import QColor, QImage, QImageWriter, QPainter
from qgis.core import Qgis, QgsMessageLog
from qgis.gui import QgsMessageBar

from . import transform_math, utils


class ExportGeorefRasterCommand(object):
    def __init__(self, iface):
        self.iface = iface

    def exportGeorefRaster(
        self,
        layer,
        rasterPath,
        isPutRotationInWorldFile,
        isExportOnlyWorldFile,
        isExportCOG=False,
        resamplingMethod="near",
    ):
        if isExportCOG and not isExportOnlyWorldFile:
            self.exportCOG(layer, rasterPath, isPutRotationInWorldFile, resamplingMethod)
            return

        baseRasterFilePath, _ = os.path.splitext(rasterPath)
        # suppose supported format already checked
        rasterFormat = utils.imageFormat(rasterPath)

        try:
            originalWidth = layer.image.width()
            originalHeight = layer.image.height()
            radRotation = layer.rotation * math.pi / 180

            if isPutRotationInWorldFile or isExportOnlyWorldFile:
                # keep the image as is and put all transformation params
                # in world file
                img = layer.image

                a = layer.xScale * math.cos(radRotation)
                # sin instead of -sin because angle in CW
                b = -layer.yScale * math.sin(radRotation)
                d = layer.xScale * -math.sin(radRotation)
                e = -layer.yScale * math.cos(radRotation)
                c = layer.center.x() - (
                    a * (originalWidth - 1) / 2 + b * (originalHeight - 1) / 2
                )
                f = layer.center.y() - (
                    d * (originalWidth - 1) / 2 + e * (originalHeight - 1) / 2
                )

            else:
                # transform the image with rotation and scaling between the
                # axes
                # maintain at least the original resolution of the raster
                ratio = layer.xScale / layer.yScale
                if ratio > 1:
                    # increase x
                    scaleX = ratio
                    scaleY = 1
                else:
                    # increase y
                    scaleX = 1
                    scaleY = 1.0 / ratio

                width = abs(scaleX * originalWidth * math.cos(radRotation)) + abs(
                    scaleY * originalHeight * math.sin(radRotation)
                )
                height = abs(scaleX * originalWidth * math.sin(radRotation)) + abs(
                    scaleY * originalHeight * math.cos(radRotation)
                )

                qDebug("wh %f,%f" % (width, height))

                img = QImage(
                    QSize(math.ceil(width), math.ceil(height)), QImage.Format_ARGB32
                )
                # transparent background
                img.fill(QColor(0, 0, 0, 0))

                painter = QPainter(img)
                painter.setRenderHint(QPainter.Antialiasing, True)
                # painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

                rect = QRectF(
                    QPointF(-layer.image.width() / 2.0, -layer.image.height() / 2.0),
                    QPointF(layer.image.width() / 2.0, layer.image.height() / 2.0),
                )

                painter.translate(QPointF(width / 2.0, height / 2.0))
                painter.rotate(layer.rotation)
                painter.scale(scaleX, scaleY)
                painter.drawImage(rect, layer.image)
                painter.end()

                extent = layer.extent()
                a = extent.width() / width
                e = -extent.height() / height
                # 2nd term because (0,0) of world file is on center of upper
                # left pixel instead of upper left corner of that pixel
                c = extent.xMinimum() + a / 2
                f = extent.yMaximum() + e / 2
                b = d = 0.0

            if not isExportOnlyWorldFile:
                # export image
                if rasterFormat == "tif":
                    writer = QImageWriter()
                    # use LZW compression for tiff
                    # useful for scanned documents (mostly white)
                    writer.setCompression(1)
                    writer.setFormat(b"TIFF")
                    writer.setFileName(rasterPath)
                    writer.write(img)
                else:
                    img.save(rasterPath, rasterFormat)

            worldFilePath = baseRasterFilePath + "."
            if rasterFormat == "jpg":
                worldFilePath += "jgw"
            elif rasterFormat == "png":
                worldFilePath += "pgw"
            elif rasterFormat == "bmp":
                worldFilePath += "bpw"
            elif rasterFormat == "tif":
                worldFilePath += "tfw"

            with open(worldFilePath, "w") as writer:
                # order is as described at
                # http://webhelp.esri.com/arcims/9.3/General/topics/author_world_files.htm
                writer.write(
                    "%.13f\n%.13f\n%.13f\n%.13f\n%.13f\n%.13f" % (a, d, b, e, c, f)
                )

            crsFilePath = rasterPath + ".aux.xml"
            if os.path.exists(crsFilePath):
                # do not clobber an existing PAM auxiliary file (it may hold
                # statistics, histograms or a CRS of the original raster)
                widget = QgsMessageBar.createMessage(
                    "Raster Geoferencer",
                    "An .aux.xml file already exists next to the raster. "
                    "The CRS was NOT written into it.",
                )
                self.iface.messageBar().pushWidget(widget, Qgis.Warning, 5)
            else:
                with open(crsFilePath, "w") as writer:
                    writer.write(
                        self.auxContent(
                            self.iface.mapCanvas().mapSettings().destinationCrs()
                        )
                    )

            widget = QgsMessageBar.createMessage(
                "Raster Geoferencer", "Raster exported successfully."
            )
            self.iface.messageBar().pushWidget(widget, Qgis.Info, 2)
        except Exception as ex:
            QgsMessageLog.logMessage(repr(ex))
            widget = QgsMessageBar.createMessage(
                "Raster Geoferencer",
                "There was an error performing this command. "
                "See QGIS Message log for details.",
            )
            self.iface.messageBar().pushWidget(widget, Qgis.Critical, 5)

    # ------------------------------------------------------------------
    # COG export (Cloud Optimized GeoTIFF), based on the ORIGINAL raster
    # file so that any band count / data type is preserved
    # ------------------------------------------------------------------

    # COG driver note: overviews are generated automatically (OVERVIEWS=AUTO
    # is the default and there is no "ALL" value for the COG driver)
    COG_CREATION_OPTIONS = ["COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"]

    def exportCOG(self, layer, rasterPath, keepRotation, resamplingMethod):
        """
        keepRotation=True: pixels are untouched, the rotation is stored in
        the geotransform (ModelTransformation). Some software may not
        support rotated COGs; if the COG driver drops the rotation, a
        tiled GeoTIFF fallback is written instead.
        keepRotation=False: north-up COG, the rotation (and anisotropic
        scale) is baked into the pixels by warping on the 4 corner GCPs.
        """
        try:
            srcPath = layer.getAbsoluteFilepath()
            width = layer.image.width()
            height = layer.image.height()
            crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            crsWkt = crs.toWkt()

            if keepRotation:
                self._exportCogRotated(srcPath, rasterPath, layer, crsWkt, width, height)
            else:
                self._exportCogNorthUp(
                    srcPath, rasterPath, layer, crsWkt, width, height, resamplingMethod
                )

            widget = QgsMessageBar.createMessage(
                "Raster Geoferencer", "COG exported successfully."
            )
            self.iface.messageBar().pushWidget(widget, Qgis.Info, 3)
        except Exception as ex:
            QgsMessageLog.logMessage(repr(ex))
            widget = QgsMessageBar.createMessage(
                "Raster Geoferencer",
                "There was an error exporting the COG. "
                "See QGIS Message log for details.",
            )
            self.iface.messageBar().pushWidget(widget, Qgis.Critical, 5)

    def _sourceVrt(self, srcPath):
        vrtPath = "/vsimem/fhrgr_export_%d.vrt" % id(self)
        vrt = gdal.Translate(vrtPath, srcPath)
        if vrt is None:
            raise RuntimeError("Unable to open the source raster with GDAL: " + srcPath)
        return vrtPath, vrt

    def _exportCogRotated(self, srcPath, rasterPath, layer, crsWkt, width, height):
        vrtPath, vrt = self._sourceVrt(srcPath)
        try:
            gt = transform_math.geotransform_from_params(
                layer.center.x(),
                layer.center.y(),
                layer.rotation,
                layer.xScale,
                layer.yScale,
                width,
                height,
            )
            vrt.SetGeoTransform(gt)
            vrt.SetProjection(crsWkt)

            driver = gdal.GetDriverByName("COG")
            rotationExpected = abs(math.sin(layer.rotation * math.pi / 180.0)) > 1e-9
            out = None
            rotationKept = False
            if driver is not None:
                out = driver.CreateCopy(
                    rasterPath, vrt, options=self.COG_CREATION_OPTIONS
                )
                if out is not None:
                    backGt = out.GetGeoTransform()
                    rotationKept = (
                        abs(backGt[2] - gt[2]) < 1e-9 and abs(backGt[4] - gt[4]) < 1e-9
                    )
                    out = None
            if driver is None or (rotationExpected and not rotationKept):
                # the COG driver dropped the rotation: fall back to a tiled
                # GeoTIFF which keeps it
                gtiff = gdal.GetDriverByName("GTiff")
                gtiff.CreateCopy(
                    rasterPath,
                    vrt,
                    options=[
                        "TILED=YES",
                        "BLOCKXSIZE=512",
                        "BLOCKYSIZE=512",
                        "COMPRESS=DEFLATE",
                        "BIGTIFF=IF_SAFER",
                    ],
                )
                if driver is not None:
                    widget = QgsMessageBar.createMessage(
                        "Raster Geoferencer",
                        "The COG driver did not keep the rotated geotransform. "
                        "A tiled GeoTIFF was written instead.",
                    )
                    self.iface.messageBar().pushWidget(widget, Qgis.Warning, 6)
        finally:
            gdal.Unlink(vrtPath)

    def _northUpOutputBounds(self, layer, width, height):
        """
        Bounding box of the rotated raster, snapped OUTWARD to whole
        pixels so that the warped output never clips the raster.
        """
        corners = transform_math.corners(
            layer.center.x(),
            layer.center.y(),
            layer.rotation,
            layer.xScale,
            layer.yScale,
            width,
            height,
        )
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        minX = math.floor(min(xs) / layer.xScale) * layer.xScale
        maxX = math.ceil(max(xs) / layer.xScale) * layer.xScale
        minY = math.floor(min(ys) / layer.yScale) * layer.yScale
        maxY = math.ceil(max(ys) / layer.yScale) * layer.yScale
        return (minX, minY, maxX, maxY)

    def _exportCogNorthUp(
        self, srcPath, rasterPath, layer, crsWkt, width, height, resamplingMethod
    ):
        vrtPath, vrt = self._sourceVrt(srcPath)
        try:
            # corners of the image as GCPs (gdal pixel/line convention:
            # center of the first pixel is (0.5, 0.5))
            gcps = []
            for px, py in (
                (0, 0),
                (width - 1, 0),
                (width - 1, height - 1),
                (0, height - 1),
            ):
                mx, my = transform_math.pixel_to_map(
                    px,
                    py,
                    layer.center.x(),
                    layer.center.y(),
                    layer.rotation,
                    layer.xScale,
                    layer.yScale,
                    width,
                    height,
                )
                gcps.append(gdal.GCP(mx, my, 0.0, px + 0.5, py + 0.5))
            vrt.SetGCPs(gcps, crsWkt)

            gdal.Warp(
                rasterPath,
                vrt,
                format="COG",
                dstSRS=crsWkt,
                resampleAlg=resamplingMethod,
                dstAlpha=True,
                # enforce the intended pixel size and full coverage: GDAL's
                # suggested output for GCP warps only preserves the pixel
                # density and can clip the extreme corners
                outputBounds=self._northUpOutputBounds(layer, width, height),
                xRes=layer.xScale,
                yRes=layer.yScale,
                creationOptions=self.COG_CREATION_OPTIONS,
            )
        finally:
            gdal.Unlink(vrtPath)

    def auxContent(self, crs):
        content = """<PAMDataset>
  <Metadata domain="xml:ESRI" format="xml">
    <GeodataXform xsi:type="typens:IdentityXform" 
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
      xmlns:xs="http://www.w3.org/2001/XMLSchema" 
      xmlns:typens="http://www.esri.com/schemas/ArcGIS/9.2">
      <SpatialReference xsi:type="typens:%sCoordinateSystem">
        <WKT>%s</WKT>
      </SpatialReference>
    </GeodataXform>
  </Metadata>
</PAMDataset>"""  # noqa
        geogOrProj = "Geographic" if crs.isGeographic() else "Projected"
        return content % (geogOrProj, crs.toWkt())
