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

# Track-tube radius and vertex-marker size are fractions of the scene's bounding
# radius (computed in g4tp/scene.py), so they look right at any geometry scale --
# millimetres (silicon tracker) or metres (calorimeter). Deliberately no absolute
# floor: a floor stops small scenes from scaling down (the old max(...,0.5mm) made
# 1mm-diameter tubes look fat inside the 1.5mm silicon stack).
TRACK_RADIUS_FRAC = 0.0004   # tube radius      = 0.04% of scene radius
VERTEX_EDGE_FRAC = 0.0016    # vertex cube edge = 0.16% of scene radius


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


def add_track(coll, track, bev, frame_of):
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
    cu.bevel_depth = bev  # tube radius (set by caller)
    obj = bpy.data.objects.new(cu.name, cu)
    m = mat(f"p_{track['n']}", hex_rgba(track["c"]), emission=True)
    obj.data.materials.append(m)
    _move_to(obj, coll)

    # Time-driven reveal: keyframe bevel_factor_end (fraction of the track drawn)
    # against the timeline frame each step's global time maps to. The track is
    # invisible (bevel_factor_end=0) before its first point's frame, then grows.
    times = track["t"]
    seglen = [0.0]
    for i in range(1, n):
        a = coords[i - 1]; b = coords[i]
        seglen.append(seglen[-1] + math.dist(a, b))
    total = seglen[-1] or 1.0
    cu.bevel_factor_end = 0.0
    # Points that map to the same frame (prompt tracks) just overwrite that frame's
    # keyframe, so the last (largest) drawn fraction wins -- the reveal stays monotonic.
    for i in range(n):
        cu.bevel_factor_end = seglen[i] / total
        cu.keyframe_insert("bevel_factor_end", frame=frame_of(times[i]))
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


def _build_frame_mapper(scenes, fps, max_seconds, log_time):
    """Build time->frame mapping for the reveal animation.

    The animation has a FIXED length (max_seconds), independent of the event's
    physical time span, so it never collapses to a single frame. Time is mapped
    logarithmically by default: each decade of (t - t0) gets a comparable share
    of frames, so the prompt/early behavior is spread across many frames while
    the long-time tail is compressed -- instead of one slow track stretching the
    whole timeline and the interesting start happening within frame 1.
    --linear-time forces a plain real-time ramp instead.
    """
    all_times = []
    for s in scenes:
        for t in s["tracks"]:
            if t.get("t"):
                all_times += list(t["t"])
    t0 = min(all_times) if all_times else 0.0
    tmax = max(all_times) if all_times else 1.0
    span = (tmax - t0) or 1.0
    max_frame = max(2, int(round(max_seconds * fps)))

    # Characteristic early time tau ~ 5th percentile of positive offsets, so the
    # earliest real activity is resolved (not swamped by one slow outlier track).
    offs = sorted(o for o in (x - t0 for x in all_times) if o > 0)
    if offs:
        tau = max(offs[min(len(offs) - 1, int(0.05 * len(offs)))], span * 1e-6)
    else:
        tau = span
    log_den = math.log1p(span / tau)

    def frame_of(t):
        o = t - t0
        if o <= 0.0:
            u = 0.0
        elif log_time and log_den > 0.0:
            u = math.log1p(o / tau) / log_den
        else:
            u = o / span
        u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
        return 1 + int(round(u * (max_frame - 1)))

    return frame_of, max_frame, t0, span


def main():
    args = argv_after_dd()
    scenes_json, out_blend = args[0], args[1]
    fps = int(args[2]) if len(args) > 2 else 30
    # args[3] (legacy time_scale) is ignored: the timeline is now normalized to
    # max_seconds rather than scaled from real time.
    max_seconds = float(args[4]) if len(args) > 4 else 12.0
    log_time = (args[5].lower() != "linear") if len(args) > 5 else True

    scenes = json.load(open(scenes_json))
    clear_scene()
    bpy.context.scene.render.fps = fps

    geo_coll = new_collection("Geometry")
    if scenes:
        add_geometry(geo_coll, scenes[0]["geometry"])

    frame_of, max_frame, t0, span = _build_frame_mapper(scenes, fps, max_seconds, log_time)
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = max_frame
    print(f"[g4tp] timeline: {max_frame} frames ({max_seconds:g}s @ {fps}fps), "
          f"{'log' if log_time else 'linear'}-time over {span:.3g} ns "
          f"(t0={t0:.3g} ns); frame 1 is empty, early behavior emphasized.")

    # Track width and vertex size scale with the scene's bounding radius (no
    # absolute floor), so both shrink/grow with the geometry.
    radius_m = (scenes[0]["radius"] * MM) if scenes else MM
    bev = radius_m * TRACK_RADIUS_FRAC
    vtx_size = radius_m * VERTEX_EDGE_FRAC

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
            add_track(sub, t, bev, frame_of)
        for i, v in enumerate(s["vertices"]):
            bpy.ops.mesh.primitive_cube_add(size=vtx_size,
                                            location=(v[0] * MM, v[1] * MM, v[2] * MM))
            o = bpy.context.object
            o.name = f"vtx_{s['event_id']:02d}_{i}"
            _move_to(o, vtx_coll)

    bpy.ops.wm.save_as_mainfile(filepath=out_blend)
    print(f"[g4tp] wrote {out_blend} with {len(scenes)} event(s), frames 1..{max_frame}")


if __name__ == "__main__":
    main()
