#!/usr/bin/env python3
"""In-container Pythia 8 driver for GDMLTargetPractice.

Reads a `pythia_job.json` (written on the host by gdmltp's pythia backend),
renders a Pythia command ('.cmnd') file from it, runs the generator, and
converts the HepMC3 output to the common `output.root` schema:

    render .cmnd  ->  pythia_gen (Pythia8 -> HepMC3)  ->  output.root

`pythia_gen` is the tiny C++ main in this directory (pythia/pythia_gen.cc),
compiled into the image: it reads the card, generates `Main:numberOfEvents`
events and writes HepMC3 ASCII. The HepMC3 -> schema step reuses the shared
converter (backends/achilles_convert), which is a generic HepMC3 reader; the
Pythia events are labelled "Pythia8" so the provenance is visible in
nu_interactionProcess / trk_creatorProcess.

Fixed-target kinematics: the beam (job["probe"]) is shot at a nucleon
(job["nucleon"]) AT REST, via Pythia's `Beams:frameType = 2` with the target
energy set to its mass. Pythia is a free-nucleon generator -- no nuclear medium,
Fermi motion or cascade (use the genie/achilles backends for those).

Like the other vertex-level drivers, a host-sampled beam file is replayed per
event (one Pythia run per ray); otherwise a single run at the nominal energy.
Pythia's own initialization dominates a small run, so per-event replay is slow
for large N -- the beam replay reuses one initialization per distinct energy
where it can (see _run_group).

This script shells out to Pythia and is therefore validated by the (non-gating)
pythia CI smoke test, not the pure-python unit suite; the card rendering and the
job plumbing ARE unit-tested (tests/test_pythia.py).
"""
import json
import math
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

from gdmltp.backends.genie import parse_energy_gev
from gdmltp.backends.pythia import preset_settings
from gdmltp.masses import mass_mev

GEN_BIN = "pythia_gen"
HEPMC_OUT = "pythia_events.hepmc"


def _gev(spec):
    return parse_energy_gev(spec)


def render_cmnd(job, events, energy_gev, out_name=HEPMC_OUT, seed=None):
    """Build the Pythia command-file text for one generation run.

    Order matters only in that raw `settings` come LAST, so a user can override
    anything a preset set. Energies are GeV (Pythia's unit)."""
    probe = int(job["probe"])
    nucleon = int(job["nucleon"])
    m_target = mass_mev(nucleon) / 1000.0          # MeV -> GeV, target at rest

    lines = [
        f"! gdmltp-generated Pythia 8 card ({job.get('process', 'dis')} preset)",
        f"Main:numberOfEvents = {int(events)}",
        "Main:timesAllowErrors = 100",
        # fixed target: back-to-back frame with the target's energy = its mass,
        # i.e. zero momentum -> a stationary nucleon in the lab
        "Beams:frameType = 2",
        f"Beams:idA = {probe}",
        f"Beams:idB = {nucleon}",
        f"Beams:eA = {float(energy_gev):.10g}",
        f"Beams:eB = {m_target:.10g}",
    ]
    lines += preset_settings(job.get("process", "dis"), probe,
                            pt_min=job.get("pt_min"), q2_min=job.get("q2_min"))
    if seed is not None:
        lines += ["Random:setSeed = on", f"Random:seed = {int(seed) % 900000000}"]
    # The HepMC output path is passed to pythia_gen on the command line, NOT via
    # a card setting (HEPMCoutput:file is a mainNN-example convention that is not
    # a declared setting in every release).
    lines += list(job.get("settings") or [])
    return "\n".join(lines) + "\n"


def _generate(job, workdir, cmnd_name, events, energy_gev, out_name, seed=None):
    """Run one Pythia job; returns the HepMC3 file it wrote."""
    if job.get("cmnd"):
        card_file = workdir / job["cmnd"]          # verbatim user card
    else:
        card_file = workdir / cmnd_name
        card_file.write_text(render_cmnd(job, events, energy_gev, out_name, seed))
    print(f"[run_pythia] {GEN_BIN} {card_file.name} "
          f"({events} event(s) @ {energy_gev:g} GeV)", flush=True)
    subprocess.run([GEN_BIN, str(card_file), str(workdir / out_name)],
                   cwd=workdir, check=True)
    produced = workdir / out_name
    if not produced.exists():
        raise FileNotFoundError(f"{GEN_BIN} produced no {out_name} in {workdir}")
    return produced


def _energy_groups(entries, decimals=3):
    """Group beam rays by (rounded) energy so Pythia initializes once per
    distinct energy instead of once per ray. Returns
    OrderedDict[energy_gev] = [ray indices] preserving first-appearance order."""
    groups = OrderedDict()
    for i, (_name, _pos, mom) in enumerate(entries):
        e_gev = math.sqrt(sum(c * c for c in mom)) / 1000.0
        key = round(e_gev, decimals)
        groups.setdefault(key, []).append(i)
    return groups


def _run_beam(job, workdir, out):
    """Per-event replay of a host-sampled beam file. Rays are grouped by energy
    so one Pythia initialization serves every ray at that energy; the converter
    then places each event on its own ray (vertex + rotation)."""
    from gdmltp.beam import read_beam_file
    from gdmltp.backends import achilles_convert

    entries = read_beam_file(str(workdir / job["beam_file"]))
    groups = _energy_groups(entries)
    print(f"[run_pythia] per-event replay of {len(entries)} rays in "
          f"{len(groups)} energy group(s) ...", flush=True)

    # Generate per group, then stitch the per-event records back into ray order
    # so event i corresponds to beam ray i (what the converter's beam replay
    # assumes).
    seed = job.get("seed")
    per_index = {}
    for g, (e_gev, idxs) in enumerate(groups.items()):
        hepmc = _generate(job, workdir, f"_beam_{g}.cmnd", len(idxs), e_gev,
                          f"_beam_{g}.hepmc",
                          seed=None if seed is None else int(seed) + g)
        blocks = _split_events(hepmc.read_text())
        if len(blocks) < len(idxs):
            raise RuntimeError(
                f"pythia produced {len(blocks)} events for group {g} but "
                f"{len(idxs)} rays were requested")
        for k, ray in enumerate(idxs):
            per_index[ray] = blocks[k]

    merged = workdir / HEPMC_OUT
    ordered = [per_index[i] for i in range(len(entries)) if i in per_index]
    merged.write_text(_join_events(ordered))
    achilles_convert.convert(str(merged), str(workdir / out),
                             beam=str(workdir / job["beam_file"]),
                             process_label="Pythia8",
                             target_pdg=int(job["nucleon"]))


def _split_events(text):
    """Split a HepMC3 ASCII stream into per-event blocks (each starting at an
    'E ' line), keeping the leading header with the first block so every block
    stays a valid standalone stream when re-joined."""
    lines = text.splitlines(keepends=True)
    header, blocks, cur = [], [], None
    for ln in lines:
        if ln.startswith("E "):
            if cur is not None:
                blocks.append("".join(cur))
            cur = [ln]
        elif cur is None:
            header.append(ln)                      # HepMC::Version / ::Asciiv3 / U
        else:
            if ln.startswith("HepMC::Asciiv3-END"):
                continue                            # re-emitted by _join_events
            cur.append(ln)
    if cur is not None:
        blocks.append("".join(cur))
    _split_events.header = "".join(header)
    return blocks


def _join_events(blocks):
    """Reassemble event blocks into one HepMC3 ASCII stream."""
    header = getattr(_split_events, "header", "")
    if not header:
        header = ("HepMC::Version 3.02.05\nHepMC::Asciiv3-START_EVENT_LISTING\n")
    body = "".join(blocks)
    return header + body + "HepMC::Asciiv3-END_EVENT_LISTING\n"


def run(job_path):
    job = json.loads(Path(job_path).read_text())
    workdir = Path(job_path).resolve().parent
    out = job.get("output", "output.root")

    if job.get("beam_file"):
        _run_beam(job, workdir, out)
        print(f"[run_pythia] done -> {workdir / out}", flush=True)
        return 0

    from gdmltp.backends import achilles_convert
    flux = job.get("flux", {})
    mode = flux.get("mode", "mono")
    if mode != "mono":
        # Pythia's beam energy is fixed per run; a spread flux without phase-space
        # painting is approximated by its nominal energy (same v1 caveat the
        # other drivers carry).
        print(f"[run_pythia] WARNING: energy mode {mode!r} is approximated by "
              f"its nominal energy; use beam distributions (a beam file) for a "
              f"true spectrum.", file=sys.stderr)
    hepmc = _generate(job, workdir, "pythia_run.cmnd", int(job["events"]),
                      _gev(flux.get("value", "1 GeV")), HEPMC_OUT,
                      seed=job.get("seed"))
    achilles_convert.convert(str(hepmc), str(workdir / out),
                             process_label="Pythia8",
                             target_pdg=int(job["nucleon"]))
    print(f"[run_pythia] done -> {workdir / out}", flush=True)
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: run_pythia.py <pythia_job.json>", file=sys.stderr)
        return 2
    return run(argv[0])


if __name__ == "__main__":
    sys.exit(main())
