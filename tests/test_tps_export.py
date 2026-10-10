"""
Integration test of the rubbersheet (TPS) export path: run the REAL
ExportGeorefRasterCommand (qgis stubbed) against a real GDAL raster with
a TPS-fitted layer stub, then verify the georeferenced output. Skipped
automatically if GDAL python bindings or PyQt5 are missing.
"""

import math
import os
import sys
import types

import pytest

gdal = pytest.importorskip("osgeo.gdal")
pytest.importorskip("PyQt5.QtGui")

gdal.UseExceptions()  # QGIS 3.34+ enables exceptions globally
gdal.SetConfigOption("CPL_LOG", "/dev/null")

REPO_PARENT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

# ---- stub qgis BEFORE importing the command module ---------------------
_qpkg = types.ModuleType("qgis")
_qcore = types.ModuleType("qgis.core")
_qgui = types.ModuleType("qgis.gui")


class _Qgis:
    Info = 0
    Warning = 1
    Critical = 2


_qcore.Qgis = _Qgis
_qcore.QgsMessageLog = types.SimpleNamespace(
    logMessage=staticmethod(lambda *a: None)
)


class _QgsProject:
    _inst = None

    @classmethod
    def instance(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def fileName(self):
        return ""


_qcore.QgsProject = _QgsProject


class _QgsMessageBar:
    @staticmethod
    def createMessage(title, text):
        return types.SimpleNamespace(title=title, text=text)


_qgui.QgsMessageBar = _QgsMessageBar
_qpkg.core = _qcore
_qpkg.gui = _qgui
sys.modules.setdefault("qgis", _qpkg)
sys.modules.setdefault("qgis.core", _qcore)
sys.modules.setdefault("qgis.gui", _qgui)

from _FreehandRasterGeoreferencer import transform_math as tm  # noqa: E402
from _FreehandRasterGeoreferencer import polymesh  # noqa: E402
from _FreehandRasterGeoreferencer.freehandrastergeoreferencer_commands import (  # noqa: E402
    ExportGeorefRasterCommand,
)

WKT = (
    'PROJCS["WGS 84 / UTM zone 37N",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
    'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",39],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AUTHORITY["EPSG","32637"]]'
)

W, H = 40, 30


def _field(px, py):
    """Affine base + gentle bends (the surface the fit must reproduce)."""
    mx, my = tm.pixel_to_map(px, py, 500000.0, 4500000.0, 8.0, 2.0, 2.0, W, H)
    mx += 3.0 * math.sin(px / W * math.pi)
    my += 2.5 * math.cos(py / H * math.pi)
    return mx, my


# pixel/line convention of the layer: pixel-center indices
TIE_PIXELS = [(2, 2), (38, 3), (37, 27), (3, 26), (20, 14), (10, 8), (30, 20)]
TIE_PAIRS = [
    (float(px), float(py), *_field(px, py)) for px, py in TIE_PIXELS
]
FIT = tm.fit_tps(TIE_PAIRS, W, H)
LOCAL = tm.tps_local_params(FIT, W, H)


# ---- fakes --------------------------------------------------------------


class FakeCrs:
    def isGeographic(self):
        return False

    def toWkt(self):
        return WKT


class FakeSettings:
    def destinationCrs(self):
        return FakeCrs()


class FakeCanvas:
    def mapSettings(self):
        return FakeSettings()


class FakeBar:
    def __init__(self):
        self.messages = []

    def pushWidget(self, widget, level=None, duration=None):
        self.messages.append((level, widget.text))


class FakeIface:
    def __init__(self):
        self.bar = FakeBar()

    def mapCanvas(self):
        return FakeCanvas()

    def messageBar(self):
        return self.bar


class FakeRect:
    def __init__(self, x0, y0, x1, y1):
        self._r = (x0, y0, x1, y1)

    def xMinimum(self):
        return self._r[0]

    def yMinimum(self):
        return self._r[1]

    def xMaximum(self):
        return self._r[2]

    def yMaximum(self):
        return self._r[3]


def _display_image(width, height):
    from PyQt5.QtGui import QImage

    bpl = 3 * width
    buf = bytearray(bytes(range(256)) * (bpl * height // 256 + 1))
    return QImage(
        bytes(buf[: bpl * height]), width, height, bpl, QImage.Format_RGB888
    ).copy()


class FakeLayerTps:
    """A plugin layer stub running the rubbersheet fit model."""

    def __init__(self, src, enabled=None):
        self.filepath = src
        self.image = _display_image(W, H)
        self.rotation = LOCAL["rotation"]
        self.xScale = LOCAL["xScale"]
        self.yScale = LOCAL["yScale"]
        self.center = types.SimpleNamespace(
            x=lambda: LOCAL["cx"], y=lambda: LOCAL["cy"]
        )
        self._points = []
        for i, (px, py, mx, my) in enumerate(TIE_PAIRS):
            self._points.append(
                {
                    "px": px,
                    "py": py,
                    "mx": mx,
                    "my": my,
                    "en": enabled is None or i in enabled,
                }
            )

    def getAbsoluteFilepath(self):
        return self.filepath

    def isTPSMode(self):
        return True

    def enabledTiePoints(self):
        return [p for p in self._points if p.get("en", True)]

    def fitTransform(self):
        return {"kind": "tps", "fit": dict(FIT)}

    def extent(self):
        minX, minY, maxX, maxY = polymesh.warped_bounds(
            lambda px, py: tm.tps_pixel_to_map(px, py, FIT, W, H), W, H
        )
        return FakeRect(minX, minY, maxX, maxY)


@pytest.fixture(scope="module")
def src_path(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("tps") / "src.tif")
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, W, H, 3, gdal.GDT_Byte)
    for b in range(1, 4):
        ds.GetRasterBand(b).WriteRaster(
            0, 0, W, H,
            bytes([(c * 7 + b * 11) % 256 for c in range(W * H)]),
            buf_type=gdal.GDT_Byte,
        )
    ds = None
    return path


def _snapped_bounds():
    extent = FakeLayerTps("").extent()
    sx, sy = LOCAL["xScale"], LOCAL["yScale"]
    return (
        math.floor(extent.xMinimum() / sx) * sx,
        math.floor(extent.yMinimum() / sy) * sy,
        math.ceil(extent.xMaximum() / sx) * sx,
        math.ceil(extent.yMaximum() / sy) * sy,
    )


class TestTpsExport:
    def test_export_plain_geotiff(self, tmp_path, src_path):
        dest = str(tmp_path / "tps_out.tif")
        iface = FakeIface()
        cmd = ExportGeorefRasterCommand(iface)
        cmd.exportGeorefRaster(
            FakeLayerTps(src_path), dest, False, False, False, "near",
            "DEFLATE",
        )
        assert os.path.exists(dest)
        ds = gdal.Open(dest)
        assert ds is not None
        gt = ds.GetGeoTransform()
        # north-up output at the local pixel size
        assert gt[1] == pytest.approx(LOCAL["xScale"], rel=1e-6)
        assert abs(gt[5]) == pytest.approx(LOCAL["yScale"], rel=1e-6)
        assert gt[2] == pytest.approx(0.0, abs=1e-12)
        assert gt[4] == pytest.approx(0.0, abs=1e-12)
        minX, minY, maxX, maxY = _snapped_bounds()
        assert gt[0] == pytest.approx(minX, abs=abs(gt[1]))
        assert gt[3] == pytest.approx(maxY, abs=abs(gt[5]))

        # the source center pixel must be displayed at the location the
        # layer shows (GDAL TPS through the same GCPs == the layer fit)
        mx, my = tm.tps_pixel_to_map(W / 2.0, H / 2.0, FIT, W, H)
        col = int(round((mx - gt[0]) / gt[1]))
        row = int(round((gt[3] - my) / abs(gt[5])))
        assert 0 <= col < ds.RasterXSize
        assert 0 <= row < ds.RasterYSize
        alpha = ds.GetRasterBand(ds.RasterCount)
        buf = alpha.ReadRaster(
            max(0, col - 1), max(0, row - 1), 3, 3, buf_type=gdal.GDT_Byte
        )
        assert max(buf) > 200  # real data, not nodata
        ds = None

    def test_export_cog(self, tmp_path, src_path):
        dest = str(tmp_path / "tps_out_cog.tif")
        iface = FakeIface()
        cmd = ExportGeorefRasterCommand(iface)
        cmd.exportGeorefRaster(
            FakeLayerTps(src_path), dest, False, False, True, "near",
            "DEFLATE",
        )
        assert os.path.exists(dest)
        ds = gdal.Open(dest)
        gt = ds.GetGeoTransform()
        assert gt[1] == pytest.approx(LOCAL["xScale"], rel=1e-6)
        assert abs(gt[5]) == pytest.approx(LOCAL["yScale"], rel=1e-6)
        assert ds.GetDriver().ShortName == "GTiff"  # COG driver output
        ds = None

    def test_export_world_file_only_refused(self, tmp_path, src_path):
        dest = str(tmp_path / "tps_out_refused.tif")
        iface = FakeIface()
        cmd = ExportGeorefRasterCommand(iface)
        cmd.exportGeorefRaster(
            FakeLayerTps(src_path), dest, False, True, False, "near",
            "DEFLATE",
        )
        assert not os.path.exists(dest)
        assert any(
            level == _Qgis.Warning and "world file" in text.lower()
            for level, text in iface.bar.messages
        )

    def test_export_too_few_points_reported(self, tmp_path, src_path):
        dest = str(tmp_path / "tps_out_few.tif")
        iface = FakeIface()
        cmd = ExportGeorefRasterCommand(iface)
        layer = FakeLayerTps(src_path, enabled={0, 1})  # 2 enabled points
        cmd.exportGeorefRaster(
            layer, dest, False, False, False, "near", "DEFLATE"
        )
        assert not os.path.exists(dest)
        assert any(
            level == _Qgis.Critical for level, text in iface.bar.messages
        )
