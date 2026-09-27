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
Serialization of tie (georeferencing) points for the Freehand Raster
Georeferencer plugin.

This module MUST stay free of QGIS / Qt imports so that it can be unit
tested headlessly.

A tie point is a dict {"px": float, "py": float, "mx": float, "my": float,
"en": bool} where (px, py) are image pixel coordinates (pixel-center
convention), (mx, my) the corresponding map coordinates (in the CRS stored
alongside) and "en" the enabled flag. A disabled point is kept and shown
in the points table but excluded from the fit, following the behaviour of
the QGIS built-in georeferencer.
"""

import csv
import io
import json
import math

# legacy plugin header (pixel first)
LEGACY_HEADER = ("pixel_x", "pixel_y", "map_x", "map_y")

# header of the .points files written by the QGIS built-in georeferencer
# (map first, with enable flag and residual columns)
QGIS_HEADER = ("mapX", "mapY", "pixelX", "pixelY", "enable", "dX", "dY", "residual")

# keys of the JSON representation, short to keep the QGIS project compact
_JSON_KEYS = ("px", "py", "mx", "my")

_FALSE_VALUES = ("0", "false", "no", "n", "f")


def _as_bool(value):
    """Interpret a value read from CSV/JSON as a boolean enable flag."""
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_VALUES
    return bool(value)


def normalize_point(p):
    """Return a tie point with float values and an enable flag, or None."""
    try:
        vals = [float(p[k]) for k in _JSON_KEYS]
    except (KeyError, TypeError, ValueError):
        return None
    if any(v != v for v in vals):  # NaN
        return None
    point = dict(zip(_JSON_KEYS, vals))
    point["en"] = _as_bool(p.get("en", True))
    return point


def to_json(points):
    """Serialize points to a JSON string (for QGIS custom properties)."""
    clean = [normalize_point(p) for p in points]
    clean = [p for p in clean if p is not None]
    return json.dumps(clean, separators=(",", ":"))


def from_json(text):
    """Parse points from a JSON string. Returns list (possibly empty)."""
    if not text:
        return []
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        p = normalize_point(item)
        if p is not None:
            out.append(p)
    return out


def to_csv(points, residuals=None):
    """
    Serialize to the .points format of the QGIS built-in georeferencer:
    a header line "mapX,mapY,pixelX,pixelY,enable,dX,dY,residual" followed
    by one line per point (full float precision).

    residuals is an optional list of (dx, dy) tuples (map units) in the
    same order as points; unknown residuals are written as 0.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(QGIS_HEADER)
    for i, p in enumerate(points):
        np = normalize_point(p)
        if np is None:
            continue
        if residuals is not None and i < len(residuals):
            dx, dy = residuals[i]
        else:
            dx, dy = 0.0, 0.0
        writer.writerow(
            [
                repr(np["mx"]),
                repr(np["my"]),
                repr(np["px"]),
                repr(np["py"]),
                1 if np["en"] else 0,
                repr(dx),
                repr(dy),
                repr(math.sqrt(dx * dx + dy * dy)),
            ]
        )
    return buf.getvalue()


def from_csv(text):
    """
    Parse .points CSV content. Understands both the QGIS georeferencer
    format (mapX,mapY,pixelX,pixelY,enable,dX,dY,residual) and the legacy
    plugin format (pixel_x,pixel_y,map_x,map_y), detected from the header
    line. Tolerates a missing header (assumed to be the QGIS format),
    missing trailing columns and whitespace. Returns a list of points.
    """
    if not text:
        return []
    out = []
    pixel_first = None  # None until the header tells us (or first data row)
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if not row:
            continue
        cells = [c.strip() for c in row]
        first = cells[0].lower()
        if first in ("mapx", "map_x"):
            pixel_first = False  # header line of the QGIS format
            continue
        if first in LEGACY_HEADER:
            pixel_first = True  # header line of the legacy plugin format
            continue
        if pixel_first is None:
            pixel_first = False  # headerless: assume the QGIS format
        if len(cells) < 4:
            continue
        if pixel_first:
            px, py, mx, my = cells[0], cells[1], cells[2], cells[3]
        else:
            mx, my, px, py = cells[0], cells[1], cells[2], cells[3]
        p = normalize_point(
            {
                "px": px,
                "py": py,
                "mx": mx,
                "my": my,
                "en": _as_bool(cells[4]) if len(cells) > 4 else True,
            }
        )
        if p is not None:
            out.append(p)
    return out
