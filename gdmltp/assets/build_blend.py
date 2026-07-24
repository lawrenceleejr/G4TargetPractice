"""bpy script: build a .blend from a gdmltp scenes JSON. Run inside Blender:

    blender --background --python build_blend.py -- scenes.json out.blend

One Blender scene. Geometry shared in a "Geometry" collection. Each event gets
its own collection ("Event_00", ...) holding that event's tracks (per-particle
sub-collections) and vertices, so you can show an ensemble or a single event.
A shared timeline animates the time-ordered reveal of every track (respecting
each step's global time and the particle's speed), so showers grow in time.
"""
import bpy, bmesh, json, sys, math, time
from mathutils import Matrix, Vector


def argv_after_dd():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


class Progress:
    """Heartbeat progress for the long build loops. Blender's bundled Python has
    no tqdm and its stdout is piped (through Docker), so a redrawing bar won't
    render -- emit periodic count / % / rate / ETA lines instead (flushed), per
    the project's progress convention for non-TTY output."""

    def __init__(self, total, label, every=1.0):
        self.total = max(int(total), 0)
        self.label = label
        self.every = every
        self.t0 = time.time()
        self.last = 0.0
        self.n = 0
        if self.total:
            print(f"[gdmltp] {label}: 0/{self.total} ...", flush=True)

    def update(self, k=1):
        self.n += k
        now = time.time()
        if self.total and (now - self.last >= self.every or self.n >= self.total):
            self.last = now
            el = now - self.t0
            rate = self.n / el if el > 0 else 0.0
            eta = (self.total - self.n) / rate if rate > 0 else 0.0
            pct = 100.0 * self.n / self.total
            print(f"[gdmltp] {self.label}: {self.n}/{self.total} ({pct:.0f}%) "
                  f"{rate:.0f}/s  ETA {eta:.0f}s", flush=True)


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


def kelvin_to_rgb(kelvin):
    """Approximate blackbody RGB for a Kelvin value (fallback for Blender builds
    without native per-light temperature)."""
    t = kelvin / 100.0
    if t <= 66:
        r = 255.0
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
    if t <= 66:
        g = 99.4708025861 * math.log(t) - 161.1195681661 if t > 0 else 0.0
    else:
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10) - 305.0447927307
    c = lambda x: max(0.0, min(255.0, x)) / 255.0
    return (c(r), c(g), c(b))


def _set_temperature(light, kelvin):
    """Native Kelvin control on Blender 4.2+/5.x; RGB fallback on older builds."""
    if hasattr(light, "use_temperature"):
        light.use_temperature = True
        light.temperature = kelvin
    else:
        light.color = kelvin_to_rgb(kelvin)


def _aim(obj, target):
    d = Vector(target) - Vector(obj.location)
    if d.length > 0:
        obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


WARM_K = 2700.0   # color temperature of the environment + key lights (warm)


def add_lighting_environment(center_m, radius_m):
    """Always add a warm, soft lighting rig and a very large enclosing sphere so
    the scene is lit and never floats in a black void.

    - A huge inside-out emissive sphere (warm, 2700 K) is the visible backdrop.
    - A dim warm world gives ambient fill in ANY engine (an emissive mesh alone
      does not light other objects in EEVEE without light probes).
    - A few big soft 2700 K area lights give gentle directional shape.

    Everything is sized to the scene's bounding radius, so it looks right from
    millimetre (silicon tracker) to metre (MAIA) scale. Area-light power scales
    with distance^2 -> roughly scale-invariant irradiance."""
    R = max(radius_m, MM)
    cx, cy, cz = center_m
    warm = kelvin_to_rgb(WARM_K)
    coll = new_collection("Lighting")

    # --- enclosing environment sphere: very large, inside-out, warm emissive ---
    # A high-res UV sphere, shaded smooth so the backdrop reads as a seamless
    # dome rather than faceted panels.
    bm = bmesh.new()
    _uvsphere(bm, R * 14.0, Matrix.Translation((cx, cy, cz)), segs=96)
    bmesh.ops.reverse_faces(bm, faces=list(bm.faces))   # normals face inward
    me = bpy.data.meshes.new("Environment")
    bm.to_mesh(me)
    bm.free()
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))  # shade smooth
    em = bpy.data.materials.new("environment")
    em.use_nodes = True
    bsdf = em.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        # Black base so the area lights don't light up the sphere's diffuse
        # interior (that blew the whole backdrop out); it's a PURE emitter.
        bsdf.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        for k in ("Emission Color", "Emission"):
            if k in bsdf.inputs:
                bsdf.inputs[k].default_value = (*warm, 1.0)
                break
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 0.15   # soft warm backdrop
    env = bpy.data.objects.new("Environment", me)
    env.data.materials.append(em)
    coll.objects.link(env)

    # --- warm world ambient fill (lights the scene in EEVEE and Cycles) ---
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (*warm, 1.0)
        bg.inputs["Strength"].default_value = 0.05

    # --- a few big soft warm 2700 K area lights for shape ---
    specs = [("Key",  (2.5, -3.0, 3.0),  8.0, 1.0),
             ("Fill", (-3.0, -1.5, 2.0), 12.0, 0.45),
             ("Rim",  (0.0, 3.5, 3.5),   6.0, 0.7)]
    for name, (dx, dy, dz), sz, pw in specs:
        d = bpy.data.lights.new(name, "AREA")
        d.shape = "DISK"
        d.size = sz * R                 # large area = soft shadows
        _set_temperature(d, WARM_K)
        loc = (cx + dx * R, cy + dy * R, cz + dz * R)
        dist = math.dist(loc, (cx, cy, cz)) or R
        d.energy = pw * 150.0 * dist * dist   # ~scale-invariant irradiance
        o = bpy.data.objects.new(name, d)
        coll.objects.link(o)
        o.location = loc
        _aim(o, (cx, cy, cz))


MM = 0.001  # mm -> Blender meters

# Track-tube radius and vertex-marker size are fractions of the scene's bounding
# radius (computed in gdmltp/scene.py), so they look right at any geometry scale --
# millimetres (silicon tracker) or metres (calorimeter). Deliberately no absolute
# floor: a floor stops small scenes from scaling down (the old max(...,0.5mm) made
# 1mm-diameter tubes look fat inside the 1.5mm silicon stack).
TRACK_RADIUS_FRAC = 0.0004   # tube radius      = 0.04% of scene radius
VERTEX_EDGE_FRAC = 0.0016    # vertex cube edge = 0.16% of scene radius


GEO_SEG = 24   # segments for curved geometry primitives (smoothness vs speed)


def _uvsphere(bm, radius, matrix, segs=GEO_SEG):
    """Add a UV sphere to `bm`. bmesh.ops.create_uvsphere's radius kwarg was
    named `diameter` before ~3.0 and `radius` after -- try radius, fall back."""
    v = max(3, segs // 2)
    try:
        bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=v,
                                  radius=radius, matrix=matrix)
    except TypeError:
        bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=v,
                                  diameter=radius, matrix=matrix)


def add_geometry(coll, geometry, name="Geometry_solids"):
    """All detector solids merged into ONE mesh via bmesh -- no bpy.ops.

    bpy.ops.mesh.primitive_*_add runs a full scene/view-layer update on every
    call, so hundreds of GDML solids took seconds and left hundreds of separate
    objects in the outliner. bmesh.ops build each primitive as raw geometry (a
    couple of C calls) into one shared bmesh that becomes a single joined
    object -- far faster and a single backdrop you can hide/move as a unit."""
    bm = bmesh.new()
    prog = Progress(len(geometry), "geometry")
    for g in geometry:
        prog.update()
        t = g["type"]
        loc = Matrix.Translation((g["x"] * MM, g["y"] * MM, g["z"] * MM))
        if t in ("box", "bbox"):
            scale = Matrix.Diagonal((g.get("sx", 1) * MM, g.get("sy", 1) * MM,
                                     g.get("sz", 1) * MM, 1.0))
            bmesh.ops.create_cube(bm, size=1.0, matrix=loc @ scale)
        elif t == "orb":
            _uvsphere(bm, g.get("r", 1) * MM, loc)
        elif t == "tube":
            r = g.get("rmax", 1) * MM
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=GEO_SEG,
                                  radius1=r, radius2=r, depth=g.get("z", 1) * MM,
                                  matrix=loc)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat("geo", (0.4, 0.55, 0.7, 0.18)))
    obj = bpy.data.objects.new(name, me)
    coll.objects.link(obj)
    return obj


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


def add_event_curve(coll, tracks, bev, name, prog=None):
    """All of an event's tracks as ONE curve object -- one POLY spline per
    track, colored per-track via spline.material_index. This is both the fast
    path (no per-object/ops overhead: thousands of tracks build in one
    datablock) and a single object you can select/move/parent as a unit.

    Point coordinates are set in bulk with foreach_set (one C call per spline),
    not a per-point Python assignment -- the difference between seconds and
    minutes when tracks carry many step points. `prog`, if given, ticks once
    per track so a single big event still shows progress. Returns (obj, count)."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = bev
    slot = {}                      # particle name -> material slot index
    n_added = 0
    for tk in tracks:
        if prog is not None:
            prog.update()
        pts = tk["p"]
        n = len(pts) // 3
        if n < 2:
            continue
        sp = cu.splines.new("POLY")
        sp.points.add(n - 1)
        # POLY point.co is (x, y, z, w); flatten to 4*n and set in one call
        flat = [0.0] * (4 * n)
        for i in range(n):
            flat[4 * i] = pts[3 * i] * MM
            flat[4 * i + 1] = pts[3 * i + 1] * MM
            flat[4 * i + 2] = pts[3 * i + 2] * MM
            flat[4 * i + 3] = 1.0
        sp.points.foreach_set("co", flat)
        nm = tk["n"]
        if nm not in slot:
            cu.materials.append(mat(f"p_{nm}", hex_rgba(tk["c"]), emission=True))
            slot[nm] = len(cu.materials) - 1
        sp.material_index = slot[nm]
        n_added += 1
    obj = bpy.data.objects.new(name, cu)
    coll.objects.link(obj)
    return obj, n_added


def _keyframe_grow(curve, f0, f1):
    """Reveal a whole curve object (all its splines) from nothing to full over
    [f0, f1] by keyframing bevel_factor_end, so hitting Play draws the tracks
    out. All splines grow together (a single per-object property); for a
    per-track, physical-time-ordered reveal use --animate. Needs bevel_depth>0
    (set by the caller) so the drawn portion is a visible tube."""
    curve.bevel_factor_end = 0.0
    curve.keyframe_insert("bevel_factor_end", frame=f0)
    curve.bevel_factor_end = 1.0
    curve.keyframe_insert("bevel_factor_end", frame=f1)
    if curve.animation_data and curve.animation_data.action:
        for fc in curve.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"


# unit cube (verts + quad faces) for building many vertex markers into one mesh
_CUBE_V = [(-.5, -.5, -.5), (.5, -.5, -.5), (.5, .5, -.5), (-.5, .5, -.5),
           (-.5, -.5, .5), (.5, -.5, .5), (.5, .5, .5), (-.5, .5, .5)]
_CUBE_F = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
           (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def add_event_vertices(coll, vertices, size, name):
    """All of an event's vertex markers as ONE mesh object (a cube at each hit),
    built with from_pydata in a single call -- fast and renderable."""
    verts, faces = [], []
    for v in vertices:
        cx, cy, cz = v[0] * MM, v[1] * MM, v[2] * MM
        base = len(verts)
        verts += [(cx + x * size, cy + y * size, cz + z * size)
                  for (x, y, z) in _CUBE_V]
        faces += [tuple(base + i for i in f) for f in _CUBE_F]
    if not verts:
        return None
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.materials.append(mat("vtx", (1.0, 0.85, 0.1, 1.0), emission=True))
    obj = bpy.data.objects.new(name, me)
    coll.objects.link(obj)
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
    # args[6]: "anim" -> the per-track time-reveal animation (one object per
    # track, slower); default "static" -> one curve object per event (fast,
    # thousands of tracks, manipulable as a unit).
    animate = (len(args) > 6 and args[6].lower() == "anim")

    scenes = json.load(open(scenes_json))
    clear_scene()
    bpy.context.scene.render.fps = fps

    geo_coll = new_collection("Geometry")
    if scenes:
        add_geometry(geo_coll, scenes[0]["geometry"])

    radius_m = (scenes[0]["radius"] * MM) if scenes else MM
    center_m = tuple(v * MM for v in scenes[0]["center"]) if scenes else (0.0, 0.0, 0.0)
    bev = radius_m * TRACK_RADIUS_FRAC
    vtx_size = radius_m * VERTEX_EDGE_FRAC
    n_tracks = sum(len(s["tracks"]) for s in scenes)
    n_verts = sum(len(s["vertices"]) for s in scenes)

    # Always light the scene and wrap it in a large warm sphere (never a void).
    add_lighting_environment(center_m, radius_m)

    if animate:
        frame_of, max_frame, t0, span = _build_frame_mapper(scenes, fps, max_seconds, log_time)
        bpy.context.scene.frame_start = 1
        bpy.context.scene.frame_end = max_frame
        print(f"[gdmltp] animated timeline: {max_frame} frames ({max_seconds:g}s @ "
              f"{fps}fps), {'log' if log_time else 'linear'}-time over {span:.3g} ns.",
              flush=True)
        tprog = Progress(n_tracks, "tracks (animated)")
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
                tprog.update()
            # vertices as one joined mesh (fast), not one bpy.ops cube each
            add_event_vertices(vtx_coll, s["vertices"], vtx_size,
                               f"Event_{s['event_id']:02d}_vertices")
    else:
        # Fast, single-object-per-event build (default) -- and still animated:
        # each event's curve reveals over the timeline (bevel_factor_end 0->1)
        # so hitting Play grows the tracks out from their origins. One object
        # per event (thousands of tracks stay fast); --animate gives the richer
        # per-track, physical-time-ordered reveal (one object per track).
        max_frame = max(2, int(round(max_seconds * fps)))
        bpy.context.scene.frame_start = 1
        bpy.context.scene.frame_end = max_frame
        print(f"[gdmltp] building one object per event ({n_tracks} track(s), "
              f"{n_verts} vertex marker(s)); tracks reveal over {max_frame} "
              f"frames ({max_seconds:g}s @ {fps}fps) on Play (--animate for the "
              f"per-track time-ordered reveal).", flush=True)
        tprog = Progress(n_tracks, "tracks")     # per-track: a single big event still shows progress
        for s in scenes:
            ev = new_collection(f"Event_{s['event_id']:02d}")
            obj, _ = add_event_curve(ev, s["tracks"], bev,
                                     f"Event_{s['event_id']:02d}_tracks", prog=tprog)
            _keyframe_grow(obj.data, 1, max_frame)
            add_event_vertices(ev, s["vertices"], vtx_size,
                               f"Event_{s['event_id']:02d}_vertices")

    print(f"[gdmltp] saving {out_blend} ...", flush=True)
    bpy.ops.wm.save_as_mainfile(filepath=out_blend)
    print(f"[gdmltp] wrote {out_blend} with {len(scenes)} event(s)"
          f"{' (animated)' if animate else ''}", flush=True)


if __name__ == "__main__":
    main()
