"""GDML -> placed primitives in mm.

Two parsers behind one `parse_gdml`:

  * pyg4ometry (preferred when installed): the standard GDML tool. It resolves
    the full volume tree, transforms, and every solid type -- and gives an
    accurate mesh bounding box for solids the display can't draw natively
    (polycones, polyhedra, ...), instead of the crude heuristics below. Used
    automatically when importable.
  * a built-in lightweight XML parser (fallback): handles the simple example
    geometries (box, orb, tube, trd) with nested inline <physvol> placements;
    unsupported solids get a coarse bbox; very large files switch to bbox-only.
    Keeps the display working with no heavy dependency (pyg4ometry pulls in vtk).

Both emit the same Primitive contract (type/params in mm, 4x4 transform, ...),
so scene/render/info are parser-agnostic. Force one with the env var
GDMLTP_GDML_PARSER=pyg4ometry|lightweight.
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
class Mesh:
    """A real triangulated solid surface in the solid's own local frame (mm).

    Shared across every placement of the same solid, so a detector that places
    one logical volume thousands of times carries the geometry once and the
    emitters instance it (dedupe by `id(mesh)`).
    """
    vertices: np.ndarray          # (N,3) local mm
    faces: np.ndarray             # (M,3) int, triangles


@dataclass
class Primitive:
    type: str                     # box | orb | tube | trd | bbox | mesh
    params: dict                  # in mm (for mesh: the local AABB, for fallbacks)
    transform: np.ndarray         # 4x4, mm
    material: str = ""
    volume_name: str = ""
    is_world: bool = False
    mesh: "Mesh" = None           # set when type == "mesh": faithful surface


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
        for sub in pv:
            if _strip_ns(sub.tag) == "volumeref":
                ref = sub.get("ref")
        pos, rot = self.read_pos_rot(pv)
        return {"ref": ref, "pos": pos, "rot": rot}

    def read_pos_rot(self, el, prefix=""):
        """(position mm, rotation rad) from an element's position/rotation
        children or their *ref forms -- shared by physvol, boolean solids
        (`prefix="first"` picks up firstposition/firstrotation) and
        multiUnionNode."""
        pos = (0.0, 0.0, 0.0)
        rot = (0.0, 0.0, 0.0)
        for sub in el:
            st = _strip_ns(sub.tag)
            if st == prefix + "position":
                s = _len_scale(sub)
                pos = (_f(sub, "x") * s, _f(sub, "y") * s, _f(sub, "z") * s)
            elif st == prefix + "positionref":
                pos = self.defines_pos.get(sub.get("ref"), (0.0, 0.0, 0.0))
            elif st == prefix + "rotation":
                a = AUNIT_TO_RAD.get((sub.get("aunit") or sub.get("unit") or "rad").lower(), 1.0)
                rot = (_f(sub, "x") * a, _f(sub, "y") * a, _f(sub, "z") * a)
            elif st == prefix + "rotationref":
                rot = self.defines_rot.get(sub.get("ref"), (0.0, 0.0, 0.0))
        return pos, rot


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


# --------------------------------------------------------------------------- #
# Boolean solids
#
# The lightweight parser does no CSG, so a boolean is reduced to the positive
# shapes that BOUND it -- enough for the display's job (context around the
# tracks) and for `info`'s extent. Without this, geometry that is *entirely*
# boolean -- a FLUKA-converted accelerator model, say, where every region is an
# intersection of bodies minus its neighbours -- parses to nothing at all.
# pyg4ometry, when installed, meshes these properly instead.
# --------------------------------------------------------------------------- #
_BOOLEAN_TAGS = ("subtraction", "intersection", "union", "multiUnion")


def _params_half_extent(ptype, params):
    return _half_extent(Primitive(ptype, params, _identity()))


def _parts_span(parts):
    """Diagonal of the AABB around [(ptype, params, offset)], for comparing how
    tightly two operands bound an intersection. inf when there is nothing."""
    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)
    for ptype, params, off in parts:
        c = off[:3, 3]
        h = _params_half_extent(ptype, params)
        lo = np.minimum(lo, c - h)
        hi = np.maximum(hi, c + h)
    if not np.all(np.isfinite(lo)):
        return np.inf
    return float(np.linalg.norm(hi - lo))


def _solid_parts(g, name, depth=0):
    """[(ptype, params, offset 4x4)] bounding the named solid.

      primitive        -> itself (exact)
      subtraction      -> the first operand; what is cut away is not drawn
      intersection     -> whichever operand bounds the result more tightly
      union/multiUnion -> every constituent, each at its own offset
    """
    if depth > 8 or name not in g.solids:
        return []
    stype, el = g.solids[name]
    ptype, params = _solid_primitive(stype, el)
    if ptype is not None:
        return [(ptype, params, _identity())]
    if stype not in _BOOLEAN_TAGS:
        bb = _bbox_of_solid(stype, el)
        if not bb:
            return []
        params, off = bb
        return [("bbox", params, _translation(*off))]

    def placed(parts, pos, rot):
        m = _translation(*pos) @ _rotation(*rot)
        return [(t, p, m @ off) for t, p, off in parts]

    if stype == "multiUnion":
        out = []
        for node in el:
            if _strip_ns(node.tag) != "multiUnionNode":
                continue
            ref = next((s.get("ref") for s in node
                        if _strip_ns(s.tag) == "solid"), None)
            if ref:
                out += placed(_solid_parts(g, ref, depth + 1),
                              *g.read_pos_rot(node))
        return out

    first = next((s.get("ref") for s in el if _strip_ns(s.tag) == "first"), None)
    second = next((s.get("ref") for s in el if _strip_ns(s.tag) == "second"), None)
    a = placed(_solid_parts(g, first, depth + 1), *g.read_pos_rot(el, "first"))
    if stype == "subtraction":
        return a
    b = placed(_solid_parts(g, second, depth + 1), *g.read_pos_rot(el))
    if stype == "union":
        return a + b
    return a if _parts_span(a) <= _parts_span(b) else b     # intersection


def _clip_to_world(prims, world_half):
    """Trim primitives to the world box, dropping those wholly outside it.

    Geant4 tracks nothing beyond the world, so nothing trackable is lost -- a
    solid that straddles the boundary keeps its axis-aligned footprint inside.
    What this buys is scale: a FLUKA-converted model carries its outermost
    "blackhole" regions as bodies kilometres across inside a world a few metres
    wide, and unclipped they blow up the scene bounds until the display is a dot.
    """
    out = []
    for p in prims:
        if p.is_world or p.transform is None:
            out.append(p)
            continue
        c = p.transform[:3, 3]
        h = _half_extent(p)
        lo = np.maximum(c - h, -world_half)
        hi = np.minimum(c + h, world_half)
        if np.any(hi <= lo):
            continue                                   # entirely outside
        if np.allclose(lo, c - h) and np.allclose(hi, c + h):
            out.append(p)                              # fits: keep the real shape
            continue
        mid = 0.5 * (lo + hi)
        out.append(Primitive("bbox", {"sx": hi[0] - lo[0], "sy": hi[1] - lo[1],
                                      "sz": hi[2] - lo[2]},
                             _translation(*mid), p.material, p.volume_name))
    return out


def _use_pyg4ometry(path):
    """Which parser to use. Honor GDMLTP_GDML_PARSER; else prefer pyg4ometry
    when it imports."""
    choice = os.environ.get("GDMLTP_GDML_PARSER", "").lower()
    if choice == "lightweight":
        return False
    if choice == "pyg4ometry":
        return True
    try:
        import pyg4ometry  # noqa: F401
        return True
    except Exception:
        return False


def parse_gdml(path, include_world=False, max_bytes=DEFAULT_MAX_BYTES):
    """Parse a GDML file into a list[Primitive] in mm, via pyg4ometry when
    available (accurate) else the built-in lightweight parser."""
    if _use_pyg4ometry(path):
        try:
            return _parse_pyg4ometry(path, include_world=include_world)
        except Exception as e:
            warnings.warn(f"pyg4ometry parse failed ({e}); falling back to the "
                          f"lightweight parser.")
    return _parse_lightweight(path, include_world=include_world, max_bytes=max_bytes)


# --------------------------------------------------------------------------- #
# pyg4ometry-backed parser (the standard tool; FAITHFUL solid surfaces)
# --------------------------------------------------------------------------- #
# Box and Orb are drawn analytically (a cube/sphere IS the exact shape, and it
# keeps the common case light). EVERY other solid -- polycone, polyhedron,
# cone, trd, (cut/hollow) tube, boolean, ... -- is meshed to its true surface
# so the display matches the GDML instead of a bounding-box caricature. The
# mesh of a given solid is built ONCE and shared across all its placements
# (id(mesh) dedupe), so a detector that instances a volume thousands of times
# stays cheap; the emitters instance the shared surface.
#
# Placement cap: a full LHC-scale detector can place volumes millions of times.
# We emit up to this many placements (env GDMLTP_MAX_PLACEMENTS overrides), then
# stop and warn -- honest truncation beats a multi-GB scene the renderers choke
# on. Realistic single-target geometries are far under it.
_MAX_PLACEMENTS_DEFAULT = 40000


def _triangulate(polys):
    """Fan-triangulate polygons (index lists, any length >= 3) into (M,3) int."""
    tris = []
    for p in polys:
        idx = list(p)
        for k in range(1, len(idx) - 1):
            tris.append((idx[0], idx[k], idx[k + 1]))
    return np.asarray(tris, dtype=np.int32).reshape(-1, 3)


def _mesh_of_solid(s):
    """Real surface of a pyg4ometry solid as a Mesh (local mm), or None."""
    vp = s.mesh().toVerticesAndPolygons()
    v = np.asarray(vp[0], float)
    faces = _triangulate(vp[1])
    if not len(v) or not len(faces):
        return None
    return Mesh(vertices=v, faces=faces)


def _parse_pyg4ometry(path, include_world=False, max_placements=None):
    import pyg4ometry as pg
    from pyg4ometry import transformation as _T

    if max_placements is None:
        max_placements = int(os.environ.get("GDMLTP_MAX_PLACEMENTS",
                                            _MAX_PLACEMENTS_DEFAULT))
    reg = pg.gdml.Reader(str(path), skipMaterials=True).getRegistry()
    world = reg.getWorldVolume()
    prims = []
    mesh_cache = {}          # id(solid) -> (ptype, params, Mesh|None)
    capped = [False]

    def solid_repr(s):
        """(ptype, params_mm, Mesh|None) for a solid -- built once, cached."""
        key = id(s)
        hit = mesh_cache.get(key)
        if hit is not None:
            return hit
        t = type(s).__name__

        def g(a):
            return float(s.evaluateParameterWithUnits(a))

        if t == "Box":
            out = ("box", {"sx": g("pX"), "sy": g("pY"), "sz": g("pZ")}, None)
        elif t == "Orb":
            out = ("orb", {"r": g("pRMax")}, None)
        else:
            m = None
            try:
                m = _mesh_of_solid(s)
            except Exception:
                m = None
            if m is not None:
                lo, hi = m.vertices.min(axis=0), m.vertices.max(axis=0)
                ext = hi - lo
                out = ("mesh", {"sx": float(ext[0]), "sy": float(ext[1]),
                                "sz": float(ext[2]),
                                "cx": float(0.5 * (lo[0] + hi[0])),
                                "cy": float(0.5 * (lo[1] + hi[1])),
                                "cz": float(0.5 * (lo[2] + hi[2]))}, m)
            else:
                # last resort: a sphere for anything we truly cannot mesh
                out = ("orb", {"r": g("pRMax") if _has(s, "pRMax") else 1.0}, None)
        mesh_cache[key] = out
        return out

    def matname(lv):
        m = getattr(lv, "material", None)
        return getattr(m, "name", "") if m is not None else ""

    def recurse(lv, transform, is_world, depth):
        if depth > 25 or capped[0]:
            return
        solid = getattr(lv, "solid", None)          # AssemblyVolume has none
        if solid is not None and (not is_world or include_world):
            if len(prims) >= max_placements:
                capped[0] = True
                return
            ptype, params, mesh = solid_repr(solid)
            prims.append(Primitive(ptype, params, transform.copy(),
                                   matname(lv), lv.name, is_world, mesh=mesh))
        for pv in getattr(lv, "daughterVolumes", []):
            if capped[0]:
                return
            pos = np.asarray(pv.position.eval(), float)
            rot = pv.rotation.eval() if getattr(pv, "rotation", None) is not None else [0, 0, 0]
            local = np.eye(4)
            local[:3, :3] = _T.tbxyz2matrix(rot)
            local[:3, 3] = pos
            recurse(pv.logicalVolume, transform @ local, False, depth + 1)

    recurse(world, np.eye(4), True, 0)
    if capped[0]:
        warnings.warn(f"{os.path.basename(str(path))}: reached the "
                      f"{max_placements}-placement display cap; remaining volumes "
                      f"omitted (set GDMLTP_MAX_PLACEMENTS to raise it).")
    return prims


def _has(s, attr):
    try:
        s.evaluateParameterWithUnits(attr)
        return True
    except Exception:
        return False


def _parse_lightweight(path, include_world=False, max_bytes=DEFAULT_MAX_BYTES):
    """Parse a GDML file into a list[Primitive] in mm (built-in fallback)."""
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
                            what = ("decomposed into its positive parts"
                                    if stype in _BOOLEAN_TAGS else "bbox fallback")
                            warnings.warn(f"Unsupported solid '{stype}'; {what}.")
                            warned.add(stype)
                        for ptype, params, off in _solid_parts(g, sref):
                            prims.append(Primitive(ptype, params, transform @ off,
                                                   vol.get("materialref", ""),
                                                   volname, is_world))
        if bbox_only and not is_world:
            return  # don't recurse deeply in huge files
        for pv in vol.get("physvols", []):
            child = pv["ref"]
            local = _translation(*pv["pos"]) @ _rotation(*pv["rot"])
            recurse(child, transform @ local, depth + 1)

    if g.world:
        recurse(g.world, _identity(), 0)
        wsolid = g.solids.get((g.volumes.get(g.world) or {}).get("solidref"))
        if wsolid and wsolid[0] == "box":
            s = _len_scale(wsolid[1])
            prims = _clip_to_world(prims, 0.5 * s * np.array(
                [_f(wsolid[1], "x"), _f(wsolid[1], "y"), _f(wsolid[1], "z")]))
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
        if p.type == "mesh" and p.mesh is not None:
            # transform the real vertices so a rotated solid's true extent is used
            R, t = p.transform[:3, :3], p.transform[:3, 3]
            w = p.mesh.vertices @ R.T + t
            lo = np.minimum(lo, w.min(axis=0))
            hi = np.maximum(hi, w.max(axis=0))
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
    if p.type == "box" or p.type == "bbox" or p.type == "mesh":
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
