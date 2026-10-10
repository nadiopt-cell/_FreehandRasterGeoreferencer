"""Regression tests for the polynomial EXPORT (v0.9.16).

The pre-0.9.16 export passed a GCP grid sampled from the layer's
polynomial to gdal.Warp and let GDAL fit its own polynomial through the
samples. The least squares in raw pixel coordinates is catastrophically
conditioned for the large rasters this plugin serves (scanned maps,
tens of thousands of pixels): GDAL's re-fit diverged from the layer's
transform by up to ~700 map units on a 20000x15000 raster and the
exported raster did not match the canvas.

The fix (polywarp.py) warps with the LAYER's coefficients directly:
inverse-mapped output pixels (vectorized Newton, the same algorithm as
the scalar poly_map_to_pixel) + separable kernel sampling. These tests
verify exact registration on synthetic fits, kernel behaviour, palette
expansion and dtype preservation.

Only numpy + GDAL are required (no QGIS / Qt stubs needed):
polywarp imports transform_math only.
"""

import os
import sys

import numpy as np
import pytest

pytest.importorskip("osgeo.gdal")
pytest.importorskip("numpy")

from osgeo import gdal  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from _FreehandRasterGeoreferencer import polywarp, transform_math  # noqa: E402

gdal.UseExceptions()

WKT = (
    'PROJCS["WGS 84 / UTM zone 54N",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",141],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],UNIT["metre",1]]'
)


def _block_fit(order=3, cx=500000.0, cy=4350000.0, s=10.0):
    """A mild polynomial fit: affine (scale s, 5 deg CW) + small cubic
    terms - the shape a real tie-point fit has."""
    basis = transform_math._POLY_BASIS[order]
    cxk = {t: 0.0 for t in basis}
    cyk = {t: 0.0 for t in basis}
    cxk[(0, 0)] = cx
    cyk[(0, 0)] = cy
    cxk[(1, 0)] = s * 0.996
    cxk[(0, 1)] = -s * 0.087
    cyk[(1, 0)] = s * 0.087
    cyk[(0, 1)] = -s * 0.996
    if order >= 3:
        cxk[(3, 0)] = 1e-9
        cxk[(0, 3)] = -8e-10
        cyk[(2, 1)] = 7e-10
        cyk[(1, 2)] = -9e-10
    return {
        "poly": order,
        "coeffs": [cxk[t] for t in basis] + [cyk[t] for t in basis],
    }


def _make_source(path, w, h, block=50, dtype=gdal.GDT_Byte, palette=False):
    drv = gdal.GetDriverByName("GTiff")
    options = ["PHOTOMETRIC=PALETTE"] if palette else []
    ds = drv.Create(path, w, h, 1, dtype, options=options)
    if palette:
        ct = gdal.ColorTable()
        for i, c in enumerate([(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)]):
            ct.SetColorEntry(i, c)
        ds.GetRasterBand(1).SetRasterColorTable(ct)
    rows_at_once = max(1, min(h, 32 * 1024 * 1024 // (w * 8)))
    for row0 in range(0, h, rows_at_once):
        nrows = min(rows_at_once, h - row0)
        yy, xx = np.mgrid[row0 : row0 + nrows, 0:w]
        if palette:
            # cycle the 4 palette entries per block (all of them appear)
            band = ((xx // block) + (yy // block)) % 4
        else:
            band = (((xx // block) * 13 + (yy // block) * 7) % 251 + 1)
        ds.WriteArray(band.astype(np.uint8), yoff=row0)
    ds.FlushCache()
    ds = None


def _footprint(fit, w, h, s, pad_px=4):
    """Warped footprint bounds snapped outward to whole pixels, like the
    plugin does from the layer extent."""
    n = 32
    pts = []
    for py in np.linspace(0, h - 1, n):
        for px in (0.0, w - 1.0):
            pts.append(transform_math.poly_pixel_to_map(px, py, fit, w, h))
    for px in np.linspace(0, w - 1, n):
        for py in (0.0, h - 1.0):
            pts.append(transform_math.poly_pixel_to_map(px, py, fit, w, h))
    minX = min(p[0] for p in pts) - pad_px * s
    maxX = max(p[0] for p in pts) + pad_px * s
    minY = min(p[1] for p in pts) - pad_px * s
    maxY = max(p[1] for p in pts) + pad_px * s
    return (
        np.floor(minX / s) * s,
        np.floor(minY / s) * s,
        np.ceil(maxX / s) * s,
        np.ceil(maxY / s) * s,
    )


def test_polywarp_exact_registration_mild_fit(tmp_path):
    """Block-pattern source + mild poly3 fit: every sampled output pixel
    must hold the value of its source block (near resampling), proving
    the export is registered with the layer's transform."""
    w, h, s = 900, 700, 10.0
    srcPath = str(tmp_path / "src.tif")
    outPath = str(tmp_path / "out.tif")
    _make_source(srcPath, w, h, block=50)
    fit = _block_fit(3, s=s)
    bounds = _footprint(fit, w, h, s)

    polywarp.warp_poly(
        srcPath, outPath, fit, w, h, WKT, bounds, s, s,
        resampling="near", creationOptions=[],
    )

    out = gdal.Open(outPath)
    assert out.RasterCount == 2  # data + alpha
    gt = out.GetGeoTransform()
    assert gt[1] == pytest.approx(s) and gt[5] == pytest.approx(-s)
    assert gt[2] == 0.0 and gt[4] == 0.0  # north-up grid
    assert out.GetProjection() != ""

    data = out.GetRasterBand(1).ReadAsArray().astype(int)
    alpha = out.GetRasterBand(2).ReadAsArray()

    def expected_value(px, py):
        return int(((int(px) // 50) * 13 + (int(py) // 50) * 7) % 251 + 1)

    checked = 0
    # sample block CENTERS: a +-1px registration error cannot cross a
    # block border there (the pattern blocks are 50 px)
    for py in range(25, h - 25, 50):
        for px in range(25, w - 25, 50):
            mx, my = transform_math.poly_pixel_to_map(
                float(px), float(py), fit, w, h
            )
            i = int(round((mx - gt[0]) / gt[1] - 0.5))
            j = int(round((my - gt[3]) / gt[5] - 0.5))
            if i < 0 or j < 0 or i >= out.RasterXSize or j >= out.RasterYSize:
                continue
            # block pattern: a +-1px registration error cannot cross a
            # block border except at the edges (25px margin here)
            assert alpha[j, i] > 0, "interior pixel must be valid"
            assert data[j, i] == expected_value(px, py), (
                "export content mismatch at source pixel %d,%d" % (px, py)
            )
            checked += 1
    assert checked > 200


def test_polywarp_grid_newton_matches_scalar():
    """The vectorized Newton of poly_map_to_pixel_grid must agree with
    the scalar poly_map_to_pixel on a regular (non-folded) fit."""
    fit = _block_fit(3)
    w, h = 800, 600
    # dense map grid inside the footprint
    m0x, m0y = transform_math.poly_pixel_to_map(0, 0, fit, w, h)
    m1x, m1y = transform_math.poly_pixel_to_map(w - 1, h - 1, fit, w, h)
    xs = np.linspace(min(m0x, m1x) + 50, max(m0x, m1x) - 50, 40)
    ys = np.linspace(min(m0y, m1y) + 50, max(m0y, m1y) - 50, 40)
    MX, MY = np.meshgrid(xs, ys)
    px, py, ok = transform_math.poly_map_to_pixel_grid(
        MX.ravel(), MY.ravel(), fit, w, h
    )
    assert ok.all(), "Newton must converge everywhere in the footprint"
    for k in range(px.size):
        sx, sy = transform_math.poly_map_to_pixel(
            float(MX.ravel()[k]), float(MY.ravel()[k]), fit, w, h
        )
        assert abs(sx - px[k]) < 1e-6
        assert abs(sy - py[k]) < 1e-6


def test_polywarp_palette_expanded_and_dtype_kept(tmp_path):
    w, h, s = 200, 150, 10.0
    fit = _block_fit(3, s=s)
    bounds = _footprint(fit, w, h, s)

    # palette -> RGB + alpha
    palPath = str(tmp_path / "pal.tif")
    palOut = str(tmp_path / "pal_out.tif")
    _make_source(palPath, w, h, block=30, palette=True)
    polywarp.warp_poly(
        palPath, palOut, fit, w, h, WKT, bounds, s, s,
        resampling="near", creationOptions=[],
    )
    out = gdal.Open(palOut)
    assert out.RasterCount == 4  # RGB + alpha
    bands = [out.GetRasterBand(b + 1).ReadAsArray() for b in range(3)]
    colors = set(
        zip(bands[0].ravel().tolist(), bands[1].ravel().tolist(),
            bands[2].ravel().tolist())
    )
    assert colors.issubset({(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)})
    assert len(colors) == 4

    # UInt16 kept
    u16Path = str(tmp_path / "u16.tif")
    u16Out = str(tmp_path / "u16_out.tif")
    _make_source(u16Path, w, h, block=30, dtype=gdal.GDT_UInt16)
    polywarp.warp_poly(
        u16Path, u16Out, fit, w, h, WKT, bounds, s, s,
        resampling="near", creationOptions=[],
    )
    out = gdal.Open(u16Out)
    assert gdal.GetDataTypeName(out.GetRasterBand(1).DataType) == "UInt16"


def test_polywarp_bilinear_and_cubic_kernels(tmp_path):
    w, h, s = 300, 200, 10.0
    fit = _block_fit(3, s=s)
    bounds = _footprint(fit, w, h, s)
    srcPath = str(tmp_path / "src.tif")
    _make_source(srcPath, w, h, block=50)
    results = []
    for kern in ("near", "bilinear", "cubic"):
        outPath = str(tmp_path / ("out_%s.tif" % kern))
        polywarp.warp_poly(
            srcPath, outPath, fit, w, h, WKT, bounds, s, s,
            resampling=kern, creationOptions=["COMPRESS=DEFLATE"],
        )
        out = gdal.Open(outPath)
        data = out.GetRasterBand(1).ReadAsArray().astype(float)
        alpha = out.GetRasterBand(2).ReadAsArray()
        assert np.isfinite(data).all()
        assert (alpha > 0).mean() > 0.3
        results.append(data[alpha > 0])
    # a smooth kernel must differ from nearest somewhere (interpolation)
    assert not np.array_equal(results[0], results[1])


def test_polywarp_resampling_fallback_unknown(tmp_path):
    """Unknown resampling names fall back to near instead of failing."""
    w, h, s = 120, 100, 10.0
    fit = _block_fit(1, s=s)
    bounds = _footprint(fit, w, h, s)
    srcPath = str(tmp_path / "src.tif")
    outPath = str(tmp_path / "out.tif")
    _make_source(srcPath, w, h, block=25)
    polywarp.warp_poly(
        srcPath, outPath, fit, w, h, WKT, bounds, s, s,
        resampling="lanczos", creationOptions=[],
    )
    out = gdal.Open(outPath)
    assert out.RasterXSize > 0 and out.RasterCount == 2


def test_polywarp_rejects_absurd_output(tmp_path):
    """A broken fit / wrong units must raise instead of allocating 4 TB."""
    w, h, s = 50, 40, 10.0
    fit = _block_fit(3, s=s)
    srcPath = str(tmp_path / "src.tif")
    outPath = str(tmp_path / "out.tif")
    _make_source(srcPath, w, h, block=10)
    with pytest.raises(RuntimeError):
        polywarp.warp_poly(
            srcPath, outPath, fit, w, h, WKT,
            (400000.0, 4300000.0, 600000.0, 4400000.0),  # ~10 km wide
            0.001, 0.001,
            resampling="near", creationOptions=[],
        )
