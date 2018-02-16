import operator
import pickle
import re
import warnings
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import (Any, Callable, Dict, Iterator, List, NamedTuple, Optional,
                    Tuple)
from xml.etree import ElementTree

import numpy as np
from matplotlib.patches import Polygon as MplPolygon

from fastkml import kml
from fastkml.geometry import Geometry
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import cascaded_union

ExtrudedPolygon = NamedTuple('ExtrudedPolygon',
                             [('polygon', Polygon),
                              ('lower', float), ('upper', float)])
SectorList = List[ExtrudedPolygon]


class Sector(object):

    def __init__(self, name: str, area: List[ExtrudedPolygon],
                 type_: Optional[str]=None) -> None:
        self.area: List[ExtrudedPolygon] = area
        self.name: str = name
        self.type: Optional[str] = type_

    def flatten(self) -> Polygon:
        return cascaded_union([p.polygon for p in self])

    def intersects(self, structure):
        pass

    def __getitem__(self, *args):
        return self.area.__getitem__(*args)

    def __iter__(self):
        return self.area.__iter__()

    def _repr_svg_(self):
        print("{self.name}/{self.type}")
        for polygon in self:
            print(polygon.lower, polygon.upper)
        return self.flatten()._repr_svg_()

    def __repr__(self):
        return f"Sector {self.name}/{self.type}"

    def __str__(self):
        return f"""Sector {self.name} with {len(self.area)} parts"""

    def plot(self, ax, **kwargs):
        flat = self.flatten()
        if isinstance(flat, MultiPolygon):
            for poly in flat:
                # quick and dirty
                sub = Sector("", [ExtrudedPolygon(poly, 0, 0)])
                sub.plot(ax, **kwargs)
            return
        coords = np.stack(flat.exterior.coords)
        if 'projection' in ax.__dict__:
            from cartopy.crs import PlateCarree
            coords = ax.projection.transform_points(
                PlateCarree(), *coords.T)[:, :2]
        if 'facecolor' not in kwargs:
            kwargs['facecolor'] = 'None'
        if 'edgecolor' not in kwargs:
            kwargs['edgecolor'] = 'red'
        ax.add_patch(MplPolygon(coords, **kwargs))

    @property
    def bounds(self) -> Tuple[float, ...]:
        return self.flatten().bounds

    def decompose(self, extr_p):
        c = np.stack(extr_p.polygon.exterior.coords)
        alt = np.zeros(c.shape[0], dtype=float)

        alt[:] = min(extr_p.upper, 400) * 30.48
        upper_layer = np.c_[c, alt]
        yield Polygon(upper_layer)
        alt[:] = max(0, extr_p.lower) * 30.48
        lower_layer = np.c_[c, alt][::-1, :]
        yield Polygon(lower_layer)

        for i, j in zip(range(c.shape[0]-1), range(c.shape[0], 1, -1)):
            yield Polygon(np.r_[lower_layer[i:i+2,:], upper_layer[j-2:j, :]])

    def export_kml(self, **kwargs):
        folder = kml.Folder(name=self.name, description=self.type)
        for extr_p in self:
            for elt in self.decompose(extr_p):
                placemark = kml.Placemark(**kwargs)
                placemark.geometry = kml.Geometry(
                    geometry=elt, altitude_mode='relativeToGround')
                folder.append(placemark)
        return folder

def cascaded_union_with_alt(polyalt: SectorList) -> SectorList:
    altitudes = set(alt for _, *low_up in polyalt for alt in low_up)
    slices = sorted(altitudes)
    if len(slices) == 1 and slices[0] is None:
        simple_union = cascaded_union([p for p, *_ in polyalt])
        return [ExtrudedPolygon(simple_union, float("-inf"), float("inf"))]
    results: List[ExtrudedPolygon] = []
    for low, up in zip(slices, slices[1:]):
        matched_poly = [p for (p, low_, up_) in polyalt
                        if low_ <= low <= up_ and low_ <= up <= up_]
        new_poly = ExtrudedPolygon(cascaded_union(matched_poly), low, up)
        if len(results) > 0 and new_poly.polygon.equals(results[-1].polygon):
            merged = ExtrudedPolygon(new_poly.polygon, results[-1].lower, up)
            results[-1] = merged
        else:
            results.append(new_poly)
    return results


class SectorParser(object):

    ns = {'adrmsg': 'http://www.eurocontrol.int/cfmu/b2b/ADRMessage',
          'aixm': 'http://www.aixm.aero/schema/5.1',
          'gml': 'http://www.opengis.net/gml/3.2',
          'xlink': 'http://www.w3.org/1999/xlink'}

    def __init__(self, airac_path: Path, cache_dir: Path) -> None:

        self.full_dict: Dict[str, Any] = {}
        self.all_points: Dict[str, Tuple[float, ...]] = {}

        assert airac_path.is_dir()

        cache_file = cache_dir / "airac.cache"
        if cache_file.exists():
            with cache_file.open("rb") as fh:
                self.full_dict, self.all_points, self.tree = pickle.load(fh)
                return

        for filename in ['Airspace.BASELINE', 'DesignatedPoint.BASELINE',
                         'Navaid.BASELINE']:

            if ~(airac_path / filename).exists():
                zippath = zipfile.ZipFile(
                    airac_path.joinpath(f"{filename}.zip").as_posix())
                zippath.extractall(airac_path.as_posix())

        self.tree = ElementTree.parse(
            (airac_path / 'Airspace.BASELINE').as_posix())

        for airspace in self.tree.findall(
                'adrmsg:hasMember/aixm:Airspace', self.ns):

            identifier = airspace.find('gml:identifier', self.ns)
            assert(identifier is not None)
            assert(identifier.text is not None)
            self.full_dict[identifier.text] = airspace

        points = ElementTree.parse((airac_path / 'DesignatedPoint.BASELINE').
                                   as_posix())

        for point in points.findall(
                "adrmsg:hasMember/aixm:DesignatedPoint", self.ns):

            identifier = point.find("gml:identifier", self.ns)
            assert(identifier is not None)
            assert(identifier.text is not None)

            floats = point.find(
                "aixm:timeSlice/aixm:DesignatedPointTimeSlice/"
                "aixm:location/aixm:Point/gml:pos", self.ns)
            assert(floats is not None)
            assert(floats.text is not None)

            self.all_points[identifier.text] = tuple(
                float(x) for x in floats.text.split())

        points = ElementTree.parse((airac_path / 'Navaid.BASELINE').as_posix())

        for point in points.findall(
                "adrmsg:hasMember/aixm:Navaid", self.ns):

            identifier = point.find("gml:identifier", self.ns)
            assert(identifier is not None)
            assert(identifier.text is not None)

            floats = point.find(
                "aixm:timeSlice/aixm:NavaidTimeSlice/"
                "aixm:location/aixm:ElevatedPoint/gml:pos", self.ns)
            assert(floats is not None)
            assert(floats.text is not None)

            self.all_points[identifier.text] = tuple(
                float(x) for x in floats.text.split())

        with cache_file.open("wb") as fh:
            pickle.dump((self.full_dict, self.all_points, self.tree), fh)

    def append_coords(self, lr, block_poly):
        coords: List[Tuple[float, ...]] = []
        gml, xlink = self.ns['gml'], self.ns['xlink']
        for point in lr.iter():
            if point.tag in ('{%s}pos' % (gml),
                             '{%s}pointProperty' % (gml)):
                if point.tag.endswith('pos'):
                    coords.append(tuple(float(x) for x in point.text.split()))
                else:
                    points = point.attrib['{%s}href' % (xlink)]
                    coords.append(self.all_points[points.split(':')[2]])
        block_poly.append(
            (Polygon([(lon, lat) for lat, lon in coords]), None, None))


    @lru_cache(None)
    def make_polygon(self, airspace) -> SectorList:
        polygons: SectorList = []
        for block in airspace.findall(
                "aixm:geometryComponent/aixm:AirspaceGeometryComponent/"
                "aixm:theAirspaceVolume/aixm:AirspaceVolume", self.ns):
            block_poly: SectorList = []
            upper = block.find("aixm:upperLimit", self.ns)
            lower = block.find("aixm:lowerLimit", self.ns)

            upper = (float(upper.text) if upper is not None and
                     re.match("\d{3}", upper.text) else float("inf"))
            lower = (float(lower.text) if lower is not None and
                     re.match("\d{3}", lower.text) else float("-inf"))

            for component in block.findall(
                    "aixm:contributorAirspace/aixm:AirspaceVolumeDependency/"
                    "aixm:theAirspace", self.ns):
                key = component.attrib['{http://www.w3.org/1999/xlink}href']
                key = key.split(':')[2]
                child = self.full_dict[key]
                for ats in child.findall(
                        "aixm:timeSlice/aixm:AirspaceTimeSlice", self.ns):
                    new_d = ats.find("aixm:designator", self.ns)
                    if new_d is not None:
                        block_poly += self.make_polygon(ats)
                    else:
                        for sub in ats.findall(
                                "aixm:geometryComponent/"
                                "aixm:AirspaceGeometryComponent/"
                                "aixm:theAirspaceVolume/aixm:AirspaceVolume",
                                self.ns):

                            assert sub.find('aixm:lowerLimit', self.ns) is None

                            for lr in sub.findall(
                                    "aixm:horizontalProjection/aixm:Surface/"
                                    "gml:patches/gml:PolygonPatch/gml:exterior/"
                                    "gml:LinearRing", self.ns):
                                self.append_coords(lr, block_poly)

            if upper == float('inf') and lower == float('-inf'):
                polygons += cascaded_union_with_alt(block_poly)
            else:
                polygons.append(ExtrudedPolygon(cascaded_union(
                    [p for (p, *_) in block_poly]), lower, upper))

        return(cascaded_union_with_alt(polygons))

    def __getitem__(self, name: str) -> Optional[Sector]:
        return next(self.search(name, operator.eq), None)

    def search(self, name: str, cmp: Callable=re.match) -> Iterator[Sector]:
        polygon = None
        type_: Optional[str] = None

        names = name.split('/')
        if len(names) > 1:
            name, type_ = names

        for airspace in self.tree.findall(
                'adrmsg:hasMember/aixm:Airspace', self.ns):
            for ts in airspace.findall(
                    "aixm:timeSlice/aixm:AirspaceTimeSlice", self.ns):

                designator = ts.find("aixm:designator", self.ns)

                if (designator is not None and cmp(name, designator.text) and
                        (type_ is None or
                         ts.find("aixm:type", self.ns).text == type_)):

                    polygon = self.make_polygon(ts)
                    type_ = ts.find("aixm:type", self.ns).text
                    if len(polygon) > 0:
                        yield Sector(designator.text, polygon, type_)
                    else:
                        warnings.warn(
                            f"{designator.text} produces an empty sector",
                            RuntimeWarning)
