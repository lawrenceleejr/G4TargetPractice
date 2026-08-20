"""External backend: bring events from a real generator (Pythia8, MadGraph,
or anything that writes HepMC3 ASCII) into the common pipeline.

This is the escape hatch for physics this framework deliberately does not
generate itself -- e.g. BSM decays with proper matrix elements or
polarization: produce the events with the established tool, then

    generator: external
    external: {file: my_events.hepmc, transport: true}

converts them to the common vertex-level `output.root` (so validate / analyze
/ display / compare work as usual) and, with transport on, replays the
final-state particles through the GDML detector in the Geant4 image via the
standard hand-off. HepMC event weights (W lines) land in `eventWeight`; the
event vertex (V/E `@` positions) becomes the vertex, its time goes to `decayT`
and into the Geant4 stage.

Conversion runs on the host in prepare() (pure Python, reusing the tolerant
HepMC3 ASCII parser the Achilles converter is built on).
"""
from pathlib import Path

import numpy as np

from .base import Backend, Prepared
from ..config import ConfigError

C_MM_PER_NS = 299.792458


def convert(hepmc_path, out_path, out_tree="tree"):
    """Generic HepMC3 -> schema conversion: primary = the status-4 beam
    particle (fallback: the first listed), final state = status 1, vertex from
    the file, weight from W lines. Vertex-level: step_* empty."""
    import awkward as ak
    import uproot
    from .achilles_convert import parse_nuhepmc
    from .genie_convert import _empty_jagged, _empty_jagged_str
    from ..masses import mass_mev

    events = parse_nuhepmc(hepmc_path)
    n = len(events)
    if n == 0:
        raise ConfigError(f"{hepmc_path}: no events parsed (HepMC3 ASCII expected)")

    prim_pdg = np.zeros(n, np.int64)
    prim_p = np.zeros((n, 3))
    prim_e = np.zeros(n)
    vtx = np.zeros((n, 3))
    t_ns = np.zeros(n)
    weight = np.ones(n)
    counts, flat_pdg, flat_p, flat_kin = [], [], [], []

    for i, ev in enumerate(events):
        es, ls = ev["e_scale"], ev["l_scale"]
        parts = ev["particles"]
        if not parts:
            raise ConfigError(f"{hepmc_path}: event {i} has no particles")
        beam = next((p for p in parts if p[6] == 4), parts[0])
        prim_pdg[i] = beam[0]
        prim_p[i] = np.array(beam[1:4]) * es
        prim_e[i] = beam[4] * es
        if ev["vertex"] is not None:
            vtx[i] = np.array(ev["vertex"][:3]) * ls
            # HepMC time is stored as length (x0 = c*t): convert via c
            t_ns[i] = ev["vertex"][3] * ls / C_MM_PER_NS
        if ev["weight"] is not None:
            weight[i] = ev["weight"]

        fs = [p for p in parts if p[6] == 1]
        counts.append(len(fs))
        for p in fs:
            flat_pdg.append(p[0])
            flat_p.append(np.array(p[1:4]) * es)
            flat_kin.append(max(0.0, p[4] * es - mass_mev(p[0])))

    counts = np.array(counts, np.int64)
    flat_pdg = np.array(flat_pdg, np.int64)
    flat_p = np.vstack(flat_p) if len(flat_p) else np.zeros((0, 3))
    flat_kin = np.array(flat_kin)

    j = lambda flat: ak.unflatten(flat, counts)
    zeros_j = j(np.zeros(int(counts.sum())))
    vx, vy, vz = vtx.T

    data = {
        "eventID": np.arange(n, dtype=np.int32),
        "primaryPDG": prim_pdg.astype(np.int32),
        "primaryE": prim_e,
        "primaryStartX": vx, "primaryStartY": vy, "primaryStartZ": vz,
        "primaryStartPx": prim_p[:, 0], "primaryStartPy": prim_p[:, 1],
        "primaryStartPz": prim_p[:, 2],
        "primaryEndE": np.zeros(n),
        "primaryEndX": vx, "primaryEndY": vy, "primaryEndZ": vz,
        "primaryEndPx": np.zeros(n), "primaryEndPy": np.zeros(n),
        "primaryEndPz": np.zeros(n),
        "totalEdep": np.zeros(n),
        "nSteps": np.zeros(n, np.int32),
        "nTracks": counts.astype(np.int32),
        "eventWeight": weight,
        "decayT": t_ns,
        "trk_id": j(np.concatenate([np.arange(1, c + 1) for c in counts])
                    .astype(np.int32) if counts.sum() else np.array([], np.int32)),
        "trk_parentID": ak.values_astype(zeros_j, np.int32),
        "trk_pdg": j(flat_pdg.astype(np.int32)),
        "trk_startX": j(np.repeat(vx, counts)),
        "trk_startY": j(np.repeat(vy, counts)),
        "trk_startZ": j(np.repeat(vz, counts)),
        "trk_startE": j(flat_kin),
        "trk_endX": j(np.repeat(vx, counts)),
        "trk_endY": j(np.repeat(vy, counts)),
        "trk_endZ": j(np.repeat(vz, counts)),
        "trk_endE": zeros_j,
        "trk_edep": zeros_j, "trk_length": zeros_j,
        "trk_creatorProcess": j(np.array(["External"] * int(counts.sum()))),
        "trk_px": j(flat_p[:, 0]), "trk_py": j(flat_p[:, 1]),
        "trk_pz": j(flat_p[:, 2]),
        "step_trackID": _empty_jagged(n, np.int32),
        "step_pdg": _empty_jagged(n, np.int32),
        "step_x": _empty_jagged(n, np.float64),
        "step_y": _empty_jagged(n, np.float64),
        "step_z": _empty_jagged(n, np.float64),
        "step_kinE": _empty_jagged(n, np.float64),
        "step_edep": _empty_jagged(n, np.float64),
        "step_length": _empty_jagged(n, np.float64),
        "step_time": _empty_jagged(n, np.float64),
        "step_process": _empty_jagged_str(n),
    }
    from ..io import write_tree
    write_tree(out_path, data, tree=out_tree)
    return n


class ExternalBackend(Backend):
    name = "external"
    default_image = ""            # conversion runs on the host
    host = True

    def prepare(self, cfg, outdir, image=None) -> Prepared:
        outdir = Path(outdir)
        src = Path(cfg.external["file"])
        if not src.exists():
            raise ConfigError(f"external.file not found: {src}")
        n = convert(str(src), outdir / cfg.run.output)
        print(f"[gdmltp] external: converted {n} event(s) from {src} "
              f"-> {outdir / cfg.run.output}")
        return Prepared(argv=[], image="", env={}, output=cfg.run.output)
