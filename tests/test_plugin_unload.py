"""
Lifecycle test of the plugin object: initGui -> use -> unload().

Regression tests for the uninstall error reported on 0.9.12: QGIS shows
an "Error while unloading plugin" dialog when unload() raises. Two real
ways unload() could raise (or leave a broken state behind):

1. uninstalling while a georeferencing map tool was ACTIVE: the old code
   left the tool on the canvas together with its rubber bands / tie point
   labels - dead plugin code reachable by the next map click;
2. uninstalling when initGui had failed earlier (QGIS still calls
   unload() on the instance): the old code hit AttributeError /
   RuntimeError on the missing attributes and unprotected disconnects.

The qgis modules are stubbed (the real bindings are not importable in
the test environment); everything else - actions, toolbars, dock, table,
map tools, canvas items - is the real plugin code on real PyQt widgets.
Skipped automatically if PyQt5 or GDAL is missing.
"""

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

from PyQt5.QtCore import QObject, pyqtSignal  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMainWindow, QToolBar  # noqa: E402

# ---- stub qgis BEFORE importing the plugin package ---------------------


def _module(name):
    m = types.ModuleType(name)
    sys.modules.setdefault(name, m)
    return m


_qpkg = _module("qgis")
_qcore = _module("qgis.core")
_qgui = _module("qgis.gui")
_qpkg.core = _qcore
_qpkg.gui = _qgui


class _Qgis:
    Info = 0
    Warning = 1
    Critical = 2
    PointGeometry = 0
    LineGeometry = 1


class _QgsWkbTypes:
    PointGeometry = 0
    LineGeometry = 1


class _QgsPointXY:
    def __init__(self, x=0.0, y=0.0):
        self._x, self._y = float(x), float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y


class _QPointF:
    def __init__(self, x=0.0, y=0.0):
        self._x, self._y = float(x), float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y


class _QgsRectangle:
    def __init__(self, *args):
        self._args = args

    def xMinimum(self):
        return 0.0

    def yMinimum(self):
        return 0.0

    def xMaximum(self):
        return 100.0

    def yMaximum(self):
        return 100.0

    def width(self):
        return 100.0

    def height(self):
        return 100.0

    def isEmpty(self):
        return False


class _QgsProject(QObject):
    layerRemoved = pyqtSignal(list)
    _inst = None

    @classmethod
    def instance(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def fileName(self):
        return ""

    def setDirty(self, dirty):
        pass


class _PluginLayerRegistry:
    def __init__(self):
        self.registered = []

    def addPluginLayerType(self, layerType):
        self.registered.append(layerType.type())

    def removePluginLayerType(self, typeName):
        if typeName in self.registered:
            self.registered.remove(typeName)


class _QgsApplication:
    _registry = _PluginLayerRegistry()

    @classmethod
    def pluginLayerRegistry(cls):
        return cls._registry


class _QgsMapLayer:
    PluginLayer = 2


class _QgsMapCanvasItem(QObject):
    def __init__(self, canvas=None):
        QObject.__init__(self)
        self._canvas = canvas
        self._pos = _QPointF(0.0, 0.0)
        self._visible = False

    def setPos(self, x, y=None):
        self._pos = _QPointF(x, y if y is not None else x)

    def pos(self):
        return self._pos

    def setRect(self, rect):
        self._rect = rect

    def setVisible(self, visible):
        self._visible = bool(visible)

    def show(self):
        self._visible = True

    def hide(self):
        self._visible = False

    def update(self):
        pass

    def setZValue(self, z):
        pass

    def toCanvasCoordinates(self, point):
        return _QPointF(point.x(), point.y())


class _QgsRubberBand:
    ICON_NONE = 0
    ICON_CIRCLE = 1
    ICON_SQUARE = 2

    def __init__(self, canvas=None, geometryType=0):
        self._vertexCount = 0

    def reset(self, geometryType=0):
        self._vertexCount = 0

    def addPoint(self, point, update=False):
        self._vertexCount += 1

    def vertexCount(self):
        return self._vertexCount

    def setColor(self, color):
        pass

    def setSecondaryStrokeColor(self, color):
        pass

    def setIcon(self, icon):
        pass

    def setIconSize(self, size):
        pass

    def setWidth(self, width):
        pass

    def show(self):
        pass

    def hide(self):
        pass


class _QgsMapToolEmitPoint:
    def __init__(self, canvas=None):
        self._canvas = canvas

    def deactivate(self):
        pass

    def setAction(self, action):
        self.action = action

    def toMapCoordinates(self, pos):
        return _QgsPointXY(0.0, 0.0)


_qcore.Qgis = _Qgis
_qcore.QgsWkbTypes = _QgsWkbTypes
_qcore.QgsPointXY = _QgsPointXY
_qcore.QgsRectangle = _QgsRectangle
_qcore.QgsProject = _QgsProject
_qcore.QgsApplication = _QgsApplication
_qcore.QgsMapLayer = _QgsMapLayer
_qcore.QgsMessageLog = types.SimpleNamespace(
    logMessage=staticmethod(lambda *a, **k: None)
)
for _name in (
    "QgsCoordinateReferenceSystem",
    "QgsCoordinateTransform",
    "QgsDataProvider",
    "QgsLayerMetadata",
    "QgsMapLayerRenderer",
    "QgsRasterLayer",
    "QgsGeometry",
):
    setattr(_qcore, _name, type(_name, (), {}))


def _tolerant_init(self, *args, **kwargs):
    if args:
        self._typeName = args[0]


def _type_name(self):
    return getattr(self, "_typeName", None)


for _name in ("QgsPluginLayer", "QgsPluginLayerType"):
    setattr(
        _qcore,
        _name,
        type(_name, (), {"__init__": _tolerant_init, "type": _type_name}),
    )

_qgui.QgsMapCanvasItem = _QgsMapCanvasItem
_qgui.QgsRubberBand = _QgsRubberBand
_qgui.QgsMapToolEmitPoint = _QgsMapToolEmitPoint
_qgui.QgsMessageBar = types.SimpleNamespace(
    # compatible with the stubs of the export tests (this module may be
    # the first to register the qgis stubs in sys.modules)
    createMessage=staticmethod(
        lambda title="", text="": types.SimpleNamespace(title=title, text=text)
    )
)

# ---- import the REAL plugin --------------------------------------------

from _FreehandRasterGeoreferencer.freehandrastergeoreferencer import (  # noqa: E402
    FreehandRasterGeoreferencer,
)
from _FreehandRasterGeoreferencer.freehandrastergeoreferencer_layer import (  # noqa: E402
    FreehandRasterGeoreferencerLayer,
)

LAYER_TYPE = FreehandRasterGeoreferencerLayer.LAYER_TYPE

PLUGIN_MENU = FreehandRasterGeoreferencer.PLUGIN_MENU


# ---- fakes -------------------------------------------------------------


class _FakePanAction:
    def __init__(self):
        self.triggers = 0

    def trigger(self):
        self.triggers += 1


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class _FakeCanvas(QObject):
    destinationCrsChanged = pyqtSignal()

    def __init__(self):
        QObject.__init__(self)
        self.mapTool = None
        self._extent = _QgsRectangle(0, 0, 100, 100)
        self.refreshCount = 0

    def setMapTool(self, tool):
        self.mapTool = tool

    def unsetMapTool(self, tool):
        if self.mapTool is tool:
            self.mapTool = None

    def extent(self):
        return self._extent

    def setExtent(self, extent):
        self._extent = extent

    def refresh(self):
        self.refreshCount += 1

    def height(self):
        return 600

    def width(self):
        return 800


class _FakeIface(QObject):
    currentLayerChanged = pyqtSignal(object)

    def __init__(self):
        QObject.__init__(self)
        self.win = QMainWindow()
        self.canvas = _FakeCanvas()
        self.layerTb = QToolBar("layer tools", self.win)
        self.pluginToolBars = []
        self.addLayerActions = []
        self.rasterMenu = {}
        self.pan = _FakePanAction()
        self.messageBar_ = _FakeMessageBar()
        self.activeLayer_ = None

    def mainWindow(self):
        return self.win

    def mapCanvas(self):
        return self.canvas

    def layerToolBar(self):
        return self.layerTb

    def addToolBar(self, name):
        toolbar = QToolBar(name, self.win)
        self.pluginToolBars.append(toolbar)
        return toolbar

    def actionPan(self):
        return self.pan

    def insertAddLayerAction(self, action):
        self.addLayerActions.append(action)

    def removeAddLayerAction(self, action):
        if action in self.addLayerActions:
            self.addLayerActions.remove(action)

    def addPluginToRasterMenu(self, text, action):
        self.rasterMenu.setdefault(text, []).append(action)

    def removePluginRasterMenu(self, text, action):
        actions = self.rasterMenu.get(text, [])
        if action in actions:
            actions.remove(action)

    def addDockWidget(self, area, dock):
        self.win.addDockWidget(area, dock)

    def activeLayer(self):
        return self.activeLayer_

    def setActiveLayer(self, layer):
        self.activeLayer_ = layer

    def messageBar(self):
        return self.messageBar_


class _FakePluginLayer(QObject):
    """Minimal stand-in for a loaded FreehandRasterGeoreferencerLayer:
    enough for checkCurrentLayerIsPluginLayer / updateTransformWidgets
    (no image -> the widget sync takes the early-out branch)."""

    transformParametersChanged = pyqtSignal(tuple)

    def __init__(self):
        QObject.__init__(self)
        self.image = None
        self.tiePoints = []

    def type(self):
        return _QgsMapLayer.PluginLayer

    def pluginLayerType(self):
        return LAYER_TYPE


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_plugin():
    iface = _FakeIface()
    return iface, FreehandRasterGeoreferencer(iface)


def _menu_empty(iface):
    return all(not actions for actions in iface.rasterMenu.values())


# ---- tests --------------------------------------------------------------


def test_unload_without_initgui_does_not_raise(qapp):
    """Uninstalling a plugin whose initGui failed at startup: QGIS still
    calls unload() on the instance; the guarded teardown must never
    raise (previously: AttributeError on the missing actions)."""
    iface, plugin = _make_plugin()
    plugin.unload()  # must not raise
    assert plugin.dockPoints is None
    assert plugin.toolbar is None
    assert _menu_empty(iface)


def test_initgui_unload_roundtrip(qapp):
    """Normal uninstall: everything registered by initGui is removed."""
    iface, plugin = _make_plugin()
    plugin.initGui()

    assert _QgsApplication._registry.registered
    assert iface.addLayerActions == [plugin.actionAddLayer]
    assert plugin.actionAddLayer in iface.layerTb.actions()
    assert len(iface.pluginToolBars) == 2
    assert sorted(
        iface.rasterMenu[PLUGIN_MENU], key=lambda action: action.objectName()
    ) == [
        plugin.actionAddLayer,
        plugin.actionLoadTiePoints,
        plugin.actionSaveTiePoints,
        plugin.actionShowPointsDock,
    ]

    plugin.unload()

    assert not _QgsApplication._registry.registered
    assert iface.addLayerActions == []
    assert iface.layerTb.actions() == []
    assert _menu_empty(iface)
    assert len(iface.pluginToolBars) == 2  # toolbars removed, not deleted
    assert plugin.toolbar is None
    assert plugin.toolbarValues is None
    assert plugin.dockPoints is None
    assert plugin.currentTool is None


def test_unload_with_active_npoints_tool(qapp):
    """Uninstalling while the N-points tool is active: the tool must be
    detached from the canvas and its on-screen items cleared - previously
    the dead tool, rubber bands and tie point labels stayed on the canvas
    and the next map click could hit unloaded plugin code."""
    iface, plugin = _make_plugin()
    plugin.initGui()

    layer = _FakePluginLayer()
    iface.setActiveLayer(layer)
    plugin.georefNPRaster()
    assert iface.canvas.mapTool is plugin.georefNPTool
    assert plugin.currentTool is plugin.georefNPTool

    # simulated leftover screen state: markers + labels + dock
    tool = plugin.georefNPTool
    tool.rubberBandTargets.addPoint(_QgsPointXY(1, 1), True)
    tool.tiePointLabels.setPoints([(_QgsPointXY(1, 1), 1, True)])
    plugin.dockPoints.show()

    plugin.unload()

    assert iface.canvas.mapTool is None
    assert iface.pan.triggers >= 1
    assert tool.rubberBandTargets.vertexCount() == 0
    assert tool.rubberBandResiduals.vertexCount() == 0
    assert tool.tiePointLabels._points == []
    assert plugin.currentTool is None
    assert plugin.dockPoints is None


def test_unload_disconnects_active_layer_signal(qapp):
    """A transformParametersChanged emitted by a layer AFTER the plugin
    was unloaded must not reach the plugin slots (the layer outlives the
    plugin in the project)."""
    iface, plugin = _make_plugin()
    plugin.initGui()

    layer = _FakePluginLayer()
    iface.setActiveLayer(layer)
    plugin.checkCurrentLayerIsPluginLayer()
    assert plugin.layer is layer

    plugin.unload()
    assert plugin.layer is None

    # late emit: must not raise anywhere in the plugin slots
    layer.transformParametersChanged.emit((1.0, 1.0, 0.0, None))


def test_unload_is_idempotent(qapp):
    iface, plugin = _make_plugin()
    plugin.initGui()
    plugin.unload()
    plugin.unload()  # second call: still no exception
    assert plugin.toolbar is None
