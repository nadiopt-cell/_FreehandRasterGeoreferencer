"""
Tests of the export creation-option builder (export_options.py): the
compression validation / fallback rules and the predictor selection, plus
integration tests replicating the exact GDAL calls of the COG export
paths with the produced options. Skipped automatically if GDAL python
bindings are missing.
"""

import pytest

gdal = pytest.importorskip("osgeo.gdal")

import export_options as eo  # noqa: E402

gdal.UseExceptions()

W, H = 200, 100


# ---------------------------------------------------------------------------
# unit tests of the option builder (pure logic, no files)
# ---------------------------------------------------------------------------


class TestPredictorFor:
    def test_integer_types_get_standard(self):
        for dt in (
            gdal.GDT_Byte,
            gdal.GDT_Int16,
            gdal.GDT_UInt16,
            gdal.GDT_Int32,
            gdal.GDT_UInt32,
        ):
            assert eo.predictorFor(dt) == "STANDARD"

    def test_float_types_get_floating_point(self):
        assert eo.predictorFor(gdal.GDT_Float32) == "FLOATING_POINT"
        assert eo.predictorFor(gdal.GDT_Float64) == "FLOATING_POINT"

    def test_complex_types_get_no_predictor(self):
        assert eo.predictorFor(gdal.GDT_CInt16) is None
        assert eo.predictorFor(gdal.GDT_CFloat32) is None


class TestRasterCreationOptions:
    def test_deflate_byte_gets_standard_predictor(self):
        options, warning = eo.rasterCreationOptions(
            "DEFLATE", gdal.GDT_Byte, 3, "COG"
        )
        assert warning is None
        assert "COMPRESS=DEFLATE" in options
        assert "PREDICTOR=STANDARD" in options

    def test_deflate_float_gets_floating_point_predictor(self):
        options, warning = eo.rasterCreationOptions(
            "DEFLATE", gdal.GDT_Float32, 1, "GTiff"
        )
        assert warning is None
        assert "PREDICTOR=FLOATING_POINT" in options

    def test_deflate_is_the_no_warning_default(self):
        options, warning = eo.rasterCreationOptions(
            None, gdal.GDT_Byte, 3, "COG"
        )
        assert warning is None
        assert options[0] == "COMPRESS=DEFLATE"

    def test_jpeg_kept_for_3_band_byte(self):
        options, warning = eo.rasterCreationOptions(
            "JPEG", gdal.GDT_Byte, 3, "COG"
        )
        assert warning is None
        assert "COMPRESS=JPEG" in options
        assert "QUALITY=%d" % eo.JPEG_QUALITY in options
        assert not any(o.startswith("PREDICTOR") for o in options)

    def test_jpeg_falls_back_when_alpha_would_be_lost(self):
        # the warp paths add an alpha band: 3 source bands + 1 = 4
        options, warning = eo.rasterCreationOptions(
            "JPEG", gdal.GDT_Byte, 4, "COG"
        )
        assert warning and "DEFLATE was used" in warning
        assert options[0] == "COMPRESS=DEFLATE"

    def test_jpeg_falls_back_for_exotic_types(self):
        options, warning = eo.rasterCreationOptions(
            "JPEG", gdal.GDT_Float32, 1, "COG"
        )
        assert warning
        assert options[0] == "COMPRESS=DEFLATE"

    def test_webp_kept_for_4_band_byte(self):
        options, warning = eo.rasterCreationOptions(
            "WEBP", gdal.GDT_Byte, 4, "COG"
        )
        assert warning is None
        assert "COMPRESS=WEBP" in options
        assert "QUALITY=%d" % eo.WEBP_QUALITY in options

    def test_webp_falls_back_for_non_byte(self):
        options, warning = eo.rasterCreationOptions(
            "WEBP", gdal.GDT_UInt16, 1, "COG"
        )
        assert warning and "WEBP" in warning
        assert options[0] == "COMPRESS=DEFLATE"

    def test_webp_falls_back_for_two_bands(self):
        options, warning = eo.rasterCreationOptions(
            "WEBP", gdal.GDT_Byte, 2, "COG"
        )
        assert warning
        assert options[0] == "COMPRESS=DEFLATE"

    def test_unsupported_driver_falls_back(self):
        options, warning = eo.rasterCreationOptions(
            "ZSTD", gdal.GDT_Byte, 3, "NoSuchDriver"
        )
        assert warning and "not supported" in warning
        assert options[0] == "COMPRESS=DEFLATE"
        # the fallback still gets the predictor
        assert "PREDICTOR=STANDARD" in options

    def test_lowercase_input_is_normalized(self):
        options, warning = eo.rasterCreationOptions(
            "jpeg", gdal.GDT_Byte, 3, "COG"
        )
        assert warning is None
        assert "COMPRESS=JPEG" in options

    def test_zstd_support_detected_on_this_build(self):
        # the CI / dev GDAL build ships ZSTD; when it does, no fallback
        if eo.supportsCompression("ZSTD", "COG"):
            options, warning = eo.rasterCreationOptions(
                "ZSTD", gdal.GDT_Byte, 3, "COG"
            )
            assert warning is None
            assert "COMPRESS=ZSTD" in options
            assert "PREDICTOR=STANDARD" in options


# ---------------------------------------------------------------------------
# integration tests: replicate the exact GDAL calls of the export command
# with the built options (a plain stub replaces the QGIS layer)
# ---------------------------------------------------------------------------

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

CX, CY, ROTATION, SX, SY = 500000.0, 4500000.0, 23.0, 10.0, 15.0


def _image_compression(path):
    info = gdal.Info(path, format="json")
    return info.get("metadata", {}).get("IMAGE_STRUCTURE", {}).get("COMPRESSION", "")


@pytest.fixture(scope="module")
def src_path(tmp_path_factory):
    """Synthetic RGB Byte source raster with a gradient pattern."""
    path = str(tmp_path_factory.mktemp("expo") / "src.tif")
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, W, H, 3, gdal.GDT_Byte)
    for band in range(1, 4):
        data = bytearray()
        for row in range(H):
            for col in range(W):
                data.append((col * 7 + row * 3 + band * 40) % 256)
        ds.GetRasterBand(band).WriteRaster(
            0, 0, W, H, bytes(data), buf_type=gdal.GDT_Byte
        )
    ds = None
    return path


class TestCompressionIntegration:
    def _rotated_vrt(self, src_path, vrtPath):
        import transform_math as tm

        vrt = gdal.Translate(vrtPath, src_path)
        gt = tm.geotransform_from_params(CX, CY, ROTATION, SX, SY, W, H)
        vrt.SetGeoTransform(gt)
        vrt.SetProjection(PROJ4_UTM37N)
        return vrt

    def test_rotated_cog_jpeg(self, tmp_path, src_path):
        """Rotated COG of a 3-band byte raster with JPEG: the requested
        compression is kept and the output is a 3-band JPEG COG."""
        dest = str(tmp_path / "rot_jpeg.tif")
        vrtPath = "/vsimem/test_expo_rot.vrt"
        vrt = self._rotated_vrt(src_path, vrtPath)
        try:
            options, warning = eo.rasterCreationOptions(
                "JPEG", vrt.GetRasterBand(1).DataType, vrt.RasterCount, "COG"
            )
            assert warning is None
            driver = gdal.GetDriverByName("COG")
            driver.CreateCopy(dest, vrt, options=options)
            # no band dropped: the 3-band source stays 3-band
            assert gdal.Open(dest).RasterCount == 3
            assert "JPEG" in _image_compression(dest)
        finally:
            gdal.Unlink(vrtPath)

    def test_rotated_cog_deflate_predictor(self, tmp_path, src_path):
        dest = str(tmp_path / "rot_def.tif")
        vrtPath = "/vsimem/test_expo_def.vrt"
        vrt = self._rotated_vrt(src_path, vrtPath)
        try:
            options, warning = eo.rasterCreationOptions(
                "DEFLATE", vrt.GetRasterBand(1).DataType, vrt.RasterCount, "COG"
            )
            assert warning is None
            assert "PREDICTOR=STANDARD" in options
            driver = gdal.GetDriverByName("COG")
            driver.CreateCopy(dest, vrt, options=options)
            assert _image_compression(dest) == "DEFLATE"
        finally:
            gdal.Unlink(vrtPath)

    def _warped_cog(self, tmp_path, src_path, dest, compression):
        """Replicate _exportCogNorthUp: 4 corner GCPs + warp with
        dstAlpha=True and the validated creation options."""
        import transform_math as tm

        vrtPath = "/vsimem/test_expo_warp.vrt"
        vrt = gdal.Translate(vrtPath, src_path)
        try:
            gcps = []
            for px, py in (
                (0, 0),
                (W - 1, 0),
                (W - 1, H - 1),
                (0, H - 1),
            ):
                mx, my = tm.pixel_to_map(
                    px, py, CX, CY, ROTATION, SX, SY, W, H
                )
                gcps.append(gdal.GCP(mx, my, 0.0, px + 0.5, py + 0.5))
            vrt.SetGCPs(gcps, PROJ4_UTM37N)

            # band count seen by the export command: RGB source + alpha
            bands = vrt.RasterCount + 1
            options, warning = eo.rasterCreationOptions(
                compression, vrt.GetRasterBand(1).DataType, bands, "COG"
            )
            gdal.Warp(
                dest,
                vrt,
                format="COG",
                dstSRS=PROJ4_UTM37N,
                resampleAlg="near",
                dstAlpha=True,
                outputBounds=(
                    CX - W / 2.0 * SX - SX,
                    CY - H / 2.0 * SY - SY,
                    CX + W / 2.0 * SX + SX,
                    CY + H / 2.0 * SY + SY,
                ),
                xRes=SX,
                yRes=SY,
                creationOptions=options,
            )
            return warning
        finally:
            gdal.Unlink(vrtPath)

    def test_north_up_warp_jpeg_falls_back_to_deflate(
        self, tmp_path, src_path
    ):
        """JPEG + the alpha band added by the warp: the option builder
        falls back to DEFLATE so no alpha band is silently dropped."""
        dest = str(tmp_path / "warp_jpeg.tif")
        warning = self._warped_cog(tmp_path, src_path, dest, "JPEG")
        assert warning and "DEFLATE was used" in warning
        ds = gdal.Open(dest)
        assert ds.RasterCount == 4  # alpha band preserved
        ds = None
        assert _image_compression(dest) == "DEFLATE"

    def test_north_up_warp_webp_keeps_alpha(self, tmp_path, src_path):
        dest = str(tmp_path / "warp_webp.tif")
        warning = self._warped_cog(tmp_path, src_path, dest, "WEBP")
        if eo.supportsCompression("WEBP", "COG"):
            assert warning is None
            ds = gdal.Open(dest)
            assert ds.RasterCount == 4
            ds = None
            assert _image_compression(dest) == "WEBP"
        else:
            assert warning  # unsupported build: DEFLATE fallback
