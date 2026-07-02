"""Shared fixtures: synthetic output.root files faithful to the g4sim schema.

Units mirror RunAction.cc exactly: positions/lengths in mm, energies in MeV,
times in ns (Geant4 internal units -- g4sim writes raw values, no conversion).
Every branch g4sim writes is present (scalars + trk_* + step_*; nu_* optional)
so io/scene/analyze/compare/display all exercise the real schema without
needing Geant4 or Docker.
"""
import numpy as np
import awkward as ak
import uproot
import pytest


def write_synthetic(path, n_events=30, e0_mev=50000.0, x0_cm=3.0,
                    z0_cm=650.0, pz_sign=-1.0, mean_leak=0.02,
                    steps_per_event=200, tracks_per_event=20, seed=0,
                    with_nu=False):
    """EM-shower-like run: primary starts at (0,0,z0_cm), travels along pz_sign*z.

    The longitudinal energy profile is Gamma(shape=3, scale=x0_cm) in depth, so
    the true dE/dz mode is 2*x0_cm. Per-event leakage fraction is Gamma with
    the requested mean, and step_edep sums to totalEdep per event, so the
    energy bookkeeping is self-consistent.
    """
    rng = np.random.default_rng(seed)
    z0_mm = z0_cm * 10.0
    x0_mm = x0_cm * 10.0

    leak = np.clip(rng.gamma(4.0, mean_leak / 4.0, n_events), 0.0, 0.95)
    total_edep = e0_mev * (1.0 - leak)

    sc = {
        "eventID": np.arange(n_events, dtype=np.int32),
        "primaryPDG": np.full(n_events, 11, np.int32),
        "primaryE": np.full(n_events, e0_mev, np.float64),
        "primaryStartX": np.zeros(n_events), "primaryStartY": np.zeros(n_events),
        "primaryStartZ": np.full(n_events, z0_mm, np.float64),
        "primaryStartPx": np.zeros(n_events), "primaryStartPy": np.zeros(n_events),
        "primaryStartPz": np.full(n_events, pz_sign * e0_mev, np.float64),
        "primaryEndE": np.zeros(n_events),
        "primaryEndX": np.zeros(n_events), "primaryEndY": np.zeros(n_events),
        "primaryEndZ": np.full(n_events, z0_mm + pz_sign * 5 * x0_mm),
        "primaryEndPx": np.zeros(n_events), "primaryEndPy": np.zeros(n_events),
        "primaryEndPz": np.zeros(n_events),
        "totalEdep": total_edep,
        "nSteps": np.full(n_events, steps_per_event, np.int32),
        "nTracks": np.full(n_events, tracks_per_event, np.int32),
    }

    trk = {k: [] for k in ("id", "parentID", "pdg", "startX", "startY", "startZ",
                           "startE", "endX", "endY", "endZ", "endE", "edep",
                           "length", "creatorProcess")}
    stp = {k: [] for k in ("trackID", "pdg", "x", "y", "z", "kinE", "edep",
                           "length", "time", "process")}
    pdgs = np.array([11, -11, 22, 2112, 2212])

    for iev in range(n_events):
        nt = tracks_per_event
        tid = np.arange(1, nt + 1)
        parent = np.concatenate([[0], rng.integers(1, np.maximum(2, tid[:-1] + 1))])
        tpdg = np.concatenate([[11], rng.choice(pdgs, nt - 1)])
        depth0 = np.concatenate([[0.0], rng.gamma(3.0, x0_mm, nt - 1)])   # mm
        tlen = rng.gamma(2.0, x0_mm, nt)
        trk["id"].append(tid.astype(np.int32))
        trk["parentID"].append(parent.astype(np.int32))
        trk["pdg"].append(tpdg.astype(np.int32))
        trk["startX"].append(rng.normal(0, 2, nt)); trk["startY"].append(rng.normal(0, 2, nt))
        trk["startZ"].append(z0_mm + pz_sign * depth0)
        trk["startE"].append(rng.gamma(2.0, 50.0, nt))
        trk["endX"].append(rng.normal(0, 3, nt)); trk["endY"].append(rng.normal(0, 3, nt))
        trk["endZ"].append(z0_mm + pz_sign * (depth0 + tlen))
        trk["endE"].append(np.zeros(nt))
        trk["edep"].append(rng.gamma(2.0, 20.0, nt))
        trk["length"].append(tlen)
        trk["creatorProcess"].append(["Primary"] + ["eBrem"] * (nt - 1))

        m = steps_per_event
        sdepth = rng.gamma(3.0, x0_mm, m)                       # mm into absorber
        sid = rng.integers(1, nt + 1, m)
        order = np.argsort(sid, kind="stable")                  # steps arrive track-grouped
        stp["trackID"].append(sid[order].astype(np.int32))
        stp["pdg"].append(rng.choice(pdgs, m)[order].astype(np.int32))
        stp["x"].append(rng.normal(0, 3, m)[order]); stp["y"].append(rng.normal(0, 3, m)[order])
        stp["z"].append((z0_mm + pz_sign * sdepth)[order])
        stp["kinE"].append(rng.gamma(2.0, 30.0, m)[order])
        wraw = rng.gamma(2.0, 1.0, m)                           # sums to totalEdep
        stp["edep"].append((wraw / wraw.sum() * total_edep[iev])[order])
        stp["length"].append(rng.gamma(1.5, 2.0, m)[order])
        stp["time"].append(np.sort(rng.gamma(2.0, 0.05, m))[order])
        stp["process"].append(["eIoni"] * m)

    data = dict(sc)
    for k, v in trk.items():
        data[f"trk_{k}"] = ak.Array(v)
    for k, v in stp.items():
        data[f"step_{k}"] = ak.Array(v)
    if with_nu:
        rng2 = np.random.default_rng(seed + 1)
        data["nu_isCC"] = rng2.random(n_events) < 0.7
        data["nu_isNC"] = ~data["nu_isCC"]
        data["nu_vertexX"] = np.zeros(n_events)
        data["nu_vertexY"] = np.zeros(n_events)
        data["nu_vertexZ"] = np.full(n_events, z0_mm)
        data["nu_Q2"] = rng2.gamma(2.0, 1000.0, n_events)
        data["nu_W"] = rng2.gamma(2.0, 800.0, n_events)

    with uproot.recreate(path) as f:
        f["tree"] = data
    return str(path)


@pytest.fixture(scope="session")
def synth_root(tmp_path_factory):
    """Standard synthetic run: 50 GeV e-, -z beam from z=650 cm, 2% leakage."""
    p = tmp_path_factory.mktemp("data") / "synth.root"
    return write_synthetic(p, seed=1)


@pytest.fixture(scope="session")
def synth_pair(tmp_path_factory):
    """(dense, loose) pair: dense has a shorter profile and less leakage."""
    d = tmp_path_factory.mktemp("pair")
    a = write_synthetic(d / "dense.root", x0_cm=2.5, mean_leak=0.012, seed=2)
    b = write_synthetic(d / "loose.root", x0_cm=3.5, mean_leak=0.030, seed=3)
    return a, b


@pytest.fixture(scope="session")
def synth_nu(tmp_path_factory):
    p = tmp_path_factory.mktemp("nu") / "nu.root"
    return write_synthetic(p, with_nu=True, seed=4)


@pytest.fixture(scope="session")
def empty_root(tmp_path_factory):
    """A tree with the scalar schema but zero entries."""
    p = tmp_path_factory.mktemp("empty") / "empty.root"
    with uproot.recreate(p) as f:
        f.mktree("tree", {"eventID": np.int32, "primaryE": np.float64,
                          "totalEdep": np.float64})
    return str(p)


@pytest.fixture(scope="session")
def repo_root():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent
