"""bpy script: build a .blend from a g4tp scenes JSON. Run inside Blender:

    blender --background --python build_blend.py -- scenes.json out.blend

One Blender scene. Geometry shared in a "Geometry" collection. Each event gets
its own collection ("Event_00", ...) holding that event's tracks (per-particle
sub-collections) and vertices, so you can show an ensemble or a single event.
A shared timeline animates the time-ordered reveal of every track (respecting
each step's global time and the particle's speed), so showers grow in time.
"""
import bpy, json, sys, math


def argv_after_dd():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


def clear_scene():
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def new_collection(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c


def mat(name, rgba, emission=False):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = rgba[3]
        if emission:
            try:
                bsdf.inputs["Emission Color"].default_value = rgba
                bsdf.inputs["Emission Strength"].default_value = 1.5
            except KeyError:
                pass
    if rgba[3] < 1.0:
        m.blend_method = "BLEND"
    return m


def hex_rgba(h, a=1.0):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


MM = 0.001  # mm -> Blender meters


def add_geometry(coll, geometry):
    gm = mat("geo", (0.4, 0.55, 0.7, 0.18))
    for i, g in enumerate(geometry):
        t = g["type"]
        x, y, z = g["x"] * MM, g["y"] * MM, g["z"] * MM
        if t in ("box", "bbox"):
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z))
            o = bpy.context.object
            o.scale = (g.get("sx", 1) * MM, g.get("sy", 1) * MM, g.get("sz", 1) * MM)
        elif t == "orb":
            bpy.ops.mesh.primitive_uv_sphere_add(radius=g.get("r", 1) * MM, location=(x, y, z))
            o = bpy.context.object
        elif t == "tube":
            bpy.ops.mesh.primitive_cylinder_add(radius=g.get("rmax", 1) * MM,
                                                depth=g.get("z", 1) * MM, location=(x, y, z))
            o = bpy.context.object
        else:
            continue
        o.name = f"geo_{g.get('name', i)}"
        o.data.materials.append(gm)
        _move_to(o, coll)


def add_track(coll, track, t0, scale, fps, max_frame):
    pts = track["p"]
    n = len(pts) // 3
    if n < 2:
        return None
    cu = bpy.data.curves.new(f"trk_{track['n']}_{track['id']}", "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(n - 1)
    coords = []
    for i in range(n):
        px, py, pz = pts[3 * i] * MM, pts[3 * i + 1] * MM, pts[3 * i + 2] * MM
        sp.points[i].co = (px, py, pz, 1.0)
        coords.append((px, py, pz))
    cu.bevel_depth = scale  # set by caller as a small radius
    obj = bpy.data.objects.new(cu.name, cu)
    m = mat(f"p_{track['n']}", hex_rgba(track["c"]), emission=True)
    obj.data.materials.append(m)
    _move_to(obj, coll)

    # time-driven reveal: keyframe bevel_factor_end vs cumulative length fraction
    times = track["t"]
    seglen = [0.0]
    for i in range(1, n):
        a = coords[i - 1]; b = coords[i]
        seglen.append(seglen[-1] + math.dist(a, b))
    total = seglen[-1] or 1.0
    cu.bevel_factor_end = 0.0
    for i in range(n):
        frame = int(round((times[i] - t0) * scale_time))
        frame = max(1, min(frame, max_frame))
        cu.bevel_factor_end = seglen[i] / total
        cu.keyframe_insert("bevel_factor_end", frame=frame)
    # linear interpolation
    if cu.animation_data and cu.animation_data.action:
        for fc in cu.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
    return obj


def _move_to(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)


# global set by main
scale_time = 1.0


def main():
    global scale_time
    args = argv_after_dd()
    scenes_json, out_blend = args[0], args[1]
    fps = int(args[2]) if len(args) > 2 else 30
    time_scale = float(args[3]) if len(args) > 3 else 0.5  # animation-seconds per ns
    max_seconds = float(args[4]) if len(args) > 4 else 30.0
    scale_time = time_scale * fps  # frames per ns

    scenes = json.load(open(scenes_json))
    clear_scene()
    bpy.context.scene.render.fps = fps

    geo_coll = new_collection("Geometry")
    if scenes:
        add_geometry(geo_coll, scenes[0]["geometry"])

    # global time origin and span across all events for a shared timeline
    all_t = []
    for s in scenes:
        for t in s["tracks"]:
            if t.get("t"):
                all_t += [t["t"][0], t["t"][-1]]
    t0 = min(all_t) if all_t else 0.0
    tmax = max(all_t) if all_t else 1.0
    max_frame = int(min(max_seconds, (tmax - t0) * time_scale) * fps) or 1
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = max_frame

    bev = 0.0
    # bevel radius ~ 0.4% of scene radius for a visible tube
    if scenes:
        bev = max(scenes[0]["radius"] * MM * 0.004, 0.0005)

    for s in scenes:
        ev = new_collection(f"Event_{s['event_id']:02d}")
        tracks_coll = new_collection("Tracks", ev)
        vtx_coll = new_collection("Vertices", ev)
        by_type = {}
        for t in s["tracks"]:
            sub = by_type.get(t["n"])
            if sub is None:
                sub = new_collection(t["n"], tracks_coll)
                by_type[t["n"]] = sub
            add_track(sub, t, t0, bev, fps, max_frame)
        for i, v in enumerate(s["vertices"]):
            bpy.ops.mesh.primitive_cube_add(size=bev * 4 if bev else 0.002,
                                            location=(v[0] * MM, v[1] * MM, v[2] * MM))
            o = bpy.context.object
            o.name = f"vtx_{s['event_id']:02d}_{i}"
            _move_to(o, vtx_coll)

    bpy.ops.wm.save_as_mainfile(filepath=out_blend)
    print(f"[g4tp] wrote {out_blend} with {len(scenes)} event(s), frames 1..{max_frame}")


if __name__ == "__main__":
    main()
