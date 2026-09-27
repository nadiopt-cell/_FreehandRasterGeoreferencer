"""Unit tests for gdal_utils helpers (stable-behaviour regressions).

Covers the zero-range guard of to_byte (division by zero on flat bands)
and the data-path helpers against a temporary real GeoTIFF (the dataset
must be closed inside the functions - no file handle leaks).
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

gdal = pytest.importorskip("osgeo.gdal")

import gdal_utils  # noqa: E402


class TestToByte:
    def test_normal_range(self):
        data = np.array([[0.0, 10.0], [5.0, 2.5]], dtype=np.float32)
        out = gdal_utils.to_byte(data)
        assert out.dtype == np.uint8
        assert out.min() == 0
        assert out.max() == 255

    def test_flat_band_does_not_raise(self):
        # max == min used to raise ZeroDivisionError
        data = np.full((4, 3), 7.0, dtype=np.float64)
        out = gdal_utils.to_byte(data)
        assert out.dtype == np.uint8
        assert out.shape == data.shape
        assert int(out.min()) == 0 and int(out.max()) == 0

    def test_int_input(self):
        data = np.array([[10, 20, 30]], dtype=np.int16)
        out = gdal_utils.to_byte(data)
        assert out.dtype == np.uint8
        assert out[0, 0] == 0 and out[0, -1] == 255

    def test_single_pixel(self):
        out = gdal_utils.to_byte(np.array([[42]], dtype=np.float32))
        assert out.dtype == np.uint8


@pytest.fixture
def tiny_tiff(tmp_path):
    """A tiny 2-band Int16 GeoTIFF to exercise format() / pixels()."""
    path = str(tmp_path / "tiny.tif")
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, 4, 3, 2, gdal.GDT_Int16)
    band1 = np.arange(12, dtype=np.int16).reshape(3, 4)
    band2 = np.full((3, 4), -5, dtype=np.int16)
    ds.GetRasterBand(1).WriteArray(band1)
    ds.GetRasterBand(2).WriteArray(band2)
    ds.FlushCache()
    ds = None
    return path, band1, band2


class TestFormatAndPixels:
    def test_format(self, tiny_tiff):
        path, _, _ = tiny_tiff
        info = gdal_utils.format(path)
        bands, bandtype, cols, rows = info
        assert bands == 2
        assert bandtype == "Int16"
        assert cols == 4 and rows == 3

    def test_pixels(self, tiny_tiff):
        path, band1, band2 = tiny_tiff
        data = gdal_utils.pixels(path)
        assert data.shape == (2, 3, 4)
        assert np.array_equal(data[0], band1)
        assert np.array_equal(data[1], band2)

    def test_pixels_monoband_reshaped(self, tmp_path):
        path = str(tmp_path / "mono.tif")
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(path, 2, 2, 1, gdal.GDT_Byte)
        ds.GetRasterBand(1).WriteArray(np.array([[1, 2], [3, 4]], dtype=np.uint8))
        ds.FlushCache()
        ds = None
        data = gdal_utils.pixels(path)
        # monoband rasters are returned as (1, rows, cols)
        assert data.shape == (1, 2, 2)

    def test_repeated_calls_release_handles(self, tiny_tiff):
        # call the helpers many times: if the datasets were leaked the
        # repeated opens would eventually fail (or lock the file)
        path, _, _ = tiny_tiff
        for _ in range(30):
            assert gdal_utils.format(path) is not None
        for _ in range(30):
            assert gdal_utils.pixels(path).shape == (2, 3, 4)
