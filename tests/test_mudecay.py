"""Muon-decay neutrino spectrum energy modes (mudecay_numu / mudecay_nue) --
the neutrino-factory / muon-collider "neutrino slice" flux (arXiv:2412.14115).

The exact angle-integrated lab spectra in y = E/E_mu (unpolarized):
  nu_mu / anti-nu_mu: 5/3 - 3y^2 + 4/3 y^3   -> <y> = 0.35
  nu_e  / anti-nu_e : 2 - 6y^2 + 4y^3        -> <y> = 0.30
"""
import numpy as np
import pytest

from gdmltp import beam as beammod, config
from gdmltp.config import ConfigError


def _cfg(yaml_text, tmp_path=None):
    import yaml
    cfg = config.from_dict(yaml.safe_load(yaml_text))
    cfg.validate()
    return cfg


# --- config ---------------------------------------------------------------- #

def test_mudecay_modes_are_valid(tmp_path):
    cfg = _cfg("""
generator: genie
geometry: {gdml: g.gdml}
beam:
  particle: nu_mu
  energy: {mode: mudecay_numu, value: "5 TeV"}
""", tmp_path)
    assert cfg.beam.energy.mode == "mudecay_numu"
    assert cfg.beam.energy.value == "5 TeV"


def test_unknown_mode_still_rejected(tmp_path):
    with pytest.raises(ConfigError, match="energy mode"):
        _cfg("""
geometry: {gdml: g.gdml}
beam:
  energy: {mode: mudecay_nutau, value: "1 TeV"}
""", tmp_path)


def test_mudecay_forces_host_sampling_but_not_phase_space(tmp_path):
    cfg = _cfg("""
geometry: {gdml: g.gdml}
beam:
  particle: nu_mu
  energy: {mode: mudecay_numu, value: "5 TeV"}
""", tmp_path)
    assert cfg.beam.needs_sampling()                  # no native g4sim command
    assert not cfg.beam.needs_phase_space_sampling()  # genie can map it natively


# --- sampler ---------------------------------------------------------------- #

def _energies(mode, emu="5 TeV", n=40000, seed=7):
    e = config.Energy(mode=mode, value=emu)
    rng = np.random.default_rng(seed)
    return beammod._sample_energy_mev(e, n, rng)


def test_numu_spectrum_moments():
    ene = _energies("mudecay_numu")            # MeV, E_mu = 5e6 MeV
    y = ene / 5e6
    assert 0.0 <= y.min() and y.max() <= 1.0
    assert y.mean() == pytest.approx(0.35, rel=0.02)
    # median of the exact CDF (5/3 y - y^3 + y^4/3 = 1/2) is ~0.317
    assert np.median(y) == pytest.approx(0.317, abs=0.02)


def test_nue_spectrum_moments():
    ene = _energies("mudecay_nue")
    y = ene / 5e6
    assert 0.0 <= y.min() and y.max() <= 1.0
    assert y.mean() == pytest.approx(0.30, rel=0.02)


def test_spectra_differ_and_are_deterministic():
    a = _energies("mudecay_numu", seed=3)
    b = _energies("mudecay_numu", seed=3)
    assert np.array_equal(a, b)
    # nu_mu spectrum is harder than nu_e-bar on average
    assert _energies("mudecay_numu", seed=5).mean() > _energies("mudecay_nue", seed=5).mean()


def test_sample_full_beam(tmp_path):
    """End to end through beam.sample: neutrino mass 0 -> |p| = E."""
    cfg = _cfg("""
generator: genie
geometry: {gdml: g.gdml}
beam:
  particle: nu_mu
  energy: {mode: mudecay_numu, value: "3 TeV"}
run: {events: 500, seed: 11}
""", tmp_path)
    s = beammod.sample(cfg, 500, seed=11)
    pmag = np.linalg.norm(s.mom, axis=1)
    assert pmag.max() <= 3e6 + 1e-6
    assert pmag.mean() == pytest.approx(0.35 * 3e6, rel=0.05)


# --- genie flux mapping ------------------------------------------------------ #

def test_genie_flux_args_mudecay():
    from gdmltp.backends.genie import flux_gevgen_args, flux_emax_gev
    flux = {"mode": "mudecay_numu", "value": "5 TeV", "min": None, "max": None, "bins": []}
    args, approx = flux_gevgen_args(flux)
    assert not approx                          # exact, not nominal-energy fallback
    assert args[args.index("-e") + 1] == "5,5000"
    expr = args[args.index("-f") + 1]
    assert "pow((x/5000)" in expr and expr.startswith("5./3.")
    assert flux_emax_gev(flux) == 5000.0

    flux["mode"] = "mudecay_nue"
    args, approx = flux_gevgen_args(flux)
    assert not approx
    assert args[args.index("-f") + 1].startswith("2.-6.")


def test_genie_flux_emax_other_modes():
    from gdmltp.backends.genie import flux_emax_gev
    assert flux_emax_gev({"mode": "mono", "value": "2 GeV"}) == 2.0
    assert flux_emax_gev({"mode": "exp", "value": "2 GeV", "max": "20 GeV"}) == 20.0
    assert flux_emax_gev({"mode": "arb", "bins": [
        {"value": "1 GeV"}, {"value": "750 GeV"}]}) == 750.0
    assert flux_emax_gev({"mode": "gauss", "value": "10 GeV", "sigma": "2 GeV"}) == 20.0


def test_genie_prepare_mudecay_uses_native_flux(tmp_path):
    """A pure mudecay spectrum (no phase-space dists) must NOT write a beam
    file -- gevgen's functional flux is exact and O(1) instead of O(N)."""
    from gdmltp.backends.genie import GenieBackend
    import json
    cfg = _cfg("""
generator: genie
geometry: {gdml: g.gdml}
beam:
  particle: nu_mu
  energy: {mode: mudecay_numu, value: "5 TeV"}
run: {events: 100, seed: 1}
genie: {target: 1000741840}
""", tmp_path)
    cfg.gdml = str(tmp_path / "g.gdml"); (tmp_path / "g.gdml").write_text("<gdml/>")
    prep = GenieBackend().prepare(cfg, tmp_path)
    job = json.loads((tmp_path / "genie_job.json").read_text())
    assert "beam_file" not in job
    assert job["flux"]["mode"] == "mudecay_numu"
    assert job["flux_emax_gev"] == 5000.0
    assert job["target"] == 1000741840


def test_genie_prepare_slice_config_writes_beam_file(tmp_path):
    """mudecay + phase-space dists (the MAIA slice configs) -> per-event replay."""
    import json
    from gdmltp.backends.genie import GenieBackend
    cfg = _cfg("""
generator: genie
geometry: {gdml: g.gdml}
beam:
  particle: nu_mu
  energy: {mode: mudecay_numu, value: "5 TeV"}
  position:
    x: {dist: uniform, min: "-25 cm", max: "25 cm"}
    y: {dist: gauss, sigma: "5 mm"}
    z: {dist: uniform, min: "100 cm", max: "595 cm"}
  direction:
    central: "0 0 1"
    xprime: {dist: gauss, sigma: "10 mrad"}
    yprime: {dist: gauss, sigma: "0.1 mrad"}
run: {events: 20, seed: 2}
genie: {target: 1000741840}
""", tmp_path)
    cfg.gdml = str(tmp_path / "g.gdml"); (tmp_path / "g.gdml").write_text("<gdml/>")
    GenieBackend().prepare(cfg, tmp_path)
    job = json.loads((tmp_path / "genie_job.json").read_text())
    assert job["beam_file"] == "beam.dat"
    entries = beammod.read_beam_file(tmp_path / "beam.dat")
    assert len(entries) == 20
    zs = [pos[2] for _, pos, _ in entries]
    assert 1000.0 <= min(zs) and max(zs) <= 5950.0       # mm
    es = [np.linalg.norm(mom) for _, _, mom in entries]
    assert max(es) <= 5e6


# --- geant4 path -------------------------------------------------------------- #

def test_geant4_mudecay_goes_through_beam_file(tmp_path):
    from gdmltp.backends.geant4 import Geant4Backend
    cfg = _cfg("""
generator: geant4
geometry: {gdml: g.gdml}
beam:
  particle: nu_mu
  energy: {mode: mudecay_numu, value: "1 TeV"}
run: {events: 50, seed: 3}
""", tmp_path)
    cfg.gdml = str(tmp_path / "g.gdml"); (tmp_path / "g.gdml").write_text("<gdml/>")
    Geant4Backend().prepare(cfg, tmp_path)
    mac = next(tmp_path.glob("*.mac")).read_text()
    assert "/gun/beamFile" in mac
    assert (tmp_path / "beam.dat").exists()


# --- driver spline reach ------------------------------------------------------ #

def test_spline_emax(repo_root):
    import importlib.util
    path = repo_root / "genie" / "run_genie.py"
    spec = importlib.util.spec_from_file_location("run_genie_t", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.spline_emax_gev({"flux_emax_gev": 2.0}) == 100.0        # floor
    assert mod.spline_emax_gev({"flux_emax_gev": 5000.0}) == 5000.0
    assert mod.spline_emax_gev({}, beam_energies_gev=[1.0, 4200.5]) == 4201.0
