"""
Integration tests of the COG export paths (they exercise the exact math
used by ExportGeorefRasterCommand with a plain object instead of the
QGIS layer). Skipped automatically if GDAL python bindings are missing.
"""

import pytest

gdal = pytest.importorskip("osgeo.gdal")

import transform_math as tm  # noqa: E402

gdal.UseExceptions()

W, H = 200, 100
CX, CY, ROTATION, SX, SY = 500000.0, 4500000.0, 23.0, 10.0, 15.0

PROJ4_UTM37N = (
    'PROJCS["WGS 84 / UTM zone 37N",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
    'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",39],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AUTHORITY["EPSG","32637"]]'
)


class _LayerStub:
    """Mimics the layer attributes used by the COG export code."""

    def __init__(self):
        self.center = type("P", (), {"x": lambda s: CX, "y": lambda s: CY})()
        self.rotation = ROTATION
        self.xScale = SX
        self.yScale = SY
        self.image = type("I", (), {"width": lambda s: W, "height": lambda s: H})()


class _IfaceStub:
    """Mimics iface.mapCanvas().mapSettings().destinationCrs()."""

    class _Canvas:
        class _Settings:
            @staticmethod
            def destinationCrs():
                return type("C", (), {"toWkt": lambda s: PROJ4_UTM37N})()

        @staticmethod
        def mapSettings():
            return _IfaceStub._Canvas._Settings

    class _Bar:
        @staticmethod
        def pushWidget(*args, **kwargs):
            pass

        @staticmethod
        def createMessage(*args, **kwargs):
            return "msg"

    def __init__(self):
        self.mapCanvas = lambda: _IfaceStub._Canvas
        self.messageBar = _IfaceStub._Bar


@pytest.fixture(scope="module")
def src_path(tmp_path_factory):
    """Synthetic source raster with a gradient pattern, no georeferencing."""
    path = str(tmp_path_factory.mktemp("cog") / "src.tif")
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, W, H, 3, gdal.GDT_Byte)
    for band in range(1, 4):
        data = bytearray()
        for row in range(H):
            for col in range(W):
                data.append((col * 7 + row * 3 + band * 40) % 256)
        ds.GetRasterBand(band).WriteRaster(0, 0, W, H, bytes(data), buf_type=gdal.GDT_Byte)
    ds = None
    return path


class TestGdalCogMath:
    """These tests replicate the exact GDAL calls of the export command."""

    def _snapped_bounds(self):
        import math as _math

        corners = tm.corners(CX, CY, ROTATION, SX, SY, W, H)
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        minX = _math.floor(min(xs) / SX) * SX
        maxX = _math.ceil(max(xs) / SX) * SX
        minY = _math.floor(min(ys) / SY) * SY
        maxY = _math.ceil(max(ys) / SY) * SY
        return (minX, minY, maxX, maxY)


    def test_cog_rotated_geotransform(self, tmp_path, src_path):
        dest = str(tmp_path / "rotated.tif")
        vrtPath = "/vsimem/test_rotated.vrt"
        vrt = gdal.Translate(vrtPath, src_path)
        gt = tm.geotransform_from_params(CX, CY, ROTATION, SX, SY, W, H)
        vrt.SetGeoTransform(gt)
        vrt.SetProjection(PROJ4_UTM37N)

        driver = gdal.GetDriverByName("COG")
        out = driver.CreateCopy(
            dest, vrt, options=["COMPRESS=DEFLATE", "OVERVIEWS=ALL"]
        )
        backGt = out.GetGeoTransform()
        out = None
        gdal.Unlink(vrtPath)

        # does this GDAL version keep the rotation in a COG?
        kept = (
            abs(backGt[2] - gt[2]) < 1e-9 and abs(backGt[4] - gt[4]) < 1e-9
        )
        if not kept:
            pytest.skip(
                "This GDAL version (%s) drops rotation in COG; the plugin "
                "falls back to tiled GeoTIFF" % gdal.__version__
            )
        # geotransform roundtrip through the file
        ds = gdal.Open(dest)
        readGt = ds.GetGeoTransform()
        ds = None
        cx2, cy2, rot2, sx2, sy2 = tm.params_from_geotransform(readGt, W, H)
        assert (cx2, cy2) == pytest.approx((CX, CY), abs=1e-6)
        assert rot2 == pytest.approx(ROTATION, abs=1e-6)
        assert sx2 == pytest.approx(SX, abs=1e-6)
        assert sy2 == pytest.approx(SY, abs=1e-6)

    def test_cog_north_up_gcp_warp(self, tmp_path, src_path):
        dest = str(tmp_path / "northup.tif")
        vrtPath = "/vsimem/test_northup.vrt"
        vrt = gdal.Translate(vrtPath, src_path)

        gcps = []
        for px, py in ((0, 0), (W - 1, 0), (W - 1, H - 1), (0, H - 1)):
            mx, my = tm.pixel_to_map(px, py, CX, CY, ROTATION, SX, SY, W, H)
            gcps.append(gdal.GCP(mx, my, 0.0, px + 0.5, py + 0.5))
        vrt.SetGCPs(gcps, PROJ4_UTM37N)

        gdal.Warp(
            dest,
            vrt,
            format="COG",
            dstSRS=PROJ4_UTM37N,
            resampleAlg="near",
            dstAlpha=True,
            # same snapping as _northUpOutputBounds: bbox snapped outward
            # to whole pixels so the raster is never clipped
            outputBounds=self._snapped_bounds(),
            xRes=SX,
            yRes=SY,
            creationOptions=["COMPRESS=DEFLATE"],
        )
        gdal.Unlink(vrtPath)

        ds = gdal.Open(dest)
        gt = ds.GetGeoTransform()
        outW, outH = ds.RasterXSize, ds.RasterYSize
        assert ds.GetProjection(), "output must carry the CRS"
        # north-up: rotation terms are zero, pixel size matches scale
        assert gt[2] == pytest.approx(0.0, abs=1e-9)
        assert gt[4] == pytest.approx(0.0, abs=1e-9)
        assert gt[1] == pytest.approx(SX, rel=1e-6)
        assert abs(gt[5]) == pytest.approx(SY, rel=1e-6)
        ds = None

        # the output footprint must contain the rotated corners
        corners = tm.corners(CX, CY, ROTATION, SX, SY, W, H)
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        x_min = gt[0]
        x_max = gt[0] + outW * gt[1]
        y_max = gt[3]
        y_min = gt[3] + outH * gt[5]
        assert x_min <= min(xs) + 1e-6
        assert x_max >= max(xs) - 1e-6
        assert y_min <= min(ys) + 1e-6
        assert y_max >= max(ys) - 1e-6

    def test_pixel_size_consistency_with_layer(self):
        """
        The GT of the rotated mode must map pixel centers exactly like
        pixel_to_map does (the layer and the export must agree).
        """
        gt = tm.geotransform_from_params(CX, CY, ROTATION, SX, SY, W, H)
        for px, py in ((0, 0), (57, 31), (W - 1, H - 1)):
            gx = gt[0] + gt[1] * (px + 0.5) + gt[2] * (py + 0.5)
            gy = gt[3] + gt[4] * (px + 0.5) + gt[5] * (py + 0.5)
            ex, ey = tm.pixel_to_map(px, py, CX, CY, ROTATION, SX, SY, W, H)
            assert (gx, gy) == pytest.approx((ex, ey), abs=1e-9)
