#!/usr/bin/env python3
"""In-container Achilles driver for GDMLTargetPractice.

Reads an `achilles_job.json` (written on the host by gdmltp's achilles backend),
renders an Achilles YAML run card from it, runs `achilles`, and converts the
NuHepMC output to the common `output.root` schema:

    render run card  ->  achilles run.yml  ->  achilles2root (achilles_convert)

The run-card template below targets the documented Achilles card layout
(Main/Process/Beams/Nucleus/Cascade sections). Exact key spellings are
release-sensitive -- this template is validated by the (non-gating) achilles CI
smoke against the pinned image, and a verbatim card can always be supplied via
achilles.run_card in the user config.

v1 scope (vertex-level): like the GENIE driver, a host-sampled beam file is
replayed per event (one achilles run per ray -- slow for large N); otherwise a
single run at the aggregate flux.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import yaml

from gdmltp.backends.genie import parse_energy_gev


def _mev(spec):
    return parse_energy_gev(spec) * 1000.0


def render_run_card(job, events, energy_mev, out_name="achilles_events.hepmc"):
    """Build the Achilles run-card dict for one generation run."""
    probe = int(job["probe"])
    if job.get("processes"):
        procs = [{"Leptons": [probe, [int(p) for p in fs]]} for fs in job["processes"]]
    elif abs(probe) in (12, 14, 16):
        cc = int(math.copysign(abs(probe) - 1, probe))
        procs = [{"Leptons": [probe, [cc]]}, {"Leptons": [probe, [probe]]}]  # CC + NC
    else:
        procs = [{"Leptons": [probe, [probe]]}]                               # e-scattering

    card = {
        "Main": {
            "NEvents": int(events),
            "Output": {"Format": "NuHepMC", "Name": out_name, "Zipped": False},
        },
        "Processes": procs,
        "Beams": [{"Beam": {"PID": probe,
                            "Beam Params": {"Type": "Monochromatic",
                                            "Energy": float(energy_mev)}}}],
        "Nucleus": {"Name": job["nucleus"]},
        "Cascade": {"Run": bool(job.get("cascade", True))},
    }
    if job.get("seed") is not None:
        card.setdefault("Initialize", {})["Seed"] = int(job["seed"])
    if job.get("nuclear_model"):
        card["NuclearModel"] = {"Model": job["nuclear_model"]}
    # raw overrides win last (deep-merge one level)
    for key, val in (job.get("options") or {}).items():
        if isinstance(val, dict) and isinstance(card.get(key), dict):
            card[key].update(val)
        else:
            card[key] = val
    return card


def _generate(job, workdir, card_path, events, energy_mev, out_name):
    if job.get("run_card"):
        card_file = workdir / job["run_card"]      # verbatim user card
    else:
        card = render_run_card(job, events, energy_mev, out_name)
        card_file = workdir / card_path
        card_file.write_text(yaml.safe_dump(card, sort_keys=False))
    print(f"[run_achilles] achilles {card_file.name}", flush=True)
    subprocess.run(["achilles", str(card_file)], cwd=workdir, check=True)
    # achilles may append .gz despite Zipped: false on some builds
    for cand in (workdir / out_name, workdir / (out_name + ".gz")):
        if cand.exists():
            return cand
    raise FileNotFoundError(f"achilles produced no {out_name}[.gz] in {workdir}")


def run(job_path):
    job = json.loads(Path(job_path).read_text())
    workdir = Path(job_path).resolve().parent
    out = job.get("output", "output.root")
    from gdmltp.backends import achilles_convert

    if job.get("beam_file"):
        from gdmltp.beam import read_beam_file
        entries = read_beam_file(str(workdir / job["beam_file"]))
        print(f"[run_achilles] per-event replay of {len(entries)} rays "
              f"({len(entries)} achilles runs; this can be slow) ...", flush=True)
        hepmc_files = []
        for i, (_name, _pos, mom) in enumerate(entries):
            e_mev = math.sqrt(sum(c * c for c in mom))
            j = dict(job)
            if job.get("seed") is not None:
                j["seed"] = int(job["seed"]) + i
            hepmc_files.append(str(_generate(j, workdir, f"_beam_{i}.yml", 1, e_mev,
                                             f"_beam_{i}.hepmc")))
        # concatenate parsed events by converting from a combined stream: the
        # converter takes one file, so merge the ASCII files (plain text) first.
        merged = workdir / "achilles_events.hepmc"
        with open(merged, "w") as outf:
            for hf in hepmc_files:
                outf.write(Path(hf).read_text())
        achilles_convert.convert(str(merged), str(workdir / out),
                                 beam=str(workdir / job["beam_file"]))
    else:
        flux = job.get("flux", {})
        if flux.get("mode", "mono") != "mono":
            print(f"[run_achilles] WARNING: energy mode {flux.get('mode')!r} is "
                  f"approximated by its nominal energy in v1.", file=sys.stderr)
        hepmc = _generate(job, workdir, "achilles_run.yml",
                          int(job["events"]), _mev(flux.get("value", "1 GeV")),
                          "achilles_events.hepmc")
        achilles_convert.convert(str(hepmc), str(workdir / out))
    print(f"[run_achilles] done -> {workdir / out}", flush=True)
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: run_achilles.py <achilles_job.json>", file=sys.stderr)
        return 2
    return run(argv[0])


if __name__ == "__main__":
    sys.exit(main())
