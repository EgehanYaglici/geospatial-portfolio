"""
GeoPackage writing helper.

A GeoPackage is a SQLite database, and SQLite needs byte-range locking that the
shared folder this project lives on does not provide - writing one directly
onto it fails part-way through with "no such table: gpkg_contents". So every
GeoPackage is built on local disk first and then copied into place, which is a
plain sequential write and works fine.
"""
import pathlib
import shutil
import tempfile


def write_gpkg(gdf, path, layer, **kwargs):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td) / path.name
        gdf.to_file(tmp, layer=layer, driver="GPKG", **kwargs)
        shutil.copyfile(tmp, path)
    return path


def append_gpkg(gdf, path, layer, fresh=False, **kwargs):
    """Add a layer to a GeoPackage (copy out, append, copy back).

    `fresh=True` starts a new file even if one is already there. The share does
    not allow unlink either, so an existing file is replaced by copying over
    it rather than deleting it first.
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td) / path.name
        if path.exists() and not fresh:
            shutil.copyfile(path, tmp)
            gdf.to_file(tmp, layer=layer, driver="GPKG", mode="a", **kwargs)
        else:
            gdf.to_file(tmp, layer=layer, driver="GPKG", **kwargs)
        shutil.copyfile(tmp, path)
    return path


def read_gpkg(path, layer=None):
    """Read a GeoPackage that lives on the shared folder.

    Reading also fails there: SQLite wants a write lock even for SELECT, and
    the share reports the database as read-only. Copying to local disk first
    sidesteps it.
    """
    import geopandas as gpd
    path = pathlib.Path(path)
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td) / path.name
        shutil.copyfile(path, tmp)
        return gpd.read_file(tmp, layer=layer)
