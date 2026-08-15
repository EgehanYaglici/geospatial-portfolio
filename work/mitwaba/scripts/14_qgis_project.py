#!/usr/bin/env python3
"""
Step 14 - Write the QGIS project.

The project is generated rather than saved out of the GUI so that it stays in
step with the data: re-run the pipeline and the styling, the layer order and
the colours come back identical. It carries the same palette as the printed
sheet - one hue per sector, one shade per groupement - so opening the project
shows the delivered map rather than a default QGIS rendering of it.

Four things have to be right or the project opens on an empty canvas, and all
four are easy to leave out when the file is written by hand rather than saved
by QGIS:

  * a <mapcanvas> with an explicit extent. With no extent QGIS opens on its
    default view, which is nowhere near 27E 8S, so every layer loads correctly
    and none of them is on screen. This is what an "empty project" usually is.
  * a CRS definition QGIS can actually resolve. An <authid> on its own is not
    enough on every build; the WKT is what readXml looks for first. A layer
    whose CRS fails to parse is dropped from the canvas silently.
  * layer-tree entries whose source and provider match the layer they point
    at. Writing one datasource for all of them - which is what happens when
    the tree is built from a loop variable that was never updated - leaves
    QGIS resolving raster layers through the vector provider.
  * relative paths switched on explicitly, so the folder can be zipped and
    sent on and still open on the recipient's machine.

Everything written here is checked against the files on disk before the
project is saved, so a missing raster or a renamed layer fails loudly at build
time instead of quietly at the client's end.

Output: 05_qgis/Mitwaba.qgz (and the plain .qgs beside it)
"""
import pathlib
import sqlite3
import sys
import time
import zipfile
from xml.sax.saxutils import escape, quoteattr

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
VEC = ROOT / "03_vector"
CTX = ROOT / "04_context"
GEO = ROOT / "02_georef"
QGIS = ROOT / "05_qgis"
QGIS.mkdir(exist_ok=True)

WGS84 = 4326
UTM35S = 32735

SECTOR_HUES = {
    "Balomotwa":  ["#e8c39e", "#dcae82", "#cf9866", "#c2834f", "#b06f3d"],
    "Banweshi":   ["#cddca0", "#bccf85", "#a9c26a", "#95b352", "#7fa03e"],
    "Kiona-Ngoy": ["#c9c3de", "#b3aad0", "#9d91c2", "#8678b3", "#6f5fa3"],
}


# --------------------------------------------------------------------------
# the shared folder this project lives on drops reads under load; anything
# that touches it gets a few attempts before it is treated as a real failure
# --------------------------------------------------------------------------
def retry(fn, tries=6, wait=2.5, what=""):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:      # OSError from the share, and the driver
            last = e                # errors GDAL raises on a short read
            if i < tries - 1:
                time.sleep(wait)
    raise RuntimeError(f"gave up reading {what}: {last}")


def write_shared(path, data):
    """Write a file onto the shared folder: new file first, then replace.

    Opening an existing file on this share for truncating write deadlocks -
    the same class of problem that makes the GeoPackages unwritable in place.
    Writing a fresh sibling and renaming it over the target avoids the
    truncate entirely, and rename is atomic, so a reader either gets the old
    project or the new one and never a half-written file.
    """
    import os

    blob = data if isinstance(data, bytes) else data.encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")

    def _write():
        with open(tmp, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    retry(_write, what=str(path))
    return path


def rgb(hexcol, alpha=255):
    h = hexcol.lstrip("#")
    return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{alpha}"


# --------------------------------------------------------------------------
# CRS blocks
# --------------------------------------------------------------------------
def srs_block(epsg, indent=6):
    """
    A CRS as QGIS wants to read it back.

    QgsCoordinateReferenceSystem::readXml looks for <wkt> first and only falls
    back to <proj4> and the authority id after that, so the WKT is generated
    from pyproj rather than typed out - it is the definition the rest of the
    pipeline reprojected with, not a second copy of it that could drift.
    """
    from pyproj import CRS

    crs = CRS.from_epsg(epsg)
    pad = " " * indent
    geo = "true" if crs.is_geographic else "false"
    return (
        f'{pad}<spatialrefsys nativeFormat="Wkt">\n'
        f'{pad}  <wkt>{escape(crs.to_wkt())}</wkt>\n'
        f'{pad}  <proj4>{escape(crs.to_proj4())}</proj4>\n'
        f'{pad}  <srsid>{epsg}</srsid>\n'
        f'{pad}  <srid>{epsg}</srid>\n'
        f'{pad}  <authid>EPSG:{epsg}</authid>\n'
        f'{pad}  <description>{escape(crs.name)}</description>\n'
        f'{pad}  <projectionacronym>'
        f'{"longlat" if crs.is_geographic else "utm"}</projectionacronym>\n'
        f'{pad}  <ellipsoidacronym>EPSG:7030</ellipsoidacronym>\n'
        f'{pad}  <geographicflag>{geo}</geographicflag>\n'
        f'{pad}</spatialrefsys>'
    )


def extent_block(b, tag="extent", indent=4):
    pad = " " * indent
    return (f"{pad}<{tag}>\n"
            f"{pad}  <xmin>{b[0]:.10f}</xmin>\n"
            f"{pad}  <ymin>{b[1]:.10f}</ymin>\n"
            f"{pad}  <xmax>{b[2]:.10f}</xmax>\n"
            f"{pad}  <ymax>{b[3]:.10f}</ymax>\n"
            f"{pad}</{tag}>")


# --------------------------------------------------------------------------
# symbols
# --------------------------------------------------------------------------
def fill_symbol(idx, colour, outline="90,84,72,255", width="0.26"):
    return f"""        <symbol type="fill" name="{idx}" alpha="1" force_rhr="0" clip_to_extent="1">
          <layer class="SimpleFill" enabled="1" pass="0" locked="0">
            <Option type="Map">
              <Option type="QString" name="color" value="{colour}"/>
              <Option type="QString" name="outline_color" value="{outline}"/>
              <Option type="QString" name="outline_width" value="{width}"/>
              <Option type="QString" name="outline_width_unit" value="MM"/>
              <Option type="QString" name="outline_style" value="solid"/>
              <Option type="QString" name="joinstyle" value="round"/>
              <Option type="QString" name="style" value="solid"/>
            </Option>
          </layer>
        </symbol>"""


def line_symbol(idx, colour, width, style="solid"):
    return f"""        <symbol type="line" name="{idx}" alpha="1" force_rhr="0" clip_to_extent="1">
          <layer class="SimpleLine" enabled="1" pass="0" locked="0">
            <Option type="Map">
              <Option type="QString" name="line_color" value="{colour}"/>
              <Option type="QString" name="line_width" value="{width}"/>
              <Option type="QString" name="line_width_unit" value="MM"/>
              <Option type="QString" name="line_style" value="{style}"/>
              <Option type="QString" name="capstyle" value="round"/>
              <Option type="QString" name="joinstyle" value="round"/>
            </Option>
          </layer>
        </symbol>"""


def marker_symbol(idx, colour, size, outline="28,28,28,255"):
    return f"""        <symbol type="marker" name="{idx}" alpha="1" force_rhr="0" clip_to_extent="1">
          <layer class="SimpleMarker" enabled="1" pass="0" locked="0">
            <Option type="Map">
              <Option type="QString" name="color" value="{colour}"/>
              <Option type="QString" name="name" value="circle"/>
              <Option type="QString" name="outline_color" value="{outline}"/>
              <Option type="QString" name="outline_width" value="0.3"/>
              <Option type="QString" name="outline_width_unit" value="MM"/>
              <Option type="QString" name="size" value="{size}"/>
              <Option type="QString" name="size_unit" value="MM"/>
            </Option>
          </layer>
        </symbol>"""


def single(sym):
    return f"""    <renderer-v2 type="singleSymbol" forceraster="0" symbollevels="0"
                 enableorderby="0" referencescale="-1">
      <symbols>
{sym}
      </symbols>
    </renderer-v2>"""


def labeling(field, size, bold=False, italic=False, colour="26,20,15,255"):
    weight = 75 if bold else 50
    return f"""    <labeling type="simple">
      <settings calloutType="simple">
        <text-style fontFamily="Helvetica" fontSize="{size}" fontSizeUnit="Point"
                    fontWeight="{weight}" fontItalic="{1 if italic else 0}"
                    textColor="{colour}" textOpacity="1"
                    fieldName="{field}" isExpression="0">
          <text-buffer bufferDraw="1" bufferSize="1" bufferSizeUnits="MM"
                       bufferColor="255,255,255,230" bufferOpacity="1"
                       bufferJoinStyle="128"/>
        </text-style>
        <placement placement="0" overlapHandling="PreventOverlap" dist="1"
                   distUnits="MM" centroidWhole="0"/>
        <rendering scaleVisibility="0" displayAll="0" obstacle="1"/>
      </settings>
    </labeling>"""


# --------------------------------------------------------------------------
# layers
# --------------------------------------------------------------------------
def layer_id(key):
    """A layer id QGIS will actually keep.

    QgsMapLayer::readLayerXml only adopts the id written in the project if it
    is longer than ten characters - the check exists because QGIS's own ids
    are a name followed by a seventeen-digit timestamp, and anything shorter
    is assumed to be junk. A short id is silently replaced by a fresh random
    one, which then no longer matches the id the layer tree refers to: every
    layer loads, nothing is bound to the tree, and the project opens with the
    layer names listed and an empty canvas.

    The hash keeps the id stable across runs, so regenerating the project does
    not rewrite every id and produce a meaningless diff.
    """
    import hashlib

    h = hashlib.blake2s(key.encode(), digest_size=8).hexdigest()
    return f"{key}_{h}"          # >= 3 + 1 + 16 characters


class Layer:
    """One entry, carrying everything both the tree and <projectlayers> need.

    The tree and the layer definition are built from the same object for a
    reason: when they were written separately the tree ended up pointing every
    entry at one datasource, which is invisible in the XML and only shows up
    as missing layers on someone else's machine.
    """

    def __init__(self, lid, name, path, layername, kind, epsg,
                 renderer="", labels="", geom="", checked=True,
                 opacity="1", extent=None):
        self.key = lid
        self.id = layer_id(lid)
        self.name = name
        self.path = path              # relative to the project file
        self.layername = layername    # gpkg table, or "" for rasters
        self.kind = kind              # "vector" | "raster"
        self.epsg = epsg
        self.renderer = renderer
        self.labels = labels
        self.geom = geom
        self.checked = checked
        self.opacity = opacity
        self.extent = extent

    @property
    def provider(self):
        return "ogr" if self.kind == "vector" else "gdal"

    @property
    def datasource(self):
        if self.layername:
            return f"{self.path}|layername={self.layername}"
        return self.path

    def tree_entry(self):
        state = "Qt::Checked" if self.checked else "Qt::Unchecked"
        return (f'    <layer-tree-layer id={quoteattr(self.id)} '
                f'name={quoteattr(self.name)} checked="{state}" expanded="0" '
                f'providerKey={quoteattr(self.provider)} '
                f'source={quoteattr(self.datasource)}>\n'
                f'      <customproperties/>\n'
                f'    </layer-tree-layer>')

    def xml(self):
        ext = extent_block(self.extent, indent=4) + "\n" if self.extent else ""
        if self.kind == "vector":
            body = f"{self.renderer}\n{self.labels}" if self.labels else self.renderer
            return f"""  <maplayer type="vector" geometry="{self.geom}"
            hasScaleBasedVisibilityFlag="0" refreshOnNotifyEnabled="0"
            autoRefreshEnabled="0" readOnly="0">
    <id>{escape(self.id)}</id>
    <datasource>{escape(self.datasource)}</datasource>
    <layername>{escape(self.name)}</layername>
    <provider encoding="UTF-8">ogr</provider>
{ext}    <srs>
{srs_block(self.epsg)}
    </srs>
    <layerOpacity>{self.opacity}</layerOpacity>
{body}
    <customproperties/>
    <blendMode>0</blendMode>
  </maplayer>"""
        return f"""  <maplayer type="raster" hasScaleBasedVisibilityFlag="0"
            refreshOnNotifyEnabled="0" autoRefreshEnabled="0">
    <id>{escape(self.id)}</id>
    <datasource>{escape(self.datasource)}</datasource>
    <layername>{escape(self.name)}</layername>
    <provider>gdal</provider>
{ext}    <srs>
{srs_block(self.epsg)}
    </srs>
{self.renderer}
    <customproperties/>
    <blendMode>0</blendMode>
  </maplayer>"""


def raster_renderer(bands, opacity):
    """Match the renderer to what is actually in the file.

    The hillshade is one band and the scanned plates are three or four; asking
    for a three-band composite on a single-band file gives a layer that loads
    and draws nothing, which looks exactly like a broken path.
    """
    if bands >= 3:
        return f"""    <pipe>
      <rasterrenderer type="multibandcolor" redBand="1" greenBand="2"
                      blueBand="3" opacity="{opacity}" alphaBand="-1">
        <rasterTransparency/>
        <minMaxOrigin>
          <limits>None</limits>
          <extent>WholeRaster</extent>
        </minMaxOrigin>
      </rasterrenderer>
      <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
      <huesaturation saturation="0" grayscaleMode="0" colorizeOn="0"/>
      <resamplefilter zoomedInResampler="bilinear"
                      zoomedOutResampler="average" maxOversampling="2"/>
    </pipe>"""
    return f"""    <pipe>
      <rasterrenderer type="singlebandgray" band="1" opacity="{opacity}"
                      gradient="BlackToWhite" alphaBand="-1">
        <rasterTransparency/>
        <minMaxOrigin>
          <limits>None</limits>
          <extent>WholeRaster</extent>
        </minMaxOrigin>
        <contrastEnhancement>
          <minValue>0</minValue>
          <maxValue>255</maxValue>
          <algorithm>StretchToMinimumMaximum</algorithm>
        </contrastEnhancement>
      </rasterrenderer>
      <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
      <huesaturation saturation="0" grayscaleMode="0" colorizeOn="0"/>
      <resamplefilter zoomedInResampler="bilinear"
                      zoomedOutResampler="average" maxOversampling="2"/>
    </pipe>"""


def gpkg_layers(path):
    """Table names and bounds in a GeoPackage, without going through OGR.

    gpkg_contents already stores each table's bounding box, so the extents
    written into the project are the layers' real ones rather than one
    envelope reused for all of them. QGIS only trusts them when the project
    is set to trust layer metadata, but if someone turns that on the numbers
    should be right rather than merely present.
    """
    import shutil
    import tempfile

    def _read():
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td) / "x.gpkg"
            shutil.copyfile(path, tmp)
            con = sqlite3.connect(tmp)
            rows = con.execute(
                "select table_name, min_x, min_y, max_x, max_y "
                "from gpkg_contents").fetchall()
            con.close()
            return {r[0]: tuple(r[1:]) for r in rows}

    return retry(_read, what=str(path))


# --------------------------------------------------------------------------
def main():
    from pyproj import Transformer

    grp = read_gpkg(VEC / "mitwaba.gpkg", "groupements")
    ter = read_gpkg(VEC / "mitwaba.gpkg", "territoire")

    colour = {}
    for s, shades in SECTOR_HUES.items():
        for i, n in enumerate(sorted(grp.loc[grp.sector == s, "groupement"])):
            colour[n] = shades[i % len(shades)]

    cats, syms = [], []
    for i, (name, col) in enumerate(sorted(colour.items())):
        cats.append(f'        <category render="1" symbol="{i}" '
                    f'value={quoteattr(name)} label={quoteattr(name)}/>')
        syms.append(fill_symbol(i, rgb(col)))
    grp_renderer = f"""    <renderer-v2 type="categorizedSymbol" attr="groupement"
                 forceraster="0" symbollevels="0" enableorderby="0"
                 referencescale="-1">
      <categories>
{chr(10).join(cats)}
      </categories>
      <symbols>
{chr(10).join(syms)}
      </symbols>
    </renderer-v2>"""

    rel_vec = "../03_vector/mitwaba.gpkg"
    rel_ctx = "../04_context/context.gpkg"

    tables = {rel_vec: gpkg_layers(VEC / "mitwaba.gpkg"),
              rel_ctx: gpkg_layers(CTX / "context.gpkg")}

    def bounds(path, table):
        return tables[path][table]

    vec_b = tuple(ter.total_bounds)

    layers = [
        Layer("places", "Localités", rel_ctx, "places", "vector", WGS84,
              single(marker_symbol(0, "58,51,43,255", "2.2")),
              labeling("name", 8, italic=True), geom="Point",
              extent=bounds(rel_ctx, "places")),
        Layer("terr", "Territoire de Mitwaba", rel_vec, "territoire",
              "vector", WGS84,
              single(fill_symbol(0, "0,0,0,0", "28,28,28,255", "1.4")),
              geom="Polygon", extent=bounds(rel_vec, "territoire")),
        Layer("sect", "Secteurs et chefferie", rel_vec, "sectors",
              "vector", WGS84,
              single(fill_symbol(0, "0,0,0,0", "28,28,28,255", "0.8")),
              labeling("sector", 13, bold=True), geom="Polygon",
              extent=bounds(rel_vec, "sectors")),
        Layer("roads", "Routes", rel_ctx, "roads", "vector", WGS84,
              single(line_symbol(0, "181,45,31,255", "0.5")),
              geom="LineString", extent=bounds(rel_ctx, "roads")),
        Layer("rivers", "Cours d'eau", rel_ctx, "rivers", "vector", WGS84,
              single(line_symbol(0, "107,168,202,255", "0.2")),
              geom="LineString", extent=bounds(rel_ctx, "rivers")),
        Layer("water", "Lacs et étendues d'eau", rel_ctx, "water",
              "vector", WGS84,
              single(fill_symbol(0, "143,194,221,255", "107,168,202,255",
                                 "0.15")),
              geom="Polygon", extent=bounds(rel_ctx, "water")),
        Layer("grp", "Groupements", rel_vec, "groupements", "vector", WGS84,
              grp_renderer, labeling("groupement", 9), geom="Polygon",
              extent=bounds(rel_vec, "groupements")),
    ]

    # Rasters: the relief the printed sheet sits on, then the georeferenced
    # source plates. The plates ship switched off - they are there so the
    # client can tick one on and see the delivered boundary lying on the atlas
    # page it was traced from, which is the first check anyone will want to
    # make and should not require hunting for a file.
    #
    # Band count and CRS are stated here rather than read back off the files,
    # because they are decided by the steps that write them and not by
    # anything that can drift in between: step 18 writes the hillshade
    # count=1, uint8, EPSG:32735, and step 4 tags each colour scan in place as
    # EPSG:4326 keeping the scan's own bands. Getting this wrong is not
    # subtle - a single-band file asked to render as an RGB composite loads
    # cleanly and draws nothing, which looks exactly like a broken path - so
    # it is worth the two entries below being explicit and checked by eye
    # against those two scripts.
    #
    # No <extent> is written for rasters: unlike a vector layer, a GeoTIFF
    # carries its own, and QGIS reads it from the file on load.
    raster_specs = [
        # id,     name,                    relative path,   epsg, bands, opacity, on
        ("relief", "Relief (ombrage SRTM)",
         "../04_context/hillshade_utm35s.tif", UTM35S, 1, "0.45", True),
        ("src22", "Source · pl.54 Balomotwa (géoréférencée)",
         "../02_georef/page-22_4326.tif", WGS84, 3, "1", False),
        ("src23", "Source · pl.55 Banweshi (géoréférencée)",
         "../02_georef/page-23_4326.tif", WGS84, 3, "1", False),
        ("src24", "Source · pl.56 Kiona-Ngoy (géoréférencée)",
         "../02_georef/page-24_4326.tif", WGS84, 3, "1", False),
    ]
    for lid, name, rel, epsg, bands, opacity, on in raster_specs:
        layers.append(Layer(lid, name, rel, "", "raster", epsg,
                            renderer=raster_renderer(bands, opacity),
                            checked=on, opacity=opacity))
        print(f"  {name:<44} {bands} band(s)  EPSG:{epsg}")

    # ---- check the project against the disk before writing it -------------
    problems = []
    for lay in layers:
        target = (QGIS / lay.path).resolve()
        if not target.exists():
            problems.append(f"{lay.key}: missing file {lay.path}")
        elif lay.layername and lay.layername not in tables.get(lay.path, {}):
            problems.append(
                f"{lay.key}: '{lay.layername}' not a table in {lay.path} "
                f"(has: {sorted(tables.get(lay.path, {}))})")
        # the id has to survive QgsMapLayer::readLayerXml, which discards
        # anything ten characters or shorter and hands the layer a fresh
        # random id - leaving the layer tree pointing at an id nothing has
        if len(lay.id) <= 10:
            problems.append(f"{lay.key}: id '{lay.id}' too short, QGIS would "
                            f"discard it and unbind the layer from the tree")
    if len({lay.id for lay in layers}) != len(layers):
        problems.append("duplicate layer ids")
    if problems:
        raise SystemExit("project would not open:\n  "
                         + "\n  ".join(problems))

    # ---- canvas ------------------------------------------------------------
    # the extent QGIS opens on, in the project CRS, with a small margin so the
    # territory does not sit hard against the window edge
    tf = Transformer.from_crs(WGS84, UTM35S, always_xy=True)
    xs, ys = tf.transform([vec_b[0], vec_b[2]], [vec_b[1], vec_b[3]])
    mx, my = (max(xs) - min(xs)) * 0.04, (max(ys) - min(ys)) * 0.04
    canvas = (min(xs) - mx, min(ys) - my, max(xs) + mx, max(ys) + my)

    tree = "\n".join(lay.tree_entry() for lay in layers)
    order = "\n".join(f"      <item>{escape(lay.id)}</item>" for lay in layers)
    draw = "\n".join(f'    <layer id={quoteattr(lay.id)}/>' for lay in layers)
    body = "\n".join(lay.xml() for lay in layers)

    qgs = f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis projectname="Territoire de Mitwaba - limites administratives"
      version="3.34.0-Prizren" saveDateTime="">
  <homePath path=""/>
  <title>Territoire de Mitwaba — limites administratives (CENI 2016)</title>
  <autotransaction active="0"/>
  <evaluateDefaultValues active="0"/>
  <trust active="0"/>
  <projectCrs>
{srs_block(UTM35S, indent=4)}
  </projectCrs>
  <layer-tree-group name="" checked="Qt::Checked" expanded="1">
    <customproperties/>
{tree}
    <custom-order enabled="0">
{order}
    </custom-order>
  </layer-tree-group>
  <snapping-settings enabled="0" type="1" tolerance="12" unit="1"
                     mode="2" intersection-snapping="0"/>
  <relations/>
  <mapcanvas name="theMapCanvas" annotationsVisible="1">
    <units>meters</units>
{extent_block(canvas, indent=4)}
    <rotation>0</rotation>
    <destinationsrs>
{srs_block(UTM35S, indent=6)}
    </destinationsrs>
    <rendermaptile>0</rendermaptile>
    <expressionContextScope/>
  </mapcanvas>
  <projectlayers>
{body}
  </projectlayers>
  <layerorder>
{draw}
  </layerorder>
  <properties>
    <Paths>
      <Absolute type="bool">false</Absolute>
    </Paths>
    <Measure>
      <Ellipsoid type="QString">EPSG:7030</Ellipsoid>
    </Measure>
    <PositionPrecision>
      <Automatic type="bool">true</Automatic>
      <DecimalPlaces type="int">2</DecimalPlaces>
    </PositionPrecision>
    <Gui>
      <CanvasColour type="QString">#ffffff</CanvasColour>
      <SelectionColorRedPart type="int">255</SelectionColorRedPart>
      <SelectionColorGreenPart type="int">255</SelectionColorGreenPart>
      <SelectionColorBluePart type="int">0</SelectionColorBluePart>
    </Gui>
  </properties>
  <visibility-presets/>
  <transformContext/>
  <projectMetadata>
    <identifier>mitwaba-limites-administratives</identifier>
    <title>Territoire de Mitwaba — limites administratives</title>
    <abstract>Limites du territoire, des secteurs/chefferie et des groupements,
vectorisées depuis l'atlas CENI 2016 (planches 54-56). Contexte
(routes, hydrographie, localités) depuis OpenStreetMap.</abstract>
    <crs>
{srs_block(UTM35S, indent=6)}
    </crs>
  </projectMetadata>
</qgis>
"""

    # well-formedness is checked before anything is written: a project that
    # will not parse is worse than no project at all
    import xml.etree.ElementTree as ET
    ET.fromstring(qgs)

    import io

    qgs_path = write_shared(QGIS / "Mitwaba.qgs", qgs)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Mitwaba.qgs", qgs)
    qgz = write_shared(QGIS / "Mitwaba.qgz", buf.getvalue())

    print(f"\nwrote {qgz}")
    print(f"wrote {qgs_path}")
    print(f"  {len(layers)} layers, {len(colour)} groupement categories")
    print(f"  project CRS EPSG:{UTM35S}, canvas "
          f"{canvas[0]:.0f} {canvas[1]:.0f} -> {canvas[2]:.0f} {canvas[3]:.0f} m")
    print("  all datasources resolved against disk")


if __name__ == "__main__":
    main()
