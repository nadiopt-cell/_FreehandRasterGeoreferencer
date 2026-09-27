"""
/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

"""
Pure math for the Freehand Raster Georeferencer plugin.

This module MUST stay free of QGIS / Qt imports so that it can be unit
tested headlessly (pytest) and reused by the export code.

Conventions (same as FreehandRasterGeoreferencerLayer):
    - rotation is expressed in degrees, positive = clockwise (visual, Qt-like)
    - xScale / yScale are "map units per image pixel"
    - (cx, cy) is the map position of the CENTER of the image
    - pixel coordinates follow the GDAL "pixel center" convention:
      pixel (0, 0) is the center of the first pixel, so the centers of the
      pixels run from (0, 0) to (w - 1, h - 1) and the geometric corners of
      the image are at (-0.5, -0.5) and (w - 0.5, h - 0.5)
"""

import math

import numpy as np


def normalize_rotation(rotation):
    """Round to 3 decimals and keep inside [-180, 180]."""
    rotation = round(rotation, 3)
    if rotation < -180:
        rotation += 360
    if rotation > 180:
        rotation -= 360
    return rotation


def _rotation_rad(rotation_deg):
    """Math (CCW, Y-up) angle corresponding to a clockwise degrees angle."""
    return -rotation_deg * math.pi / 180.0


def _centered_offset_from_pixel(px, py, w, h, x_scale, y_scale):
    """
    Offset of a pixel center from the image center, in an Y-up,
    non-rotated frame (map orientation before rotation).
    """
    return (px + 0.5 - w / 2.0) * x_scale, (h / 2.0 - py - 0.5) * y_scale


def pixel_to_map(px, py, cx, cy, rotation, x_scale, y_scale, w, h):
    """Map coordinates of a (fractional) pixel center."""
    theta = _rotation_rad(rotation)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    ox, oy = _centered_offset_from_pixel(px, py, w, h, x_scale, y_scale)
    return (
        cx + cos_t * ox - sin_t * oy,
        cy + sin_t * ox + cos_t * oy,
    )


def map_to_pixel(x, y, cx, cy, rotation, x_scale, y_scale, w, h):
    """Pixel (fractional) coordinates of a map position. Inverse of pixel_to_map."""
    if x_scale == 0 or y_scale == 0:
        raise ValueError("Zero scale: cannot invert transform")
    theta = _rotation_rad(rotation)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    dx = x - cx
    dy = y - cy
    # inverse rotation
    ox = cos_t * dx + sin_t * dy
    oy = -sin_t * dx + cos_t * dy
    px = (ox / x_scale) + w / 2.0 - 0.5
    py = h / 2.0 - 0.5 - (oy / y_scale)
    return px, py


def corners(cx, cy, rotation, x_scale, y_scale, w, h):
    """
    Map coordinates of the image corners (geometric corners of the corner
    pixels): returns (topLeft, topRight, bottomRight, bottomLeft) tuples,
    matching FreehandRasterGeoreferencerLayer.transformedCornerCoordinates.
    """
    half_w = w / 2.0
    half_h = h / 2.0
    local = [(-half_w, half_h), (half_w, half_h), (half_w, -half_h), (-half_w, -half_h)]
    theta = _rotation_rad(rotation)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    out = []
    for lx, ly in local:
        ox = lx * x_scale
        oy = ly * y_scale
        out.append(
            (
                cx + cos_t * ox - sin_t * oy,
                cy + sin_t * ox + cos_t * oy,
            )
        )
    return tuple(out)


def geotransform_from_params(cx, cy, rotation, x_scale, y_scale, w, h):
    """
    GDAL geotransform (corner of pixel grid convention, i.e. X = gt0 +
    gt1*px + gt2*py with (px, py) pixel-center indices) equivalent to the
    plugin transform parameters.
    """
    gt0, gt3 = pixel_to_map(-0.5, -0.5, cx, cy, rotation, x_scale, y_scale, w, h)
    theta = _rotation_rad(rotation)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    gt1 = x_scale * cos_t
    gt2 = y_scale * sin_t
    gt4 = x_scale * sin_t
    gt5 = -y_scale * cos_t
    return (gt0, gt1, gt2, gt3, gt4, gt5)


def params_from_geotransform(gt, w, h):
    """
    Inverse of geotransform_from_params.

    Returns (cx, cy, rotation, x_scale, y_scale). Assumes no shearing
    (det check is left to the caller); yScale is kept positive.
    """
    gt0, gt1, gt2, gt3, gt4, gt5 = gt
    theta = math.atan2(gt4, gt1)
    x_scale = math.hypot(gt1, gt4)
    y_scale = math.hypot(gt2, -gt5) or x_scale
    rotation = -math.degrees(theta)
    # geometric center of the image, in gdal corner-based pixel indices
    gcx = w / 2.0
    gcy = h / 2.0
    cx = gt0 + gt1 * gcx + gt2 * gcy
    cy = gt3 + gt4 * gcx + gt5 * gcy
    return (cx, cy, rotation, x_scale, y_scale)


def world_file_from_params(cx, cy, rotation, x_scale, y_scale, w, h):
    """
    World file coefficients (a, d, b, e, c, f) for the "rotation in world
    file" export mode. Kept bit-compatible with the historical formulas of
    ExportGeorefRasterCommand (pixel-center of the (w-1)/2 pixel anchor).
    """
    rad = rotation * math.pi / 180.0
    a = x_scale * math.cos(rad)
    b = -y_scale * math.sin(rad)
    d = x_scale * -math.sin(rad)
    e = -y_scale * math.cos(rad)
    c = cx - (a * (w - 1) / 2.0 + b * (h - 1) / 2.0)
    f = cy - (d * (w - 1) / 2.0 + e * (h - 1) / 2.0)
    return (a, d, b, e, c, f)


# ---------------------------------------------------------------------------
# Tie points fitting
# ---------------------------------------------------------------------------


def _pairs_to_arrays(pairs, w, h):
    """
    pairs: sequence of (px, py, mx, my).
    Returns src (N,2): pixel offsets from image center, Y-UP (so that the
    pixel->map matrix is a proper rotation * positive scales), and dst (N,2).
    """
    icx = (w - 1) / 2.0
    icy = (h - 1) / 2.0
    src = np.array([(p[0] - icx, icy - p[1]) for p in pairs], dtype=float)
    dst = np.array([(p[2], p[3]) for p in pairs], dtype=float)
    return src, dst


def fit_similarity(pairs, w, h):
    """
    Least-squares fit of a similarity transform (rotation + UNIFORM scale +
    translation), closed form (Umeyama). Exact for 2 points.

    Returns dict(rotation=CW deg, xScale=, yScale=, cx=, cy=) where
    (cx, cy) is the map position of the image center, or None.
    """
    n = len(pairs)
    if n < 2:
        return None
    src, dst = _pairs_to_arrays(pairs, w, h)

    mean_src = src.mean(axis=0)
    mean_dst = dst.mean(axis=0)
    src_c = src - mean_src
    dst_c = dst - mean_dst

    # covariance sum of outer(dst_c, src_c); rot maps src_c -> dst_c
    cov = (dst_c.T @ src_c) / n
    u, d, vt = np.linalg.svd(cov)
    s_sign = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        s_sign[1, 1] = -1.0
    rot = u @ s_sign @ vt  # proper rotation, det > 0

    var_src = (src_c ** 2).sum() / n
    if var_src <= 0:
        return None
    scale = float((d * np.diag(s_sign)).sum() / var_src)

    theta = math.atan2(rot[1, 0], rot[0, 0])  # math CCW angle
    rotation = -math.degrees(theta)  # visual CW degrees
    # dst = center + scale * rot * src  (src already relative to image center)
    center = mean_dst - scale * (rot @ mean_src)

    return {
        "rotation": rotation,
        "xScale": scale,
        "yScale": scale,
        "cx": float(center[0]),
        "cy": float(center[1]),
    }


def _apply_anisotropic(theta, sx, sy, tx, ty, src_c):
    """
    src_c: (N,2) pixel offsets from image center, Y-UP.
    Returns predicted map coords (N,2).
    """
    vx = sx * src_c[:, 0]
    vy = sy * src_c[:, 1]
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    mx = tx + cos_t * vx - sin_t * vy
    my = ty + sin_t * vx + cos_t * vy
    return np.column_stack([mx, my])


def fit_anisotropic(pairs, w, h, init=None, max_iter=60, tol=1e-12):
    """
    Gauss-Newton least squares fit of an anisotropic scaled rotation
    (rotation + sx + sy + translation, NO shearing) - the transform model
    of the plugin layer.

    Returns dict(rotation=CW deg, xScale=, yScale=, cx=, cy=) or None.
    """
    n = len(pairs)
    if n < 2:
        return None
    src_c, dst = _pairs_to_arrays(pairs, w, h)

    if init is None:
        sim = fit_similarity(pairs, w, h)
        if sim is None:
            return None
        theta0 = -sim["rotation"] * math.pi / 180.0
        p = np.array([theta0, sim["xScale"], sim["yScale"], sim["cx"], sim["cy"]])
    else:
        p = np.array(init, dtype=float)

    for _ in range(max_iter):
        theta, sx, sy, tx, ty = p
        if abs(sx) < 1e-12 or abs(sy) < 1e-12:
            break
        pred = _apply_anisotropic(theta, sx, sy, tx, ty, src_c)
        res = dst - pred  # (N, 2)

        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        vx = sx * src_c[:, 0]
        vy = sy * src_c[:, 1]
        jac = np.zeros((2 * n, 5))
        jac[0::2, 0] = -sin_t * vx - cos_t * vy
        jac[1::2, 0] = cos_t * vx - sin_t * vy
        jac[0::2, 1] = cos_t * src_c[:, 0]
        jac[1::2, 1] = sin_t * src_c[:, 0]
        jac[0::2, 2] = -sin_t * src_c[:, 1]
        jac[1::2, 2] = cos_t * src_c[:, 1]
        jac[0::2, 3] = 1.0
        jac[1::2, 4] = 1.0

        rhs = jac.T @ res.ravel()
        normal = jac.T @ jac
        try:
            delta = np.linalg.solve(normal + np.eye(5) * 1e-12, rhs)
        except np.linalg.LinAlgError:
            return None
        p = p + delta
        if np.max(np.abs(delta)) < tol:
            break

    theta, sx, sy, tx, ty = p
    # keep scales positive: fold any sign into the rotation by 180 deg
    if sx < 0:
        sx = -sx
        theta += math.pi
    if sy < 0:
        sy = -sy
        theta += math.pi
    return {
        "rotation": -math.degrees(theta),  # math CCW -> visual CW degrees
        "xScale": float(sx),
        "yScale": float(sy),
        "cx": float(tx),
        "cy": float(ty),
    }


def fit_points(pairs, w, h):
    """
    Fit the layer transform from tie points.
    2 points -> exact similarity (uniform scale);
    >= 3 points -> anisotropic scaled rotation (least squares).
    Returns dict or None if not enough points.
    """
    if len(pairs) < 2:
        return None
    if len(pairs) == 2:
        return fit_similarity(pairs, w, h)
    return fit_anisotropic(pairs, w, h)


def residuals(pairs, params, w, h):
    """
    Per-point residuals (target - predicted), in map units.
    Returns (list of (dx, dy), rms).
    """
    if not pairs:
        return [], 0.0
    res = []
    for px, py, mx, my in pairs:
        ex, ey = pixel_to_map(
            px,
            py,
            params["cx"],
            params["cy"],
            params["rotation"],
            params["xScale"],
            params["yScale"],
            w,
            h,
        )
        res.append((mx - ex, my - ey))
    sq = [(rx * rx + ry * ry) for rx, ry in res]
    rms = math.sqrt(sum(sq) / len(sq))
    return res, rms


# ---------------------------------------------------------------------------
# Polynomial transforms (order 1 = affine, 2 = quadratic, 3 = cubic)
#
# The polynomials map PIXEL offsets from the image center (Y-up frame, the
# same convention as the fits above) to map coordinates:
#     X = sum(cX_k * M_k(x, y)),  Y = sum(cY_k * M_k(x, y))
# with the monomial basis
#     order 1: (1, x, y)
#     order 2: (1, x, y, x^2, xy, y^2)
#     order 3: (1, x, y, x^2, xy, y^2, x^3, x^2 y, x y^2, y^3)
# Both coordinates share the basis but have independent coefficients
# (stored flat: first the X coefficients, then the Y ones).
# ---------------------------------------------------------------------------

POLY_ORDERS = (1, 2, 3)
_POLY_BASIS = {
    1: ((0, 0), (1, 0), (0, 1)),
    2: ((0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2)),
    3: (
        (0, 0),
        (1, 0),
        (0, 1),
        (2, 0),
        (1, 1),
        (0, 2),
        (3, 0),
        (2, 1),
        (1, 2),
        (0, 3),
    ),
}


def poly_num_coeffs(order):
    """Number of coefficients per output coordinate for a polynomial order."""
    if order not in _POLY_BASIS:
        raise ValueError("Unsupported polynomial order: %r" % (order,))
    return len(_POLY_BASIS[order])


def poly_min_points(order):
    """Minimum number of tie points required to fit a polynomial order."""
    return poly_num_coeffs(order)


def poly_monomials(x, y, order):
    """Row of the monomial basis evaluated at (x, y)."""
    basis = _POLY_BASIS[order]
    return np.array(
        [(x ** i) * (y ** j) for (i, j) in basis], dtype=float
    )


def fit_poly(order, pairs, w, h):
    """
    Least-squares (closed form) fit of a polynomial transform of the given
    order. Returns dict(poly=order, coeffs=[...]) or None when there are
    not enough points or the point configuration is degenerate (rank
    deficient, e.g. collinear points for order 1).
    """
    if order not in _POLY_BASIS:
        raise ValueError("Unsupported polynomial order: %r" % (order,))
    n = len(pairs)
    ncoeff = poly_num_coeffs(order)
    if n < ncoeff:
        return None
    src, dst = _pairs_to_arrays(pairs, w, h)

    # design matrix shared by both coordinates
    rows = [poly_monomials(x, y, order) for x, y in src]
    mat = np.vstack(rows)  # (N, ncoeff)
    if np.linalg.matrix_rank(mat) < ncoeff:
        return None

    coeffs = []
    for component in range(2):
        target = dst[:, component]
        sol, _, _, _ = np.linalg.lstsq(mat, target, rcond=None)
        coeffs.extend(float(v) for v in sol)
    return {"poly": order, "coeffs": coeffs}


def poly_pixel_to_map(px, py, fit, w, h):
    """Map coordinates of a (fractional) pixel center under a poly fit."""
    icx = (w - 1) / 2.0
    icy = (h - 1) / 2.0
    x = px - icx
    y = icy - py
    order = fit["poly"]
    row = poly_monomials(x, y, order)
    coeffs = fit["coeffs"]
    ncoeff = poly_num_coeffs(order)
    cx = float(np.dot(row, coeffs[0:ncoeff]))
    cy = float(np.dot(row, coeffs[ncoeff : 2 * ncoeff]))
    return cx, cy


def poly_map_to_pixel(x, y, fit, w, h, max_iter=30, tol=1e-10):
    """
    (Fractional) pixel coordinates of a map position: Newton iteration on
    the polynomial, started from the affine equivalent at the image
    center. Returns (px, py); may raise ValueError if it does not
    converge (target far outside the raster footprint).
    """
    order = fit["poly"]
    ncoeff = poly_num_coeffs(order)
    coeffs = fit["coeffs"]
    coeffsX = np.asarray(coeffs[0:ncoeff])
    coeffsY = np.asarray(coeffs[ncoeff : 2 * ncoeff])
    basis = _POLY_BASIS[order]
    # derivative monomial indices for d/dx and d/dy (0 coefficient when the
    # exponent is 0)
    dxbasis = [(i - 1, j, i) for (i, j) in basis]
    dybasis = [(i, j - 1, j) for (i, j) in basis]

    icx = (w - 1) / 2.0
    icy = (h - 1) / 2.0

    def evalXY(x, y):
        row = poly_monomials(x, y, order)
        return float(np.dot(row, coeffsX)), float(np.dot(row, coeffsY))

    def jacobian(x, y):
        j00 = j01 = j10 = j11 = 0.0
        for k, (i, j, m) in enumerate(dxbasis):
            if m > 0:
                v = m * (x ** i) * (y ** j)
                j00 += v * coeffsX[k]
                j10 += v * coeffsY[k]
        for k, (i, j, m) in enumerate(dybasis):
            if m > 0:
                v = m * (x ** i) * (y ** j)
                j01 += v * coeffsX[k]
                j11 += v * coeffsY[k]
        return j00, j01, j10, j11

    # Newton starts at the image center (the centered Y-up frame works on
    # (x, y) offsets, whose origin IS the image center)
    x_c = 0.0
    y_c = 0.0
    for _ in range(max_iter):
        fx, fy = evalXY(x_c, y_c)
        rx = fx - x
        ry = fy - y
        if abs(rx) < tol and abs(ry) < tol:
            break
        j00, j01, j10, j11 = jacobian(x_c, y_c)
        det = j00 * j11 - j01 * j10
        if abs(det) < 1e-30:
            raise ValueError("Singular Jacobian: cannot invert polynomial")
        dx = (j11 * rx - j01 * ry) / det
        dy = (-j10 * rx + j00 * ry) / det
        x_c -= dx
        y_c -= dy
    else:
        raise ValueError("Polynomial inversion did not converge")

    return icx + x_c, icy - y_c


def poly_local_params(fit, w, h):
    """
    Affine (classic) parameters equivalent to the polynomial locally at
    the image center: position of the center and the Jacobian decomposed
    into rotation + positive scales (no shear representation). Used to
    show meaningful values in the numeric widgets and as export hints.
    """
    order = fit["poly"]
    ncoeff = poly_num_coeffs(order)
    coeffs = fit["coeffs"]
    row = poly_monomials(0.0, 0.0, order)
    cx = float(np.dot(row, coeffs[0:ncoeff]))
    cy = float(np.dot(row, coeffs[ncoeff : 2 * ncoeff]))

    # Jacobian at the center: derivative of the monomials at (0, 0)
    j00 = j01 = j10 = j11 = 0.0
    for k, (i, j) in enumerate(_POLY_BASIS[order]):
        if i == 1:
            j00 += coeffs[k]
            j10 += coeffs[ncoeff + k]
        if j == 1:
            j01 += coeffs[k]
            j11 += coeffs[ncoeff + k]
    # J = R(theta) * diag(sx, sy) with Y-up math convention
    sx = math.hypot(j00, j10)
    sy = math.hypot(j01, j11)
    theta = math.atan2(j10, j00)  # math CCW
    rotation = -math.degrees(theta)  # visual CW degrees
    return {
        "cx": cx,
        "cy": cy,
        "rotation": normalize_rotation(rotation),
        "xScale": sx,
        "yScale": sy,
    }


def poly_residuals(pairs, fit, w, h):
    """Per-point residuals (target - predicted) for a poly fit + rms."""
    if not pairs:
        return [], 0.0
    res = []
    for px, py, mx, my in pairs:
        ex, ey = poly_pixel_to_map(px, py, fit, w, h)
        res.append((mx - ex, my - ey))
    sq = [(rx * rx + ry * ry) for rx, ry in res]
    rms = math.sqrt(sum(sq) / len(sq))
    return res, rms


def poly1_world_file(fit, w, h):
    """
    World file coefficients (a, d, b, e, c, f) of an order-1 polynomial
    fit. The world file anchors pixel (0, 0) center:
        X = a * col + b * row + c,  Y = d * col + e * row + f
    """
    if fit["poly"] != 1:
        raise ValueError("poly1_world_file requires an order-1 fit")
    ncoeff = poly_num_coeffs(1)
    c00, c01, c02 = fit["coeffs"][0:ncoeff]
    c10, c11, c12 = fit["coeffs"][ncoeff : 2 * ncoeff]
    icx = (w - 1) / 2.0
    icy = (h - 1) / 2.0
    # centered Y-up -> pixel indices: x = px - icx, y = icy - py
    a = c01
    b = -c02
    d = c11
    e = -c12
    c = c00 - a * icx - b * icy
    f = c10 - d * icx - e * icy
    return (a, d, b, e, c, f)


def affine_from_correspondences(src, dst):
    """
    Least-squares affine (6 parameters) mapping src points to dst points.
    src, dst: (N, 2) arrays. Returns (a, b, c, d, e, f) with
        X = a*x + b*y + c,  Y = d*x + e*y + f
    or None when degenerate.
    """
    n = len(src)
    if n < 3:
        return None
    mat = np.column_stack([src[:, 0], src[:, 1], np.ones(n)])
    if np.linalg.matrix_rank(mat) < 3:
        return None
    out = []
    for component in range(2):
        sol, _, _, _ = np.linalg.lstsq(mat, dst[:, component], rcond=None)
        out.extend(float(v) for v in sol)
    return tuple(out)
