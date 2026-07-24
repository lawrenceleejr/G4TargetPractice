"""The decay backend: BSM projectiles decayed in flight on the host.

Physics is validated against exact results: two-body momenta, N-body
conservation and mass shells, the Michel spectrum from the vA matrix element
(muon decay is the closure test -- same |M|^2 pairing), exponential decay
lengths, and the truncated-exponential forced-fiducial weights.
"""
import math

import numpy as np
import pytest
import yaml

from gdmltp import config, decay
from gdmltp.config import ConfigError


def _cfg(text):
    cfg = config.from_dict(yaml.safe_load(text))
    cfg.validate()
    return cfg


HNL = """
generator: decay
geometry: {gdml: g.gdml}
beam:
  pdg: 9900014
  mass: "1.0 GeV"
  energy: {mode: mono, value: "500 GeV"}
  position: "0 0 -50 m"
  direction: "0 0 1"
decay:
  ctau: "1 m"
  channels:
    - {to: [13, 211], br: 0.6}
    - {to: [14, 13, -13], br: 0.4, model: vA}
  fiducial: {z: ["-2.5 m", "2.5 m"]}
run: {events: 500, seed: 7}
"""


# --- rest-frame kinematics ---------------------------------------------------- #

def test_two_body_exact():
    rng = np.random.default_rng(2)
    M, m1, m2 = 1000.0, 105.658, 139.570
    p4 = decay.two_body(M, m1, m2, 3000, rng)
    tot = p4.sum(axis=1)
    assert np.allclose(tot[:, 0], M)
    assert np.abs(tot[:, 1:]).max() < 1e-9
    pstar = math.sqrt((M**2 - (m1 + m2)**2) * (M**2 - (m1 - m2)**2)) / (2 * M)
    assert np.allclose(np.linalg.norm(p4[:, 0, 1:], axis=1), pstar)
    # isotropy: <cos theta> ~ 0
    cz = p4[:, 0, 3] / pstar
    assert abs(cz.mean()) < 0.06


@pytest.mark.parametrize("M,ms", [
    (1000.0, [0.0, 0.0, 0.0]),                       # all massless (HNL -> 3nu)
    (1000.0, [0.0, 105.658, 105.658]),               # N -> nu mu mu
    (1968.0, [493.677, 139.57, 139.57, 139.57]),     # 4-body
])
def test_nbody_conservation_and_mass_shells(M, ms):
    rng = np.random.default_rng(3)
    ch = decay.Channel(pdgs=[0] * len(ms), br=1.0, model="phase_space",
                       masses=list(ms))
    p4 = decay.rest_frame_decay(M, ch, 5000, rng)
    tot = p4.sum(axis=1)
    assert np.abs(tot[:, 0] - M).max() < 1e-6 * M
    assert np.abs(tot[:, 1:]).max() < 1e-6 * M
    for i, m in enumerate(ms):
        m2 = p4[:, i, 0] ** 2 - (p4[:, i, 1:] ** 2).sum(axis=1)
        assert np.abs(np.sqrt(np.abs(m2)) - m).max() < 1e-3


def test_vA_reproduces_michel_spectrum():
    """Muon decay [e, nu_e-bar, nu_mu] through the generic vA weight must give
    the Michel spectrum x^2(3-2x): the pairing convention closure test."""
    rng = np.random.default_rng(4)
    M = 105.658
    ch = decay.Channel(pdgs=[11, -12, 14], br=1.0, model="vA",
                       masses=[0.511, 0.0, 0.0])
    p4 = decay.rest_frame_decay(M, ch, 60000, rng)
    x = 2 * p4[:, 0, 0] / M
    assert x.mean() == pytest.approx(0.7, rel=0.01)          # <x> = 7/10
    # shape at quantiles of the exact CDF (x^3 - x^4/2, normalized to 1/2)
    cdf = lambda q: 2 * (q**3 - q**4 / 2)
    for q in (0.3, 0.5, 0.7, 0.9):
        assert (x < q).mean() == pytest.approx(cdf(q), abs=0.01)


def test_phase_space_differs_from_vA():
    """Flat 3-body phase space with (near-)massless daughters: the Dalitz
    density gives pdf(x) = 2x, so <x> = 2/3 and P(x < 0.5) = 1/4 -- distinct
    from the vA Michel shape (<x> = 0.7, P(x < 0.5) ~ 0.19)."""
    rng = np.random.default_rng(5)
    M = 105.658
    ps = decay.Channel(pdgs=[11, -12, 14], br=1.0, model="phase_space",
                       masses=[0.511, 0.0, 0.0])
    x_ps = 2 * decay.rest_frame_decay(M, ps, 30000, rng)[:, 0, 0] / M
    assert x_ps.mean() == pytest.approx(2.0 / 3.0, abs=0.01)
    assert (x_ps < 0.5).mean() == pytest.approx(0.25, abs=0.01)


# --- flight and vertex --------------------------------------------------------- #

def test_free_decay_length_is_exponential():
    rng = np.random.default_rng(6)
    n = 20000
    pos = np.zeros((n, 3))
    mom = np.tile([0.0, 0.0, 5e5], (n, 1))          # 500 GeV/c
    mass, ctau = 1000.0, 1000.0                     # 1 GeV, 1 m
    lam = (5e5 / mass) * ctau                       # 500 m
    v, t, w = decay.sample_flight(pos, mom, mass, ctau, None, rng)
    s = v[:, 2]
    assert np.all(w == 1.0)
    assert s.mean() == pytest.approx(lam, rel=0.02)
    assert s.std() == pytest.approx(lam, rel=0.03)  # exponential: std = mean
    # time: s = beta*c*t
    beta = 5e5 / math.sqrt(5e5**2 + mass**2)
    assert np.allclose(s, beta * decay.C_MM_PER_NS * t)


def test_forced_fiducial_weight_matches_analytic():
    rng = np.random.default_rng(7)
    n = 5000
    pos = np.tile([0.0, 0.0, -50000.0], (n, 1))     # start at z = -50 m
    mom = np.tile([0.0, 0.0, 5e5], (n, 1))
    mass, ctau = 1000.0, 1000.0
    lam = (5e5 / mass) * ctau
    fid = {"z": ["-2.5 m", "2.5 m"]}
    v, t, w = decay.sample_flight(pos, mom, mass, ctau, fid, rng)
    assert v[:, 2].min() >= -2500.0 - 1e-6
    assert v[:, 2].max() <= 2500.0 + 1e-6
    expect = math.exp(-47500.0 / lam) - math.exp(-52500.0 / lam)
    assert np.allclose(w, expect)


def test_fiducial_never_crossed_is_an_error():
    rng = np.random.default_rng(8)
    pos = np.zeros((10, 3))
    mom = np.tile([0.0, 0.0, 5e5], (10, 1))         # +z beam
    with pytest.raises(ConfigError, match="never cross"):
        decay.sample_flight(pos, mom, 1000.0, 1000.0,
                            {"z": ["-2 m", "-1 m"]}, rng)   # window behind the beam


def test_transverse_beam_needs_path_fiducial():
    rng = np.random.default_rng(9)
    pos = np.zeros((10, 3))
    mom = np.tile([5e5, 0.0, 0.0], (10, 1))         # +x beam
    with pytest.raises(ConfigError, match="path"):
        decay.sample_flight(pos, mom, 1000.0, 1000.0, {"z": ["0 m", "1 m"]}, rng)
    v, _, w = decay.sample_flight(pos, mom, 1000.0, 1000.0,
                                  {"path": ["1 m", "2 m"]}, rng)
    assert (v[:, 0] >= 1000.0 - 1e-6).all() and (v[:, 0] <= 2000.0 + 1e-6).all()


# --- config validation ---------------------------------------------------------- #

def test_decay_requires_ctau_and_channels():
    with pytest.raises(ConfigError, match="ctau"):
        _cfg("""
generator: decay
geometry: {gdml: g.gdml}
beam: {pdg: 9900014, mass: "1 GeV"}
decay: {channels: [{to: [13, 211]}]}
""")
    with pytest.raises(ConfigError, match="channels"):
        _cfg("""
generator: decay
geometry: {gdml: g.gdml}
beam: {pdg: 9900014, mass: "1 GeV"}
decay: {ctau: "1 m"}
""")


def test_vA_needs_three_daughters():
    with pytest.raises(ConfigError, match="3 daughters"):
        _cfg("""
generator: decay
geometry: {gdml: g.gdml}
beam: {pdg: 9900014, mass: "1 GeV"}
decay:
  ctau: "1 m"
  channels: [{to: [13, 211], model: vA}]
""")


def test_daughters_heavier_than_parent_rejected():
    cfg = _cfg("""
generator: decay
geometry: {gdml: g.gdml}
beam: {pdg: 9900014, mass: "0.2 GeV"}
decay:
  ctau: "1 m"
  channels: [{to: [13, -13]}]
run: {events: 10, seed: 1}
""")
    with pytest.raises(ConfigError, match="parent mass"):
        decay.generate(cfg, 10, seed=1)


def test_unknown_parent_mass_rejected():
    cfg = _cfg("""
generator: decay
geometry: {gdml: g.gdml}
beam: {pdg: 9900014}
decay:
  ctau: "1 m"
  channels: [{to: [13, 211]}]
run: {events: 10, seed: 1}
""")
    with pytest.raises(ConfigError, match="beam.mass"):
        decay.generate(cfg, 10, seed=1)


def test_lifetime_alternative_to_ctau():
    cfg = _cfg("""
generator: decay
geometry: {gdml: g.gdml}
beam: {pdg: 9900014, mass: "1 GeV", energy: {mode: mono, value: "500 GeV"}}
decay:
  lifetime: "3.335640952 ns"
  channels: [{to: [13, 211]}]
run: {events: 10, seed: 1}
""")
    assert decay._ctau_mm(cfg.decay, 1000.0) == pytest.approx(1000.0, rel=1e-6)


# --- end to end ----------------------------------------------------------------- #

def test_generate_and_validate(tmp_path):
    from gdmltp import validate as val
    cfg = _cfg(HNL)
    ev = decay.generate(cfg, 500, seed=7)
    out = tmp_path / "output.root"
    decay.write_output(ev, out)
    report, code = val.validate(str(out), strict=True)
    assert code == 0, report
    assert "eventWeight in (0, 1]" in report


def test_generate_determinism_and_channel_mix():
    cfg = _cfg(HNL)
    a = decay.generate(cfg, 400, seed=9)
    b = decay.generate(cfg, 400, seed=9)
    assert np.array_equal(a["vertex"], b["vertex"])
    assert a["daughters_pdg"] == b["daughters_pdg"]
    two = np.mean([len(p) == 2 for p in a["daughters_pdg"]])
    assert two == pytest.approx(0.6, abs=0.08)
    # daughters conserve the parent four-momentum (vertex-level exactness)
    for i in range(20):
        p4 = np.asarray(a["daughters_p4"][i])
        e_parent = a["e_parent"][i]
        assert p4[:, 0].sum() == pytest.approx(e_parent, rel=1e-9)
        assert np.allclose(p4[:, 1:].sum(axis=0), a["mom"][i], rtol=1e-9, atol=1e-6)


def test_run_config_host_backend(tmp_path):
    """The decay backend runs entirely on the host: a full (non-dry) run needs
    no Docker and lands output.root in the outdir."""
    from gdmltp import run as runmod
    gdml = tmp_path / "g.gdml"
    gdml.write_text("<gdml/>")
    cfg = _cfg(HNL)
    cfg.gdml = str(gdml)
    runmod.run_config(cfg, outdir=tmp_path)
    assert (tmp_path / "output.root").exists()


def test_handoff_event_file_from_decay(tmp_path):
    """The transport hand-off must take the vertex from primaryEnd* and carry
    the decay time on the E lines."""
    from gdmltp import handoff
    cfg = _cfg(HNL)
    ev = decay.generate(cfg, 50, seed=3)
    out = tmp_path / "output.root"
    decay.write_output(ev, out)
    n = handoff.write_event_file(str(out), tmp_path / "events.dat")
    assert n == 50
    text = (tmp_path / "events.dat").read_text()
    first_e = next(l for l in text.splitlines() if l.startswith("E "))
    assert len(first_e.split()) == 6          # E n vx vy vz t
    parsed = handoff.read_event_file(tmp_path / "events.dat")
    assert len(parsed) == 50
    vx, vy, vz = parsed[0][0]
    assert vz == pytest.approx(ev["vertex"][0][2], rel=1e-5)


def test_merge_grafts_decay_scalars(tmp_path):
    """merge_nu_block on a decay vertex file grafts primary identity,
    primaryEnd (decay vertex), eventWeight, and decayT onto the transported
    tree."""
    from gdmltp import handoff
    from conftest import write_synthetic
    cfg = _cfg(HNL)
    ev = decay.generate(cfg, 30, seed=4)
    vertex = tmp_path / "vertex.root"
    decay.write_output(ev, vertex)
    transported = write_synthetic(tmp_path / "transported.root", n_events=30, seed=5)
    merged = tmp_path / "merged.root"
    handoff.merge_nu_block(str(transported), str(vertex), str(merged))
    import uproot
    with uproot.open(merged) as f:
        t = f["tree"]
        assert t["primaryPDG"].array(library="np")[0] == 9900014
        assert "eventWeight" in {k.split(";")[0] for k in t.keys()}
        assert np.allclose(t["primaryEndZ"].array(library="np"),
                           ev["vertex"][:, 2])
        assert np.allclose(t["decayT"].array(library="np"), ev["t_ns"])


def test_cli_generator_choice():
    from gdmltp import cli
    p, _ = cli._build_parser()
    args = p.parse_args(["run", "--generator", "decay", "--gdml", "g.gdml"])
    assert args.generator == "decay"


def test_display_scene_from_decay_file(tmp_path):
    """Displaced-decay events display through the existing vertex-level path
    (momentum rays from the decay point)."""
    from gdmltp import io, scene
    cfg = _cfg(HNL)
    ev = decay.generate(cfg, 5, seed=11)
    out = tmp_path / "output.root"
    decay.write_output(ev, out)
    events = io.load_events(str(out), entry_start=0, entry_stop=1)
    sc = scene.build_scene([], events[0])
    assert sc.tracks, "daughter tracks should be drawable"
