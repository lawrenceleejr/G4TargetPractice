"""Lightweight GDML parser -> placed primitives in mm.

Supports the simple example geometries (box, orb, tube, trd) with nested inline
<physvol> placements and unit conversion to mm. Unsupported solids fall back to
a bounding box; very large files (e.g. MAIA) switch to a coarse bbox-only mode.
"""
import os
import math
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
import numpy as np

LUNIT_TO_MM = {"mm": 1.0, "millimeter": 1.0, "cm": 10.0, "centimeter": 10.0,
               "m": 1000.0, "meter": 1000.0, "um": 1e-3, "nm": 1e-6, "km": 1e6}
AUNIT_TO_RAD = {"deg": math.pi / 180.0, "degree": math.pi / 180.0,
                "rad": 1.0, "radian": 1.0}

DEFAULT_MAX_BYTES = 8_000_000


@dataclass
class Primitive:
    type: str                     # box | orb | tube | trd | bbox
    params: dict                  # in mm
    transform: np.ndarray         # 4x4, mm
    material: str = ""
    volume_name: str = ""
    is_world: bool = False


def _strip_ns(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _f(el, attr, default=0.0):
    v = el.get(attr)
    return float(v) if v is not None else default


def _len_scale(el):
    return LUNIT_TO_MM.get((el.get("lunit") or el.get("unit") or "mm").lower(), 1.0)


def _identity():
    return np.eye(4)


def _translation(x, y, z):
    m = np.eye(4)
    m[0, 3], m[1, 3], m[2, 3] = x, y, z
    return m


def _rotation(rx, ry, rz):
    # GDML rotations are active rotations of the solid; approximate with XYZ.
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    R = Rz @ Ry @ Rx
    m = np.eye(4)
    m[:3, :3] = R
    return m


class _GDML:
    def __init__(self, root):
        self.root = root
        self.solids = {}      # name -> (type, element)
        self.defines_pos = {}  # name -> (x,y,z) mm
        self.defines_rot = {}  # name -> (rx,ry,rz) rad
        self.volumes = {}     # name -> dict(solidref, materialref, physvols=[...])
        self.world = None
        self._index()

    def _index(self):
        for child in self.root:
            tag = _strip_ns(child.tag)
            if tag == "define":
                for d in child:
                    dtag = _strip_ns(d.tag)
                    s = _len_scale(d)
                    if dtag == "position":
                        self.defines_pos[d.get("name")] = (
                            _f(d, "x") * s, _f(d, "y") * s, _f(d, "z") * s)
                    elif dtag == "rotation":
                        a = AUNIT_TO_RAD.get((d.get("aunit") or d.get("unit") or "rad").lower(), 1.0)
                        self.defines_rot[d.get("name")] = (
                            _f(d, "x") * a, _f(d, "y") * a, _f(d, "z") * a)
            elif tag == "solids":
                for s in child:
                    self.solids[s.get("name")] = (_strip_ns(s.tag), s)
            elif tag == "structure":
                for v in child:
                    if _strip_ns(v.tag) not in ("volume", "assembly"):
                        continue
                    name = v.get("name")
                    vol = {"solidref": None, "materialref": "", "physvols": [],
                           "assembly": _strip_ns(v.tag) == "assembly"}
                    for sub in v:
                        st = _strip_ns(sub.tag)
                        if st == "solidref":
                            vol["solidref"] = sub.get("ref")
                        elif st == "materialref":
                            vol["materialref"] = sub.get("ref") or ""
                        elif st == "physvol":
                            vol["physvols"].append(self._read_physvol(sub))
                    self.volumes[name] = vol
            elif tag == "setup":
                w = child.find("{*}world")
                if w is None:
                    for sub in child:
                        if _strip_ns(sub.tag) == "world":
                            w = sub
                self.world = w.get("ref") if w is not None else None

    def _read_physvol(self, pv):
        ref = None
        pos = (0.0, 0.0, 0.0)
        rot = (0.0, 0.0, 0.0)
        for sub in pv:
            st = _strip_ns(sub.tag)
            if st == "volumeref":
                ref = sub.get("ref")
            elif st == "position":
                s = _len_scale(sub)
                pos = (_f(sub, "x") * s, _f(sub, "y") * s, _f(sub, "z") * s)
            elif st == "positionref":
                pos = self.defines_pos.get(sub.get("ref"), (0.0, 0.0, 0.0))
            elif st == "rotation":
                a = AUNIT_TO_RAD.get((sub.get("aunit") or sub.get("unit") or "rad").lower(), 1.0)
                rot = (_f(sub, "x") * a, _f(sub, "y") * a, _f(sub, "z") * a)
            elif st == "rotationref":
                rot = self.defines_rot.get(sub.get("ref"), (0.0, 0.0, 0.0))
        return {"ref": ref, "pos": pos, "rot": rot}


def _solid_primitive(solidtype, el):
    """Return (type, params_mm) or (None, None) if unsupported."""
    s = _len_scale(el)
    if solidtype == "box":
        return "box", {"sx": _f(el, "x") * s, "sy": _f(el, "y") * s, "sz": _f(el, "z") * s}
    if solidtype in ("orb", "sphere"):
        return "orb", {"r": _f(el, "r", _f(el, "rmax")) * s}
    if solidtype == "tube":
        return "tube", {"rmin": _f(el, "rmin") * s, "rmax": _f(el, "rmax") * s,
                        "z": _f(el, "z") * s}
    if solidtype == "trd":
        return "trd", {"x1": _f(el, "x1") * s, "x2": _f(el, "x2") * s,
                       "y1": _f(el, "y1") * s, "y2": _f(el, "y2") * s, "z": _f(el, "z") * s}
    return None, None


def _bbox_of_solid(solidtype, el):
    """Coarse bounds for an unsupported solid: (params_mm, center_offset_mm) or None.

    The offset matters for z-plane solids: a polycone spanning z=6..595 cm is
    NOT centered on its placement point, so a centered bbox would sit in the
    wrong place entirely.
    """
    s = _len_scale(el)
    try:
        if solidtype in ("polycone", "polyhedra", "genericPolycone", "genericPolyhedra"):
            zs, rs = [], []
            for c in el:
                tag = _strip_ns(c.tag)
                if tag == "zplane":
                    zs.append(_f(c, "z") * s)
                    rs.append(max(_f(c, "rmax"), _f(c, "rmin")) * s)
                elif tag == "rzpoint":          # genericPolycone/genericPolyhedra
                    zs.append(_f(c, "z") * s)
                    rs.append(_f(c, "r") * s)
            if zs:
                r = max(rs)
                zlo, zhi = min(zs), max(zs)
                return ({"sx": 2 * r, "sy": 2 * r, "sz": zhi - zlo},
                        (0.0, 0.0, 0.5 * (zlo + zhi)))
        if solidtype == "cone":
            r = max(_f(el, "rmax1"), _f(el, "rmax2"), _f(el, "rmax")) * s
            z = _f(el, "z") * s
            if r > 0:
                return {"sx": 2 * r, "sy": 2 * r, "sz": z if z > 0 else 2 * r}, (0.0, 0.0, 0.0)
    except Exception:
        return None
    return None


def parse_gdml(path, include_world=False, max_bytes=DEFAULT_MAX_BYTES):
    """Parse a GDML file into a list[Primitive] in mm."""
    size = os.path.getsize(path)
    bbox_only = size > max_bytes
    if bbox_only:
        warnings.warn(f"{os.path.basename(path)} is large ({size/1e6:.0f} MB); "
                      "rendering coarse bounding boxes only.")
    tree = ET.parse(path)
    g = _GDML(tree.getroot())
    prims = []
    warned = set()

    def recurse(volname, transform, depth):
        if depth > 12 or volname not in g.volumes:
            return
        vol = g.volumes[volname]
        is_world = volname == g.world
        if not is_world or include_world:
            if not vol.get("assembly"):
                # emit this volume's own solid
                sref = vol.get("solidref")
                if sref in g.solids:
                    stype, sel = g.solids[sref]
                    ptype, params = _solid_primitive(stype, sel)
                    if ptype is not None:
                        prims.append(Primitive(ptype, params, transform,
                                               vol.get("materialref", ""), volname, is_world))
                    else:
                        if stype not in warned:
                            warnings.warn(f"Unsupported solid '{stype}'; bbox fallback.")
                            warned.add(stype)
                        bb = _bbox_of_solid(stype, sel)
                        if bb:
                            params, off = bb
                            prims.append(Primitive("bbox", params,
                                                   transform @ _translation(*off),
                                                   vol.get("materialref", ""), volname, is_world))
        if bbox_only and not is_world:
            return  # don't recurse deeply in huge files
        for pv in vol.get("physvols", []):
            child = pv["ref"]
            local = _translation(*pv["pos"]) @ _rotation(*pv["rot"])
            recurse(child, transform @ local, depth + 1)

    if g.world:
        recurse(g.world, _identity(), 0)
    return prims


def bounding_box(prims, include_world=False):
    """(min, max) over primitive extents in mm, or None."""
    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)
    for p in prims:
        if p.is_world and not include_world:
            continue
        if p.transform is None:
            continue
        c = p.transform[:3, 3]
        ext = _half_extent(p)
        lo = np.minimum(lo, c - ext)
        hi = np.maximum(hi, c + ext)
    if not np.all(np.isfinite(lo)):
        return None
    return lo, hi


def _half_extent(p):
    pm = p.params or {}
    if p.type == "box" or p.type == "bbox":
        return np.array([pm.get("sx", 0) / 2, pm.get("sy", 0) / 2, pm.get("sz", 0) / 2])
    if p.type == "orb":
        r = pm.get("r", 0)
        return np.array([r, r, r])
    if p.type == "tube":
        r = pm.get("rmax", 0)
        return np.array([r, r, pm.get("z", 0) / 2])
    if p.type == "trd":
        return np.array([max(pm.get("x1", 0), pm.get("x2", 0)) / 2,
                         max(pm.get("y1", 0), pm.get("y2", 0)) / 2, pm.get("z", 0) / 2])
    return np.zeros(3)
