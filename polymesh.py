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
Mesh rendering of polynomially warped rasters.

A polynomial transform (order >= 2) is non-affine, so the raster cannot be
drawn with a single QPainter transform. The image is split into a coarse
grid of cells; each cell is drawn with the least-squares affine
approximation of the polynomial over that cell (exact on the cell corners
for order 1). Adjacent cells share their corner positions, which keeps the
seams between cells at sub-pixel level; a small overlap hides them
entirely.

This module only glues Qt to the pure math of transform_math; all geometry
decisions (cell layout, affine solving) live there so that they stay unit
testable without Qt.
"""

import math

import numpy as np
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QTransform

from . import transform_math

# target source size of a mesh cell (pixels) and cap per axis; with the cap
# the per-repaint cost stays bounded (max 24x24 = 576 drawImage calls)
CELL_TARGET_PX = 200.0
CELL_MAX_PER_AXIS = 24

# overlap of adjacent cells, in source pixels, to hide antialiasing seams
CELL_OVERLAP_PX = 0.5


def mesh_cell_grid(w, h, target=CELL_TARGET_PX, max_per_axis=CELL_MAX_PER_AXIS):
    """
    (nx, ny) number of cells per axis for a w x h image: about target
    pixels per cell, clamped to [2, max_per_axis] per axis (small images
    still get 2 cells so that the warp curvature is visible).
    """
    nx = int(min(max_per_axis, max(2, math.ceil(w / target))))
    ny = int(min(max_per_axis, max(2, math.ceil(h / target))))
    return nx, ny


def draw_warped_raster(
    painter,
    image,
    pixel_to_map_fn,
    map_to_device_fn,
    w,
    h,
    target=CELL_TARGET_PX,
    max_per_axis=CELL_MAX_PER_AXIS,
):
    """
    Draw `image` warped by the polynomial through the given painter.

    pixel_to_map_fn(px, py) -> (mx, my): the polynomial in map units.
    map_to_device_fn(mx, my) -> (dx, dy): map coords to painter device
    coords (QgsMapToPixel.transform).

    The painter transform is combined per cell and restored afterwards
    (painter.save / painter.restore inside this function).
    """
    nx, ny = mesh_cell_grid(w, h, target, max_per_axis)
    cw = w / float(nx)
    ch = h / float(ny)

    # grid line positions, in image pixel coords (Y down, like Qt);
    # the last line is exactly the image edge
    xs = [i * cw for i in range(nx + 1)]
    ys = [j * ch for j in range(ny + 1)]
    xs[-1] = float(w)
    ys[-1] = float(h)

    src = np.empty((4, 2), dtype=float)
    dst = np.empty((4, 2), dtype=float)

    painter.save()
    try:
        # the cell affine maps image pixels to FINAL device coords; the
        # painter base transform (identity for map rendering jobs, the
        # canvas-item position translation for QgsMapCanvasItem painters)
        # must stay on the outside: device = base(cell(image)).
        # setTransform(cell, combine=True) must NOT be used inside this
        # loop: combine multiplies with the matrix left by the PREVIOUS
        # cell, so the transforms accumulate across the loop and only the
        # first cell is drawn (the image disappears and only the outline
        # remains). Qt product order: (cell * base).map(p) = base(cell(p)).
        base = painter.transform()
        for i in range(nx):
            for j in range(ny):
                x0, x1 = xs[i], xs[i + 1]
                y0, y1 = ys[j], ys[j + 1]
                corners_px = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
                for k, (px, py) in enumerate(corners_px):
                    src[k] = (px, py)
                    mx, my = pixel_to_map_fn(px, py)
                    dx, dy = map_to_device_fn(mx, my)
                    dst[k] = (dx, dy)

                affine = transform_math.affine_from_correspondences(src, dst)
                if affine is None:
                    continue
                a, b, c, d, e, f = affine
                # QTransform maps (x, y) -> (m11*x + m21*y + dx,
                # m12*x + m22*y + dy)
                painter.setTransform(
                    QTransform(a, d, b, e, c, f) * base
                )

                # source and target are the same image-coordinate rect;
                # the QTransform does the warping. The small overlap into
                # the next cell hides the antialiasing seams
                cw_cell = min(x1 - x0 + CELL_OVERLAP_PX, w - x0)
                ch_cell = min(y1 - y0 + CELL_OVERLAP_PX, h - y0)
                rect = QRectF(x0, y0, cw_cell, ch_cell)
                painter.drawImage(rect, image, rect)
    finally:
        painter.restore()


def draw_warped_outline(painter, pixel_to_map_fn, map_to_device_fn, w, h, samples=24):
    """
    Stroke the warped image border (cosmetic pen expected to be set by the
    caller), in device coordinates.
    """
    steps = [(i / float(samples) * w, 0.0) for i in range(samples + 1)]
    steps += [(float(w), i / float(samples) * h) for i in range(1, samples + 1)]
    steps += [
        ((samples - i) / float(samples) * w, float(h))
        for i in range(1, samples + 1)
    ]
    steps += [(0.0, (samples - i) / float(samples) * h) for i in range(1, samples)]

    points = []
    for px, py in steps:
        mx, my = pixel_to_map_fn(px, py)
        dx, dy = map_to_device_fn(mx, my)
        points.append(QPointF(dx, dy))
    painter.drawPolyline(points)


def warped_bounds(pixel_to_map_fn, w, h, samples=24):
    """
    Map-units bounding box (minX, minY, maxX, maxY) of the warped image,
    sampled on the border plus a coarse interior grid (polynomials can
    bulge inside the footprint).
    """
    xs = []
    ys = []
    n = max(4, samples)
    for i in range(n + 1):
        fx = i / float(n)
        for j in range(n + 1):
            fy = j / float(n)
            px = fx * w
            py = fy * h
            mx, my = pixel_to_map_fn(px, py)
            xs.append(mx)
            ys.append(my)
    return min(xs), min(ys), max(xs), max(ys)
