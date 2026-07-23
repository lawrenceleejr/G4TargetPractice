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
import os
import subprocess
import sys
from pathlib import Path

from gdmltp.backends.genie import flux_gevgen_args


def run(job_path):
    job = json.loads(Path(job_path).read_text())
    workdir = Path(job_path).resolve().parent
    events = int(job["events"])
    probe = int(job["probe"])
    target = int(job["target"])
    tune = job.get("tune", "G18_10a_00_000")
    xsec = job.get("cross_sections", "auto")
    genlist = job.get("event_generator_list", "Default")
    seed = job.get("seed")
    out = job.get("output", "output.root")
    vtx_units = job.get("length_units", "cm")

    ghep = str(workdir / "genie_events.ghep.root")
    gst = str(workdir / "genie_events.gst.root")

    cmd = ["gevgen", "-n", str(events), "-p", str(probe), "-t", str(target),
           "--tune", tune, "--event-generator-list", genlist,
           "-o", ghep]
    fargs, approx = flux_gevgen_args(job["flux"])
    if approx:
        print(f"[run_genie] WARNING: energy mode {job['flux'].get('mode')!r} is "
              f"approximated by its nominal energy in v1.", file=sys.stderr)
    cmd += fargs
    if seed is not None:
        cmd += ["--seed", str(int(seed))]
    if xsec and xsec != "auto":
        cmd += ["--cross-sections", xsec]
    elif os.environ.get("GENIE_XSEC_FILE"):
        cmd += ["--cross-sections", os.environ["GENIE_XSEC_FILE"]]

    print("[run_genie] generating:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=workdir, check=True)

    print("[run_genie] converting GHEP -> gst ...", flush=True)
    subprocess.run(["gntpc", "-i", ghep, "-f", "gst", "-o", gst],
                   cwd=workdir, check=True)

    print("[run_genie] converting gst -> output.root ...", flush=True)
    # Import rather than shell out so the exact converter version travels with gdmltp.
    from gdmltp.backends import genie_convert
    genie_convert.convert(gst, str(workdir / out), vtx_units=vtx_units)
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
