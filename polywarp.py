"""
Exact polynomial warp for the export of a fitted layer.

The previous implementation passed a GCP grid sampled from the layer's
polynomial to gdal.Warp and asked GDAL to fit ITS OWN polynomial of the
same order through those samples. GDAL solves the least squares in raw
pixel coordinates: for the rasters this plugin deals with (scanned maps,
tens of thousands of pixels) the normal equations are catastrophically
conditioned and GDAL's polynomial diverges from the layer's polynomial
by tens / hundreds of MAPP units - the exported raster did not match
the canvas at all.

This module warps with the LAYER's coefficients directly: for every
output pixel center it evaluates the output geotransform, inverts the
layer polynomial with the same vectorized Newton iteration used on the
canvas (transform_math.poly_map_to_pixel_grid) and samples the source
with a separable kernel. The result matches the screen exactly (the
same transform_math functions), for any raster size.

Only numpy + GDAL - no QGIS / Qt, so it is testable headlessly.
"""

import math

import numpy as np
from osgeo import gdal

from . import transform_math

gdal.UseExceptions()

# guard against absurd output sizes (broken fit / wrong units)
MAX_OUTPUT_PIXELS = 400_000_000

# output tiles: Newton + sampling run on tile*tile windows
TILE = 512


# ----------------------------------------------------------------------
# separable sampling kernels (taps at integer offsets, weights)
# ----------------------------------------------------------------------

def _kernel_taps(name):
    """(offsets, weight function) of the resampling kernel in GDAL terms."""
    if name == "bilinear":
        return (0, 1), "bilinear"
    if name == "cubic":
        return (-1, 0, 1, 2), "cubic"
    # near and anything unknown
    return (0,), "near"


def _weights(kind, t):
    """Kernel weights for fractional distance t in [0, 1)."""
    if kind == "bilinear":
        return (1.0 - t, t)
    if kind == "cubic":
        # Catmull-Rom style cubic convolution, a = -0.5 (GDAL "cubic")
        a = -0.5
        w = []
        for off in (-1, 0, 1, 2):
            d = np.abs(t - off)
            inner = (a + 2.0) * d**3 - (a + 3.0) * d**2 + 1.0
            outer = a * (d**3 - 5.0 * d**2 + 8.0 * d - 4.0)
            w.append(np.where(d < 1.0, inner, np.where(d < 2.0, outer, 0.0)))
        return tuple(w)
    return (np.ones_like(t),)


def _sample(window, px, py, col0, row0, kernel, bands):
    """Sample the source window (rows, cols, bands) at window-relative
    fractional positions (px - col0, py - row0). Returns (values, inside)
    with values (rows, cols, bands) and the boolean inside mask (source
    coordinates within the raster bounds)."""
    h_px, w_px = px.shape
    lr = py - row0
    lc = px - col0
    inside = (
        (lr >= -0.5) & (lr <= window.shape[0] - 0.5) &
        (lc >= -0.5) & (lc <= window.shape[1] - 0.5)
    )

    taps, wkind = _kernel_taps(kernel)
    lr0 = np.floor(lr)
    lc0 = np.floor(lc)
    ty = lr - lr0
    tx = lc - lc0
    wy = _weights(wkind, ty)
    wx = _weights(wkind, tx)

    out = np.zeros((h_px, w_px, bands), dtype=np.float64)
    wsum = np.zeros((h_px, w_px))
    for iy, oy in enumerate(taps):
        ry = (lr0 + oy).astype(np.int64)
        wyv = wy[iy] if wkind != "near" else 1.0
        for ix, ox in enumerate(taps):
            cx = (lc0 + ox).astype(np.int64)
            wxv = wx[ix] if wkind != "near" else 1.0
            # clamp the taps into the window: outside pixels contribute 0
            # (nodata) but do not crash the gather
            ry_c = np.clip(ry, 0, window.shape[0] - 1)
            cx_c = np.clip(cx, 0, window.shape[1] - 1)
            vals = window[ry_c, cx_c]
            wgt = np.asarray(wyv) * np.asarray(wxv)
            out += vals * wgt[..., None]
            wsum += wgt
    if wkind != "near":
        with np.errstate(invalid="ignore", divide="ignore"):
            out = out / np.where(wsum > 1e-12, wsum, 1.0)[..., None]
    else:
        out = np.where(wsum[..., None] > 0, out, 0.0)
    return out, inside


# ----------------------------------------------------------------------
# main entry
# ----------------------------------------------------------------------

def output_info(srcPath):
    """(bandType, outBands) of the warp output for a source raster:
    a paletted single band is expanded to RGB, an alpha band is always
    appended by the warp."""
    src = gdal.Open(srcPath)
    if src is None:
        raise RuntimeError("Unable to open the source raster: %s" % srcPath)
    bandCount = src.RasterCount
    bandType = src.GetRasterBand(1).DataType
    bandsOut = bandCount
    if bandCount == 1 and src.GetRasterBand(1).GetColorTable() is not None:
        bandsOut = 3
    return bandType, bandsOut + 1


def warp_poly(
    srcPath,
    outPath,
    fit,
    width,
    height,
    crsWkt,
    outBounds,
    xRes,
    yRes,
    resampling="near",
    creationOptions=None,
    driver="GTiff",
    progress=None,
):
    """
    Warp the source raster through the layer's polynomial fit `fit`
    (transform_math dict: {"poly": order, "coeffs": [...]}) EXACTLY:
    the layer's coefficients are evaluated per output pixel - nothing is
    re-fitted.

    outBounds: (minX, minY, maxX, maxY) in map units (the warped
    footprint, snapped outward by the caller).
    xRes / yRes: output pixel size in map units (the local affine
    equivalent at the image center, kept by the caller).
    resampling: "near" | "bilinear" | "cubic" (unknown -> near).
    creationOptions: list of GDAL creation options (validated by the
    caller through export_options).
    progress: optional callable(fraction 0..1) - called per output tile.

    Returns the output dataset size (nx, ny). The output is a north-up
    GeoTIFF (or whatever driver is requested) with the geotransform and
    projection set; an extra alpha band marks the valid (inside) area.
    """
    if resampling not in ("near", "bilinear", "cubic"):
        resampling = "near"

    minX, minY, maxX, maxY = outBounds
    nx = int(round((maxX - minX) / float(xRes)))
    ny = int(round((maxY - minY) / float(yRes)))
    if nx <= 0 or ny <= 0:
        raise RuntimeError("Empty export extent for the fitted transform")
    if nx * ny > MAX_OUTPUT_PIXELS:
        raise RuntimeError(
            "Export extent too large (%d x %d pixels); check the fit"
            % (nx, ny)
        )

    src = gdal.Open(srcPath)
    if src is None:
        raise RuntimeError("Unable to open the source raster: %s" % srcPath)

    bandCount = src.RasterCount
    bandType = src.GetRasterBand(1).DataType
    # a paletted band is expanded to RGB (a warp output is never paletted)
    expandPalette = False
    palette = None
    if bandCount == 1:
        ct = src.GetRasterBand(1).GetColorTable()
        if ct is not None:
            expandPalette = True
            count = max(256, ct.GetCount())
            palette = np.zeros((count, 3), dtype=np.float64)
            for i in range(ct.GetCount()):
                e = ct.GetColorEntry(i)
                palette[i] = (e[0], e[1], e[2])
            bandsOut = 3
        else:
            bandsOut = 1
    else:
        bandsOut = bandCount

    outBands = bandsOut + 1  # alpha

    drv = gdal.GetDriverByName(driver)
    if drv is None:
        raise RuntimeError("GDAL driver not available: %s" % driver)
    opts = list(creationOptions or [])
    out = drv.Create(outPath, nx, ny, outBands, bandType, opts)
    if out is None:
        raise RuntimeError("Cannot create the export raster: %s" % outPath)
    out.SetGeoTransform((minX, xRes, 0.0, maxY, 0.0, -yRes))
    out.SetProjection(crsWkt)

    gt = (minX, xRes, 0.0, maxY, 0.0, -yRes)

    half = 1 + (len(_kernel_taps(resampling)[0]) // 2)
    for ty0 in range(0, ny, TILE):
        ty1 = min(ny, ty0 + TILE)
        for tx0 in range(0, nx, TILE):
            tx1 = min(nx, tx0 + TILE)
            _warp_tile(
                out, src, fit, width, height, gt, tx0, ty0, tx1, ty1,
                resampling, bandType, bandsOut, expandPalette, palette,
                half,
            )
        if progress is not None:
            progress(min(1.0, ty1 / float(ny)))

    out.FlushCache()
    out = None
    src = None
    return nx, ny


def _warp_tile(
    out, src, fit, width, height, gt, tx0, ty0, tx1, ty1,
    resampling, bandType, bandsOut, expandPalette, palette, half,
):
    j, i = np.meshgrid(
        np.arange(ty0, ty1, dtype=float), np.arange(tx0, tx1, dtype=float),
        indexing="ij",
    )
    # map coordinates of the output pixel centers
    mx = gt[0] + (i + 0.5) * gt[1] + (j + 0.5) * gt[2]
    my = gt[3] + (i + 0.5) * gt[4] + (j + 0.5) * gt[5]

    # the layer's polynomial, inverted exactly (vectorized Newton)
    px, py, ok = transform_math.poly_map_to_pixel_grid(mx, my, fit, width, height)

    # source window covering the tile footprint (kernel half width + 1)
    valid = ok
    if valid.any():
        c0 = int(max(0, math.floor(px[valid].min()) - half))
        c1 = int(min(width - 1, math.ceil(px[valid].max()) + half))
        r0 = int(max(0, math.floor(py[valid].min()) - half))
        r1 = int(min(height - 1, math.ceil(py[valid].max()) + half))
    else:
        c0 = r0 = 0
        c1 = min(width, 2) - 1
        r1 = min(height, 2) - 1
    if c1 < c0 or r1 < r0:
        valid = np.zeros_like(valid)
        c0, c1, r0, r1 = 0, min(width, 1), 0, min(height, 1)

    winW = c1 - c0 + 1
    winH = r1 - r0 + 1
    win = np.zeros((winH, winW, bandsOut), dtype=np.float64)
    if valid.any() and winW > 0 and winH > 0:
        if expandPalette:
            # single paletted band -> expand to the RGB planes
            arr = src.GetRasterBand(1).ReadAsArray(c0, r0, winW, winH)
            idx = np.clip(arr.astype(np.int64), 0, palette.shape[0] - 1)
            rgb = palette[idx]
            win[..., 0] = rgb[..., 0]
            win[..., 1] = rgb[..., 1]
            win[..., 2] = rgb[..., 2]
        else:
            for b in range(bandsOut):
                win[..., b] = src.GetRasterBand(b + 1).ReadAsArray(
                    c0, r0, winW, winH
                ).astype(np.float64)

    values, inside = _sample(win, px, py, float(c0), float(r0), resampling, bandsOut)
    alpha = (valid & inside)
    values = np.where(alpha[..., None], values, 0.0)

    lo, hi = _dtype_range(bandType)
    values = np.clip(values, lo, hi)

    for b in range(bandsOut):
        band = out.GetRasterBand(b + 1)
        band.WriteArray(values[..., b].astype(_numpy_dtype(bandType)), tx0, ty0)
    aband = out.GetRasterBand(bandsOut + 1)
    aband.WriteArray((alpha * 255).astype(np.uint8), tx0, ty0)


def _numpy_dtype(gdalType):
    from osgeo import gdal_array

    return gdal_array.GDALTypeCodeToNumericTypeCode(gdalType)


def _dtype_range(gdalType):
    typeCode = gdal.GetDataTypeName(gdalType)
    ranges = {
        "Byte": (0, 255),
        "Int16": (-32768, 32767),
        "UInt16": (0, 65535),
        "Int32": (-2147483648, 2147483647),
        "UInt32": (0, 4294967295),
        "Float32": (-3.4028235e38, 3.4028235e38),
        "Float64": (-1.7976931348623157e308, 1.7976931348623157e308),
    }
    return ranges.get(typeCode, (0, 255))
