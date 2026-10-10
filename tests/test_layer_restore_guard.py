"""
Regression tests for the two bugs reported on 0.9.14:

1. QGIS crash / restart with a saved project:

       AttributeError: 'FreehandRasterGeoreferencerLayer' object has no
       attribute 'image'

   A layer restored from a project is created WITHOUT a filepath
   (createLayer -> readXml fills it later) and loads its image lazily
   on the first draw / extent request. Everything that touched the
   transform maths before that raised AttributeError - and the
   exception escaped into Qt signal handlers (currentLayerChanged),
   so QGIS showed the Python error dialog right after the restart.

2. The georeferencing "not saved entirely" with the polynomial-3
   model: the .points CSV cannot hold the transform model (only the
   QGIS-georeferencer-compatible columns), and a CRS change left STALE
   fitted coefficients in place. Covered here: the .points.json
   sidecar round trip (save -> load restores the model) and the
   guarded CRS-change handler.

The qgis modules are stubbed (see test_plugin_unload, imported first);
the rasters are real PNGs loaded by the real QImageReader. Skipped
automatically if PyQt5 or GDAL is missing.
"""

import json
import os
import sys
import types

import pytest

pytest.importorskip("osgeo.gdal")
pytest.importorskip("PyQt5.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_PARENT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

# importing test_plugin_unload registers the qgis stubs FIRST (shared
# via sys.modules - the real plugin modules are imported exactly once)
import test_plugin_unload as _base  # noqa: E402,F401
from test_plugin_unload import _make_plugin  # noqa: E402

from PyQt5.QtGui import QColor, QImage  # noqa: E402

from _FreehandRasterGeoreferencer import tiepoints, transform_math  # noqa: E402
from _FreehandRasterGeoreferencer import (  # noqa: E402
    freehandrastergeoreferencer as plugin_module,
)
from _FreehandRasterGeoreferencer.freehandrastergeoreferencer_layer import (  # noqa: E402
    FreehandRasterGeoreferencerLayer,
)


@pytest.fixture(scope="module")
def qapp():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _clean_shared_stub_state():
    """initGui registers the plugin layer type in the SHARED stub
    registry; clear it after every test so that test_plugin_unload's
    assertions about the registry stay valid regardless of the
    collection order."""
    yield
    _base._QgsApplication._registry.registered.clear()


@pytest.fixture
def fake_crs():
    """Destination CRS returned by the stubbed map settings."""
    return types.SimpleNamespace(
        toWkt=lambda: "EPSG:4326-WKT",
        description=lambda: "WGS 84",
        isValid=lambda: True,
    )


@pytest.fixture(autouse=True)
def _canvas_map_settings(monkeypatch, fake_crs):
    """The layer setupCrs() asks the canvas for the destination CRS."""
    monkeypatch.setattr(
        _base._FakeCanvas,
        "mapSettings",
        lambda self: types.SimpleNamespace(destinationCrs=lambda: fake_crs),
        raising=False,
    )


@pytest.fixture
def raster_png(tmp_path):
    """A small real PNG on disk (loaded by the real QImageReader)."""
    img = QImage(40, 30, QImage.Format_RGB32)
    img.fill(QColor(200, 100, 50))
    path = tmp_path / "raster.png"
    assert img.save(str(path))
    return str(path)


def _ready_layer(plugin, raster_png):
    layer = FreehandRasterGeoreferencerLayer(plugin, raster_png, "r", None)
    assert layer.isReady()
    return layer


def _unready_layer(plugin):
    # the createLayer() path of a project restore: no filepath, image
    # not loaded (yet)
    layer = FreehandRasterGeoreferencerLayer(plugin, None, "", None)
    assert not layer.isReady()
    return layer


def _poly3_points(layer, count=16):
    """Tie points whose targets follow a known cubic (poly3-exact).
    A 4x4 grid in general position: full-rank design matrix for the
    10 cubic monomials (a grid that is too flat is rank deficient and
    fit_poly legitimately refuses it)."""
    w, h = layer.image.width(), layer.image.height()
    coeffs = [
        1000.0, 2.0, 0.5, 0.01, 0.002, -0.003, 0.0001, 0.00002, 0.00003,
        -0.00004,  # x-part (10 coefficients)
        500.0, -0.7, 1.3, 0.004, -0.001, 0.002, -0.00005, 0.00001,
        0.00002, 0.00001,  # y-part
    ]
    grid = [
        (2.0 + ix * (w - 4.0) / 3.0, 2.0 + iy * (h - 4.0) / 3.0)
        for ix in range(4)
        for iy in range(4)
    ]
    pts = []
    for px, py in grid[:count]:
        x = px - (w - 1) / 2.0
        y = (h - 1) / 2.0 - py
        row = transform_math.poly_monomials(x, y, 3)
        mx = sum(c * v for c, v in zip(coeffs[:10], row))
        my = sum(c * v for c, v in zip(coeffs[10:], row))
        pts.append({"px": px, "py": py, "mx": mx, "my": my, "en": True})
    return pts


# ---- regression 1: the missing 'image' attribute ------------------------


def test_restored_layer_has_image_attribute(qapp):
    """createLayer() builds the layer without a filepath: self.image
    must EXIST (None) from the constructor on - previously it did not
    exist at all and every later access raised AttributeError."""
    iface, plugin = _make_plugin()
    layer = _unready_layer(plugin)
    assert hasattr(layer, "image")
    assert layer.image is None


def test_preinit_transform_calls_do_not_raise(qapp):
    """The whole transform-maths surface must tolerate the pre-init
    state (this is the code the user's traceback went through)."""
    iface, plugin = _make_plugin()
    layer = _unready_layer(plugin)

    assert layer.pixelToMap(3, 4) is not None
    assert layer.mapToPixel(10, 20) is not None
    layer.setTiePoints(
        [{"px": 1, "py": 2, "mx": 3, "my": 4}, {"px": 5, "py": 6, "mx": 7, "my": 8}]
    )
    residuals, rms = layer.tiePointResiduals()
    assert len(residuals) == 2
    assert layer.applyTiePointFit() is False  # refuses: image not loaded
    layer.extent()  # must not raise
    layer.transformedCornerCoordinates(layer.center, 0.0, 1.0, 1.0)
    layer.metadataText()  # must not raise


def test_check_current_layer_with_unready_layer_does_not_raise(qapp):
    """currentLayerChanged -> checkCurrentLayerIsPluginLayer with a
    restored (not yet initialized) layer: the guard must keep the
    exception out of the Qt signal handler."""
    iface, plugin = _make_plugin()
    plugin.initGui()

    layer = _unready_layer(plugin)
    iface.setActiveLayer(layer)
    plugin.georefNPRaster()  # currentTool = N-points tool
    # activate the unready layer: refreshPoints ran pixelToMap on it
    plugin.checkCurrentLayerIsPluginLayer()  # must not raise


def test_tool_refreshpoints_skips_unready_layer(qapp, raster_png):
    """refreshPoints draws no markers while the raster is loading - and
    draws them once the layer is ready."""
    iface, plugin = _make_plugin()
    plugin.initGui()
    plugin.georefNPRaster()
    tool = plugin.georefNPTool

    unready = _unready_layer(plugin)
    unready.setTiePoints([{"px": 1, "py": 2, "mx": 3, "my": 4}])
    tool.setLayer(unready)
    tool.refreshPoints()  # must not raise
    assert tool.tiePointLabels._points == []

    ready = _ready_layer(plugin, raster_png)
    ready.setTiePoints([{"px": 1, "py": 2, "mx": 3, "my": 4}])
    tool.setLayer(ready)
    tool.refreshPoints()
    assert len(tool.tiePointLabels._points) == 1


# ---- regression 2a: poly3 fit survives the (stubbed) project round trip


def test_poly3_fit_state_is_stored_in_custom_properties(qapp, raster_png):
    iface, plugin = _make_plugin()
    layer = _ready_layer(plugin, raster_png)

    layer.setFitModel(3)
    layer.setTiePoints(_poly3_points(layer))
    assert layer.applyTiePointFit() is True
    assert layer.polyCoeffs is not None and len(layer.polyCoeffs) == 20

    # what writeXml persists
    assert int(layer.customProperty("fitModel")) == 3
    stored = json.loads(layer.customProperty("polyCoeffs"))
    assert len(stored) == 20

    # the fitted transform really maps the pixels to the cubic targets
    for p in layer.tiePoints:
        got = layer.pixelToMap(p["px"], p["py"])
        assert abs(got.x() - p["mx"]) < 1e-4
        assert abs(got.y() - p["my"]) < 1e-4

    # fitStateSnapshot / restoreFitState (the undo payload)
    snap = layer.fitStateSnapshot()
    layer.fitModel = 0
    layer.polyCoeffs = None
    layer.restoreFitState(snap)
    assert layer.fitModel == 3
    assert layer.polyCoeffs == list(snap["polyCoeffs"])


def test_crs_change_handler_never_raises(qapp, raster_png):
    """The CRS-change handler is a Qt slot: with the stubbed coordinate
    transform it must swallow the error instead of raising."""
    iface, plugin = _make_plugin()
    layer = _ready_layer(plugin, raster_png)
    layer.setTiePoints(_poly3_points(layer))
    layer.applyTiePointFit()
    layer.resetTransformParametersToNewCrs()  # must not raise


# ---- regression 2b: the .points sidecar restores the fit model ----------


def test_model_sidecar_round_trip(tmp_path):
    model = {
        "fitModel": 3,
        "polyCoeffs": [1.0, 2.5, -3.0],
        "tpsFit": None,
        "crsWkt": "EPSG:4326-WKT",
    }
    path = str(tmp_path / "points.points.json")
    tiepoints.write_model_sidecar(path, model)
    got = tiepoints.read_model_sidecar(path)
    for key, value in model.items():
        assert got[key] == value
    assert got["app"] == "FreehandRasterGeoreferencer"
    # broken / foreign sidecars are ignored
    with open(path, "w") as fh:
        fh.write("{not json")
    assert tiepoints.read_model_sidecar(path) is None
    tiepoints.write_model_sidecar(path, {"app": "OtherTool", "fitModel": 1})
    assert tiepoints.read_model_sidecar(path) is None
    assert tiepoints.read_model_sidecar(str(tmp_path / "absent.json")) is None


def test_save_load_points_restores_fit_model(qapp, raster_png, monkeypatch, tmp_path):
    iface, plugin = _make_plugin()
    plugin.initGui()

    layer = _ready_layer(plugin, raster_png)
    layer.setFitModel(3)
    layer.setTiePoints(_poly3_points(layer))
    assert layer.applyTiePointFit() is True
    iface.setActiveLayer(layer)

    points_path = os.path.join(str(tmp_path), "saved.points")
    monkeypatch.setattr(
        plugin_module.QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (points_path, ""),
    )
    plugin.saveTiePoints()
    assert os.path.exists(points_path)
    sidecar = points_path + ".json"
    assert os.path.exists(sidecar)
    with open(sidecar) as fh:
        assert json.load(fh)["fitModel"] == 3

    # a fresh layer (classic model, no points) loads the saved points:
    # the model must come back as polynomial 3
    fresh = _ready_layer(plugin, raster_png)
    assert fresh.fitModel == 0 and not fresh.tiePoints
    iface.setActiveLayer(fresh)
    monkeypatch.setattr(
        plugin_module.QFileDialog,
        "getOpenFileName",
        lambda *a, **k: (points_path, ""),
    )
    plugin.loadTiePoints()

    assert fresh.fitModel == 3
    assert len(fresh.tiePoints) == len(layer.tiePoints)
    assert fresh.polyCoeffs is not None and len(fresh.polyCoeffs) == 20
    # the fit reproduces the saved georeferencing
    for p in layer.tiePoints:
        got = fresh.pixelToMap(p["px"], p["py"])
        assert abs(got.x() - p["mx"]) < 1e-4
        assert abs(got.y() - p["my"]) < 1e-4
    # undo returns the fresh layer to its pre-load state (classic model)
    plugin.undo()
    assert fresh.fitModel == 0
    assert fresh.tiePoints == []


def test_load_points_without_sidecar_still_works(qapp, raster_png, monkeypatch, tmp_path):
    """A plain .points file (e.g. written by the QGIS georeferencer)
    loads as before - no sidecar required."""
    iface, plugin = _make_plugin()
    plugin.initGui()

    layer = _ready_layer(plugin, raster_png)
    iface.setActiveLayer(layer)

    points_path = os.path.join(str(tmp_path), "plain.points")
    with open(points_path, "w") as fh:
        fh.write("mapX,mapY,pixelX,pixelY,enable\n1,2,1,1,true\n3,4,5,6,true\n")
    monkeypatch.setattr(
        plugin_module.QFileDialog,
        "getOpenFileName",
        lambda *a, **k: (points_path, ""),
    )
    plugin.loadTiePoints()
    assert len(layer.tiePoints) == 2


def test_lazy_load_notifies_widgets(qapp, raster_png):
    """When the lazy image load finishes, the layer emits
    transformParametersChanged so the widgets / markers resync."""
    iface, plugin = _make_plugin()
    plugin.initGui()

    layer = _unready_layer(plugin)
    layer.filepath = raster_png
    seen = []
    layer.transformParametersChanged.connect(
        lambda params: seen.append(params)
    )
    layer.initializeLayer()
    assert layer.isReady()
    assert len(seen) == 1
