"""
Runtime patches for ete3 rendering under PyQt5.

PyQt5's QSize is strict about integer dimensions. ete3 passes floats, which
raises TypeError when rendering SVG/PNG. We patch ete3.treeview.main.save to
round dimensions to ints before constructing QSize/QImage while preserving the
original scaling calculations.
"""
from __future__ import annotations

import math

from ete3.treeview import main as _tm


def _patched_save(scene, imgName, w=None, h=None, dpi=90, take_region=False, units="px"):
    # Copied from ete3.treeview.main.save with minimal changes: cast w/h to
    # floats for math, then to ints before QSize/QImage/QPrinter use.
    ipython_inline = False
    if imgName == "%%inline":
        ipython_inline = True
        ext = "PNG"
    elif imgName == "%%inlineSVG":
        ipython_inline = True
        ext = "SVG"
    elif imgName.startswith("%%return"):
        try:
            ext = imgName.split(".")[1].upper()
        except IndexError:
            ext = "SVG"
        imgName = "%%return"
    else:
        ext = imgName.split(".")[-1].upper()

    main_rect = scene.sceneRect()
    aspect_ratio = main_rect.height() / main_rect.width()

    # auto adjust size
    if not w and not h:
        units = "px"
        w = main_rect.width()
        h = main_rect.height()
        ratio_mode = _tm.Qt.KeepAspectRatio
    elif w and h:
        ratio_mode = _tm.Qt.IgnoreAspectRatio
    elif h is None:
        h = w * aspect_ratio
        ratio_mode = _tm.Qt.KeepAspectRatio
    elif w is None:
        w = h / aspect_ratio
        ratio_mode = _tm.Qt.KeepAspectRatio

    # Adjust to resolution
    if units == "mm":
        if w:
            w = w * 0.0393700787 * dpi
        if h:
            h = h * 0.0393700787 * dpi
    elif units == "in":
        if w:
            w = w * dpi
        if h:
            h = h * dpi
    elif units == "px":
        pass
    else:
        raise Exception("wrong unit format")

    x_scale, y_scale = w / main_rect.width(), h / main_rect.height()

    w_int = int(round(w)) if w is not None else 0
    h_int = int(round(h)) if h is not None else 0

    if ext == "SVG":
        svg = _tm.QSvgGenerator()
        targetRect = _tm.QRectF(0, 0, w_int, h_int)
        svg.setSize(_tm.QSize(w_int, h_int))
        svg.setViewBox(targetRect)
        svg.setTitle("Generated with ETE http://etetoolkit.org")
        svg.setDescription("Generated with ETE http://etetoolkit.org")

        if imgName == "%%return":
            ba = _tm.QByteArray()
            buf = _tm.QBuffer(ba)
            buf.open(_tm.QIODevice.WriteOnly)
            svg.setOutputDevice(buf)
        else:
            svg.setFileName(imgName)

        pp = _tm.QPainter()
        pp.begin(svg)
        scene.render(pp, targetRect, scene.sceneRect(), ratio_mode)
        pp.end()
        if imgName == "%%return":
            compatible_code = str(ba)
            print("from memory")
        else:
            compatible_code = open(imgName).read()
        # Fix a very annoying problem with Radial gradients in
        # inkscape and browsers...
        compatible_code = compatible_code.replace("xml:id=", "id=")
        compatible_code = _tm.re.sub(
            'font-size="(\\d+)"', 'font-size="\\1pt"', compatible_code
        )
        compatible_code = compatible_code.replace("\n", " ")
        compatible_code = _tm.re.sub("<g [^>]+>\\s*</g>", "", compatible_code)
        # End of fix
        if ipython_inline:
            from IPython.core.display import SVG

            return SVG(compatible_code)

        elif imgName == "%%return":
            return x_scale, y_scale, compatible_code
        else:
            open(imgName, "w").write(compatible_code)

    elif ext == "PDF" or ext == "PS":
        if ext == "PS":
            format = _tm.QPrinter.PostScriptFormat
        else:
            format = _tm.QPrinter.PdfFormat

        printer = _tm.QPrinter(_tm.QPrinter.HighResolution)
        printer.setResolution(dpi)
        printer.setOutputFormat(format)
        printer.setPageSize(_tm.QPrinter.A4)
        printer.setPaperSize(_tm.QSizeF(w_int, h_int), _tm.QPrinter.DevicePixel)
        printer.setPageMargins(0, 0, 0, 0, _tm.QPrinter.DevicePixel)

        printer.setFullPage(True)
        printer.setOutputFileName(imgName)
        pp = _tm.QPainter(printer)
        targetRect = _tm.QRectF(0, 0, w_int, h_int)
        scene.render(pp, targetRect, scene.sceneRect(), ratio_mode)
    else:
        targetRect = _tm.QRectF(0, 0, w_int, h_int)
        ii = _tm.QImage(w_int, h_int, _tm.QImage.Format_ARGB32)
        ii.fill(_tm.QColor(_tm.Qt.white).rgb())
        ii.setDotsPerMeterX(dpi / 0.0254)  # Convert inches to meters
        ii.setDotsPerMeterY(dpi / 0.0254)
        pp = _tm.QPainter(ii)
        pp.setRenderHint(_tm.QPainter.Antialiasing)
        pp.setRenderHint(_tm.QPainter.TextAntialiasing)
        pp.setRenderHint(_tm.QPainter.SmoothPixmapTransform)

        scene.render(pp, targetRect, scene.sceneRect(), ratio_mode)
        pp.end()
        if ipython_inline:
            ba = _tm.QByteArray()
            buf = _tm.QBuffer(ba)
            buf.open(_tm.QIODevice.WriteOnly)
            ii.save(buf, "PNG")
            from IPython.core.display import Image

            return Image(ba.data())
        elif imgName == "%%return":
            ba = _tm.QByteArray()
            buf = _tm.QBuffer(ba)
            buf.open(_tm.QIODevice.WriteOnly)
            ii.save(buf, "PNG")
            return x_scale, y_scale, ba.toBase64()
        else:
            ii.save(imgName)

    return w / main_rect.width(), h / main_rect.height()


if not getattr(_tm.save, "_patched_for_qsize_ints", False):
    _tm.save = _patched_save
    _tm.save._patched_for_qsize_ints = True
