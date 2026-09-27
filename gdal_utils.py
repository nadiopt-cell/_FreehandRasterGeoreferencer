import numpy as np
from osgeo import gdal


def format(filepath):
    dataset = gdal.Open(filepath, gdal.GA_ReadOnly)
    try:
        cols = dataset.RasterXSize
        rows = dataset.RasterYSize
        bands = dataset.RasterCount
        if bands == 0:
            return None
        band = dataset.GetRasterBand(1)
        bandtype = gdal.GetDataTypeName(band.DataType)

        return bands, bandtype, cols, rows
    finally:
        # release the file handle NOW: a GDAL dataset left open until the
        # garbage collector runs keeps the file locked (Windows / network
        # shares) and breaks later exports over the same file
        dataset = None


def pixels(filepath):
    dataset = gdal.Open(filepath, gdal.GA_ReadOnly)
    try:
        cols = dataset.RasterXSize
        rows = dataset.RasterYSize
        data = dataset.ReadAsArray(0, 0, cols, rows)
    finally:
        dataset = None
    if len(data.shape) == 2:
        # monoband
        data = data.reshape((1, *data.shape))
    return data


def to_byte(data):
    min_ = np.min(data)
    max_ = np.max(data)
    if max_ == min_:
        # flat band: avoid the division by zero (rendered as black)
        return np.zeros(np.shape(data), dtype=np.uint8)
    data = 255.0 * (data - min_) / (max_ - min_)
    data = data.astype(np.uint8)
    return data
