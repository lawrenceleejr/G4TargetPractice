"""Convert Achilles NuHepMC (HepMC3 ASCII) output into the common `output.root`.

Achilles is a vertex-level generator (like GENIE here): it produces the
interaction and its final-state particles, not transport. The converted ntuple
therefore carries a full `nu_*` block, one `trk_*` row per final-state particle
(including the optional trk_px/py/pz momentum branches the displays use to draw
momentum rays), and empty `step_*`/`totalEdep`.

The parser is a small, tolerant, pure-Python reader of the HepMC3 ASCIIv3
dialect (E/U/V/P lines; A/W/T/F ignored; gzip transparently handled), so it is
unit-testable against a synthetic .hepmc fixture with no HepMC3/Achilles
dependency. NuHepMC status conventions used: 4 = incoming beam, 11 = target,
1 = undecayed final state. It is validated against real Achilles output by the
(non-gating) achilles CI smoke.

Kinematics (nu_Q2/W/x/y/q0) are computed exactly as g4sim's EventAction does --
from the beam and outgoing-lepton four-vectors with a fixed nucleon mass -- so
the branches are comparable across all three backends. Units in: GeV or MeV
(from the U line); out: MeV, MeV/c, MeV^2, mm, ns.
"""
import gzip
import math

import numpy as np
import awkward as ak
import uproot

from .genie_convert import _empty_jagged, _empty_jagged_str
from ..masses import mass_mev

NUCLEON_MASS_MEV = 939.565          # matches g4sim/EventAction.cc
_LEPTONS = {11, -11, 12, -12, 13, -13, 14, -14, 15, -15, 16, -16}
_LEN_TO_MM = {"MM": 1.0, "CM": 10.0}
_ENE_TO_MEV = {"GEV": 1000.0, "MEV": 1.0}


def _open_text(path):
    p = str(path)
    if p.endswith(".gz"):
        return gzip.open(p, "rt")
    # sniff gzip magic in case the extension was dropped
    with open(p, "rb") as f:
        magic = f.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(p, "rt")
    return open(p, "r")


def parse_nuhepmc(path):
    """Parse a NuHepMC/HepMC3 ASCII file -> list of event dicts:
    {particles: [(pdg, px,py,pz, E, m, status)], vertex: (x,y,z,t) or None,
     e_scale (->MeV), l_scale (->mm)}. Momenta/energies still in file units;
    the per-event scales say how to convert."""
    events = []
    cur = None
    e_scale, l_scale = 1000.0, 1.0            # HepMC default GEV / MM

    with _open_text(path) as f:
        for line in f:
            if not line or line[0] in "#\n":
                continue
            tag = line[0]
            if tag == "E":
                if cur is not None:
                    events.append(cur)
                cur = {"particles": [], "vertex": None, "weight": None,
                       "e_scale": e_scale, "l_scale": l_scale}
                # optional event position shift: "E n nvtx npart @ x y z t"
                if "@" in line:
                    try:
                        pos = [float(v) for v in line.split("@", 1)[1].split()[:4]]
                        cur["vertex"] = tuple(pos)
                    except ValueError:
                        pass
            elif cur is None:
                continue
            elif tag == "U":
                t = line.split()
                e_scale = _ENE_TO_MEV.get(t[1].upper(), 1000.0) if len(t) > 1 else 1000.0
                l_scale = _LEN_TO_MM.get(t[2].upper(), 1.0) if len(t) > 2 else 1.0
                cur["e_scale"], cur["l_scale"] = e_scale, l_scale
            elif tag == "V":
                # vertex position, when recorded: "V id status [...] @ x y z t"
                if "@" in line and cur["vertex"] is None:
                    try:
                        pos = [float(v) for v in line.split("@", 1)[1].split()[:4]]
                        cur["vertex"] = tuple(pos)
                    except ValueError:
                        pass
            elif tag == "W":
                # event weight(s): keep the first (the external backend stores
                # it as eventWeight; Achilles conversion ignores it)
                try:
                    cur["weight"] = float(line.split()[1])
                except (IndexError, ValueError):
                    pass
            elif tag == "P":
                t = line.split()
                # P id parent pdg px py pz e m status
                if len(t) >= 10:
                    try:
                        pdg = int(t[3])
                        px, py, pz, en, m = (float(v) for v in t[4:9])
                        status = int(t[9])
                    except ValueError:
                        continue
                    cur["particles"].append((pdg, px, py, pz, en, m, status))
    if cur is not None:
        events.append(cur)
    return events


def _classify(ev):
    """Pick out (beam, target, fs_list) from one parsed event using NuHepMC
    status codes, with tolerant fallbacks."""
    parts = ev["particles"]
    beam = next((p for p in parts if p[6] == 4), None)
    if beam is None:                      # fallback: first non-final lepton
        beam = next((p for p in parts if p[0] in _LEPTONS and p[6] != 1), None)
    target = next((p for p in parts if p[6] == 11), None)
    if target is None:
        target = next((p for p in parts if abs(p[0]) > 1_000_000_000 and p[6] != 1), None)
    fs = [p for p in parts if p[6] == 1]
    return beam, target, fs


def _out_lepton(beam_pdg, fs):
    """The outgoing lepton and CC/NC flags. Neutrino beam: a charged lepton of
    the same generation => CC, the same neutrino => NC. Charged-lepton beam
    (Achilles e-nucleus): the scattered same-flavor lepton, no CC/NC."""
    if abs(beam_pdg) in (12, 14, 16):
        cc_pdg = int(np.sign(beam_pdg) * (abs(beam_pdg) - 1))
        lep = next((p for p in fs if p[0] == cc_pdg), None)
        if lep is not None:
            return lep, True, False
        lep = next((p for p in fs if p[0] == beam_pdg), None)
        return lep, False, lep is not None
    lep = next((p for p in fs if p[0] == beam_pdg), None)
    return lep, False, False


def convert(hepmc_path, out_path, out_tree="tree", beam=None, process_label="Achilles"):
    """Convert NuHepMC at `hepmc_path` to schema `output.root` at `out_path`.

    `beam` (beam-file path or entry list) replays a host-sampled beam exactly as
    the GENIE converter does: each event's vertex moves to the ray's position and
    all momenta rotate from the generator's axis onto the ray direction.
    """
    events = parse_nuhepmc(hepmc_path)
    n = len(events)

    # per-event accumulators
    neu = np.zeros(n, np.int64)
    pnu = np.zeros((n, 3)); Enu = np.zeros(n)
    plep = np.zeros((n, 3)); Elep = np.zeros(n)
    lep_pdg = np.zeros(n, np.int64)
    is_cc = np.zeros(n, bool); is_nc = np.zeros(n, bool)
    vx = np.zeros(n); vy = np.zeros(n); vz = np.zeros(n); vt = np.zeros(n)
    tZ = np.full(n, -1, np.int64); tA = np.full(n, -1, np.int64)
    counts = np.zeros(n, np.int64)
    fs_pdg, fs_kin, fs_p = [], [], []

    for i, ev in enumerate(events):
        es, ls = ev["e_scale"], ev["l_scale"]
        b, tgt, fs = _classify(ev)
        if b is not None:
            neu[i] = b[0]
            pnu[i] = np.array(b[1:4]) * es
            Enu[i] = b[4] * es
        if tgt is not None and abs(tgt[0]) > 1_000_000_000:
            tZ[i] = (abs(tgt[0]) // 10000) % 1000
            tA[i] = (abs(tgt[0]) // 10) % 1000
        if ev["vertex"] is not None:
            vx[i], vy[i], vz[i] = (c * ls for c in ev["vertex"][:3])
            vt[i] = ev["vertex"][3]        # HepMC time unit ~ mm/c; keep raw
        lep, cc, nc = _out_lepton(int(neu[i]), fs)
        is_cc[i], is_nc[i] = cc, nc
        if lep is not None:
            lep_pdg[i] = lep[0]
            plep[i] = np.array(lep[1:4]) * es
            Elep[i] = lep[4] * es
        counts[i] = len(fs)
        for p in fs:
            fs_pdg.append(p[0])
            m = p[5] * es if p[5] > 0 else mass_mev(p[0])
            fs_kin.append(max(0.0, p[4] * es - m))
            fs_p.append([p[1] * es, p[2] * es, p[3] * es])

    flat_pdg = np.array(fs_pdg, np.int64)
    flat_kin = np.array(fs_kin, float)
    flat_p = np.array(fs_p, float) if fs_p else np.empty((0, 3))

    # --- optional per-event beam replay (same contract as genie_convert) ---
    if beam is not None:
        from .. import beam as beammod
        entries = beammod.read_beam_file(beam) if isinstance(beam, str) else list(beam)
        if len(entries) < n:
            raise ValueError(f"beam file has {len(entries)} entries but hepmc has {n} events")
        bpos = np.array([e[1] for e in entries[:n]], float)
        bmom = np.array([e[2] for e in entries[:n]], float)
        vx, vy, vz = bpos[:, 0].copy(), bpos[:, 1].copy(), bpos[:, 2].copy()
        pnu = bmom
        Enu = np.linalg.norm(bmom, axis=1)
        plep = beammod.rotate_uz_rows(plep, bmom)
        if flat_p.size:
            axes = np.repeat(bmom, counts, axis=0)
            flat_p = beammod.rotate_uz_rows(flat_p, axes)

    # --- exact exchange kinematics (mirrors g4sim/EventAction.cc) ---
    q0 = Enu - Elep
    qvec = pnu - plep
    Q2 = np.einsum("ij,ij->i", qvec, qvec) - q0 * q0
    W2 = NUCLEON_MASS_MEV ** 2 + 2.0 * NUCLEON_MASS_MEV * q0 - Q2
    W = np.where(W2 > 0, np.sqrt(np.maximum(W2, 0.0)), 0.0)
    denom = 2.0 * NUCLEON_MASS_MEV * q0
    xbj = np.where(denom > 0, Q2 / np.where(denom > 0, denom, 1.0), 0.0)
    ybj = np.where(Enu > 0, q0 / np.where(Enu > 0, Enu, 1.0), 0.0)

    total = int(counts.sum())
    zeros_j = ak.unflatten(np.zeros(total), counts)
    trk_id = ak.unflatten(
        np.concatenate([np.arange(1, c + 1) for c in counts]).astype(np.int32)
        if total else np.array([], np.int32), counts)

    data = {
        "eventID": np.arange(n, dtype=np.int32),
        "primaryPDG": neu.astype(np.int32),
        "primaryE": Enu,
        "primaryStartX": vx, "primaryStartY": vy, "primaryStartZ": vz,
        "primaryStartPx": pnu[:, 0], "primaryStartPy": pnu[:, 1], "primaryStartPz": pnu[:, 2],
        "primaryEndE": np.zeros(n),
        "primaryEndX": vx, "primaryEndY": vy, "primaryEndZ": vz,
        "primaryEndPx": np.zeros(n), "primaryEndPy": np.zeros(n), "primaryEndPz": np.zeros(n),
        "totalEdep": np.zeros(n),
        "nSteps": np.zeros(n, np.int32),
        "nTracks": counts.astype(np.int32),
        "trk_id": trk_id,
        "trk_parentID": ak.values_astype(zeros_j, np.int32),
        "trk_pdg": ak.unflatten(flat_pdg.astype(np.int32), counts),
        "trk_startX": ak.unflatten(np.repeat(vx, counts), counts),
        "trk_startY": ak.unflatten(np.repeat(vy, counts), counts),
        "trk_startZ": ak.unflatten(np.repeat(vz, counts), counts),
        "trk_startE": ak.unflatten(flat_kin, counts),
        "trk_endX": ak.unflatten(np.repeat(vx, counts), counts),
        "trk_endY": ak.unflatten(np.repeat(vy, counts), counts),
        "trk_endZ": ak.unflatten(np.repeat(vz, counts), counts),
        "trk_endE": zeros_j,
        "trk_edep": zeros_j, "trk_length": zeros_j,
        "trk_creatorProcess": ak.unflatten(np.array([process_label] * total), counts),
        "trk_px": ak.unflatten(flat_p[:, 0] if flat_p.size else np.array([]), counts),
        "trk_py": ak.unflatten(flat_p[:, 1] if flat_p.size else np.array([]), counts),
        "trk_pz": ak.unflatten(flat_p[:, 2] if flat_p.size else np.array([]), counts),
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
        "nu_isCC": is_cc, "nu_isNC": is_nc,
        "nu_interactionProcess": ak.Array([process_label] * n),
        "nu_vertexX": vx, "nu_vertexY": vy, "nu_vertexZ": vz, "nu_vertexT": vt,
        "nu_targetZ": tZ.astype(np.int32), "nu_targetA": tA.astype(np.int32),
        "nu_outLeptonPDG": lep_pdg.astype(np.int32),
        "nu_outLeptonE": Elep,
        "nu_outLeptonPx": plep[:, 0], "nu_outLeptonPy": plep[:, 1], "nu_outLeptonPz": plep[:, 2],
        "nu_Q2": Q2, "nu_W": W, "nu_x": xbj, "nu_y": ybj, "nu_q0": q0,
    }

    with uproot.recreate(out_path) as f:
        f[out_tree] = data
    return out_path


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        prog="achilles2root",
        description="Convert Achilles NuHepMC output to the common output.root schema.")
    p.add_argument("hepmc", help="input .hepmc / .hepmc.gz file")
    p.add_argument("-o", "--output", default="output.root")
    a = p.parse_args(argv)
    out = convert(a.hepmc, a.output)
    print(f"[achilles2root] wrote {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
