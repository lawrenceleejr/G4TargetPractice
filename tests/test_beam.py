"""Host-side beam sampler: distributions, Twiss phase space, rotation, file I/O.

All statistical, seed-deterministic, pure Python -- no Geant4/GENIE.
"""
import math
import numpy as np
import pytest

from gdmltp import config, beam
from gdmltp.masses import mass_mev


def _cfg(beam_raw, events=20000, seed=1):
    d = {"geometry": {"gdml": "g.gdml"}, "beam": beam_raw,
         "run": {"events": events, "seed": seed}}
    c = config.from_dict(d)
    c.validate()
    return c


# --- needs_sampling gating ------------------------------------------------- #
def test_fixed_beam_needs_no_sampling():
    c = _cfg({"particle": "e-", "position": "0 0 -20 cm", "direction": "0 0 1"})
    assert c.beam.needs_sampling() is False


def test_distribution_triggers_sampling():
    c = _cfg({"particle": "e-", "position": {"x": {"dist": "gauss", "sigma": "2 mm"}, "y": 0, "z": "-200 mm"}})
    assert c.beam.needs_sampling() is True


# --- independent distributions --------------------------------------------- #
def test_gauss_position_sigma_recovered():
    c = _cfg({"particle": "mu-", "momentum": "500 MeV/c",
              "position": {"x": {"dist": "gauss", "mean": "1 mm", "sigma": "3 mm"},
                           "y": {"dist": "uniform", "min": "-5 mm", "max": "5 mm"},
                           "z": "-200 mm"}})
    s = beam.sample(c, 40000, seed=2)
    assert s.pos[:, 0].mean() == pytest.approx(1.0, abs=0.1)
    assert s.pos[:, 0].std() == pytest.approx(3.0, abs=0.1)
    assert s.pos[:, 1].min() >= -5.0 and s.pos[:, 1].max() <= 5.0
    assert s.pos[:, 1].std() == pytest.approx(10.0 / math.sqrt(12), abs=0.1)  # uniform
    assert np.allclose(s.pos[:, 2], -200.0)


def test_energy_to_momentum_conversion():
    c = _cfg({"particle": "proton", "energy": {"mode": "mono", "value": "100 MeV"},
              "position": {"x": {"dist": "gauss", "sigma": "1 mm"}, "y": 0, "z": 0}})
    s = beam.sample(c, 1000, seed=1)
    m = mass_mev(2212)
    expect = math.sqrt((100.0 + m) ** 2 - m * m)
    assert np.allclose(np.linalg.norm(s.mom, axis=1), expect, atol=1e-3)


def test_momentum_gauss():
    c = _cfg({"particle": "mu-",
              "momentum": {"dist": "gauss", "mean": "500 MeV/c", "sigma": "10 MeV/c"},
              "position": {"x": {"dist": "gauss", "sigma": "1 mm"}, "y": 0, "z": 0}})
    s = beam.sample(c, 40000, seed=1)
    pmag = np.linalg.norm(s.mom, axis=1)
    assert pmag.mean() == pytest.approx(500.0, abs=0.5)
    assert pmag.std() == pytest.approx(10.0, abs=0.5)


def test_direction_slopes_and_rotation():
    # slopes around a central +z: mean direction ~ +z, slope sigma recovered
    c = _cfg({"particle": "e-", "momentum": "1 GeV/c", "direction": "0 0 1",
              "position": {"x": {"dist": "gauss", "sigma": "1 mm"}, "y": 0, "z": 0}})
    # add slope dists via a direction mapping
    c2 = config.from_dict({"geometry": {"gdml": "g.gdml"},
        "beam": {"particle": "e-", "momentum": "1 GeV/c",
                 "direction": {"xprime": {"dist": "gauss", "sigma": "10 mrad"}, "yprime": 0}},
        "run": {"events": 40000, "seed": 5}})
    c2.validate()
    s = beam.sample(c2, 40000, seed=5)
    slope_x = s.mom[:, 0] / s.mom[:, 2]
    assert slope_x.std() == pytest.approx(0.010, abs=5e-4)
    assert abs(s.mom[:, 1]).max() < 1e-6                # yprime fixed 0


def test_central_direction_rotation():
    c = _cfg({"particle": "mu-", "momentum": "500 MeV/c", "direction": "1 0 0",
              "position": {"x": {"dist": "gauss", "sigma": "1 mm"}, "y": 0, "z": 0}})
    s = beam.sample(c, 5000, seed=1)
    mean = s.mom.mean(axis=0)
    mean /= np.linalg.norm(mean)
    assert np.allclose(mean, [1, 0, 0], atol=1e-2)


# --- Twiss phase space ----------------------------------------------------- #
def test_twiss_covariance_matches_beam_matrix():
    c = _cfg({"particle": "proton", "twiss": {
        "x": {"alpha": -1.2, "beta": 5.0, "emittance": 3.0},
        "y": {"alpha": 0.4, "beta": 2.0, "emittance": 1.5},
        "p0": "800 MeV/c", "dp_over_p": 0.0}}, events=300000, seed=3)
    s = beam.sample(c, 300000, seed=3)
    for plane, tp in (("x", c.beam.twiss.x), ("y", c.beam.twiss.y)):
        i = 0 if plane == "x" else 1
        u = s.pos[:, i] / 1000.0                          # mm -> m
        uprime = s.mom[:, i] / s.mom[:, 2]                # slope [rad]
        cov = np.cov(np.vstack([u, uprime]))
        target = beam._beam_matrix(tp)
        assert np.allclose(cov, target, rtol=0.05, atol=1e-9), (plane, cov, target)


def test_twiss_momentum_spread_and_direction():
    c = _cfg({"particle": "proton", "twiss": {
        "x": {"alpha": 0, "beta": 1, "emittance": 1},
        "y": {"alpha": 0, "beta": 1, "emittance": 1},
        "p0": "1000 MeV/c", "dp_over_p": 0.03,
        "reference": {"position": "0 0 -1 m", "direction": "0 0 1"}}}, events=50000)
    s = beam.sample(c, 50000, seed=4)
    pmag = np.linalg.norm(s.mom, axis=1)
    assert pmag.mean() == pytest.approx(1000.0, rel=1e-3)
    assert (pmag.std() / 1000.0) == pytest.approx(0.03, abs=3e-3)
    assert np.allclose(s.pos[:, 2], -1000.0)              # ref z = -1 m in mm


# --- determinism + file I/O ------------------------------------------------ #
def test_determinism():
    c = _cfg({"particle": "mu-", "momentum": {"dist": "gauss", "mean": "500 MeV/c", "sigma": "5 MeV/c"},
              "position": {"x": {"dist": "gauss", "sigma": "2 mm"}, "y": 0, "z": 0}}, events=200)
    a = beam.sample(c, 200, seed=42)
    b = beam.sample(c, 200, seed=42)
    assert np.allclose(a.pos, b.pos) and np.allclose(a.mom, b.mom)


def test_beam_file_roundtrip(tmp_path):
    c = _cfg({"particle": "mu-", "momentum": "500 MeV/c",
              "position": {"x": {"dist": "gauss", "sigma": "2 mm"}, "y": 0, "z": "-200 mm"}}, events=50)
    s = beam.sample(c, 50, seed=1)
    p = tmp_path / "beam.dat"
    beam.write_beam_file(s, p)
    rows = beam.read_beam_file(p)
    assert len(rows) == 50
    name, pos, mom = rows[0]
    assert name == "mu-"
    assert pos == pytest.approx(tuple(s.pos[0]), abs=1e-3)
    assert mom == pytest.approx(tuple(s.mom[0]), abs=1e-3)


def test_rotate_uz_maps_z_to_axis():
    v = np.array([[0.0, 0.0, 1.0]])
    out = beam.rotate_uz(v, np.array([1.0, 0.0, 0.0]))
    assert np.allclose(out[0], [1, 0, 0], atol=1e-9)
