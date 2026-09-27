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
