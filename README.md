# About

This project is a plugin for QGIS 3 to perform interactive raster georeferencing. The plugin was originally made to replace a workflow where digitizers would use Google Earth to interactively georeference a raster and the tools (move, rotate, scale...) found in that software have been reimplemented. Compared to the standard raster georeferencer tool of QGIS, which needs control points and an export, this plugin allows the visualization of the result immediately, on top of the other layers of the map. 

# Install

## From the QGIS plugin registry

In QGIS, open the "Plugins" > "Manage and install plugin" dialog. Install the "Freehand raster georeferencer" plugin.

## From Github

Use the master branch:

1. Download a ZIP of the repository or clone it using "git clone"
2. The folder with the Python files should be directly under the directory with all the QGIS plugins (for example, ~/.qgis2/python/plugins/FreehandRasterGeoreferencer)
3. Compile the assets and UI (OPTIONAL since v0.9.0: the `ui_*.py` modules and the icons are provided, pyuic5/pyrcc5 are not needed anymore. Only run this if you modify the `.ui` files):  
    - On Windows, launch the OSGeo4W Shell. On Unix, launch a command line and make sure the PyQT tools (pyuic5 and pyrcc5) are on the PATH
    - Go to the plugin directory
    - Launch "build.bat" or "build.sh"
4. The next time QGIS is opened, the plugin should be listed in the "Plugins" > "Manage and install plugin" dialog

A legacy version for QGIS 2 is in the `qgis2` branch.

## Requirements

- QGIS 3 (PyQt5), GDAL python bindings (`osgeo`) for the COG / polynomial exports and the display path of non-Byte / multi-band TIFFs
- **numpy** — used by the transformation math and the raster display path; it ships with QGIS on the standard Windows and macOS installers, on Linux it comes with `python3-numpy`

# Features (v0.9.11)

- **Interactive georeferencing**: move, rotate, scale, adjust sides, georeference with 2 points — all with immediate visual feedback.
- **Selectable fit model** (v0.9.7): a "Fit model" combo in the tie points panel selects the mathematical model fitted from the tie points, like the transformation type of the built-in QGIS Georeferencer:
    - *Similarity / Anisotropic* (default): the model of the plugin layer — rotation + translation + uniform or separate X/Y scales, no shear; exact with 2 points.
    - *Polynomial 1 (affine)*: rotation, translation, X/Y scales **and shear** (6 parameters, 3 points minimum); rendered and exported exactly.
    - *Polynomial 2* and *Polynomial 3*: quadratic / cubic warps (12 / 20 parameters, 6 / 10 points minimum) that can bend the raster — keep the points spread over the image; outside their hull polynomials extrapolate erratically.
    - In polynomial mode the exact numeric controls are read-only (they display the affine equivalent at the image center) and the manual move / rotate / scale / 2-points tools are disabled: edit the tie points instead, the fit is redone after every change. The selected model and the coefficients are saved in the project and are covered by Undo.
- **Exact numeric control** (v0.9.0; dedicated "values" toolbar and tie points panel since v0.9.10): a compact second toolbar "Freehand raster georeferencing values" shows the numbers for **move and scale** next to the tools — Move X / Move Y (raster center, map units) and Scale X / Scale Y (pixel size, map units per pixel) — right next to the rotation spinbox of the main toolbar. The same controls (plus RMS) sit on top of the tie points panel (right side, opens automatically with the N-points tool or via the toolbar "Tie points panel" button). Values are updated both ways: type one for an exact placement (moves / scales the raster immediately, undoable), or let the map tools update them; the toolbar and the panel always stay in sync. In polynomial fit mode the numeric controls are read-only.
- **Georeference with N points** (v0.9.0): click on a feature of the raster, drag it to its real location and release; repeat for as many points as needed. With 2 points a similarity fit (rotation + uniform scale) is applied, with 3 points or more a least-squares anisotropic scaled-rotation fit (other models — polynomial 1/2/3 — can be selected in the panel since v0.9.7). The root mean square (RMS) of the residuals is displayed in the tie points panel and the residuals of each point are drawn on the canvas. Right click on the map gives access to remove last point / clear all points / save / load the points.
- **Tie points table** (v0.9.3): a dock panel on the right side of the screen, like the GCP table of the built-in QGIS Georeferencer. Each point shows the source pixel, the target map coordinates and the live residuals (dX, dY, residual); each point can be **enabled / disabled** (a disabled point is excluded from the fit, like in the QGIS georeferencer) and rows can be **deleted** (multi-selection supported, or right-click menu in the table). After every change — canvas drag or table edit — the raster is refitted and redrawn immediately. The table opens automatically with the N-points tool and can be toggled with the toolbar button or menu Raster > Freehand Raster Georeferencer > Tie points table.
- **Undo of any last action** (v0.9.5): the toolbar Undo button reverts the last action — moves, rotations, scale changes, 2-point georeferencing steps, but also every tie point operation: adding a point by drag, enabling / disabling a point in the table, deleting point(s), clearing all points and loading points from a file. Both the tie points and the raster placement are restored exactly as they were before the action (the target markers and the points table are refreshed accordingly).
- **Tie points persistence** (v0.9.0): the tie points are stored in the QGIS project (they survive save/load, including reprojection when the project CRS changes) and can be exported to / imported from `.points` CSV files compatible with the built-in QGIS Georeferencer (menu Raster > Freehand Raster Georeferencer > Save/Load tie points). Since v0.9.3 the `.points` files follow the exact QGIS georeferencer format (`mapX,mapY,pixelX,pixelY,enable,dX,dY,residual`) including the enable flag; the legacy pixel-first format of earlier versions is still read.
- **COG export** (v0.9.0): the export dialog can produce a Cloud Optimized GeoTIFF directly, built from the ORIGINAL raster file through GDAL — any band count or data type (16-bit, multispectral...) is preserved, the "pixel transformation" limitations of the display path do not apply. Two modes:
    - *north-up* (default): the rotation is baked into the pixels by warping on the 4 raster corners; the resampling method can be selected (nearest/bilinear/cubic); transparent borders are handled with an alpha band.
    - *"Put rotation in world file"* checked: the pixels are left untouched and the rotation is stored in the geotransform (ModelTransformation). If the GDAL version refuses to write a rotated COG, a tiled GeoTIFF is written instead (a warning is displayed).
    - In polynomial mode (v0.9.7) the export warps the raster through a grid of GCPs sampled from the fitted polynomial, forcing the same polynomial order in GDAL (output: COG or tiled GeoTIFF); for polynomial 1 "only world file" also works, since an order-1 polynomial is an exact affine (for orders 2/3 a world file cannot encode the transform).
- **Compression choice for GeoTIFF/COG exports** (v0.9.8): the export dialog offers DEFLATE (lossless, default), ZSTD (lossless, faster and usually smaller), JPEG and WEBP (lossy, much smaller files for photographic content). The requested codec is validated against the actual GDAL build and against the raster characteristics: JPEG never handles the alpha band (GDAL would drop it silently — the export falls back to DEFLATE with a warning, e.g. for north-up COGs where an alpha band is added), WEBP requires Byte with 3/4 bands. The lossless codecs get a horizontal PREDICTOR (STANDARD for integer rasters, FLOATING_POINT for float rasters), which typically reduces the DEFLATE size by 10-30%.
- **Polynomial mesh rendering** (fixed in v0.9.9): the warped image is drawn as a grid of affine cells; each cell's transform is composed with the painter base transform (map rendering job or canvas item). An earlier build combined the cell transforms with each other, which made the raster disappear and leave only the warped outline.
- **Stability hardening** (v0.9.11): the QImage built for non-Byte / multi-band TIFFs owns its pixel buffer (deep copy — an image referencing a garbage-collectible numpy buffer was the likely source of random QGIS crashes), GDAL datasets are closed right after use (no more locked source files on Windows / network shares), the map tools tolerate their layer being deleted mid-interaction and clean up their preview items when deactivated, the draw paths validate the image and canvas state and log errors instead of aborting, the undo history is capped (50 entries), `to_byte` no longer divides by zero on flat bands and the global CRS setting used for the PDF preview is always restored.
- **Export** (world file / image): unchanged, with one fix: an existing `.aux.xml` next to the raster is not overwritten anymore (the CRS is simply not written into it).

# Development

The transformation math lives in `transform_math.py` and the tie points serialization in `tiepoints.py`; both are pure Python (numpy only, no QGIS/Qt imports) and are covered by headless unit tests:

```
python3 -m pytest tests/
```

The tests include GDAL integration tests of the COG export and polynomial warp export paths (they are skipped automatically if the GDAL python bindings are not available).

# Documentation

See http://gvellut.github.io/FreehandRasterGeoreferencer/

# Issues

Report issues at https://github.com/gvellut/FreehandRasterGeoreferencer/issues

# Limitations

- The plugin uses Qt to read and and manipulate a raster and is therefore limited to the formats supported by that library. That means almost none of the GDAL raster formats are supported and very large rasters should be avoided. Currently BMP, JPEG, PNG, TIFF can be loaded.
- This georeferencer supports the scaled-rotation model of the layer and, since v0.9.7, polynomial transforms of order 1-3 (order 1 includes shear). Rubbersheeting / TPS of the standard QGIS raster georeferencer is still not provided
- There is limited support for changing CRS: If the CRS of the map changes, you will have to adjust georeferencing of the layer in the new CRS.
- The raster layer added by this plugin does not have all the capabilities of a normal QGIS raster layer: It is limited to visualization and modification using the provided tools. However, a normal QGIS raster file, along with georerencing information, can be easily exported by the plugin and can be reloaded using the standard "Add Raster" functionality.
- The rendering of some TIFF rasters needs something more sophisticated than what the plugin offers. It is the case for example of rasters with a data type other than Byte (or 1-bit) or with a number of bands other than 1 (grayscale) or 3 (assumed to be RGB): Qt will not open them properly. To display those with the plugin, some simple pixel transformation is made, ie reduce the number of bands or scale the data to fit in a Byte but it is not as complete as what the raster renderer of QGIS offers.
    - If a pixel transformation is performed, a message _Raster content has been transformed for display in the plugin. When exporting, select the 'Only export world file' checkbox_ will be displayed when a a raster is opened. When exporting the georeferencing, unless you are fine with the pixel transformation, be sure to check the "Only export world file" in the dialog, then choose the original raster file: In that case, no image data will be exported, just the georeferencing (including rotation).
    - It is also possible to perform the pixel transformation yourself, before opening the raster with the plugin. For example, if you have a 10-band raster with band 5, 3, 6 as RGB, you can use GDAL to export a version of the raster with those bands in the correct order. Make sure the dimensions (width, length) of the raster  stay the same though. Then use that version of the raster for georeferencing with the plugin. Finally, export only the world file and select the original raster. The original raster will then have a world file.