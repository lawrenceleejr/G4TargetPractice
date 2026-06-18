"""Emit a scenes JSON and build a .blend via a Blender Docker image (or local blender).

Tracks carry per-point times so the bpy script can animate the time-ordered
reveal (shower evolution). Needs docker on the host, or --local-blender.
"""
import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path

DEFAULT_BLENDER_IMAGE = "linuxserver/blender:4.2.0"


def _scene_to_dict(sc, max_tracks=4000):
    geo = []
    for p in sc.primitives:
        if p.is_world or p.transform is None:
            continue
        c = p.transform[:3, 3]
        pm = p.params or {}
        d = {"type": p.type, "x": float(c[0]), "y": float(c[1]), "z": float(c[2]),
             "name": p.volume_name}
        if p.type in ("box", "bbox"):
            d.update(sx=float(pm.get("sx", 0)), sy=float(pm.get("sy", 0)), sz=float(pm.get("sz", 0)))
        elif p.type == "orb":
            d.update(r=float(pm.get("r", 0)))
        elif p.type == "tube":
            d.update(rmax=float(pm.get("rmax", 0)), z=float(pm.get("z", 0)))
        elif p.type == "trd":
            d.update(type="box", sx=float(max(pm.get("x1", 0), pm.get("x2", 0))),
                     sy=float(max(pm.get("y1", 0), pm.get("y2", 0))), sz=float(pm.get("z", 0)))
        geo.append(d)
    tracks = []
    for t in sc.tracks[:max_tracks]:
        tracks.append({"id": t.track_id, "n": t.name, "c": t.color,
                       "p": [round(float(v), 3) for v in t.polyline.flatten()],
                       "t": [round(float(v), 6) for v in t.times]})
    return {"event_id": sc.event_id, "center": [float(v) for v in sc.center],
            "radius": float(sc.radius), "geometry": geo, "tracks": tracks,
            "vertices": [[float(v.pos[0]), float(v.pos[1]), float(v.pos[2])] for v in sc.vertices]}


def render_blend(scenes, out_path, outdir=".", blender_image=DEFAULT_BLENDER_IMAGE,
                 local_blender=None, fps=30, time_scale=0.5, max_seconds=30.0):
    if not isinstance(scenes, (list, tuple)):
        scenes = [scenes]
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = Path(out_path)
    if not out_path.is_absolute():
        out_path = outdir / out_path

    scenes_json = outdir / "scene.json"
    scenes_json.write_text(json.dumps([_scene_to_dict(s) for s in scenes]))
    builder = outdir / "build_blend.py"
    builder.write_text(resources.files("g4tp.assets").joinpath("build_blend.py").read_text())

    args = ["build_blend.py", "--", scenes_json.name, out_path.name,
            str(fps), str(time_scale), str(max_seconds)]

    if local_blender or shutil.which("blender"):
        blender = local_blender or "blender"
        cmd = [blender, "--background", "--python", str(builder), "--",
               str(scenes_json), str(out_path), str(fps), str(time_scale), str(max_seconds)]
        _run(cmd)
        return out_path
    if shutil.which("docker"):
        cmd = ["docker", "run", "--rm", "-v", f"{outdir}:/work", "-w", "/work",
               blender_image, "blender", "--background", "--python", "/work/build_blend.py",
               "--", "/work/scene.json", f"/work/{out_path.name}",
               str(fps), str(time_scale), str(max_seconds)]
        _run(cmd)
        return out_path
    print("[g4tp] No 'blender' or 'docker' found. Wrote scene.json + build_blend.py to",
          outdir, "\n        Build it with:\n"
          f"        docker run --rm -v {outdir}:/work -w /work {blender_image} \\\n"
          f"          blender --background --python build_blend.py -- scene.json {out_path.name}")
    return None


def _run(cmd):
    print("[g4tp] $", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)
