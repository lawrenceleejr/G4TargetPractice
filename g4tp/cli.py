"""g4tp command-line interface: run / display / analyze / info."""
import argparse
import sys
from pathlib import Path


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="g4tp",
        description="G4TargetPractice tooling: run sims, analyze output.root, make event displays (no ROOT needed).")
    sub = p.add_subparsers(dest="cmd", required=True)

    # run
    r = sub.add_parser("run", help="run a simulation (Docker or local g4sim)")
    r.add_argument("--mac", help="existing macro; if omitted, one is generated from the flags below")
    r.add_argument("--gdml", help="geometry file (required if no --mac references one)")
    r.add_argument("--particle", default="e-")
    r.add_argument("--energy", default="1 GeV")
    r.add_argument("--position", default="0 0 -20 cm")
    r.add_argument("--direction", default="0 0 1")
    r.add_argument("-n", "--n", type=int, default=100)
    r.add_argument("--neutrino-mode", default="auto", choices=["auto", "on", "off"])
    r.add_argument("--field", default=None, help='e.g. "0 0 5 tesla" (auto-sets CELER_DISABLE=1)')
    r.add_argument("--image", default="ghcr.io/lawrenceleejr/g4targetpractice:main")
    r.add_argument("--local", action="store_true", help="use a g4sim on PATH instead of Docker")
    r.add_argument("-o", "--outdir", default=".")
    r.add_argument("--display", action="store_true", help="open an event display after the run")
    r.add_argument("--dry-run", action="store_true")

    # display
    d = sub.add_parser("display", help="event display: WebGL HTML, PNG stills, and/or Blender")
    d.add_argument("root", nargs="?", help="output.root (optional; geometry-only allowed)")
    d.add_argument("--gdml", help="overlay this geometry")
    d.add_argument("--event", type=int, default=0)
    d.add_argument("--events", help="range A:B (embedded in HTML / first events in Blender)")
    d.add_argument("--html", dest="html", action="store_true")
    d.add_argument("--no-html", dest="html", action="store_false")
    d.add_argument("--png", dest="png", action="store_true")
    d.add_argument("--no-png", dest="png", action="store_false")
    d.add_argument("--blend", action="store_true")
    d.add_argument("--no-blend", dest="blend", action="store_false")
    d.set_defaults(html=True, png=True, blend=False)
    d.add_argument("--blender-image", default="linuxserver/blender:4.2.0")
    d.add_argument("--blend-events", type=int, default=10)
    d.add_argument("--time-scale", type=float, default=0.5,
                   help="(deprecated) timeline is now normalized to --max-seconds")
    d.add_argument("--anim-fps", type=int, default=30)
    d.add_argument("--max-seconds", type=float, default=12.0,
                   help="length of the reveal animation in seconds (fixed, not time-scaled)")
    d.add_argument("--linear-time", dest="log_time", action="store_false",
                   help="map step time to frames linearly (default: log, emphasizes early behavior)")
    d.set_defaults(log_time=True)
    d.add_argument("--max-tracks", type=int, default=2000)
    d.add_argument("--no-world", dest="world", action="store_false")
    d.set_defaults(world=False)
    d.add_argument("--world", dest="world", action="store_true", help="include world volume (wireframe)")
    d.add_argument("-o", "--outdir", default="g4tp_display")
    d.add_argument("--prefix", default="event")

    # analyze
    a = sub.add_parser("analyze", help="summary report + plots")
    a.add_argument("root", nargs="?", default="output.root")
    a.add_argument("-o", "--outdir", default="g4tp_analysis")
    a.add_argument("--no-plots", dest="plots", action="store_false")
    a.add_argument("--depth-axis", default="z", choices=["x", "y", "z"])

    # info
    i = sub.add_parser("info", help="inspect a .root or .gdml file")
    i.add_argument("file")

    args = p.parse_args(argv)
    if args.cmd == "run":
        return _run(args)
    if args.cmd == "display":
        return _display(args)
    if args.cmd == "analyze":
        from . import analyze
        analyze.summarize(args.root, outdir=args.outdir, make_plots=args.plots,
                          depth_axis=args.depth_axis)
        return 0
    if args.cmd == "info":
        return _info(args)
    return 1


def _run(args):
    from . import run as runmod
    runmod.run(mac=args.mac, gdml=args.gdml, particle=args.particle, energy=args.energy,
               position=args.position, direction=args.direction, n=args.n,
               nmode=args.neutrino_mode, field=args.field, image=args.image,
               outdir=args.outdir, local=args.local, dry_run=args.dry_run)
    if args.display and not args.dry_run:
        ns = argparse.Namespace(root=str(Path(args.outdir) / "output.root"), gdml=args.gdml,
                                event=0, events=None, html=True, png=True, blend=False,
                                blender_image="linuxserver/blender:4.2.0", blend_events=10,
                                time_scale=0.5, anim_fps=30, max_seconds=30.0, max_tracks=2000,
                                world=False, outdir="g4tp_display", prefix="event")
        _display(ns)
    return 0


def _event_range(args, n_events):
    if args.events:
        a, b = args.events.split(":")
        return range(int(a or 0), int(b or n_events))
    return range(args.event, args.event + 1)


def _display(args):
    from . import geometry, scene as scenemod, render_png, render_web
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    prims = geometry.parse_gdml(args.gdml, include_world=args.world) if args.gdml else []

    scenes = []
    if args.root and Path(args.root).exists():
        from . import io
        events = io.load_events(args.root)
        if not events:
            print("[g4tp] no events in", args.root)
        idxs = list(_event_range(args, len(events)))
        for k in idxs:
            if 0 <= k < len(events):
                scenes.append(scenemod.build_scene(prims, events[k], max_tracks=args.max_tracks,
                                                   include_world=args.world))
    else:
        # geometry-only
        from .scene import Scene
        sc = Scene(primitives=prims, event_id=0)
        scenemod._fit(sc, include_world=args.world)
        scenes = [sc]

    if not scenes:
        print("[g4tp] nothing to display"); return 1

    if args.png:
        for sc in scenes[: max(1, 1 if not args.events else len(scenes))] if not args.events else scenes:
            out = render_png.render_png(sc, outdir / f"{args.prefix}{('' if len(scenes)==1 else '_'+str(sc.event_id))}",
                                        include_world=args.world)
            print("[g4tp] PNG:", *[str(o) for o in out])
    if args.html:
        out = render_web.render_html(scenes, outdir / f"{args.prefix}.html",
                                     max_tracks=args.max_tracks)
        print("[g4tp] HTML:", out)
    if args.blend:
        from . import render_blender
        sel = scenes[: args.blend_events]
        if len(scenes) > len(sel):
            print(f"[g4tp] note: {len(scenes)} events selected but only {len(sel)} written to the "
                  f".blend (--blend-events {args.blend_events}). Raise --blend-events to include all.")
        out = render_blender.render_blend(sel, f"{args.prefix}.blend",
                                          outdir=str(outdir), blender_image=args.blender_image,
                                          fps=args.anim_fps, time_scale=args.time_scale,
                                          max_seconds=args.max_seconds, log_time=args.log_time)
        if out:
            print("[g4tp] BLEND:", out)
    return 0


def _info(args):
    f = args.file
    if f.endswith(".gdml"):
        from . import geometry
        prims = geometry.parse_gdml(f, include_world=True)
        bb = geometry.bounding_box(prims, include_world=True)
        print(f"GDML {f}: {len(prims)} placed primitive(s)")
        from collections import Counter
        print("  solid types:", dict(Counter(p.type for p in prims)))
        if bb is not None:
            print(f"  bbox [mm]: min {bb[0]} max {bb[1]}")
    else:
        from . import io
        brs = io.available_branches(f)
        events = io.load_events(f)
        print(f"ROOT {f}: {len(events)} event(s), {len(brs)} branches")
        print("  nu_* block:", "present" if any(b.startswith("nu_") for b in brs) else "absent")
        if events:
            e = events[0]
            print(f"  event0: nTracks={e.scalars.get('nTracks')} nSteps={e.scalars.get('nSteps')} "
                  f"primaryPDG={e.scalars.get('primaryPDG')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
