import math
import random

import numpy as np
import pytest

import transform_math as tm

W, H = 800, 600


def _make_pairs(cx, cy, rotation, sx, sy, pixels, noise=0.0, seed=42):
    rng = random.Random(seed)
    pairs = []
    for px, py in pixels:
        mx, my = tm.pixel_to_map(px, py, cx, cy, rotation, sx, sy, W, H)
        if noise:
            mx += rng.gauss(0, noise)
            my += rng.gauss(0, noise)
        pairs.append((float(px), float(py), mx, my))
    return pairs


PIXELS = [(0, 0), (W - 1, 0), (W - 1, H - 1), (0, H - 1), (120, 77), (512, 300)]


class TestNormalizeRotation:
    def test_rounding(self):
        assert tm.normalize_rotation(1.23456) == 1.235

    def test_wrap_positive(self):
        assert tm.normalize_rotation(181.0) == -179.0

    def test_wrap_negative(self):
        assert tm.normalize_rotation(-181.0) == 179.0

    def test_range(self):
        for v in (-180, -90, 0, 90, 180):
            assert tm.normalize_rotation(v) == v


class TestPixelMapRoundTrip:
    def test_roundtrip(self):
        for rotation in (0.0, 33.3, -125.7, 179.9):
            for sx, sy in ((1.0, 1.0), (1.35, 0.62)):
                cx, cy = 512345.6, 7890123.4
                px, py = tm.map_to_pixel(
                    512900.0, 7890800.0, cx, cy, rotation, sx, sy, W, H
                )
                x, y = tm.pixel_to_map(px, py, cx, cy, rotation, sx, sy, W, H)
                assert x == pytest.approx(512900.0, abs=1e-6)
                assert y == pytest.approx(7890800.0, abs=1e-6)


class TestCorners:
    def test_no_rotation(self):
        cx, cy, sx, sy = 100.0, 200.0, 0.5, 2.0
        tl, tr, br, bl = tm.corners(cx, cy, 0.0, sx, sy, W, H)
        assert tl == (cx - W / 2 * sx, cy + H / 2 * sy)
        assert tr == (cx + W / 2 * sx, cy + H / 2 * sy)
        assert br == (cx + W / 2 * sx, cy - H / 2 * sy)
        assert bl == (cx - W / 2 * sx, cy - H / 2 * sy)

    def test_rotation_quarter(self):
        # 90 degrees CW: the top-left corner moves to the top-right position
        cx, cy, s = 1000.0, 2000.0, 1.0
        tl, tr, br, bl = tm.corners(cx, cy, 90.0, s, s, W, H)
        assert tl == pytest.approx((cx + H / 2, cy + W / 2))
        assert tr == pytest.approx((cx + H / 2, cy - W / 2))
        assert br == pytest.approx((cx - H / 2, cy - W / 2))
        assert bl == pytest.approx((cx - H / 2, cy + W / 2))

    def test_matches_pixel_to_map(self):
        cx, cy, rotation, sx, sy = 42.0, -8.0, 23.0, 1.1, 0.9
        cs = tm.corners(cx, cy, rotation, sx, sy, W, H)
        # geometric corner = pixel-center (0,0) shifted by half pixel both ways
        px, py = tm.pixel_to_map(-0.5, -0.5, cx, cy, rotation, sx, sy, W, H)
        assert cs[0] == pytest.approx((px, py))


class TestGeotransform:
    def test_roundtrip(self):
        cx, cy, rotation, sx, sy = 512345.6, 7890123.4, 15.5, 2.5, 1.75
        gt = tm.geotransform_from_params(cx, cy, rotation, sx, sy, W, H)
        cx2, cy2, rot2, sx2, sy2 = tm.params_from_geotransform(gt, W, H)
        assert (cx2, cy2) == pytest.approx((cx, cy), abs=1e-6)
        assert rot2 == pytest.approx(rotation, abs=1e-6)
        assert sx2 == pytest.approx(sx, abs=1e-9)
        assert sy2 == pytest.approx(sy, abs=1e-9)

    def test_matches_world_file_coeffs(self):
        cx, cy, rotation, sx, sy = 100.0, 200.0, 30.0, 0.7, 1.4
        gt = tm.geotransform_from_params(cx, cy, rotation, sx, sy, W, H)
        a, d, b, e, c, f = tm.world_file_from_params(cx, cy, rotation, sx, sy, W, H)
        assert gt[1] == pytest.approx(a)
        assert gt[2] == pytest.approx(b)
        assert gt[4] == pytest.approx(d)
        assert gt[5] == pytest.approx(e)
        # world file anchors pixel (0,0) center; gt anchors grid corner
        assert gt[0] == pytest.approx(c - a / 2.0 - b / 2.0)
        assert gt[3] == pytest.approx(f - d / 2.0 - e / 2.0)

    def test_identity(self):
        gt = tm.geotransform_from_params(10.0, 20.0, 0.0, 1.0, 1.0, 100, 100)
        assert gt[1] == pytest.approx(1.0)
        assert gt[5] == pytest.approx(-1.0)
        assert gt[2] == pytest.approx(0.0)
        assert gt[4] == pytest.approx(0.0)


class TestFitSimilarity:
    def test_exact_two_points(self):
        cx, cy, rotation, s = 500.0, -300.0, 17.0, 1.4
        pairs = _make_pairs(cx, cy, rotation, s, s, [(10, 20), (700, 500)])
        fit = tm.fit_points(pairs, W, H)
        assert fit is not None
        assert fit["rotation"] == pytest.approx(rotation, abs=1e-6)
        assert fit["xScale"] == pytest.approx(s, abs=1e-9)
        assert fit["yScale"] == pytest.approx(s, abs=1e-9)
        assert fit["cx"] == pytest.approx(cx, abs=1e-6)
        assert fit["cy"] == pytest.approx(cy, abs=1e-6)

    def test_umeyama_recover(self):
        cx, cy, rotation, s = 500.0, -300.0, -42.5, 0.8
        pairs = _make_pairs(cx, cy, rotation, s, s, PIXELS)
        fit = tm.fit_similarity(pairs, W, H)
        assert fit["rotation"] == pytest.approx(rotation, abs=1e-6)
        assert fit["xScale"] == pytest.approx(s, abs=1e-6)


class TestFitAnisotropic:
    def test_exact_recovery(self):
        cx, cy, rotation, sx, sy = 512345.6, 7890123.4, -23.5, 1.3, 0.7
        pairs = _make_pairs(cx, cy, rotation, sx, sy, PIXELS)
        fit = tm.fit_anisotropic(pairs, W, H)
        assert fit is not None
        assert fit["rotation"] == pytest.approx(rotation, abs=1e-5)
        assert fit["xScale"] == pytest.approx(sx, abs=1e-6)
        assert fit["yScale"] == pytest.approx(sy, abs=1e-6)
        assert fit["cx"] == pytest.approx(cx, abs=1e-5)
        assert fit["cy"] == pytest.approx(cy, abs=1e-5)

    def test_no_shear_fallback(self):
        # affine-deformable data (sheared): fit must converge to best
        # scaled-rotation approximation, i.e. nonzero but small residuals
        pairs = []
        shear = 0.25
        for px, py in PIXELS:
            dx = (px + 0.5 - W / 2) * 1.2
            dy = (H / 2 - py - 0.5) * 0.8
            mx = 1000 + dx + shear * dy
            my = 2000 + dy
            pairs.append((float(px), float(py), mx, my))
        fit = tm.fit_anisotropic(pairs, W, H)
        _, rms = tm.residuals(pairs, fit, W, H)
        assert rms > 1e-3  # shear cannot be represented
        assert rms < 200.0  # but bounded


class TestFitPoints:
    def test_one_point_is_none(self):
        assert tm.fit_points([(1.0, 1.0, 2.0, 2.0)], W, H) is None

    def test_two_points_uniform(self):
        pairs = _make_pairs(0.0, 0.0, 10.0, 2.0, 2.0, [(0, 0), (799, 599)])
        fit = tm.fit_points(pairs, W, H)
        assert fit["xScale"] == pytest.approx(2.0)
        assert fit["yScale"] == pytest.approx(2.0)

    def test_multi_points_anisotropic(self):
        cx, cy, rotation, sx, sy = 10.0, 20.0, 5.0, 1.5, 0.9
        pairs = _make_pairs(cx, cy, rotation, sx, sy, PIXELS)
        fit = tm.fit_points(pairs, W, H)
        assert fit["xScale"] == pytest.approx(sx, abs=1e-5)
        assert fit["yScale"] == pytest.approx(sy, abs=1e-5)


class TestResiduals:
    def test_perfect_fit(self):
        cx, cy, rotation, sx, sy = 0.0, 0.0, 8.0, 1.1, 0.95
        pairs = _make_pairs(cx, cy, rotation, sx, sy, PIXELS)
        params = {
            "cx": cx,
            "cy": cy,
            "rotation": rotation,
            "xScale": sx,
            "yScale": sy,
        }
        res, rms = tm.residuals(pairs, params, W, H)
        assert rms == pytest.approx(0.0, abs=1e-7)
        assert len(res) == len(pairs)

    def test_noisy_fit(self):
        cx, cy, rotation, sx, sy = 0.0, 0.0, 8.0, 1.1, 0.95
        pairs = _make_pairs(cx, cy, rotation, sx, sy, PIXELS, noise=2.0)
        params = {
            "cx": cx,
            "cy": cy,
            "rotation": rotation,
            "xScale": sx,
            "yScale": sy,
        }
        _, rms = tm.residuals(pairs, params, W, H)
        assert 0.5 < rms < 6.0


class TestLegacyBehavior:
    def test_zero_rotation_identity_world_file(self):
        # matches historical export: no rotation, scale 1 -> a=1, e=-1
        a, d, b, e, c, f = tm.world_file_from_params(0.0, 0.0, 0.0, 1.0, 1.0, 100, 100)
        assert a == pytest.approx(1.0)
        assert e == pytest.approx(-1.0)
        assert d == pytest.approx(0.0)
        assert b == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Polynomial transforms (order 1 = affine, 2, 3)
# ---------------------------------------------------------------------------


def _classic_to_poly1_coeffs(cx, cy, rotation, sx, sy):
    """Poly1 coefficients equivalent to the classic layer parameters.

    pixel_to_map: mx = cx + cos(th)*sx*x - sin(th)*sy*y,
                  my = cy + sin(th)*sx*x + cos(th)*sy*y
    with th the math (CCW) angle and (x, y) the centered Y-up offsets.
    """
    theta = -rotation * math.pi / 180.0  # math CCW (Y-up)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    return [
        cx,
        sx * cos_t,
        -sy * sin_t,
        cy,
        sx * sin_t,
        sy * cos_t,
    ]


def _poly_pairs(fit, pixels, w=W, h=H):
    pairs = []
    for px, py in pixels:
        mx, my = tm.poly_pixel_to_map(px, py, fit, w, h)
        pairs.append((float(px), float(py), mx, my))
    return pairs


SPREAD_PIXELS = [
    (0, 0),
    (W - 1, 0),
    (W - 1, H - 1),
    (0, H - 1),
    (W / 2, 0),
    (W / 2, H - 1),
    (0, H / 2),
    (W - 1, H / 2),
    (W / 3, H / 3),
    (2 * W / 3, 2 * H / 3),
    (W / 4, 3 * H / 4),
    (3 * W / 4, H / 4),
]


class TestPolyBasics:
    def test_num_coeffs(self):
        assert tm.poly_num_coeffs(1) == 3
        assert tm.poly_num_coeffs(2) == 6
        assert tm.poly_num_coeffs(3) == 10
        assert tm.poly_min_points(1) == 3
        assert tm.poly_min_points(2) == 6
        assert tm.poly_min_points(3) == 10

    def test_monomials_order1(self):
        row = tm.poly_monomials(2.0, 3.0, 1)
        assert row == pytest.approx([1.0, 2.0, 3.0])

    def test_monomials_order2(self):
        row = tm.poly_monomials(2.0, 3.0, 2)
        assert row == pytest.approx([1.0, 2.0, 3.0, 4.0, 6.0, 9.0])

    def test_invalid_order_raises(self):
        with pytest.raises(ValueError):
            tm.fit_poly(4, [(1, 1, 2, 2)] * 20, W, H)


class TestFitPoly1:
    def test_exact_recovery(self):
        coeffs = [1500.0, 2.0, -0.5, 3000.0, 0.3, 1.5]
        fit = {"poly": 1, "coeffs": coeffs}
        pairs = _poly_pairs(fit, SPREAD_PIXELS[:5])
        got = tm.fit_poly(1, pairs, W, H)
        assert got is not None
        assert got["coeffs"] == pytest.approx(coeffs, abs=1e-6)

    def test_matches_classic_pixel_to_map(self):
        cx, cy, rotation, sx, sy = 512345.6, 7890123.4, 15.5, 2.5, 1.75
        coeffs = _classic_to_poly1_coeffs(cx, cy, rotation, sx, sy)
        fit = {"poly": 1, "coeffs": coeffs}
        for px, py in [(0, 0), (400, 300), (W - 1, H - 1)]:
            ex, ey = tm.pixel_to_map(px, py, cx, cy, rotation, sx, sy, W, H)
            gx, gy = tm.poly_pixel_to_map(px, py, fit, W, H)
            assert (gx, gy) == pytest.approx((ex, ey), abs=1e-6)

    def test_shear_is_representable(self):
        # affine with shear: the classic anisotropic fit cannot be exact,
        # the poly1 fit must be
        shear = 0.35
        pairs = []
        for px, py in SPREAD_PIXELS[:6]:
            dx = (px + 0.5 - W / 2) * 1.2
            dy = (H / 2 - py - 0.5) * 0.8
            pairs.append((float(px), float(py), 1000 + dx + shear * dy, 2000 + dy))
        poly = tm.fit_poly(1, pairs, W, H)
        _, rms_poly = tm.poly_residuals(pairs, poly, W, H)
        assert rms_poly == pytest.approx(0.0, abs=1e-6)
        classic = tm.fit_anisotropic(pairs, W, H)
        _, rms_classic = tm.residuals(pairs, classic, W, H)
        assert rms_classic > 1.0

    def test_two_points_is_none(self):
        fit = {"poly": 1, "coeffs": [0, 1, 0, 0, 0, 1]}
        pairs = _poly_pairs(fit, [(0, 0), (10, 10)])
        assert tm.fit_poly(1, pairs, W, H) is None

    def test_collinear_points_is_none(self):
        fit = {"poly": 1, "coeffs": [0, 1, 0, 0, 0, 1]}
        pairs = _poly_pairs(fit, [(0, 0), (10, 0), (20, 0)])
        assert tm.fit_poly(1, pairs, W, H) is None


class TestFitPoly2:
    def test_exact_recovery(self):
        coeffs = [
            100.0, 1.5, -0.7, 2e-5, -3e-5, 1e-5,  # X
            200.0, 0.4, 2.0, 1e-5, 4e-5, -2e-5,   # Y
        ]
        fit = {"poly": 2, "coeffs": coeffs}
        pairs = _poly_pairs(fit, SPREAD_PIXELS)
        got = tm.fit_poly(2, pairs, W, H)
        assert got is not None
        assert got["coeffs"] == pytest.approx(coeffs, rel=1e-4, abs=1e-9)
        _, rms = tm.poly_residuals(pairs, got, W, H)
        assert rms == pytest.approx(0.0, abs=1e-6)

    def test_not_enough_points(self):
        coeffs = [0.0] * 6 + [1.0, 0, 0, 0, 0, 0]
        fit = {"poly": 2, "coeffs": coeffs}
        pairs = _poly_pairs(fit, SPREAD_PIXELS[:5])
        assert tm.fit_poly(2, pairs, W, H) is None


class TestFitPoly3:
    def test_exact_recovery(self):
        rng = random.Random(7)
        coeffs = [rng.uniform(-1, 1) for _ in range(20)]
        coeffs[0] = 500.0   # X constant
        coeffs[1] = 1.0     # X dx
        coeffs[10] = -300.0  # Y constant
        coeffs[11] = 0.5    # Y dx
        coeffs[12] = 1.2    # Y dy
        fit = {"poly": 3, "coeffs": coeffs}
        pairs = _poly_pairs(fit, SPREAD_PIXELS)
        assert len(pairs) >= tm.poly_min_points(3)
        got = tm.fit_poly(3, pairs, W, H)
        assert got is not None
        _, rms = tm.poly_residuals(pairs, got, W, H)
        assert rms == pytest.approx(0.0, abs=1e-5)

    def test_not_enough_points(self):
        coeffs = [0.0] * 10 + [1.0] + [0.0] * 9
        fit = {"poly": 3, "coeffs": coeffs}
        pairs = _poly_pairs(fit, SPREAD_PIXELS[:9])
        assert tm.fit_poly(3, pairs, W, H) is None


class TestPolyInversion:
    def test_roundtrip(self):
        coeffs = [
            100.0, 1.5, -0.7, 2e-5, -3e-5, 1e-5,
            200.0, 0.4, 2.0, 1e-5, 4e-5, -2e-5,
        ]
        fit = {"poly": 2, "coeffs": coeffs}
        for px, py in [(0, 0), (100, 250), (W - 1, H - 1), (333.7, 211.2)]:
            mx, my = tm.poly_pixel_to_map(px, py, fit, W, H)
            bx, by = tm.poly_map_to_pixel(mx, my, fit, W, H)
            assert (bx, by) == pytest.approx((px, py), abs=1e-6)


class TestPolyLocalParams:
    def test_matches_classic_params(self):
        cx, cy, rotation, sx, sy = 512345.6, 7890123.4, 15.5, 2.5, 1.75
        coeffs = _classic_to_poly1_coeffs(cx, cy, rotation, sx, sy)
        fit = {"poly": 1, "coeffs": coeffs}
        local = tm.poly_local_params(fit, W, H)
        assert local["cx"] == pytest.approx(cx, abs=1e-6)
        assert local["cy"] == pytest.approx(cy, abs=1e-6)
        assert local["rotation"] == pytest.approx(rotation, abs=1e-6)
        assert local["xScale"] == pytest.approx(sx, abs=1e-9)
        assert local["yScale"] == pytest.approx(sy, abs=1e-9)


class TestPoly1WorldFile:
    def test_matches_classic_world_file(self):
        cx, cy, rotation, sx, sy = 512345.6, 7890123.4, 15.5, 2.5, 1.75
        coeffs = _classic_to_poly1_coeffs(cx, cy, rotation, sx, sy)
        fit = {"poly": 1, "coeffs": coeffs}
        got = tm.poly1_world_file(fit, W, H)
        expected = tm.world_file_from_params(cx, cy, rotation, sx, sy, W, H)
        assert got == pytest.approx(expected, rel=1e-9, abs=1e-9)

    def test_wrong_order_raises(self):
        fit = {"poly": 2, "coeffs": [0.0] * 12}
        with pytest.raises(ValueError):
            tm.poly1_world_file(fit, W, H)


class TestAffineFromCorrespondences:
    def test_exact(self):
        src = np.array([(0.0, 0.0), (10.0, 0.0), (10.0, 20.0), (0.0, 20.0)])
        dst = np.array([(100.0, 200.0), (120.0, 200.0), (130.0, 240.0), (110.0, 240.0)])
        got = tm.affine_from_correspondences(src, dst)
        assert got is not None
        a, b, c, d, e, f = got
        for (sx, sy), (tx, ty) in zip(src, dst):
            assert (a * sx + b * sy + c, d * sx + e * sy + f) == pytest.approx(
                (tx, ty), abs=1e-9
            )

    def test_degenerate_is_none(self):
        src = np.array([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
        dst = np.array([(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)])
        assert tm.affine_from_correspondences(src, dst) is None
