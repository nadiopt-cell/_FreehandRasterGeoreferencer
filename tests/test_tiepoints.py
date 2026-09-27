import tiepoints as tp

POINTS = [
    {"px": 0.0, "py": 0.0, "mx": 100.5, "my": -200.25},
    {"px": 799.0, "py": 599.0, "mx": 1.23456789e6, "my": -0.5},
]

POINTS_EN = [
    {"px": 1.0, "py": 2.0, "mx": 3.0, "my": 4.0, "en": True},
    {"px": 5.0, "py": 6.0, "mx": 7.0, "my": 8.0, "en": False},
]

QGIS_HEADER_LINE = "mapX,mapY,pixelX,pixelY,enable,dX,dY,residual"


class TestJson:
    def test_roundtrip(self):
        text = tp.to_json(POINTS)
        parsed = tp.from_json(text)
        assert len(parsed) == 2
        assert parsed[0]["px"] == POINTS[0]["px"]
        assert parsed[0]["py"] == POINTS[0]["py"]
        assert parsed[0]["mx"] == POINTS[0]["mx"]
        assert parsed[0]["my"] == POINTS[0]["my"]
        assert parsed[0]["en"] is True  # default when missing

    def test_enabled_roundtrip(self):
        text = tp.to_json(POINTS_EN)
        parsed = tp.from_json(text)
        assert parsed[0]["en"] is True
        assert parsed[1]["en"] is False

    def test_invalid_filtered(self):
        data = [
            {"px": "1", "py": 2.0, "mx": 3.0, "my": 4.0},  # string is ok
            {"px": None, "py": 2.0, "mx": 3.0, "my": 4.0},  # invalid
            {"px": float("nan"), "py": 2.0, "mx": 3.0, "my": 4.0},  # NaN
            {"py": 2.0, "mx": 3.0, "my": 4.0},  # missing key
        ]
        parsed = tp.from_json(tp.to_json(data))
        assert len(parsed) == 1
        assert parsed[0]["px"] == 1.0

    def test_garbage_text(self):
        assert tp.from_json("not json at all") == []
        assert tp.from_json('{"a": 1}') == []
        assert tp.from_json("") == []
        assert tp.from_json(None) == []


class TestCsvQgisFormat:
    """The QGIS georeferencer format: mapX,mapY,pixelX,pixelY,enable,..."""

    def test_header(self):
        text = tp.to_csv(POINTS)
        assert text.strip().splitlines()[0] == QGIS_HEADER_LINE

    def test_roundtrip(self):
        text = tp.to_csv(POINTS_EN)
        parsed = tp.from_csv(text)
        assert len(parsed) == 2
        assert parsed[0]["px"] == 1.0
        assert parsed[0]["mx"] == 3.0
        assert parsed[0]["en"] is True
        assert parsed[1]["px"] == 5.0
        assert parsed[1]["mx"] == 7.0
        assert parsed[1]["en"] is False

    def test_residuals_written(self):
        residuals = [(0.5, -0.25), (1.0, 1.0)]
        lines = tp.to_csv(POINTS_EN, residuals).strip().splitlines()
        cells = lines[1].split(",")
        assert float(cells[5]) == 0.5
        assert float(cells[6]) == -0.25
        assert abs(float(cells[7]) - (0.5**2 + 0.25**2) ** 0.5) < 1e-9

    def test_parse_qgis_sample(self):
        text = (
            QGIS_HEADER_LINE + "\n"
            "30.9990867863,-25.6381785777,1185.45034958,1104.36290004,"
            "1,-1.7e-14,5.3e-14,5.5e-14\n"
            "31.1,-25.7,1200.0,1100.0,0,0,0,0\n"
        )
        parsed = tp.from_csv(text)
        assert len(parsed) == 2
        assert parsed[0]["mx"] == 30.9990867863
        assert parsed[0]["px"] == 1185.45034958
        assert parsed[0]["en"] is True
        assert parsed[1]["en"] is False

    def test_headerless_is_qgis_format(self):
        text = "3,4,1,2\n7,8,5,6\n"
        parsed = tp.from_csv(text)
        assert parsed[0] == {"px": 1.0, "py": 2.0, "mx": 3.0, "my": 4.0, "en": True}
        assert parsed[1]["px"] == 5.0

    def test_missing_enable_column(self):
        text = "mapX,mapY,pixelX,pixelY\n3,4,1,2\n"
        parsed = tp.from_csv(text)
        assert parsed == [{"px": 1.0, "py": 2.0, "mx": 3.0, "my": 4.0, "en": True}]


class TestCsvLegacyFormat:
    """The old plugin format (pixel first) must still be readable."""

    def test_roundtrip(self):
        text = tp.to_csv(POINTS)
        parsed = tp.from_csv(text)
        assert len(parsed) == 2
        assert parsed[0]["px"] == POINTS[0]["px"]
        assert parsed[0]["mx"] == POINTS[0]["mx"]
        assert parsed[0]["en"] is True

    def test_headerless_legacy_4col_is_qgis_format(self):
        # without header, 4 columns are interpreted as QGIS map-first
        parsed = tp.from_csv("3,4,1,2\n")
        assert parsed[0]["px"] == 1.0
        assert parsed[0]["mx"] == 3.0

    def test_extra_columns_ignored(self):
        text = "pixel_x,pixel_y,map_x,map_y,enable,dX,dY\n1,2,3,4,0,0.5,0.5\n"
        parsed = tp.from_csv(text)
        assert parsed == [{"px": 1.0, "py": 2.0, "mx": 3.0, "my": 4.0, "en": False}]

    def test_bad_rows_skipped(self):
        text = (
            "pixel_x,pixel_y,map_x,map_y\n"
            "1,2,3\n"  # too few
            "a,b,c,d\n"  # not numbers
            "1,2,3,4\n"
        )
        parsed = tp.from_csv(text)
        assert len(parsed) == 1

    def test_empty(self):
        assert tp.from_csv("") == []
        assert tp.from_csv(None) == []
        assert tp.to_csv([]).strip() == QGIS_HEADER_LINE
