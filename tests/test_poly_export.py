"""
Integration test of the polynomial export path: replicate the exact GDAL
calls of ExportGeorefRasterCommand._exportPolyWarp (GCP grid sampled from
the fitted polynomial + ORDER transformer option) headlessly. Skipped
automatically if GDAL python bindings are missing.
"""

import math

import pytest

gdal = pytest.importorskip("osgeo.gdal")

import transform_math as tm  # noqa: E402

gdal.UseExceptions()

W, H = 200, 100
PROJ4_UTM37N = (
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

# poly2 coefficients: gentle quadratic warp over an affine base
COEFFS = [
    500000.0, 10.0, -0.02, 1e-9, -2e-9, 1e-9,   # X
    4500000.0, 0.01, -15.0, 5e-10, 3e-9, -1e-9,  # Y
]
FIT = {"poly": 2, "coeffs": COEFFS}
LOCAL = tm.poly_local_params(FIT, W, H)


def _gcp_grid(per_axis=9):
    gcps = []
    for j in range(per_axis):
        py = j * (H - 1) / float(per_axis - 1)
        for i in range(per_axis):
            px = i * (W - 1) / float(per_axis - 1)
            mx, my = tm.poly_pixel_to_map(px, py, FIT, W, H)
            gcps.append(gdal.GCP(mx, my, 0.0, px + 0.5, py + 0.5))
    return gcps


def _snapped_bounds():
    xs, ys = [], []
    n = 24
    for i in range(n + 1):
        for j in range(n + 1):
            mx, my = tm.poly_pixel_to_map(
                i / n * W, j / n * H, FIT, W, H
            )
            xs.append(mx)
            ys.append(my)
    sx, sy = LOCAL["xScale"], LOCAL["yScale"]
    return (
        math.floor(min(xs) / sx) * sx,
        math.floor(min(ys) / sy) * sy,
        math.ceil(max(xs) / sx) * sx,
        math.ceil(max(ys) / sy) * sy,
    )


@pytest.fixture(scope="module")
def src_path(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("poly") / "src.tif")
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, W, H, 1, gdal.GDT_Byte)
    data = bytearray()
    for row in range(H):
        for col in range(W):
            data.append((col * 7 + row * 3) % 256)
    ds.GetRasterBand(1).WriteRaster(0, 0, W, H, bytes(data), buf_type=gdal.GDT_Byte)
    ds = None
    return path


class TestPolyWarp:
    def test_warp_order2(self, tmp_path, src_path):
        dest = str(tmp_path / "warped.tif")
        vrtPath = "/vsimem/test_poly_warp.vrt"
        vrt = gdal.Translate(vrtPath, src_path)
        try:
            vrt.SetGCPs(_gcp_grid(), PROJ4_UTM37N)
            out = gdal.Warp(
                dest,
                vrt,
                format="GTiff",
                dstSRS=PROJ4_UTM37N,
                resampleAlg="near",
                dstAlpha=True,
                outputBounds=_snapped_bounds(),
                xRes=LOCAL["xScale"],
                yRes=LOCAL["yScale"],
                transformerOptions=["ORDER=2"],
                creationOptions=["TILED=YES", "COMPRESS=DEFLATE"],
            )
            assert out is not None
            gt = out.GetGeoTransform()
            out = None
            # north-up output with the requested pixel size
            assert gt[1] == pytest.approx(LOCAL["xScale"], rel=1e-6)
            assert abs(gt[5]) == pytest.approx(LOCAL["yScale"], rel=1e-6)
            assert gt[2] == pytest.approx(0.0, abs=1e-12)
            assert gt[4] == pytest.approx(0.0, abs=1e-12)
            minX, minY, maxX, maxY = _snapped_bounds()
            assert gt[0] == pytest.approx(minX, abs=abs(gt[1]))
            assert gt[3] == pytest.approx(maxY, abs=abs(gt[5]))
        finally:
            gdal.Unlink(vrtPath)

    def test_warp_order1_matches_affine(self, tmp_path, src_path):
        """Order 1: the warp output extent must match the affine bounds."""
        fit1 = {"poly": 1, "coeffs": COEFFS[:6] + COEFFS[6:9]}
        local = tm.poly_local_params(fit1, W, H)
        dest = str(tmp_path / "warped1.tif")
        vrtPath = "/vsimem/test_poly_warp1.vrt"
        vrt = gdal.Translate(vrtPath, src_path)
        try:
            gcps = []
            per_axis = 9
            for j in range(per_axis):
                py = j * (H - 1) / float(per_axis - 1)
                for i in range(per_axis):
                    px = i * (W - 1) / float(per_axis - 1)
                    mx, my = tm.poly_pixel_to_map(px, py, fit1, W, H)
                    gcps.append(gdal.GCP(mx, my, 0.0, px + 0.5, py + 0.5))
            vrt.SetGCPs(gcps, PROJ4_UTM37N)
            xs, ys = [], []
            for i in range(25):
                for j in range(25):
                    mx, my = tm.poly_pixel_to_map(
                        i / 24 * W, j / 24 * H, fit1, W, H
                    )
                    xs.append(mx)
                    ys.append(my)
            sx, sy = local["xScale"], local["yScale"]
            bounds = (
                math.floor(min(xs) / sx) * sx,
                math.floor(min(ys) / sy) * sy,
                math.ceil(max(xs) / sx) * sx,
                math.ceil(max(ys) / sy) * sy,
            )
            out = gdal.Warp(
                dest,
                vrt,
                format="GTiff",
                dstSRS=PROJ4_UTM37N,
                resampleAlg="near",
                dstAlpha=True,
                outputBounds=bounds,
                xRes=sx,
                yRes=sy,
                transformerOptions=["ORDER=1"],
            )
            assert out is not None
            gt = out.GetGeoTransform()
            out = None
            assert gt[1] == pytest.approx(sx, rel=1e-6)
            assert abs(gt[5]) == pytest.approx(sy, rel=1e-6)
        finally:
            gdal.Unlink(vrtPath)
