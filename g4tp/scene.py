"""Intermediate Scene model: geometry + tracks + vertices, with auto camera fit.

Feeds all emitters (web/png/blender). Emitters never touch uproot or GDML.
"""
from dataclasses import dataclass, field
import numpy as np

from . import particles
from .geometry import bounding_box, _half_extent  # noqa: F401


@dataclass
class Track:
    track_id: int
    parent_id: int
    pdg: int
    polyline: np.ndarray          # (N,3) mm
    times: np.ndarray             # (N,) ns, aligned to polyline points
    color: str
    name: str
    creator_process: str = ""


@dataclass
class Vertex:
    pos: np.ndarray               # (3,) mm
    kind: str                     # primary_start | production | interaction | track_end
    pdg: int = 0


@dataclass
class Scene:
    primitives: list = field(default_factory=list)
    tracks: list = field(default_factory=list)
    vertices: list = field(default_factory=list)
    bbox_min: np.ndarray = None
    bbox_max: np.ndarray = None
    center: np.ndarray = None
    radius: float = 0.0
    event_id: int = 0
    meta: dict = field(default_factory=dict)


def _track_polyline(ev, i):
    tid = int(ev.trk["trk_id"][i])
    start = np.array([ev.trk["trk_startX"][i], ev.trk["trk_startY"][i], ev.trk["trk_startZ"][i]])
    end = np.array([ev.trk["trk_endX"][i], ev.trk["trk_endY"][i], ev.trk["trk_endZ"][i]])
    # contiguous, time-ordered step points for this track
    sid = ev.step.get("step_trackID")
    if sid is not None and len(sid):
        mask = sid == tid
        pts = np.column_stack([ev.step["step_x"][mask], ev.step["step_y"][mask], ev.step["step_z"][mask]])
        tms = ev.step["step_time"][mask]
    else:
        pts = np.empty((0, 3))
        tms = np.empty((0,))
    poly = np.vstack([start[None, :], pts, end[None, :]])
    t0 = tms[0] if len(tms) else 0.0
    t1 = tms[-1] if len(tms) else 0.0
    times = np.concatenate([[t0], tms, [t1]])
    # drop consecutive duplicate points (keep first/last)
    return poly, times


def _vertex_kind(creator):
    c = (creator or "").lower()
    if c in ("primary", ""):
        return "primary_start"
    if "decay" in c or "capture" in c or "inelastic" in c or "nucl" in c:
        return "interaction"
    return "production"


def build_scene(primitives, ev, max_tracks=2000, include_world=False):
    tracks = []
    vertices = []
    n = len(ev.trk.get("trk_id", []))
    for i in range(n):
        poly, times = _track_polyline(ev, i)
        if poly.shape[0] < 2:
            continue
        pdg = int(ev.trk["trk_pdg"][i])
        creator = _decode_str(ev.trk.get("trk_creatorProcess"), i)
        tracks.append(Track(
            track_id=int(ev.trk["trk_id"][i]),
            parent_id=int(ev.trk["trk_parentID"][i]),
            pdg=pdg,
            polyline=poly,
            times=times,
            color=particles.color_for(pdg),
            name=particles.name_for(pdg),
            creator_process=creator,
        ))
        vertices.append(Vertex(pos=poly[0], kind=_vertex_kind(creator), pdg=pdg))

    if ev.has_nu and "nu_vertexX" in ev.nu:
        vertices.append(Vertex(
            pos=np.array([ev.nu["nu_vertexX"], ev.nu["nu_vertexY"], ev.nu["nu_vertexZ"]]),
            kind="interaction", pdg=int(ev.scalars.get("primaryPDG", 0))))

    # cap tracks: keep primaries + longest secondaries
    if len(tracks) > max_tracks:
        prim = [t for t in tracks if t.parent_id == 0]
        sec = sorted([t for t in tracks if t.parent_id != 0],
                     key=lambda t: _length(t.polyline), reverse=True)
        tracks = prim + sec[: max(0, max_tracks - len(prim))]

    sc = Scene(primitives=primitives, tracks=tracks, vertices=vertices,
               event_id=int(ev.scalars.get("eventID", ev.index)),
               meta=_meta(ev, tracks))
    _fit(sc, include_world)
    return sc


def build_scenes(primitives, events, **kw):
    return [build_scene(primitives, ev, **kw) for ev in events]


def _fit(sc, include_world=False):
    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)
    bb = bounding_box(sc.primitives, include_world=include_world)
    if bb is not None:
        lo = np.minimum(lo, bb[0])
        hi = np.maximum(hi, bb[1])
    for t in sc.tracks:
        lo = np.minimum(lo, t.polyline.min(axis=0))
        hi = np.maximum(hi, t.polyline.max(axis=0))
    for v in sc.vertices:
        lo = np.minimum(lo, v.pos)
        hi = np.maximum(hi, v.pos)
    if not np.all(np.isfinite(lo)):
        lo, hi = np.full(3, -100.0), np.full(3, 100.0)
    sc.bbox_min, sc.bbox_max = lo, hi
    sc.center = 0.5 * (lo + hi)
    sc.radius = max(1.0, 0.5 * float(np.linalg.norm(hi - lo)) * 1.15)


def _meta(ev, tracks):
    from collections import Counter
    counts = Counter(t.name for t in tracks)
    m = {
        "primaryPDG": int(ev.scalars.get("primaryPDG", 0)),
        "primaryE": float(ev.scalars.get("primaryE", 0.0)),
        "totalEdep": float(ev.scalars.get("totalEdep", 0.0)),
        "nTracks": int(ev.scalars.get("nTracks", len(tracks))),
        "nSteps": int(ev.scalars.get("nSteps", 0)),
        "particle_counts": dict(counts),
    }
    if ev.has_nu:
        m["nu"] = {k: ev.nu[k] for k in ("nu_isCC", "nu_isNC", "nu_interactionProcess",
                                         "nu_Q2", "nu_W") if k in ev.nu}
    return m


def _length(poly):
    return float(np.sum(np.linalg.norm(np.diff(poly, axis=0), axis=1)))


def _decode_str(arr, i):
    if arr is None or i >= len(arr):
        return ""
    v = arr[i]
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return str(v)
