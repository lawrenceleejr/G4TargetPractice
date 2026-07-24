"""gdmltp command-line interface: run / display / analyze / compare / info."""
import argparse
import sys
from pathlib import Path

from . import __version__

_EXAMPLES = {
    "run": """\
examples:
  gdmltp run --mac macros/protons_water_bragg.mac
  gdmltp run --gdml water_phantom_30cm.gdml --particle proton --energy "150 MeV" -n 500
  gdmltp run --gdml my.gdml --field "0 0 5 tesla" --display
  gdmltp run --config run.yaml                            # YAML frontend (geant4 or genie)
  gdmltp run --config run.yaml --energy "200 MeV"         # flag overrides one YAML field""",
    "display": """\
examples:
  gdmltp display output.root --gdml my_detector.gdml     # WebGL html + PNG stills
  gdmltp display output.root --events 0:10               # first ten events
  gdmltp display output.root --blend --blend-events 5    # animated Blender scene
  gdmltp display --gdml my_detector.gdml                 # geometry only, no events""",
    "analyze": """\
examples:
  gdmltp analyze output.root                             # summary.txt + plots
  gdmltp analyze output.root -o results --depth-axis x   # beam along x""",
    "compare": """\
examples:
  gdmltp compare du.root w.root --labels DU,W            # shower profile + containment + leakage
  gdmltp compare a.root b.root -o cmp --axis x""",
    "info": """\
examples:
  gdmltp info output.root                                # events, branches, nu block
  gdmltp info gdml/water_phantom_30cm.gdml               # solids + bounding box""",
    "validate": """\
examples:
  gdmltp validate output.root                            # schema + physics sanity checks
  gdmltp validate output.root --strict                   # warnings also fail (CI gating)""",
}

# Error types that mean "bad input", shown as one friendly line. Anything else
# is a gdmltp bug and gets its full traceback so it can be reported.
_USER_ERRORS = (FileNotFoundError, IsADirectoryError, NotADirectoryError,
                PermissionError, ValueError, OSError)


def _build_parser():
    """Build the CLI parser. Returns (parser, {subcommand: subparser}) so other
    code paths (e.g. `run --display`) can derive real display defaults instead
    of hand-copying them."""
    # --debug is accepted both before and after the subcommand. The subparser
    # copy uses SUPPRESS so it only writes the attribute when actually given
    # (otherwise its default would clobber a pre-subcommand --debug).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                        help="show full tracebacks instead of short error messages")

    p = argparse.ArgumentParser(
        prog="gdmltp",
        description="G4TargetPractice tooling: run sims, analyze output.root, "
                    "make event displays (no ROOT needed).",
        epilog="run 'gdmltp <command> --help' for command-specific examples")
    p.add_argument("--version", action="version", version=f"gdmltp {__version__}")
    p.add_argument("--debug", action="store_true",
                   help="show full tracebacks instead of short error messages")
    sub = p.add_subparsers(dest="cmd", required=True)
    parsers = {}

    def _sub(name, help_):
        sp = sub.add_parser(name, help=help_, epilog=_EXAMPLES.get(name),
                            formatter_class=argparse.RawDescriptionHelpFormatter,
                            parents=[common])
        parsers[name] = sp
        return sp

    # run
    r = _sub("run", "run a simulation (Docker or local g4sim)")
    r.add_argument("--config", help="YAML run config (common frontend for any backend); "
                                     "flags below override individual fields")
    r.add_argument("--generator", default="geant4",
                   choices=["geant4", "genie", "achilles"],
                   help="physics backend (default: geant4)")
    r.add_argument("--mac", help="existing macro; if omitted, one is generated from the flags below")
    r.add_argument("--gdml", help="geometry file (required if no --mac references one)")
    r.add_argument("--particle", default="e-")
    r.add_argument("--energy", default="1 GeV")
    r.add_argument("--position", default="0 0 -20 cm")
    r.add_argument("--direction", default="0 0 1")
    r.add_argument("-n", "--n", type=int, default=100)
    r.add_argument("--neutrino-mode", default="auto", choices=["auto", "on", "off"])
    r.add_argument("--field", default=None, help='e.g. "0 0 5 tesla" (auto-sets CELER_DISABLE=1)')
    r.add_argument("--image", default=None, help="container image (default: backend's own)")
    r.add_argument("--local", action="store_true", help="use a g4sim on PATH instead of Docker")
    r.add_argument("-o", "--outdir", default=".")
    r.add_argument("--display", action="store_true", help="open an event display after the run")
    r.add_argument("--dry-run", action="store_true")

    # display
    d = _sub("display", "event display: WebGL HTML, PNG stills, and/or Blender")
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
    d.add_argument("-o", "--outdir", default="gdmltp_display")
    d.add_argument("--prefix", default="event")

    # compare
    c = _sub("compare", "overlay shower stopping + leakage of two runs (e.g. DU vs W)")
    c.add_argument("root_a")
    c.add_argument("root_b")
    c.add_argument("--labels", default="A,B", help="comma-separated legend labels, e.g. DU,W")
    c.add_argument("--axis", default="z", choices=["x", "y", "z"], help="beam/depth axis")
    c.add_argument("-o", "--outdir", default="gdmltp_compare")

    # analyze
    a = _sub("analyze", "summary report + plots")
    a.add_argument("root", nargs="?", default="output.root")
    a.add_argument("-o", "--outdir", default="gdmltp_analysis")
    a.add_argument("--no-plots", dest="plots", action="store_false")
    a.add_argument("--depth-axis", default="z", choices=["x", "y", "z"])

    # info
    i = _sub("info", "inspect a .root or .gdml file")
    i.add_argument("file")

    # validate
    v = _sub("validate", "check an output.root for schema + physics sanity")
    v.add_argument("root", nargs="?", default="output.root")
    v.add_argument("--strict", action="store_true",
                   help="treat warnings as failures (exit 1)")
    v.add_argument("--events", type=int, default=20000,
                   help="max events to validate (default 20000)")

    return p, parsers


def _require_files(*paths):
    for p in paths:
        if p and not Path(p).exists():
            raise FileNotFoundError(f"no such file: {p}")


def main(argv=None):
    p, _ = _build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        p.print_help()
        return 2  # no command given is misuse (scripts must not read it as success)
    args = p.parse_args(argv)
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        print("\n[gdmltp] interrupted", file=sys.stderr)
        return 130
    except _USER_ERRORS as e:
        if getattr(args, "debug", False):
            raise
        print(f"gdmltp error: {e}\n(add --debug for the full traceback)", file=sys.stderr)
        return 1


def _dispatch(args):
    if args.cmd == "run":
        return _run(args)
    if args.cmd == "display":
        if args.root and not Path(args.root).exists():
            if args.gdml:
                # keep the documented preview workflow working: geometry-only
                # display before the simulation has produced output.root
                print(f"[gdmltp] note: {args.root} not found; rendering geometry only",
                      file=sys.stderr)
                args.root = None
            else:
                raise FileNotFoundError(f"no such file: {args.root}")
        _require_files(args.gdml)
        return _display(args)
    if args.cmd == "analyze":
        _require_files(args.root)
        from . import analyze
        analyze.summarize(args.root, outdir=args.outdir, make_plots=args.plots,
                          depth_axis=args.depth_axis)
        return 0
    if args.cmd == "compare":
        _require_files(args.root_a, args.root_b)
        from . import compare as cmp
        labels = tuple((args.labels.split(",") + ["A", "B"])[:2])
        cmp.compare(args.root_a, args.root_b, labels=labels, outdir=args.outdir, axis=args.axis)
        return 0
    if args.cmd == "info":
        _require_files(args.file)
        return _info(args)
    if args.cmd == "validate":
        _require_files(args.root)
        from . import validate as valmod
        report, code = valmod.validate(args.root, strict=args.strict,
                                       max_events=args.events)
        print(report)
        return code
    return 1


def _run(args):
    from . import run as runmod, config

    # Detect which flags were explicitly set (vs. their parser default) so that,
    # with --config, only overridden flags are overlaid on the YAML.
    _, parsers = _build_parser()
    rp = parsers["run"]
    defaults = {name: rp.get_default(name) for name in config._FLAG_FIELDS}
    cfg = config.load(args, defaults=defaults)

    # The geometry/macro come from flags or YAML; check the resolved paths exist.
    _require_files(cfg.gdml, cfg.mac)

    runmod.run_config(cfg, image=args.image, outdir=args.outdir,
                      local=args.local, dry_run=args.dry_run)

    if args.display and not args.dry_run:
        # Real display-parser defaults (not a hand-copied Namespace), with the
        # display output next to the run output.
        dargv = [str(Path(args.outdir) / cfg.run.output),
                 "-o", str(Path(args.outdir) / "gdmltp_display")]
        if cfg.gdml:
            dargv += ["--gdml", cfg.gdml]
        _display(parsers["display"].parse_args(dargv))
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

    import time
    scenes = []
    if args.root and Path(args.root).exists():
        from . import io
        n_total = io.num_events(args.root)
        if n_total == 0:
            print("[gdmltp] no events in", args.root)
        idxs = [k for k in _event_range(args, n_total) if 0 <= k < n_total]
        if idxs:
            # Read only the requested entries: a single 1 TeV shower event can be
            # hundreds of MB, so loading the whole file to show one event is wasteful.
            lo, hi = min(idxs), max(idxs) + 1
            print(f"[gdmltp] reading entr{'y' if hi - lo == 1 else 'ies'} {lo}:{hi} "
                  f"of {n_total} from {args.root} ...", flush=True)
            t0 = time.perf_counter()
            events = io.load_events(args.root, entry_start=lo, entry_stop=hi)
            print(f"[gdmltp] loaded {len(events)} event(s) in {time.perf_counter() - t0:.2f}s; "
                  f"building scene(s) ...", flush=True)
            for k in idxs:
                scenes.append(scenemod.build_scene(prims, events[k - lo], max_tracks=args.max_tracks,
                                                   include_world=args.world, verbose=True))
    else:
        # geometry-only
        from .scene import Scene
        sc = Scene(primitives=prims, event_id=0)
        scenemod._fit(sc, include_world=args.world)
        scenes = [sc]

    if not scenes:
        print("[gdmltp] nothing to display"); return 1

    if args.png:
        for sc in (scenes if args.events else scenes[:1]):
            out = render_png.render_png(sc, outdir / f"{args.prefix}{('' if len(scenes)==1 else '_'+str(sc.event_id))}",
                                        include_world=args.world)
            print("[gdmltp] PNG:", *[str(o) for o in out])
    if args.html:
        out = render_web.render_html(scenes, outdir / f"{args.prefix}.html",
                                     max_tracks=args.max_tracks)
        print("[gdmltp] HTML:", out)
    if args.blend:
        from . import render_blender
        sel = scenes[: args.blend_events]
        if len(scenes) > len(sel):
            print(f"[gdmltp] note: {len(scenes)} events selected but only {len(sel)} written to the "
                  f".blend (--blend-events {args.blend_events}). Raise --blend-events to include all.")
        out = render_blender.render_blend(sel, f"{args.prefix}.blend",
                                          outdir=str(outdir), blender_image=args.blender_image,
                                          fps=args.anim_fps, time_scale=args.time_scale,
                                          max_seconds=args.max_seconds, log_time=args.log_time)
        if out:
            print("[gdmltp] BLEND:", out)
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
        t = io.open_tree(f)                       # one open serves everything below
        brs = io.branch_names(t)
        n = int(t.num_entries)
        print(f"ROOT {f}: {n} event(s), {len(brs)} branches")
        print("  nu_* block:", "present" if any(b.startswith("nu_") for b in brs) else "absent")
        if n:
            e = io.load_events(f, entry_start=0, entry_stop=1)[0]
            print(f"  event0: nTracks={e.scalars.get('nTracks')} nSteps={e.scalars.get('nSteps')} "
                  f"primaryPDG={e.scalars.get('primaryPDG')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
