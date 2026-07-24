"""Generator -> Geant4 transport hand-off (the DUNE-style two-stage pattern).

GENIE and Achilles generate the interaction and its nuclear exit state but do
not transport anything through the detector. This module bridges the two:

  1. `write_event_file`  -- turn a vertex-level `output.root` (from
     genie_convert / achilles_convert / the decay backend, which record every
     final-state particle's momentum in trk_px/py/pz) into a g4sim hand-off
     event file:
         E <nParticles> <vx> <vy> <vz> [t]   [mm, ns]
         <pdg> <px> <py> <pz>                [MeV/c]
     g4sim replays it with `/gun/eventFile` (one multi-particle vertex per
     event, primaries stamped with t) and fills step_*, totalEdep, and real
     trk_end* by transport. The vertex comes from nu_vertex* when present
     (neutrino generators) else primaryEnd* (the decay backend records the
     decay point there); the time from decayT when present.

  2. `merge_nu_block`   -- graft the generator's record (the nu_* block when
     present, the primary identity, the vertex-level primaryEnd*, and any
     optional scalars like eventWeight/decayT) onto the transported file, so
     the final output.root carries BOTH the generator-quality physics and the
     Geant4 transport record in the one common schema.

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
# interaction record, the primary identity (probe/parent -- matching what a
# native Geant4 run would record), and the vertex-level end point (interaction
# or decay vertex; the transported file's own primaryEnd* would describe the
# first daughter instead).
_MERGE_SCALARS = ["primaryPDG", "primaryE",
                  "primaryStartX", "primaryStartY", "primaryStartZ",
                  "primaryStartPx", "primaryStartPy", "primaryStartPz",
                  "primaryEndE", "primaryEndX", "primaryEndY", "primaryEndZ",
                  "primaryEndPx", "primaryEndPy", "primaryEndPz"]

# Optional per-event scalars carried over verbatim when the vertex-level file
# has them (decay backend: forced-decay weight + decay time).
_MERGE_OPTIONAL = ["eventWeight", "decayT"]


def write_event_file(vertex_root, path, tree="tree"):
    """Write the hand-off event file from a vertex-level ntuple."""
    with uproot.open(vertex_root) as f:
        t = f[tree]
        names = {k.split(";")[0] for k in t.keys()}
        pdg = t["trk_pdg"].array()
        px = t["trk_px"].array()
        py = t["trk_py"].array()
        pz = t["trk_pz"].array()
        if "nu_vertexX" in names:
            vx = t["nu_vertexX"].array(library="np")
            vy = t["nu_vertexY"].array(library="np")
            vz = t["nu_vertexZ"].array(library="np")
        else:
            vx = t["primaryEndX"].array(library="np")
            vy = t["primaryEndY"].array(library="np")
            vz = t["primaryEndZ"].array(library="np")
        tns = t["decayT"].array(library="np") if "decayT" in names else None

        lines = ["# gdmltp hand-off event file:",
                 "#   E <nParticles> <vx> <vy> <vz> [t]   [mm, ns]",
                 "#   <pdg> <px> <py> <pz>                [MeV/c]"]
        n_events = len(vx)
        for i in range(n_events):
            ids = [int(v) for v in pdg[i]]
            head = f"E {len(ids)} {vx[i]:.6g} {vy[i]:.6g} {vz[i]:.6g}"
            if tns is not None:
                head += f" {float(tns[i]):.6g}"
            lines.append(head)
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
        for name in _MERGE_SCALARS + _MERGE_OPTIONAL:
            if name in vnames:
                data[name] = tv[name].array(library="np")

    with uproot.recreate(out_path) as f:
        f[tree] = data
    return out_path
