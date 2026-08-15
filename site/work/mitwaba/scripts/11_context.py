#!/usr/bin/env python3
"""
Step 11 - Build the contextual layers: roads, hydrography, settlements.

Per the brief the 2016 atlas is authoritative for the administrative
boundaries ONLY. Roads, rivers and settlements come from present-day
OpenStreetMap instead, because they have to be current and because OSM can
actually be redistributed as GIS data - which is the reason the client's other
suggestion, tracing Google Maps, is not usable for a deliverable dataset even
though it is fine as a visual cross-check.

Settlement selection is the one judgement call. The atlas lists 276 villages
in Mitwaba and the agreed scope is "roughly the density of the provincial
map", about 35-40 names. Rather than pick by hand, places are scored on what
makes a settlement worth naming on a territory sheet - its OSM rank, whether
it is the chef-lieu a groupement is named after, and whether it sits on a
through road - and then taken greedily subject to a minimum spacing, so the
selection is spread over the territory instead of clustering along the one
well-surveyed road.

Output: 04_context/context.gpkg (roads, rivers, water, places)
"""
import json
import pathlib
import sys
import unicodedata

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import append_gpkg, read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
VEC = ROOT / "03_vector"
CTX = ROOT / "04_context"
UTM = "EPSG:32735"

ROAD_CLASS = {"trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4,
              "unclassified": 5}
PLACE_RANK = {"city": 4, "town": 3, "village": 2, "hamlet": 1,
              "isolated_dwelling": 0}

TARGET_PLACES = 40
MIN_SPACING_M = 5000       # keeps labels from colliding at A0
EDGE_BUFFER_M = 3000       # context is carried this far outside the territory


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return s.lower().replace("-", " ").replace("'", "").strip()


def load_osm(path):
    d = json.loads(pathlib.Path(path).read_text())
    roads, rivers, water, places = [], [], [], []
    for e in d["elements"]:
        t = e.get("tags", {})
        name = t.get("name")
        if e["type"] == "node":
            if t.get("place") in PLACE_RANK:
                places.append(dict(name=name, place=t["place"],
                                   geometry=Point(e["lon"], e["lat"])))
            continue
        rings = []
        if "geometry" in e:
            rings = [[(p["lon"], p["lat"]) for p in e["geometry"]]]
        else:
            for m in e.get("members", []):
                if "geometry" in m:
                    rings.append([(p["lon"], p["lat"]) for p in m["geometry"]])
        for g in rings:
            if len(g) < 2:
                continue
            if t.get("highway") in ROAD_CLASS:
                roads.append(dict(name=name, highway=t["highway"],
                                  ref=t.get("ref"),
                                  cls=ROAD_CLASS[t["highway"]],
                                  geometry=LineString(g)))
            elif t.get("waterway") in ("river", "stream"):
                rivers.append(dict(name=name, waterway=t["waterway"],
                                   geometry=LineString(g)))
            elif t.get("natural") == "water" and len(g) >= 4:
                try:
                    water.append(dict(name=name, geometry=Polygon(g).buffer(0)))
                except Exception:
                    pass
    return roads, rivers, water, places


def main():
    terr = read_gpkg(VEC / "mitwaba.gpkg", "territoire").to_crs(UTM)
    groupements = read_gpkg(VEC / "mitwaba.gpkg", "groupements").to_crs(UTM)
    area = terr.geometry.iloc[0]
    clip = area.buffer(EDGE_BUFFER_M)

    roads, rivers, water, places = load_osm(CTX / "osm_full.json")
    print(f"OSM read: {len(roads)} road ways, {len(rivers)} watercourses, "
          f"{len(water)} water bodies, {len(places)} places")

    def frame(rows, geom_type):
        g = gpd.GeoDataFrame(rows, crs="EPSG:4326").to_crs(UTM)
        g = g[g.intersects(clip)].copy()
        g["geometry"] = g.geometry.intersection(clip)
        g = g[~g.geometry.is_empty]
        return g[g.geom_type.isin(geom_type)]

    roads_g = frame(roads, ["LineString", "MultiLineString"])
    rivers_g = frame(rivers, ["LineString", "MultiLineString"])
    water_g = frame(water, ["Polygon", "MultiPolygon"])
    places_g = frame(places, ["Point"])

    # merge road segments that share a name and class, so labels are placed on
    # a whole road rather than on each little OSM way
    roads_g = (roads_g.dissolve(by=["highway", "cls", "ref", "name"],
                                as_index=False, dropna=False)
               if len(roads_g) else roads_g)

    # ---- settlement selection
    named = places_g[places_g["name"].notna()].copy()
    named["rank"] = named["place"].map(PLACE_RANK).fillna(0)
    chef = {norm(n) for n in groupements["groupement"]}
    named["is_chef_lieu"] = [norm(n) in chef for n in named["name"]]

    through = roads_g[roads_g["cls"] <= 3]
    on_road = unary_union(through.geometry.values).buffer(2500) \
        if len(through) else None
    named["on_road"] = (named.geometry.within(on_road) if on_road is not None
                        else False)
    named["in_territory"] = named.geometry.within(area)

    named["score"] = (named["rank"] * 2
                      + named["is_chef_lieu"] * 6
                      + named["on_road"] * 2
                      + named["in_territory"] * 3)
    named = named.sort_values("score", ascending=False)

    chosen, pts = [], []
    for idx, r in named.iterrows():
        if len(chosen) >= TARGET_PLACES:
            break
        if not r["in_territory"] and r["rank"] < 3:
            continue
        if pts and min(r.geometry.distance(p) for p in pts) < MIN_SPACING_M:
            continue
        chosen.append(idx)
        pts.append(r.geometry)
    sel = named.loc[chosen].copy()
    sel["label_class"] = np.where(sel["rank"] >= 3, "town",
                                  np.where(sel["is_chef_lieu"], "chef_lieu",
                                           "village"))

    out = CTX / "context.gpkg"
    append_gpkg(roads_g.to_crs(4326), out, "roads", fresh=True)
    append_gpkg(rivers_g.to_crs(4326), out, "rivers")
    append_gpkg(water_g.to_crs(4326), out, "water")
    append_gpkg(sel.to_crs(4326)[["name", "place", "label_class", "score",
                                  "geometry"]], out, "places")
    append_gpkg(places_g.to_crs(4326), out, "places_all")

    print(f"\nclipped to territory + {EDGE_BUFFER_M/1000:.0f} km:")
    print(f"   roads       {len(roads_g):5d}  "
          f"({roads_g.length.sum()/1000:.0f} km)")
    print(f"   watercourses{len(rivers_g):5d}  "
          f"({rivers_g.length.sum()/1000:.0f} km)")
    print(f"   water bodies{len(water_g):5d}")
    print(f"   places kept {len(sel):5d} of {len(named)} named")
    print("\nselected settlements:")
    for _, r in sel.sort_values("name").iterrows():
        flag = "chef-lieu" if r["is_chef_lieu"] else r["place"]
        print(f"   {r['name']:<22} {flag}")
    print("\nwrote", out)


if __name__ == "__main__":
    main()
