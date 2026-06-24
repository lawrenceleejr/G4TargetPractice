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


def _track_polyline(ev, i, step_index):
    tid = int(ev.trk["trk_id"][i])
    start = np.array([ev.trk["trk_startX"][i], ev.trk["trk_startY"][i], ev.trk["trk_startZ"][i]])
    end = np.array([ev.trk["trk_endX"][i], ev.trk["trk_endY"][i], ev.trk["trk_endZ"][i]])
    # contiguous, time-ordered step points for this track, looked up via the
    # prebuilt index (a single sort of step_trackID) rather than re-scanning the
    # whole step array for every track.
    if step_index is not None:
        order, sid_sorted = step_index["order"], step_index["sid_sorted"]
        lo = np.searchsorted(sid_sorted, tid, side="left")
        hi = np.searchsorted(sid_sorted, tid, side="right")
        sel = order[lo:hi]   # original (time-ordered) row indices for this track
        pts = np.column_stack([step_index["x"][sel], step_index["y"][sel], step_index["z"][sel]])
        tms = step_index["t"][sel]
    else:
        pts = np.empty((0, 3))
        tms = np.empty((0,))
    poly = np.vstack([start[None, :], pts, end[None, :]])
    t0 = tms[0] if len(tms) else 0.0
    t1 = tms[-1] if len(tms) else 0.0
    times = np.concatenate([[t0], tms, [t1]])
    # drop consecutive duplicate points (keep first/last)
    return poly, times


def _build_step_index(ev):
    """Group step rows by track id with ONE stable sort.

    The reveal/polyline builder needs, per track, that track's steps in time
    order. Doing `step_trackID == tid` per track is O(nTracks * nSteps) -- the
    reason a high-energy shower (1 TeV e-: ~1e5-1e6 tracks AND steps) hangs.
    A stable argsort lets each track grab its block via two searchsorted calls;
    stability keeps the per-track rows in their original (time) order.
    """
    sid = ev.step.get("step_trackID")
    if sid is None or not len(sid):
        return None
    sid = np.asarray(sid)
    order = np.argsort(sid, kind="stable")
    return {"order": order, "sid_sorted": sid[order],
            "x": np.asarray(ev.step["step_x"]), "y": np.asarray(ev.step["step_y"]),
            "z": np.asarray(ev.step["step_z"]), "t": np.asarray(ev.step["step_time"])}


def _select_track_rows(ev, n, max_tracks):
    """Choose which track rows to keep BEFORE building polylines.

    Keep every primary plus the longest secondaries, ranked by the stored
    trk_length branch (no geometry needed). Capping here -- not after building a
    polyline for all n tracks -- is what keeps a shower tractable.
    """
    if n <= max_tracks:
        return range(n)
    parent = np.asarray(ev.trk.get("trk_parentID", np.zeros(n)))
    length = np.asarray(ev.trk.get("trk_length", np.zeros(n)), dtype=float)
    prim = np.nonzero(parent == 0)[0]
    sec = np.nonzero(parent != 0)[0]
    sec = sec[np.argsort(length[sec])[::-1]]            # longest first
    budget = max(0, max_tracks - len(prim))
    return np.concatenate([prim, sec[:budget]]).tolist()


def _vertex_kind(creator):
    c = (creator or "").lower()
    if c in ("primary", ""):
        return "primary_start"
    if "decay" in c or "capture" in c or "inelastic" in c or "nucl" in c:
        return "interaction"
    return "production"


def build_scene(primitives, ev, max_tracks=2000, include_world=False, verbose=False):
    import time
    t_start = time.perf_counter()
    tracks = []
    vertices = []
    n = len(ev.trk.get("trk_id", []))
    nsteps = len(ev.step.get("step_trackID", []))
    if verbose:
        print(f"[g4tp]   event {int(ev.scalars.get('eventID', ev.index))}: "
              f"{n} tracks, {nsteps} steps in file", flush=True)
    # Pick the kept rows first, then index the steps once -- so cost scales with
    # the number of tracks we actually draw, not the (possibly enormous) total.
    keep = _select_track_rows(ev, n, max_tracks)
    step_index = _build_step_index(ev)
    if verbose:
        print(f"[g4tp]   capped to {len(keep)} track(s) (--max-tracks {max_tracks}); "
              f"indexed steps in {time.perf_counter() - t_start:.2f}s, building polylines...",
              flush=True)
    t_poly = time.perf_counter()
    for i in keep:
        poly, times = _track_polyline(ev, i, step_index)
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

    sc = Scene(primitives=primitives, tracks=tracks, vertices=vertices,
               event_id=int(ev.scalars.get("eventID", ev.index)),
               meta=_meta(ev, tracks))
    _fit(sc, include_world)
    if verbose:
        print(f"[g4tp]   built {len(tracks)} track(s), {len(vertices)} vertices "
              f"in {time.perf_counter() - t_start:.2f}s "
              f"(polylines {time.perf_counter() - t_poly:.2f}s)", flush=True)
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


def _decode_str(arr, i):
    if arr is None or i >= len(arr):
        return ""
    v = arr[i]
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return str(v)
