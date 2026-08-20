"""Shared fixtures: synthetic output.root files faithful to the g4sim schema.

Units mirror RunAction.cc exactly: positions/lengths in mm, energies in MeV,
times in ns (Geant4 internal units -- g4sim writes raw values, no conversion).
Every branch g4sim writes is present (io.SCALAR/TRK/STEP_BRANCHES, plus the
full nu_* block when requested) so io/scene/analyze/compare/display exercise
the real schema without needing Geant4 or Docker; test_io.py asserts the
fixture stays complete against io.py's branch lists.
"""
import numpy as np
import awkward as ak
import uproot
import pytest

from gdmltp import io
from gdmltp.io import MM_PER_CM


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
    z0_mm = z0_cm * MM_PER_CM
    x0_mm = x0_cm * MM_PER_CM

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
        parent = np.concatenate([[0], rng.integers(1, tid[:-1] + 1)])
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
        is_cc = rng2.random(n_events) < 0.7
        data.update({
            "nu_isCC": is_cc, "nu_isNC": ~is_cc,
            "nu_interactionProcess": ak.Array(
                ["neutrinoInelastic" if c else "NC" for c in is_cc]),
            "nu_vertexX": np.zeros(n_events), "nu_vertexY": np.zeros(n_events),
            "nu_vertexZ": np.full(n_events, z0_mm),
            "nu_vertexT": rng2.gamma(2.0, 1.0, n_events),
            "nu_targetZ": np.full(n_events, 18, np.int32),
            "nu_targetA": np.full(n_events, 40, np.int32),
            "nu_outLeptonPDG": np.where(is_cc, 13, 0).astype(np.int32),
            "nu_outLeptonE": rng2.gamma(2.0, 500.0, n_events),
            "nu_outLeptonPx": rng2.normal(0, 100, n_events),
            "nu_outLeptonPy": rng2.normal(0, 100, n_events),
            "nu_outLeptonPz": rng2.gamma(2.0, 400.0, n_events),
            "nu_Q2": rng2.gamma(2.0, 1000.0, n_events),
            "nu_W": rng2.gamma(2.0, 800.0, n_events),
            "nu_x": rng2.random(n_events), "nu_y": rng2.random(n_events),
            "nu_q0": rng2.gamma(2.0, 300.0, n_events),
        })

    # the same writer the package uses, so fixtures are classic TTrees with the
    # process names stored exactly as a real run stores them
    io.write_tree(path, data)
    return str(path)


def write_synthetic_gst(path, n_events=25, seed=0):
    """A synthetic GENIE 'gst' summary tree, faithful to the branches the
    converter reads. Energies/momenta in GeV, Q2 in GeV^2, vertex in cm (the
    geometry length units), matching real gst output -- so genie_convert exercises
    the real branch names and units without needing GENIE installed.

    Kinematics are mutually consistent like real gst output: y = 1 - El/Ev,
    Q2 = 2*M*q0*x, W^2 = M^2 + 2*M*q0 - Q2, so validate's closure cross-checks
    (which exist to catch unit-scaling bugs between backends) hold exactly."""
    rng = np.random.default_rng(seed)
    M = 0.939565                                         # GeV, matches the converters
    is_cc = rng.random(n_events) < 0.7
    qel = (rng.random(n_events) < 0.4) & is_cc
    res = (rng.random(n_events) < 0.3) & is_cc & ~qel
    dis = is_cc & ~qel & ~res
    Ev = rng.uniform(0.5, 8.0, n_events)                 # GeV
    ybj = rng.uniform(0.05, 0.9, n_events)
    El = Ev * (1.0 - ybj)
    q0 = Ev * ybj
    xbj = rng.uniform(0.05, 0.9, n_events)
    Q2 = 2.0 * M * q0 * xbj                              # GeV^2
    W = np.sqrt(np.maximum(M * M + 2.0 * M * q0 - Q2, 0.0))

    # Per-event final-state particle lists (GeV). HADRONS ONLY -- real gst keeps
    # the primary lepton out of pdgf/Ef/p*f and reports it separately in
    # fspl/El/pxl/pyl/pzl. The fixture used to include the lepton here, which
    # made genie_convert look correct while it was silently dropping the CC muon
    # from the final state it hands to Geant4.
    pdgf, Ef, pxf, pyf, pzf, nf = [], [], [], [], [], []
    for i in range(n_events):
        parts = []
        energies = []
        nhad = int(rng.integers(1, 5))
        for _ in range(nhad):
            parts.append(int(rng.choice([2212, 2112, 211, -211, 111])))
            energies.append(float(rng.uniform(0.15, 1.5)))
        p = np.array(parts, np.int64)
        e = np.array(energies, float)
        pdgf.append(p); Ef.append(e); nf.append(len(p))
        pxf.append(rng.normal(0, 0.2, len(p)))
        pyf.append(rng.normal(0, 0.2, len(p)))
        pzf.append(np.abs(rng.normal(0.5, 0.3, len(p))))

    data = {
        "iev": np.arange(n_events, dtype=np.int64),
        "neu": np.full(n_events, 14, np.int64),
        "fspl": np.where(is_cc, 13, 14).astype(np.int64),
        "tgt": np.full(n_events, 1000180400, np.int64),
        "Z": np.full(n_events, 18, np.int64),
        "A": np.full(n_events, 40, np.int64),
        "cc": is_cc.astype(np.int32), "nc": (~is_cc).astype(np.int32),
        "qel": qel.astype(np.int32), "res": res.astype(np.int32),
        "dis": dis.astype(np.int32),
        "coh": np.zeros(n_events, np.int32), "mec": np.zeros(n_events, np.int32),
        "Ev": Ev, "pxv": np.zeros(n_events), "pyv": np.zeros(n_events), "pzv": Ev,
        "El": El, "pxl": rng.normal(0, 0.1, n_events),
        "pyl": rng.normal(0, 0.1, n_events), "pzl": El * 0.9,
        "Q2": Q2, "W": W, "x": xbj, "y": ybj,
        "vtxx": rng.normal(0, 5.0, n_events),            # cm
        "vtxy": rng.normal(0, 5.0, n_events),
        "vtxz": rng.uniform(-40, 40, n_events),
        "vtxt": np.zeros(n_events),
        "nf": np.array(nf, np.int32),
        "wght": np.linspace(0.5, 1.5, n_events),
        "pdgf": ak.Array(pdgf), "Ef": ak.Array(Ef),
        "pxf": ak.Array(pxf), "pyf": ak.Array(pyf), "pzf": ak.Array(pzf),
    }
    io.write_tree(path, data, tree="gst")
    return str(path)


@pytest.fixture(scope="session")
def synth_gst(tmp_path_factory):
    p = tmp_path_factory.mktemp("gst") / "events.gst.root"
    return write_synthetic_gst(p, seed=7)


def write_synthetic_nuhepmc(path, n_events=6, seed=0, gz=False):
    """A synthetic NuHepMC (HepMC3 ASCIIv3) file faithful to what the Achilles
    converter reads: E/U/V/P lines, GEV+MM units, NuHepMC statuses (4 = beam,
    11 = target, 1 = final state). Alternates CC (mu- out) and NC (nu_mu out)
    nu_mu events on Ar-40, beam along +z, vertex on the V line."""
    rng = np.random.default_rng(seed)
    lines = ["HepMC::Version 3.02.05", "HepMC::Asciiv3-START_EVENT_LISTING"]
    for i in range(n_events):
        enu = 2.0 + 0.25 * i                              # GeV
        cc = (i % 2 == 0)
        vx, vy, vz = rng.normal(0, 50, 3)                 # mm
        lines.append(f"E {i} 1 5")
        lines.append("U GEV MM")
        lines.append(f"V -1 0 [1,2] @ {vx:.3f} {vy:.3f} {vz:.3f} 0")
        # beam nu_mu (status 4), target Ar-40 (status 11)
        lines.append(f"P 1 0 14 0 0 {enu:.6f} {enu:.6f} 0 4")
        lines.append("P 2 0 1000180400 0 0 0 37.2247 37.2247 11")
        # outgoing lepton
        el = 0.6 * enu
        plz = 0.55 * enu; plx = 0.1 * enu
        lep = 13 if cc else 14
        m_l = 0.105658 if cc else 0.0
        lines.append(f"P 3 -1 {lep} {plx:.6f} 0 {plz:.6f} {el:.6f} {m_l:.6f} 1")
        # hadronic side: a proton and a pi+
        lines.append(f"P 4 -1 2212 {-plx:.6f} 0 {0.3*enu:.6f} {0.3*enu+0.938:.6f} 0.938272 1")
        lines.append(f"P 5 -1 211 0 0.05 {0.1*enu:.6f} {0.1*enu+0.14:.6f} 0.139570 1")
    lines.append("HepMC::Asciiv3-END_EVENT_LISTING")
    text = "\n".join(lines) + "\n"
    if gz:
        import gzip
        with gzip.open(path, "wt") as f:
            f.write(text)
    else:
        with open(path, "w") as f:
            f.write(text)
    return str(path)


@pytest.fixture(scope="session")
def synth_nuhepmc(tmp_path_factory):
    p = tmp_path_factory.mktemp("nuhepmc") / "events.hepmc"
    return write_synthetic_nuhepmc(p, seed=11)


@pytest.fixture(scope="session")
def synth_root(tmp_path_factory):
    """Standard synthetic run: 50 GeV e-, -z beam from z=650 cm, 2% leakage."""
    p = tmp_path_factory.mktemp("data") / "synth.root"
    return write_synthetic(p, seed=1)


@pytest.fixture(scope="session")
def synth_event(synth_root):
    """First event of synth_root, loaded once for scene/render tests."""
    from gdmltp import io
    return io.load_events(synth_root, entry_start=0, entry_stop=1)[0]


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
    io.write_tree(p, {"eventID": np.array([], np.int32),
                      "primaryE": np.array([]), "totalEdep": np.array([])})
    return str(p)


@pytest.fixture(scope="session")
def repo_root():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _force_lightweight_gdml(monkeypatch):
    """Keep the suite fast and parser-deterministic on any machine: the general
    tests use the built-in lightweight GDML parser regardless of whether
    pyg4ometry happens to be installed. The pyg4ometry path has its own
    dedicated test (test_geometry_pyg4ometry.py)."""
    monkeypatch.setenv("GDMLTP_GDML_PARSER", "lightweight")
