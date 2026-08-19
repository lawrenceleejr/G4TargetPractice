"""Achilles backend: NuHepMC parsing/conversion, job spec, run card, display.

Everything here runs with zero Achilles/HepMC3 dependency: the converter reads a
synthetic NuHepMC ASCII fixture and must satisfy the same schema guard as the
other backends; the run-card renderer and driver are exercised with mocks.
"""
import importlib.util
import json
import math

import numpy as np
import pytest

from gdmltp import io, config, scene
from gdmltp.backends import achilles, achilles_convert


# --- parser ----------------------------------------------------------------- #
def test_parse_nuhepmc_events(synth_nuhepmc):
    evs = achilles_convert.parse_nuhepmc(synth_nuhepmc)
    assert len(evs) == 6
    e0 = evs[0]
    assert e0["vertex"] is not None
    statuses = [p[6] for p in e0["particles"]]
    assert 4 in statuses and 11 in statuses and statuses.count(1) == 3


def test_parse_nuhepmc_gz(tmp_path):
    import sys
    sys.path.insert(0, str(tmp_path.parent))
    from conftest import write_synthetic_nuhepmc
    p = write_synthetic_nuhepmc(tmp_path / "ev.hepmc.gz", n_events=2, gz=True)
    assert len(achilles_convert.parse_nuhepmc(p)) == 2


# --- converter: schema + physics ------------------------------------------- #
def test_convert_schema_complete(synth_nuhepmc, tmp_path):
    out = str(tmp_path / "output.root")
    achilles_convert.convert(synth_nuhepmc, out)
    brs = set(io.available_branches(out))
    for b in io.SCALAR_BRANCHES + io.TRK_BRANCHES + io.STEP_BRANCHES + io.NU_BRANCHES:
        assert b in brs, f"converted file missing {b}"
    for b in io.TRK_OPTIONAL_BRANCHES:
        assert b in brs, f"converted file missing optional {b}"


def test_convert_kinematics_exact(synth_nuhepmc, tmp_path):
    """Q2/W/x/y must match the EventAction.cc formulas applied to the fixture's
    known four-vectors (event 0: CC, Enu = 2 GeV)."""
    import uproot
    out = str(tmp_path / "output.root")
    achilles_convert.convert(synth_nuhepmc, out)
    t = uproot.open(out)["tree"]

    enu = 2000.0                                   # MeV
    el = 0.6 * enu
    plx, plz = 0.1 * enu, 0.55 * enu
    q0 = enu - el
    qv = np.array([0 - plx, 0.0, enu - plz])
    Q2 = qv @ qv - q0 * q0
    M = achilles_convert.NUCLEON_MASS_MEV
    W = math.sqrt(M * M + 2 * M * q0 - Q2)

    assert t["primaryE"].array(library="np")[0] == pytest.approx(enu)
    assert t["nu_q0"].array(library="np")[0] == pytest.approx(q0)
    assert t["nu_Q2"].array(library="np")[0] == pytest.approx(Q2, rel=1e-6)
    assert t["nu_W"].array(library="np")[0] == pytest.approx(W, rel=1e-6)
    assert t["nu_x"].array(library="np")[0] == pytest.approx(Q2 / (2 * M * q0), rel=1e-6)
    assert t["nu_y"].array(library="np")[0] == pytest.approx(q0 / enu, rel=1e-6)


def test_convert_cc_nc_and_target(synth_nuhepmc, tmp_path):
    import uproot
    out = str(tmp_path / "output.root")
    achilles_convert.convert(synth_nuhepmc, out)
    t = uproot.open(out)["tree"]
    cc = t["nu_isCC"].array(library="np")
    nc = t["nu_isNC"].array(library="np")
    assert list(cc) == [True, False] * 3
    assert list(nc) == [False, True] * 3
    assert np.all(t["nu_targetZ"].array(library="np") == 18)
    assert np.all(t["nu_targetA"].array(library="np") == 40)
    lep = t["nu_outLeptonPDG"].array(library="np")
    assert lep[0] == 13 and lep[1] == 14


def test_convert_reads_back_and_displays(synth_nuhepmc, tmp_path):
    """The whole point: Achilles events flow through the same io -> scene ->
    (web/png/blender) pipeline, with visible momentum rays."""
    out = str(tmp_path / "output.root")
    achilles_convert.convert(synth_nuhepmc, out)
    evs = io.load_events(out)
    sc = scene.build_scene([], evs[0])
    assert len(sc.tracks) == 3
    lengths = [float(np.linalg.norm(t.polyline[-1] - t.polyline[0])) for t in sc.tracks]
    assert all(l > 1.0 for l in lengths), f"momentum rays must be visible: {lengths}"
    # nu vertex marker present
    assert any(v.kind == "interaction" for v in sc.vertices)


def test_convert_beam_replay(synth_nuhepmc, tmp_path):
    import uproot
    n = 6
    entries = [("nu_mu", (5.0, 0.0, -10.0), (0.0, 800.0, 0.0)) for _ in range(n)]  # +y beam
    out = str(tmp_path / "output.root")
    achilles_convert.convert(synth_nuhepmc, out, beam=entries)
    t = uproot.open(out)["tree"]
    assert np.allclose(t["nu_vertexX"].array(library="np"), 5.0)
    assert np.allclose(t["primaryStartPy"].array(library="np"), 800.0)
    # lepton pz (local, along beam) landed on +y
    lep_py = t["nu_outLeptonPy"].array(library="np")
    assert lep_py[0] == pytest.approx(0.55 * 2000.0, rel=1e-6)


# --- backend / job spec ------------------------------------------------------ #
def test_probe_pdg_names_and_ids():
    assert achilles.probe_pdg("nu_mu") == 14
    assert achilles.probe_pdg("e-") == 11
    assert achilles.probe_pdg(-12) == -12
    with pytest.raises(config.ConfigError, match="projectile"):
        achilles.probe_pdg("proton")
    with pytest.raises(config.ConfigError, match="projectile"):
        achilles.probe_pdg(2212)


def test_isotope_name():
    assert achilles.isotope_name(1000180400) == "40Ar"
    assert achilles.isotope_name(1000060120) == "12C"
    with pytest.raises(config.ConfigError, match="symbol"):
        achilles.isotope_name(1000922380)      # U not in the table yet


def test_achilles_prepare_writes_job(repo_root, tmp_path):
    from gdmltp import backends
    cfg = config.RunConfig(
        generator="achilles", gdml=str(repo_root / "gdml" / "liquid_argon_1m3.gdml"),
        beam=config.Beam(particle="nu_mu",
                         energy=config.Energy(mode="mono", value="2.0 GeV")),
        run=config.RunSettings(events=500, seed=9),
        achilles={"cascade": True})
    cfg.validate()
    b = backends.get("achilles")
    prep = b.prepare(cfg, tmp_path)
    assert prep.argv == [achilles.JOB_FILE]
    assert prep.image.endswith("-achilles:main")
    job = json.loads((tmp_path / achilles.JOB_FILE).read_text())
    assert job["probe"] == 14
    assert job["nucleus"] == "40Ar"
    assert job["events"] == 500 and job["cascade"] is True


def test_achilles_electron_beam(repo_root, tmp_path):
    from gdmltp import backends
    cfg = config.RunConfig(
        generator="achilles", gdml=str(repo_root / "gdml" / "graphite_target.gdml"),
        beam=config.Beam(particle="e-",
                         energy=config.Energy(mode="mono", value="1108 MeV")),
        run=config.RunSettings(events=100))
    cfg.validate()
    backends.get("achilles").prepare(cfg, tmp_path)
    job = json.loads((tmp_path / achilles.JOB_FILE).read_text())
    assert job["probe"] == 11
    assert job["nucleus"] == "12C"


# --- driver run-card rendering ----------------------------------------------- #
def _load_driver(repo_root):
    spec = importlib.util.spec_from_file_location(
        "run_achilles", str(repo_root / "achilles" / "run_achilles.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_run_card_neutrino(repo_root):
    mod = _load_driver(repo_root)
    job = {"probe": 14, "nucleus": "40Ar", "cascade": True, "seed": 5,
           "processes": None, "options": {}}
    card = mod.render_run_card(job, 250, 2000.0)
    assert card["Main"]["NEvents"] == 250
    assert card["Main"]["Output"]["Format"] == "NuHepMC"
    assert card["Nucleus"]["Name"] == "40Ar"
    assert card["Beams"][0]["Beam"]["PID"] == 14
    assert card["Beams"][0]["Beam"]["Beam Params"]["Energy"] == 2000.0
    # CC + NC processes by default for a neutrino probe
    assert {"Leptons": [14, [13]]} in card["Processes"]
    assert {"Leptons": [14, [14]]} in card["Processes"]
    assert card["Initialize"]["Seed"] == 5


def test_render_run_card_electron_and_overrides(repo_root):
    mod = _load_driver(repo_root)
    job = {"probe": 11, "nucleus": "12C", "cascade": False,
           "processes": None, "options": {"Cascade": {"Step": 0.04}}}
    card = mod.render_run_card(job, 10, 1108.0)
    assert card["Processes"] == [{"Leptons": [11, [11]]}]
    assert card["Cascade"]["Run"] is False
    assert card["Cascade"]["Step"] == 0.04     # raw override merged in


def test_driver_runs_and_converts(repo_root, tmp_path, monkeypatch):
    mod = _load_driver(repo_root)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        # simulate achilles writing its output next to the card
        (tmp_path / "achilles_events.hepmc").write_text("HepMC::Version 3\n")
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    import gdmltp.backends.achilles_convert as ac
    converted = {}
    monkeypatch.setattr(ac, "convert",
                        lambda src, out, **kw: converted.update(src=src, out=out))

    job = {"generator": "achilles", "probe": 14, "nucleus": "40Ar",
           "flux": {"mode": "mono", "value": "2 GeV"}, "events": 50,
           "output": "output.root", "seed": 1, "cascade": True,
           "processes": None, "run_card": None, "options": {}}
    jp = tmp_path / "achilles_job.json"
    jp.write_text(json.dumps(job))
    assert mod.run(str(jp)) == 0
    assert calls[0][0] == "achilles"
    assert converted["out"].endswith("output.root")
    # the rendered card exists and parses
    import yaml
    card = yaml.safe_load((tmp_path / "achilles_run.yml").read_text())
    assert card["Main"]["NEvents"] == 50
