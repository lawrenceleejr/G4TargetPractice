#!/usr/bin/env python3
"""In-container GENIE driver for GDMLTargetPractice.

Reads a `genie_job.json` (written on the host by gdmltp's genie backend) and runs
the generation pipeline, ending in an `output.root` in the common g4sim schema:

    gevgen  ->  gntpc -f gst  ->  genie2root (gdmltp.backends.genie_convert)

v1 scope (vertex-only): the interaction is generated on the target nucleus that
the GDML geometry selected (job["target"]), at a point vertex. Geometry-aware
vertex sampling in the full GDML volume, and handing final-state particles to
Geant4 for transport, are later phases (see the repo plan / README).

This script shells out to GENIE tools and is therefore validated by the (non-
gating) genie CI smoke test, not the pure-python unit suite.
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from gdmltp.backends.genie import flux_gevgen_args


def _xsec_args(job):
    xsec = job.get("cross_sections", "auto")
    if xsec and xsec != "auto":
        return ["--cross-sections", xsec]
    if os.environ.get("GENIE_XSEC_FILE"):
        return ["--cross-sections", os.environ["GENIE_XSEC_FILE"]]
    return []


def run(job_path):
    job = json.loads(Path(job_path).read_text())
    workdir = Path(job_path).resolve().parent
    if job.get("beam_file"):
        return _run_beam(job, workdir)

    events = int(job["events"])
    out = job.get("output", "output.root")
    vtx_units = job.get("length_units", "cm")
    ghep = str(workdir / "genie_events.ghep.root")
    gst = str(workdir / "genie_events.gst.root")

    cmd = ["gevgen", "-n", str(events), "-p", str(job["probe"]), "-t", str(job["target"]),
           "--tune", job["tune"], "--event-generator-list", job["event_generator_list"],
           "-o", ghep]
    fargs, approx = flux_gevgen_args(job["flux"])
    if approx:
        print(f"[run_genie] WARNING: energy mode {job['flux'].get('mode')!r} is "
              f"approximated by its nominal energy in v1.", file=sys.stderr)
    cmd += fargs
    if job.get("seed") is not None:
        cmd += ["--seed", str(int(job["seed"]))]
    cmd += _xsec_args(job)

    print("[run_genie] generating:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=workdir, check=True)
    print("[run_genie] converting GHEP -> gst ...", flush=True)
    subprocess.run(["gntpc", "-i", ghep, "-f", "gst", "-o", gst], cwd=workdir, check=True)
    print("[run_genie] converting gst -> output.root ...", flush=True)
    from gdmltp.backends import genie_convert
    genie_convert.convert(gst, str(workdir / out), vtx_units=vtx_units)
    print(f"[run_genie] done -> {workdir / out}", flush=True)
    return 0


def _run_beam(job, workdir):
    """Full per-event replay of a host-sampled beam file: one gevgen call per ray
    (point mode at the ray's energy), merged, then the converter places each
    vertex and orients the event along the ray. Faithful but O(N) gevgen calls;
    a single-pass gsimple flux driver is the future scale optimization."""
    from gdmltp.beam import read_beam_file
    from gdmltp.backends import genie_convert

    entries = read_beam_file(str(workdir / job["beam_file"]))
    out = job.get("output", "output.root")
    seed = job.get("seed")
    gst_files = []
    print(f"[run_genie] per-event replay of {len(entries)} rays "
          f"({len(entries)} gevgen calls; this can be slow) ...", flush=True)
    for i, (_name, _pos, mom) in enumerate(entries):
        e_gev = math.sqrt(sum(c * c for c in mom)) / 1000.0   # |p|(MeV/c) -> GeV (nu massless)
        ghep = workdir / f"_beam_{i}.ghep.root"
        gst = workdir / f"_beam_{i}.gst.root"
        cmd = ["gevgen", "-n", "1", "-p", str(job["probe"]), "-t", str(job["target"]),
               "--tune", job["tune"], "--event-generator-list", job["event_generator_list"],
               "-e", f"{e_gev:g}", "-o", str(ghep)] + _xsec_args(job)
        if seed is not None:
            cmd += ["--seed", str(int(seed) + i)]
        subprocess.run(cmd, cwd=workdir, check=True)
        subprocess.run(["gntpc", "-i", str(ghep), "-f", "gst", "-o", str(gst)],
                       cwd=workdir, check=True)
        gst_files.append(str(gst))

    merged = str(workdir / "genie_events.gst.root")
    subprocess.run(["hadd", "-f", merged] + gst_files, cwd=workdir, check=True)
    genie_convert.convert(merged, str(workdir / out),
                          vtx_units=job.get("length_units", "cm"),
                          beam=str(workdir / job["beam_file"]))
    print(f"[run_genie] done -> {workdir / out}", flush=True)
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: run_genie.py <genie_job.json>", file=sys.stderr)
        return 2
    return run(argv[0])


if __name__ == "__main__":
    sys.exit(main())
