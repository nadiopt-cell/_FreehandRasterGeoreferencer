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

A tie point is a dict {"px": float, "py": float, "mx": float, "my": float}
where (px, py) are image pixel coordinates (pixel-center convention) and
(mx, my) the corresponding map coordinates (in the CRS stored alongside).
"""

import csv
import io
import json

HEADER = ("pixel_x", "pixel_y", "map_x", "map_y")

# keys of the JSON representation, short to keep the QGIS project compact
_JSON_KEYS = ("px", "py", "mx", "my")


def normalize_point(p):
    """Return a tie point with float values, or None if invalid."""
    try:
        vals = [float(p[k]) for k in _JSON_KEYS]
    except (KeyError, TypeError, ValueError):
        return None
    if any(v != v for v in vals):  # NaN
        return None
    return dict(zip(_JSON_KEYS, vals))


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


def to_csv(points):
    """
    Serialize to the .points CSV format of the QGIS built-in georeferencer:
    a header line "pixel_x,pixel_y,map_x,map_y" followed by one line per
    point (full float precision).
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADER)
    for p in points:
        np = normalize_point(p)
        if np is None:
            continue
        writer.writerow(
            [
                repr(np["px"]),
                repr(np["py"]),
                repr(np["mx"]),
                repr(np["my"]),
            ]
        )
    return buf.getvalue()


def from_csv(text):
    """
    Parse .points CSV content. Tolerates a missing header, extra columns
    (they are ignored) and whitespace. Returns a list of points.
    """
    if not text:
        return []
    out = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if not row:
            continue
        cells = [c.strip() for c in row]
        if cells[0].lower() in HEADER:  # header line
            continue
        if len(cells) < 4:
            continue
        p = normalize_point(
            {"px": cells[0], "py": cells[1], "mx": cells[2], "my": cells[3]}
        )
        if p is not None:
            out.append(p)
    return out
