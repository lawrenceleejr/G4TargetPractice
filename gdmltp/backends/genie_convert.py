"""Convert a GENIE summary tree (`gst`) into the common `output.root` schema.

GENIE is a vertex generator: it produces the interaction record and the
final-state particle list, but does not transport particles or deposit energy.
So the ntuple this writes has a fully-populated `nu_*` block and one `trk_*` row
per final-state particle, while `step_*`/`totalEdep` are empty -- exactly the
gap the (future) GENIE->Geant4 hand-off would fill.

Pure uproot/numpy/awkward, no ROOT/GENIE dependency, so it is unit-testable
against a synthetic `gst` fixture (see tests/conftest.py::write_synthetic_gst).

Unit conventions -- GENIE gst uses GeV, GeV/c, GeV^2; the schema uses MeV,
MeV/c, MeV^2, mm, ns (Geant4 internal units, matching g4sim/EventAction.cc):
  * energies / momenta:  x1000        (GeV  -> MeV,  GeV/c -> MeV/c)
  * Q^2:                 x1e6         (GeV^2 -> MeV^2)
  * vertex position:     x len_scale  (see LEN_TO_MM; tied to the geometry's
                                       length units -- CONFIRM with the smoke test)
  * vertex time:         x1e9         (s -> ns)
"""
import numpy as np
import awkward as ak
import uproot

from ..masses import mass_mev

GEV_TO_MEV = 1000.0
GEV2_TO_MEV2 = 1.0e6
S_TO_NS = 1.0e9
# gst vertex coordinates are in the geometry's length units; a ROOT TGeo is cm.
# This default is documented as "confirm empirically" (plan risk #3); the driver
# passes the run's genie.length_units so a mismatch is a one-line fix, not a rebuild.
LEN_TO_MM = {"m": 1000.0, "cm": 10.0, "mm": 1.0}

# gst interaction-mode flags, in the priority order used to name the channel.
_MODE_FLAGS = [("qel", "QES"), ("mec", "MEC"), ("res", "RES"),
               ("dis", "DIS"), ("coh", "COH"), ("dfr", "DFR"), ("imd", "IMD")]


def _scalar(t, keys, name, n, default=0.0, dtype=float):
    if name in keys:
        return np.asarray(t[name].array(library="np")).astype(dtype)
    return np.full(n, default, dtype=dtype)


def _first_tree(f):
    for k in f.keys():
        if hasattr(f[k], "num_entries"):
            return k.split(";")[0]
    raise ValueError("no TTree found in GENIE file")


def _empty_jagged(n, dtype):
    """A length-n jagged array whose every entry is an empty typed list."""
    off = ak.index.Index64(np.zeros(n + 1, np.int64))
    return ak.Array(ak.contents.ListOffsetArray(off, ak.contents.NumpyArray(np.array([], dtype))))


def _empty_jagged_str(n):
    off = ak.index.Index64(np.zeros(n + 1, np.int64))
    charoff = ak.index.Index64(np.zeros(1, np.int64))
    chars = ak.contents.NumpyArray(np.array([], np.uint8), parameters={"__array__": "char"})
    strc = ak.contents.ListOffsetArray(charoff, chars, parameters={"__array__": "string"})
    return ak.Array(ak.contents.ListOffsetArray(off, strc))


def _process_names(t, keys, n):
    have = {k: _scalar(t, keys, k, n, dtype=float) for k, _ in _MODE_FLAGS}
    out = []
    for i in range(n):
        label = "Other"
        for flag, name in _MODE_FLAGS:
            if have[flag][i]:
                label = name
                break
        out.append(label)
    return ak.Array(out)


def _out_lepton_pdg(t, keys, neu, cc):
    if "fspl" in keys:
        return np.asarray(t["fspl"].array(library="np")).astype(np.int64)
    # Derive: CC -> charged lepton of the same generation/sign; NC -> same nu.
    charged = np.sign(neu) * (np.abs(neu) - 1)
    return np.where(cc.astype(bool), charged, neu).astype(np.int64)


_SCALAR_SPECS = [
    ("neu", np.int64), ("cc", float), ("nc", float),
    ("Ev", float), ("pxv", float), ("pyv", float), ("pzv", float),
    ("El", float), ("pxl", float), ("pyl", float), ("pzl", float),
    ("Q2", float), ("W", float), ("x", float), ("y", float),
    ("vtxx", float), ("vtxy", float), ("vtxz", float), ("vtxt", float),
    ("Z", np.int64), ("A", np.int64),
]


def _flat_fs(t, keys, name, size):
    if name in keys and size:
        return np.asarray(ak.flatten(t[name].array()), dtype=float)
    return np.zeros(size)


def _read_gst(path, gst_tree=None):
    """Read one gst file fully into numpy (per-event scalars + flattened
    final-state lists + counts), so files can be concatenated and no lazy
    uproot arrays survive the file handle."""
    with uproot.open(path) as f:
        tname = gst_tree or ("gst" if any(k.split(";")[0] == "gst" for k in f.keys())
                             else _first_tree(f))
        t = f[tname]
        n = int(t.num_entries)
        keys = {k.split(";")[0] for k in t.keys()}

        d = {name: _scalar(t, keys, name, n, dtype=dt) for name, dt in _SCALAR_SPECS}
        d["n"] = n
        d["eid"] = _scalar(t, keys, "iev", n, dtype=np.int64) if "iev" in keys \
            else np.arange(n, dtype=np.int64)
        d["lep_pdg"] = _out_lepton_pdg(t, keys, d["neu"], d["cc"])
        d["procs"] = list(_process_names(t, keys, n))

        if "pdgf" in keys:
            pdgf = t["pdgf"].array()
            d["counts"] = np.asarray(ak.num(pdgf, axis=1)).astype(np.int64)
            d["flat_pdg"] = np.asarray(ak.flatten(pdgf)).astype(np.int64)
        else:
            d["counts"] = np.zeros(n, np.int64)
            d["flat_pdg"] = np.array([], np.int64)
        size = d["flat_pdg"].size
        d["flat_Ef_mev"] = _flat_fs(t, keys, "Ef", size) * GEV_TO_MEV
        d["flat_pxf"] = _flat_fs(t, keys, "pxf", size) * GEV_TO_MEV
        d["flat_pyf"] = _flat_fs(t, keys, "pyf", size) * GEV_TO_MEV
        d["flat_pzf"] = _flat_fs(t, keys, "pzf", size) * GEV_TO_MEV
    return d


def _concat_gst(dicts):
    """Concatenate per-file gst dicts; event ids are renumbered sequentially
    (per-event replay produces many one-event files, each with iev=0)."""
    if len(dicts) == 1:
        return dicts[0]
    out = {}
    for name, _dt in _SCALAR_SPECS:
        out[name] = np.concatenate([d[name] for d in dicts])
    for name in ("counts", "flat_pdg", "flat_Ef_mev", "flat_pxf", "flat_pyf", "flat_pzf",
                 "lep_pdg"):
        out[name] = np.concatenate([d[name] for d in dicts])
    out["procs"] = [p for d in dicts for p in d["procs"]]
    out["n"] = int(sum(d["n"] for d in dicts))
    out["eid"] = np.arange(out["n"], dtype=np.int64)
    return out


def convert(gst_path, out_path, vtx_units="cm", gst_tree=None, out_tree="tree", beam=None):
    """Read GENIE `gst` (one path or a list of paths, concatenated in order) and
    write schema `output.root` at `out_path`.

    `beam` (a beam-file path or a list of (name, pos_mm, mom_mev) entries) replays
    a host-sampled beam: it overrides each event's vertex and orients the event
    along the sampled ray (see the per-event beam-replay block below).
    """
    paths = [gst_path] if isinstance(gst_path, (str, bytes)) or hasattr(gst_path, "__fspath__") \
        else list(gst_path)
    g = _concat_gst([_read_gst(p, gst_tree) for p in paths])
    n = g["n"]
    neu = g["neu"]; cc = g["cc"]; nc = g["nc"]
    Ev = g["Ev"]; pxv = g["pxv"]; pyv = g["pyv"]; pzv = g["pzv"]
    El = g["El"]; pxl = g["pxl"]; pyl = g["pyl"]; pzl = g["pzl"]
    Q2 = g["Q2"]; W = g["W"]; xbj = g["x"]; ybj = g["y"]
    vtxx = g["vtxx"]; vtxy = g["vtxy"]; vtxz = g["vtxz"]; vtxt = g["vtxt"]
    Z = g["Z"]; A = g["A"]; eid = g["eid"]
    lep_pdg = g["lep_pdg"]; procs = ak.Array(g["procs"])
    counts = g["counts"]; flat_pdg = g["flat_pdg"]; flat_Ef_mev = g["flat_Ef_mev"]
    flat_pf = np.column_stack([g["flat_pxf"], g["flat_pyf"], g["flat_pzf"]]) \
        if flat_pdg.size else np.empty((0, 3))

    len_scale = LEN_TO_MM.get(vtx_units, LEN_TO_MM["cm"])
    vx = vtxx * len_scale; vy = vtxy * len_scale; vz = vtxz * len_scale
    vt = vtxt * S_TO_NS

    # Per-event beam replay: place the vertex at the sampled ray's position and
    # orient the (point-mode, +z) GENIE event along the ray direction. The
    # incoming neutrino momentum IS the sampled beam momentum; the outgoing
    # lepton is rotated from +z onto the ray. trk_* positions follow the vertex.
    if beam is not None:
        from .. import beam as beammod
        entries = beammod.read_beam_file(beam) if isinstance(beam, str) else list(beam)
        if len(entries) < n:
            raise ValueError(f"beam file has {len(entries)} entries but gst has {n} events")
        bpos = np.array([e[1] for e in entries[:n]], float)   # (n,3) mm
        bmom = np.array([e[2] for e in entries[:n]], float)   # (n,3) MeV/c
        vx, vy, vz = bpos[:, 0].copy(), bpos[:, 1].copy(), bpos[:, 2].copy()
        primary_p = bmom
        primaryE = np.linalg.norm(bmom, axis=1)
        lep_local = np.column_stack([pxl, pyl, pzl]) * GEV_TO_MEV
        outlep_p = beammod.rotate_uz_rows(lep_local, bmom)
        # rotate every final-state particle of event i onto ray i
        if flat_pf.size:
            axes = np.repeat(bmom, counts, axis=0)
            flat_pf = beammod.rotate_uz_rows(flat_pf, axes)
        q0 = primaryE - El * GEV_TO_MEV
    else:
        primary_p = np.column_stack([pxv, pyv, pzv]) * GEV_TO_MEV
        primaryE = Ev * GEV_TO_MEV
        outlep_p = np.column_stack([pxl, pyl, pzl]) * GEV_TO_MEV
        q0 = (Ev - El) * GEV_TO_MEV

    flat_mass = np.array([mass_mev(p) for p in flat_pdg], dtype=float)
    flat_kin = np.maximum(0.0, flat_Ef_mev - flat_mass)

    # Rebuild jagged per-track arrays from numpy counts (no lazy uproot arrays).
    trk_startE = ak.unflatten(flat_kin, counts)
    trk_pdg = ak.unflatten(flat_pdg.astype(np.int32), counts)
    trk_id = ak.unflatten(
        np.concatenate([np.arange(1, c + 1) for c in counts]).astype(np.int32)
        if counts.sum() else np.array([], np.int32), counts)
    zeros_j = ak.unflatten(np.zeros(int(counts.sum())), counts)
    vx_j = ak.unflatten(np.repeat(vx, counts), counts)
    vy_j = ak.unflatten(np.repeat(vy, counts), counts)
    vz_j = ak.unflatten(np.repeat(vz, counts), counts)
    creator = ak.unflatten(np.array(["GENIE"] * int(counts.sum())), counts)

    data = {
        # --- event scalars ---
        "eventID": eid.astype(np.int32),
        "primaryPDG": neu.astype(np.int32),
        "primaryE": primaryE,
        "primaryStartX": vx, "primaryStartY": vy, "primaryStartZ": vz,
        "primaryStartPx": primary_p[:, 0], "primaryStartPy": primary_p[:, 1],
        "primaryStartPz": primary_p[:, 2],
        "primaryEndE": np.zeros(n),
        "primaryEndX": vx, "primaryEndY": vy, "primaryEndZ": vz,
        "primaryEndPx": np.zeros(n), "primaryEndPy": np.zeros(n), "primaryEndPz": np.zeros(n),
        "totalEdep": np.zeros(n),
        "nSteps": np.zeros(n, np.int32),
        "nTracks": counts.astype(np.int32),
        # --- per-track (final-state particles) ---
        "trk_id": ak.values_astype(trk_id, np.int32),
        "trk_parentID": ak.values_astype(zeros_j, np.int32),
        "trk_pdg": ak.values_astype(trk_pdg, np.int32),
        "trk_startX": vx_j, "trk_startY": vy_j, "trk_startZ": vz_j,
        "trk_startE": trk_startE,
        "trk_endX": vx_j, "trk_endY": vy_j, "trk_endZ": vz_j,
        "trk_endE": zeros_j,
        "trk_edep": zeros_j, "trk_length": zeros_j,
        "trk_creatorProcess": creator,
        # optional momentum-at-production (MeV/c): lets displays draw momentum
        # rays for untransported tracks (see io.TRK_OPTIONAL_BRANCHES)
        "trk_px": ak.unflatten(flat_pf[:, 0] if flat_pf.size else np.array([]), counts),
        "trk_py": ak.unflatten(flat_pf[:, 1] if flat_pf.size else np.array([]), counts),
        "trk_pz": ak.unflatten(flat_pf[:, 2] if flat_pf.size else np.array([]), counts),
        # --- per-step (empty: GENIE does not transport) ---
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
        # --- neutrino interaction block ---
        "nu_isCC": cc.astype(bool),
        "nu_isNC": nc.astype(bool),
        "nu_interactionProcess": procs,
        "nu_vertexX": vx, "nu_vertexY": vy, "nu_vertexZ": vz, "nu_vertexT": vt,
        "nu_targetZ": Z.astype(np.int32), "nu_targetA": A.astype(np.int32),
        # external generators do not oscillate the probe: the flavour is fixed
        "nu_nOscillations": np.zeros(n, np.int32),
        "nu_outLeptonPDG": lep_pdg.astype(np.int32),
        "nu_outLeptonE": El * GEV_TO_MEV,
        "nu_outLeptonPx": outlep_p[:, 0], "nu_outLeptonPy": outlep_p[:, 1],
        "nu_outLeptonPz": outlep_p[:, 2],
        "nu_Q2": Q2 * GEV2_TO_MEV2,
        "nu_W": W * GEV_TO_MEV,
        "nu_x": xbj, "nu_y": ybj,
        "nu_q0": q0,
    }

    with uproot.recreate(out_path) as f:
        f[out_tree] = data
    return out_path


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        prog="genie2root",
        description="Convert a GENIE gst file to the common output.root schema.")
    p.add_argument("gst", help="input GENIE gst .root file")
    p.add_argument("-o", "--output", default="output.root")
    p.add_argument("--vtx-units", default="cm", choices=list(LEN_TO_MM),
                   help="length units of the gst vertex coordinates (default cm)")
    p.add_argument("--gst-tree", default=None, help="tree name (default: gst / first tree)")
    a = p.parse_args(argv)
    out = convert(a.gst, a.output, vtx_units=a.vtx_units, gst_tree=a.gst_tree)
    print(f"[genie2root] wrote {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
