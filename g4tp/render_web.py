"""Self-contained WebGL event display (three.js). One HTML file.

By default three.js is pulled from a CDN via an importmap (works online). The
scene data is inlined as JSON, so the file needs no other local assets.
"""
import json
from importlib import resources
import numpy as np


def _scene_to_dict(sc, max_tracks=2000):
    geo = []
    for p in sc.primitives:
        if p.is_world or p.transform is None:
            continue
        c = p.transform[:3, 3]
        d = {"type": p.type, "x": float(c[0]), "y": float(c[1]), "z": float(c[2])}
        pm = p.params or {}
        if p.type in ("box", "bbox"):
            d.update(sx=float(pm.get("sx", 0)), sy=float(pm.get("sy", 0)), sz=float(pm.get("sz", 0)))
        elif p.type == "orb":
            d.update(r=float(pm.get("r", 0)))
        elif p.type == "tube":
            d.update(rmax=float(pm.get("rmax", 0)), z=float(pm.get("z", 0)))
        elif p.type == "trd":
            d = {"type": "box", "x": float(c[0]), "y": float(c[1]), "z": float(c[2]),
                 "sx": float(max(pm.get("x1", 0), pm.get("x2", 0))),
                 "sy": float(max(pm.get("y1", 0), pm.get("y2", 0))), "sz": float(pm.get("z", 0))}
        geo.append(d)
    tracks = []
    for t in sc.tracks[:max_tracks]:
        tracks.append({"p": [round(float(v), 3) for v in t.polyline.flatten()],
                       "c": t.color, "n": t.name})
    return {
        "event_id": sc.event_id,
        "center": [float(v) for v in sc.center],
        "radius": float(sc.radius),
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
    template = resources.files("g4tp.assets").joinpath("viewer_template.html").read_text()
    html = template.replace("/*{{SCENE_JSON}}*/ []", json.dumps(data))
    out_path = Path(out_path)
    out_path.write_text(html)
    return out_path
