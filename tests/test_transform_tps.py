"""
Unit tests of the rubbersheet (thin plate spline, TPS) fit in
transform_math: exact interpolation through the tie points, affine
degeneration, inversion roundtrip, local affine equivalent and JSON
persistence of the fit dict.
"""

import json
import math
import random

import pytest

import transform_math as tm

W, H = 800, 600

GRID9 = [
    (50, 40),
    (400, 30),
    (750, 50),
    (60, 300),
    (400, 300),
    (740, 310),
    (70, 560),
    (400, 570),
    (760, 550),
]


def _field(px, py):
    """Affine base + gentle nonlinear bends (a scanned map sheet)."""
    mx, my = tm.pixel_to_map(px, py, 500000.0, 4500000.0, 12.0, 2.5, 2.5, W, H)
    mx += 8.0 * math.sin(px / W * math.pi) * math.cos(py / H * math.pi)
    my += 6.0 * math.sin(py / H * 1.7 * math.pi)
    return mx, my


def _smooth_pairs(pixels):
    return [(float(px), float(py), *_field(px, py)) for px, py in pixels]


def _affine_pairs(pixels):
    return [
        (float(px), float(py), *tm.pixel_to_map(
            px, py, 500000.0, 4500000.0, 12.0, 2.5, 2.5, W, H
        ))
        for px, py in pixels
    ]


class TestFitTps:
    def test_needs_three_points(self):
        assert tm.fit_tps([], W, H) is None
        assert tm.fit_tps([(0, 0, 10.0, 20.0), (5, 5, 15.0, 25.0)], W, H) is None

    def test_min_points_constant(self):
        assert tm.tps_min_points() == 3

    def test_exact_interpolation_on_arbitrary_targets(self):
        pairs = [
            (0, 0, 100.0, 200.0),
            (W - 1, 0, 300.0, 210.0),
            (W - 1, H - 1, 290.0, 400.0),
            (0, H - 1, 105.0, 395.0),
            (300, 200, 220.0, 300.0),
            (100, 500, 150.0, 480.0),
        ]
        fit = tm.fit_tps(pairs, W, H)
        assert fit is not None
        assert fit["tps"] is True
        _, rms = tm.tps_residuals(pairs, fit, W, H)
        assert rms < 1e-6

    def test_affine_data_recovers_params_and_zero_weights(self):
        pairs = _affine_pairs(GRID9)
        fit = tm.fit_tps(pairs, W, H)
        assert fit is not None
        # the interpolant of affine data IS the affine map: weights ~ 0
        n = len(fit["src"])
        wmax = max(
            max(abs(v) for v in fit["coeffs"][:n]),
            max(abs(v) for v in fit["coeffs"][n + 3 : 2 * n + 3]),
        )
        assert wmax < 1e-6
        local = tm.tps_local_params(fit, W, H)
        assert local["rotation"] == pytest.approx(12.0, abs=1e-6)
        assert local["xScale"] == pytest.approx(2.5, rel=1e-6)
        assert local["yScale"] == pytest.approx(2.5, rel=1e-6)
        assert local["cx"] == pytest.approx(500000.0, abs=1e-6)
        assert local["cy"] == pytest.approx(4500000.0, abs=1e-6)

    def test_smooth_field_followed_and_exact_at_points(self):
        pairs = _smooth_pairs(GRID9)
        fit = tm.fit_tps(pairs, W, H)
        _, rms = tm.tps_residuals(pairs, fit, W, H)
        assert rms < 1e-6
        # between the points the surface follows the bends of the field:
        # it must deviate from the plain affine by up to a few map units
        affine = tm.fit_anisotropic(pairs, W, H)
        px, py = 200.0, 150.0
        tx, ty = tm.tps_pixel_to_map(px, py, fit, W, H)
        ax, ay = tm.pixel_to_map(
            px, py, affine["cx"], affine["cy"], affine["rotation"],
            affine["xScale"], affine["yScale"], W, H,
        )
        deviation = math.hypot(tx - ax, ty - ay)
        assert deviation > 0.5  # the rubbersheet actually bends
        assert deviation < 50.0  # ...but not wildly

    def test_roundtrip_inversion_projected(self):
        fit = tm.fit_tps(_smooth_pairs(GRID9), W, H)
        rng = random.Random(7)
        worst = 0.0
        for _ in range(300):
            px = rng.uniform(0, W)
            py = rng.uniform(0, H)
            mx, my = tm.tps_pixel_to_map(px, py, fit, W, H)
            bpx, bpy = tm.tps_map_to_pixel(mx, my, fit, W, H)
            worst = max(worst, abs(bpx - px), abs(bpy - py))
        # Newton stops on a relative tolerance: ~1e-4 px at UTM magnitudes
        assert worst < 1e-3

    def test_roundtrip_inversion_geographic(self):
        # small coordinate magnitudes: the relative tolerance is tight
        pairs = []
        rng = random.Random(3)
        for px, py in GRID9:
            mx = 39.0 + px / W * 0.05 + rng.gauss(0, 2e-4)
            my = 45.0 + py / H * 0.03 + rng.gauss(0, 2e-4)
            pairs.append((float(px), float(py), mx, my))
        fit = tm.fit_tps(pairs, W, H)
        rng = random.Random(11)
        # pixel size ~5e-5 deg; the Newton stops on a relative tolerance
        # of 1e-10 * |coord| ~= 4.5e-9 deg ~= 1e-4 px at these latitudes
        for _ in range(200):
            px = rng.uniform(0, W)
            py = rng.uniform(0, H)
            mx, my = tm.tps_pixel_to_map(px, py, fit, W, H)
            bpx, bpy = tm.tps_map_to_pixel(mx, my, fit, W, H)
            assert abs(bpx - px) < 2e-4
            assert abs(bpy - py) < 2e-4

    def test_map_to_pixel_exact_at_tie_points(self):
        pairs = _smooth_pairs(GRID9)
        fit = tm.fit_tps(pairs, W, H)
        for px, py, mx, my in pairs:
            bpx, bpy = tm.tps_map_to_pixel(mx, my, fit, W, H)
            assert bpx == pytest.approx(px, abs=1e-4)
            assert bpy == pytest.approx(py, abs=1e-4)

    def test_local_params_near_affine_base(self):
        fit = tm.fit_tps(_smooth_pairs(GRID9), W, H)
        local = tm.tps_local_params(fit, W, H)
        assert local["rotation"] == pytest.approx(12.0, abs=0.5)
        assert local["xScale"] == pytest.approx(2.5, rel=0.02)
        assert local["yScale"] == pytest.approx(2.5, rel=0.02)

    def test_duplicate_sources_still_fit(self):
        base = _smooth_pairs(GRID9)
        pairs = base + [base[0]]  # exact duplicate control point
        fit = tm.fit_tps(pairs, W, H)
        assert fit is not None
        _, rms = tm.tps_residuals(pairs, fit, W, H)
        assert rms < 1e-6

    def test_json_roundtrip_keeps_the_surface(self):
        fit = tm.fit_tps(_smooth_pairs(GRID9), W, H)
        restored = json.loads(json.dumps(fit))
        assert restored == fit
        for px, py in [(111.3, 222.7), (W / 2, H / 2), (0, 0), (W - 1, H - 1)]:
            assert tm.tps_pixel_to_map(px, py, fit, W, H) == (
                tm.tps_pixel_to_map(px, py, restored, W, H)
            )

    def test_truncated_coeffs_raise(self):
        fit = tm.fit_tps(_smooth_pairs(GRID9), W, H)
        broken = dict(fit, coeffs=fit["coeffs"][:-3])
        with pytest.raises(ValueError):
            tm.tps_pixel_to_map(10.0, 10.0, broken, W, H)


class TestFittedDispatch:
    def test_fitted_pixel_to_map_dispatch(self):
        pairs = _smooth_pairs(GRID9)
        tps = tm.fit_tps(pairs, W, H)
        x, y = tm.fitted_pixel_to_map("tps", tps, 123.4, 234.5, W, H)
        assert (x, y) == tm.tps_pixel_to_map(123.4, 234.5, tps, W, H)

    def test_fitted_pixel_to_map_poly(self):
        fit = tm.fit_poly(1, _affine_pairs(GRID9), W, H)
        x, y = tm.fitted_pixel_to_map("poly", fit, 123.4, 234.5, W, H)
        assert (x, y) == tm.poly_pixel_to_map(123.4, 234.5, fit, W, H)

    def test_fitted_residuals_dispatch(self):
        pairs = _smooth_pairs(GRID9)
        tps = tm.fit_tps(pairs, W, H)
        assert tm.fitted_residuals("tps", tps, pairs, W, H) == (
            tm.tps_residuals(pairs, tps, W, H)
        )
        fit1 = tm.fit_poly(1, _affine_pairs(GRID9), W, H)
        assert tm.fitted_residuals("poly", fit1, pairs, W, H) == (
            tm.poly_residuals(pairs, fit1, W, H)
        )
