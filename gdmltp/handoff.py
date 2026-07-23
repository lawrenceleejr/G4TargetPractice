"""Generator -> Geant4 transport hand-off (the DUNE-style two-stage pattern).

GENIE and Achilles generate the interaction and its nuclear exit state but do
not transport anything through the detector. This module bridges the two:

  1. `write_event_file`  -- turn a vertex-level `output.root` (from
     genie_convert / achilles_convert, which record every final-state
     particle's momentum in trk_px/py/pz) into a g4sim hand-off event file:
         E <nParticles> <vx> <vy> <vz>       [mm]
         <pdg> <px> <py> <pz>                [MeV/c]
     g4sim replays it with `/gun/eventFile` (one multi-particle vertex per
     event) and fills step_*, totalEdep, and real trk_end* by transport.

  2. `merge_nu_block`   -- graft the generator's interaction record (the full
     nu_* block and the neutrino primary) onto the transported file, so the
     final output.root carries BOTH the generator-quality interaction physics
     and the Geant4 transport record in the one common schema.

Neutral final-state neutrinos are kept in the event file (Geant4 transports
them trivially; with biasing off they simply leave).
"""
import numpy as np
import uproot

from . import io

TRANSPORT_MACRO = "gdmltp_transport.mac"
EVENT_FILE = "events.dat"
VERTEX_FILE = "vertex_level.root"

# Branches replaced on the transported file by the generator's values: the
# interaction record, and the primary identity (the neutrino/lepton probe --
# matching what a native Geant4 neutrino run would record as its primary).
_MERGE_SCALARS = ["primaryPDG", "primaryE",
                  "primaryStartX", "primaryStartY", "primaryStartZ",
                  "primaryStartPx", "primaryStartPy", "primaryStartPz"]


def write_event_file(vertex_root, path, tree="tree"):
    """Write the hand-off event file from a vertex-level ntuple."""
    with uproot.open(vertex_root) as f:
        t = f[tree]
        pdg = t["trk_pdg"].array()
        px = t["trk_px"].array()
        py = t["trk_py"].array()
        pz = t["trk_pz"].array()
        vx = t["nu_vertexX"].array(library="np")
        vy = t["nu_vertexY"].array(library="np")
        vz = t["nu_vertexZ"].array(library="np")

        lines = ["# gdmltp hand-off event file:",
                 "#   E <nParticles> <vx> <vy> <vz>   [mm]",
                 "#   <pdg> <px> <py> <pz>            [MeV/c]"]
        n_events = len(vx)
        for i in range(n_events):
            ids = [int(v) for v in pdg[i]]
            lines.append(f"E {len(ids)} {vx[i]:.6g} {vy[i]:.6g} {vz[i]:.6g}")
            for k, p in enumerate(ids):
                lines.append(f"{p} {float(px[i][k]):.6g} {float(py[i][k]):.6g} "
                             f"{float(pz[i][k]):.6g}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return n_events


def read_event_file(path):
    """Parse an event file back into [(vertex(3,), [(pdg,(px,py,pz)), ...])]."""
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            t = line.split()
            if t[0] == "E":
                events.append((tuple(float(v) for v in t[2:5]), []))
            else:
                events[-1][1].append((int(t[0]), tuple(float(v) for v in t[1:4])))
    return events


def build_transport_macro(gdml_name, n_events, event_file=EVENT_FILE, seed=None,
                          field=None):
    """The stage-2 g4sim macro: replay the event file through the detector.
    neutrinoMode is off -- the nu_* block comes from the generator via
    merge_nu_block, not from Geant4."""
    lines = [f"/detector/readGDML {gdml_name}", "/run/initialize",
             "/analysis/neutrinoMode off"]
    if seed is not None:
        lines.append(f"/random/setSeeds {int(seed)} {int(seed) + 1}")
    if field:
        lines.append(f"/detector/setGlobalField {field}")
    lines += [f"/gun/eventFile {event_file}",
              f"/run/printProgress {max(1, int(n_events) // 10)}",
              f"/run/beamOn {int(n_events)}"]
    return "\n".join(lines) + "\n"


def merge_nu_block(transported_root, vertex_root, out_path, tree="tree"):
    """Write `out_path` = the transported tree with the generator's nu_* block
    and primary identity grafted on. Event counts must match 1:1."""
    with uproot.open(transported_root) as ft:
        tt = ft[tree]
        n_t = int(tt.num_entries)
        names = [k.split(";")[0] for k in tt.keys()]
        data = {name: tt[name].array() for name in names}

    with uproot.open(vertex_root) as fv:
        tv = fv[tree]
        n_v = int(tv.num_entries)
        if n_t != n_v:
            raise ValueError(
                f"transported file has {n_t} events but vertex-level has {n_v}; "
                f"did the transport run use /gun/eventFile with beamOn {n_v}?")
        vnames = {k.split(";")[0] for k in tv.keys()}
        for name in list(vnames):
            if name.startswith("nu_"):
                data[name] = tv[name].array()
        for name in _MERGE_SCALARS:
            if name in vnames:
                data[name] = tv[name].array(library="np")

    with uproot.recreate(out_path) as f:
        f[tree] = data
    return out_path
