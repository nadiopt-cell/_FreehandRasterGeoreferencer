import tiepoints as tp

POINTS = [
    {"px": 0.0, "py": 0.0, "mx": 100.5, "my": -200.25},
    {"px": 799.0, "py": 599.0, "mx": 1.23456789e6, "my": -0.5},
]


class TestJson:
    def test_roundtrip(self):
        text = tp.to_json(POINTS)
        parsed = tp.from_json(text)
        assert len(parsed) == 2
        assert parsed[0] == POINTS[0]
        assert parsed[1] == POINTS[1]

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


class TestCsv:
    def test_roundtrip(self):
        text = tp.to_csv(POINTS)
        lines = text.strip().splitlines()
        assert lines[0] == "pixel_x,pixel_y,map_x,map_y"
        parsed = tp.from_csv(text)
        assert len(parsed) == 2
        assert parsed[0] == POINTS[0]

    def test_no_header(self):
        text = "1,2,3,4\n5,6,7,8\n"
        parsed = tp.from_csv(text)
        assert len(parsed) == 2
        assert parsed[0] == {"px": 1.0, "py": 2.0, "mx": 3.0, "my": 4.0}

    def test_extra_columns_ignored(self):
        text = "pixel_x,pixel_y,map_x,map_y,enable,dX,dY\n1,2,3,4,1,0.5,0.5\n"
        parsed = tp.from_csv(text)
        assert parsed == [{"px": 1.0, "py": 2.0, "mx": 3.0, "my": 4.0}]

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
        assert tp.to_csv([]).strip() == "pixel_x,pixel_y,map_x,map_y"
