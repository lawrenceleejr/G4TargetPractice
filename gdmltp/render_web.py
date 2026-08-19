"""Self-contained WebGL event display (three.js). One HTML file.

By default three.js is pulled from a CDN via an importmap (works online). The
scene data is inlined as JSON, so the file needs no other local assets.
"""
import json
from importlib import resources
import numpy as np


def _mat16(t):
    """4x4 (numpy, row-major) -> column-major 16-list for THREE.Matrix4.set is
    row-major, but Matrix4.fromArray/elements is column-major; we emit
    column-major and use .fromArray in the viewer."""
    return [float(t[r, c]) for c in range(4) for r in range(4)]


def _scene_to_dict(sc, max_tracks=2000):
    geo = []
    meshes = []            # deduped real surfaces: [{v:[...], f:[...]}]
    mesh_index = {}        # id(Mesh) -> table index
    for p in sc.primitives:
        if p.is_world or p.transform is None:
            continue
        # full placement transform (rotation included), column-major for THREE
        d = {"type": p.type, "m": _mat16(p.transform)}
        pm = p.params or {}
        if p.type == "mesh" and p.mesh is not None:
            mid = id(p.mesh)
            if mid not in mesh_index:
                mesh_index[mid] = len(meshes)
                meshes.append({
                    "v": [round(float(x), 4) for x in p.mesh.vertices.flatten()],
                    "f": [int(i) for i in p.mesh.faces.flatten()],
                })
            d["mesh"] = mesh_index[mid]
        elif p.type in ("box", "bbox"):
            d.update(sx=float(pm.get("sx", 0)), sy=float(pm.get("sy", 0)), sz=float(pm.get("sz", 0)))
        elif p.type == "orb":
            d.update(r=float(pm.get("r", 0)))
        elif p.type == "tube":
            d.update(rmax=float(pm.get("rmax", 0)), z=float(pm.get("z", 0)))
        elif p.type == "trd":
            d.update(type="trd", x1=float(pm.get("x1", 0)), x2=float(pm.get("x2", 0)),
                     y1=float(pm.get("y1", 0)), y2=float(pm.get("y2", 0)), z=float(pm.get("z", 0)))
        geo.append(d)
    tracks = []
    for t in sc.tracks[:max_tracks]:
        tracks.append({"p": [round(float(v), 3) for v in t.polyline.flatten()],
                       "c": t.color, "n": t.name})
    return {
        "event_id": sc.event_id,
        "center": [float(v) for v in sc.center],
        "radius": float(sc.radius),
        "meshes": meshes,
        "geometry": geo,
        "tracks": tracks,
        "vertices": [[float(v.pos[0]), float(v.pos[1]), float(v.pos[2])] for v in sc.vertices],
        "meta": sc.meta,
    }


def render_html(scenes, out_path, max_events_embed=20, max_tracks=2000):
    from pathlib import Path
    if not isinstance(scenes, (list, tuple)):
        scenes = [scenes]
    scenes = scenes[:max_events_embed]
    data = [_scene_to_dict(s, max_tracks=max_tracks) for s in scenes]
    template = resources.files("gdmltp.assets").joinpath("viewer_template.html").read_text()
    html = template.replace("/*{{SCENE_JSON}}*/ []", json.dumps(data))
    out_path = Path(out_path)
    out_path.write_text(html)
    return out_path
