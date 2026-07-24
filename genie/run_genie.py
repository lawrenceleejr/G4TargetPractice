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


def spline_emax_gev(job, beam_energies_gev=None):
    """Upper energy the cross-section splines must cover: the flux endpoint
    from the job (written by the host backend), or the hardest beam-file ray,
    with a 100 GeV floor so the common few-GeV case shares one cached file."""
    emax = float(job.get("flux_emax_gev") or 0.0)
    if beam_energies_gev:
        emax = max(emax, max(beam_energies_gev))
    return max(100.0, math.ceil(emax))


def _xsec_args(job, workdir, emax_gev=None):
    """Cross-section splines for gevgen, in priority order: an explicit path in
    the job, the image's $GENIE_XSEC_FILE, else generate them ON DEMAND with
    gmkspl into the run directory (cached there, so the mounted volume makes
    reruns fast). The on-demand path is what lets a freshly built image run with
    no manual setup at all -- the first run on a new probe/target just takes
    longer while the splines compute. `emax_gev` (see spline_emax_gev) sets the
    spline reach and is part of the cache name, so a TeV run never silently
    reuses a 100 GeV file."""
    xsec = job.get("cross_sections", "auto")
    if xsec and xsec != "auto":
        return ["--cross-sections", xsec]
    if os.environ.get("GENIE_XSEC_FILE"):
        return ["--cross-sections", os.environ["GENIE_XSEC_FILE"]]

    probe = int(job["probe"])
    target = int(job["target"])
    tune = job.get("tune", "G18_10a_00_000")
    emax = int(emax_gev if emax_gev is not None else spline_emax_gev(job))
    out = Path(workdir) / f"gxspl_{abs(probe)}_{target}_{tune}_{emax}gev.xml"
    if not out.exists():
        print(f"[run_genie] no spline file found; generating with gmkspl for "
              f"probe {probe} on {target} (tune {tune}, up to {emax} GeV). "
              f"This is slow the first time; the result is cached in the run "
              f"directory.", flush=True)
        cmd = ["gmkspl", "-p", f"{probe},{-probe}", "-t", str(target),
               "-n", "100", "-e", str(emax), "--tune", tune, "-o", str(out)]
        print("[run_genie]", " ".join(cmd), flush=True)
        subprocess.run(cmd, cwd=workdir, check=True)
    return ["--cross-sections", str(out)]


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
    cmd += _xsec_args(job, workdir)

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
    energies = [math.sqrt(sum(c * c for c in mom)) / 1000.0   # |p|(MeV/c) -> GeV (nu massless)
                for _name, _pos, mom in entries]
    emax = spline_emax_gev(job, energies)
    print(f"[run_genie] per-event replay of {len(entries)} rays "
          f"({len(entries)} gevgen calls; this can be slow) ...", flush=True)
    for i, e_gev in enumerate(energies):
        ghep = workdir / f"_beam_{i}.ghep.root"
        gst = workdir / f"_beam_{i}.gst.root"
        cmd = ["gevgen", "-n", "1", "-p", str(job["probe"]), "-t", str(job["target"]),
               "--tune", job["tune"], "--event-generator-list", job["event_generator_list"],
               "-e", f"{e_gev:g}", "-o", str(ghep)] + _xsec_args(job, workdir, emax)
        if seed is not None:
            cmd += ["--seed", str(int(seed) + i)]
        subprocess.run(cmd, cwd=workdir, check=True)
        subprocess.run(["gntpc", "-i", str(ghep), "-f", "gst", "-o", str(gst)],
                       cwd=workdir, check=True)
        gst_files.append(str(gst))

    # The converter concatenates the per-ray gst files itself (no hadd needed).
    genie_convert.convert(gst_files, str(workdir / out),
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
