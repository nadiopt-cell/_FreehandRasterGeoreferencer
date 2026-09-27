"""
/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/

Creation-option builders for the GeoTIFF / COG export paths.

Pure GDAL logic (no QGIS imports) so that it can be unit tested
headlessly. It centralizes:

- compression selection with runtime capability validation: the chosen
  COMPRESS value must be advertised by the target driver, otherwise the
  export silently falls back to DEFLATE (GDAL builds without WEBP / ZSTD
  support stay usable),
- lossy compatibility rules: GDAL drops the alpha band SILENTLY when
  writing JPEG-compressed TIFF/COG, so JPEG is only allowed for 1 or 3
  band Byte/UInt16 rasters (a 4th band -> DEFLATE fallback); WEBP keeps
  the alpha channel but only handles Byte rasters with 3 or 4 bands,
- horizontal predictor selection for the lossless codecs (DEFLATE / LZW
  / ZSTD): STANDARD (horizontal differencing) for integer types,
  FLOATING_POINT for float types, nothing for complex / exotic types.
"""

from osgeo import gdal

import re

DEFLATE = "DEFLATE"
JPEG = "JPEG"
WEBP = "WEBP"
ZSTD = "ZSTD"

COMPRESSIONS = (DEFLATE, JPEG, WEBP, ZSTD)

# JPEG inside TIFF/COG: Byte (or UInt16 with NBITS=12) and 1 or 3 bands;
# with any other band count GDAL either fails or silently drops the
# alpha band, so those combinations fall back to DEFLATE
JPEG_DTYPES = (gdal.GDT_Byte, gdal.GDT_UInt16)
JPEG_BANDS = (1, 3)

# WEBP: Byte only, 3 or 4 bands (4 keeps the alpha channel)
WEBP_DTYPES = (gdal.GDT_Byte,)
WEBP_BANDS = (3, 4)

# lossless codecs support the horizontal predictor; 64-bit integer and
# complex types are not covered by the TIFF predictor specification
_INT_PREDICTOR_DTYPES = (
    gdal.GDT_Byte,
    gdal.GDT_Int16,
    gdal.GDT_UInt16,
    gdal.GDT_Int32,
    gdal.GDT_UInt32,
)
_FLOAT_PREDICTOR_DTYPES = (gdal.GDT_Float32, gdal.GDT_Float64)

JPEG_QUALITY = 85
WEBP_QUALITY = 80


def predictorFor(dataType):
    """TIFF predictor value for a lossless codec, or None when the data
    type must not be combined with a predictor."""
    if dataType in _INT_PREDICTOR_DTYPES:
        return "STANDARD"
    if dataType in _FLOAT_PREDICTOR_DTYPES:
        return "FLOATING_POINT"
    return None


def supportsCompression(compression, driverName):
    """True when the driver advertises the COMPRESS value (the creation
    option list metadata is the authoritative source per GDAL build)."""
    driver = gdal.GetDriverByName(driverName)
    if driver is None:
        return False
    meta = driver.GetMetadataItem(gdal.DMD_CREATIONOPTIONLIST) or ""
    return (
        re.search(
            r"<value>\s*%s\s*</value>" % re.escape(compression), meta, re.I
        )
        is not None
    )


def rasterCreationOptions(compression, dataType, bandCount, driverName="COG"):
    """
    Creation options for the given driver and raster characteristics.

    Returns (options, warning): the list of GDAL creation options and a
    user-facing message when the requested compression had to be replaced
    by DEFLATE (unsupported by this GDAL build, or incompatible with the
    data type / band count). warning is None when the requested
    compression was kept.
    """
    comp = (compression or DEFLATE).upper()
    warning = None
    if comp != DEFLATE and not supportsCompression(comp, driverName):
        warning = (
            "Compression %s is not supported by this GDAL build; "
            "DEFLATE was used instead." % comp
        )
        comp = DEFLATE
    if comp == JPEG and (
        dataType not in JPEG_DTYPES or bandCount not in JPEG_BANDS
    ):
        warning = (
            "JPEG compression keeps only 1 or 3 bands and cannot store "
            "the alpha band; DEFLATE was used instead."
        )
        comp = DEFLATE
    elif comp == WEBP and (
        dataType not in WEBP_DTYPES or bandCount not in WEBP_BANDS
    ):
        warning = (
            "WEBP compression requires a Byte raster with 3 or 4 bands; "
            "DEFLATE was used instead."
        )
        comp = DEFLATE

    options = ["COMPRESS=" + comp]
    if comp == JPEG:
        options.append("QUALITY=%d" % JPEG_QUALITY)
    elif comp == WEBP:
        options.append("QUALITY=%d" % WEBP_QUALITY)
    else:
        # DEFLATE / LZW / ZSTD: the horizontal predictor typically
        # reduces the size by 10-30% on continuous rasters
        predictor = predictorFor(dataType)
        if predictor is not None:
            options.append("PREDICTOR=" + predictor)
    return options, warning
