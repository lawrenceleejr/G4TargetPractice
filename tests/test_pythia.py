"""Pythia 8 backend: job spec, command-file rendering, HepMC3 conversion.

Zero Pythia dependency: the card renderer and driver run with mocks, and the
converter reads a synthetic Pythia-style HepMC3 fixture (standard HepMC statuses
and NO NuHepMC status-11 target particle -- Pythia collides with a free nucleon
and records no target, which is exactly what the converter's target_pdg fallback
is for). The real Pythia run is covered by the non-gating pythia CI smoke.
"""
import importlib.util
import json

import pytest

from gdmltp import io, config
from gdmltp.backends import pythia, achilles_convert
from gdmltp.config import ConfigError


def _load_driver(repo_root):
    path = repo_root / "pythia" / "run_pythia.py"
    spec = importlib.util.spec_from_file_location("run_pythia", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- probe / target resolution ---------------------------------------------- #
def test_probe_pdg_names_and_ids():
    assert pythia.probe_pdg("nu_mu") == 14
    assert pythia.probe_pdg("anti_nu_mu") == -14
    assert pythia.probe_pdg("e-") == 11
    assert pythia.probe_pdg(2212) == 2212          # explicit PDG passes through
    with pytest.raises(ConfigError, match="does not know"):
        pythia.probe_pdg("unobtainium")


def test_nucleon_reduction():
    """Pythia collides with ONE free nucleon: a nuclear target is reduced to the
    majority nucleon (W-184 is neutron-rich, Ar-40/C-12 are Z=N)."""
    assert pythia.nucleon_pdg(1000741840) == 2112     # W-184: N=110 > Z=74
    assert pythia.nucleon_pdg(1000060120) == 2212     # C-12: Z=N -> proton
    assert pythia.nucleon_pdg(1000180400) == 2112     # Ar-40: N=22 > Z=18
    assert pythia.nucleon_pdg(2212) == 2212
    assert pythia.nucleon_pdg(2112) == 2112
    with pytest.raises(ConfigError, match="nucleon"):
        pythia.nucleon_pdg(42)


# --- process presets -------------------------------------------------------- #
def test_dis_preset_is_weak_boson_exchange():
    lines = pythia.preset_settings("dis", 14)
    joined = "\n".join(lines)
    assert "WeakBosonExchange:ff2ff(t:W) = on" in joined      # CC
    assert "WeakBosonExchange:ff2ff(t:gmZ) = on" in joined     # NC
    assert "PhaseSpace:Q2Min = 1.0" in joined
    # an explicit q2_min wins
    assert "PhaseSpace:Q2Min = 4.0" in "\n".join(
        pythia.preset_settings("dis", 14, q2_min=4.0))


def test_qcd_presets_and_none():
    assert "SoftQCD:inelastic = on" in pythia.preset_settings("softqcd", 2212)
    hard = "\n".join(pythia.preset_settings("hardqcd", 2212, pt_min=50))
    assert "HardQCD:all = on" in hard and "PhaseSpace:pTHatMin = 50" in hard
    assert pythia.preset_settings("none", 14) == []           # user card only


def test_config_rejects_bad_process_and_settings(repo_root, tmp_path):
    cfg = config.RunConfig(generator="pythia", gdml="x.gdml",
                           pythia={"process": "nonsense"})
    with pytest.raises(ConfigError, match="unknown pythia.process"):
        cfg.validate()
    cfg = config.RunConfig(generator="pythia", gdml="x.gdml",
                           pythia={"settings": "not-a-list"})
    with pytest.raises(ConfigError, match="must be a list"):
        cfg.validate()


# --- backend: job spec ------------------------------------------------------ #
def test_prepare_writes_job_spec(repo_root, tmp_path):
    import shutil
    shutil.copy(repo_root / "gdml" / "liquid_argon_1m3.gdml", tmp_path)
    cfg = config.RunConfig(
        generator="pythia", gdml=str(tmp_path / "liquid_argon_1m3.gdml"),
        pythia={"process": "dis", "settings": ["PDF:pSet = 8"]})
    cfg.run.events = 25
    cfg.run.seed = 99
    cfg.beam.particle = "nu_mu"
    cfg.beam.energy.value = "1 TeV"
    cfg.validate()

    prep = pythia.PythiaBackend().prepare(cfg, tmp_path)
    assert prep.argv == [pythia.JOB_FILE]
    job = json.loads((tmp_path / pythia.JOB_FILE).read_text())
    assert job["probe"] == 14
    assert job["nucleon"] == 2112                 # Ar-40 is neutron-rich (Z=18, N=22)
    assert job["process"] == "dis"
    assert job["settings"] == ["PDF:pSet = 8"]
    assert job["events"] == 25 and job["seed"] == 99
    assert job["flux_emax_gev"] == pytest.approx(1000.0)


def test_prepare_samples_beam_file(repo_root, tmp_path):
    """A distribution on any beam parameter triggers host-side sampling into
    beam.dat, replayed per event by the driver (same contract as genie)."""
    import shutil
    shutil.copy(repo_root / "gdml" / "liquid_argon_1m3.gdml", tmp_path)
    cfg = config.RunConfig(generator="pythia",
                           gdml=str(tmp_path / "liquid_argon_1m3.gdml"))
    cfg.run.events = 5
    cfg.run.seed = 3
    cfg.beam.particle = "nu_mu"
    cfg.beam.energy.value = "100 GeV"
    cfg.beam.position_dist = {
        "x": config.Distribution(kind="uniform", min="-1 m", max="0 m"),
        "y": config.Distribution(kind="fixed", value="0"),
        "z": config.Distribution(kind="fixed", value="-500 mm")}
    cfg.validate()
    pythia.PythiaBackend().prepare(cfg, tmp_path)
    job = json.loads((tmp_path / pythia.JOB_FILE).read_text())
    assert job["beam_file"] == pythia.BEAM_FILE
    assert (tmp_path / pythia.BEAM_FILE).exists()


# --- driver: command-file rendering ---------------------------------------- #
def _job(**over):
    job = {"probe": 14, "nucleon": 2212, "process": "dis", "settings": [],
           "events": 10, "seed": 5, "flux": {"mode": "mono", "value": "500 GeV"},
           "output": "output.root"}
    job.update(over)
    return job


def test_render_cmnd_fixed_target(repo_root):
    """The card must put the beam on a STATIONARY nucleon: frameType 2 with the
    target energy equal to its mass (=> zero momentum)."""
    mod = _load_driver(repo_root)
    card = mod.render_cmnd(_job(), events=10, energy_gev=500.0, seed=5)
    assert "Beams:frameType = 2" in card
    assert "Beams:idA = 14" in card
    assert "Beams:idB = 2212" in card
    assert "Beams:eA = 500" in card
    # eB == proton mass in GeV -> at rest
    eb = [l for l in card.splitlines() if l.startswith("Beams:eB")][0]
    assert float(eb.split("=")[1]) == pytest.approx(0.938272, abs=1e-3)
    assert "Main:numberOfEvents = 10" in card
    assert "Random:seed = 5" in card
    assert "WeakBosonExchange:ff2ff(t:W) = on" in card


def test_render_cmnd_raw_settings_win_last(repo_root):
    """Raw pythia.settings are appended AFTER the preset so they can override
    anything it set (Pythia takes the last assignment)."""
    mod = _load_driver(repo_root)
    card = mod.render_cmnd(
        _job(settings=["PhaseSpace:Q2Min = 25.0", "PDF:pSet = 8"]),
        events=2, energy_gev=100.0)
    lines = card.splitlines()
    assert lines.index("PhaseSpace:Q2Min = 25.0") > lines.index("PhaseSpace:Q2Min = 1.0")
    assert lines[-1] == "PDF:pSet = 8"


def test_render_cmnd_no_hepmc_setting(repo_root):
    """The output path is passed to pythia_gen on argv, never as a card setting
    (HEPMCoutput:file is not a declared setting in every Pythia release)."""
    mod = _load_driver(repo_root)
    assert "HEPMCoutput" not in mod.render_cmnd(_job(), 1, 10.0)


def test_energy_groups_dedupe_initializations(repo_root):
    """Beam replay groups rays by energy so Pythia initializes once per distinct
    energy instead of once per ray."""
    mod = _load_driver(repo_root)
    entries = [("nu_mu", (0, 0, 0), (0, 0, 1000.0)),      # 1 GeV
               ("nu_mu", (0, 0, 0), (0, 0, 2000.0)),      # 2 GeV
               ("nu_mu", (0, 0, 0), (0, 0, 1000.0))]      # 1 GeV again
    groups = mod._energy_groups(entries)
    assert len(groups) == 2
    assert list(groups.values()) == [[0, 2], [1]]


# --- converter: Pythia-style HepMC3 (no NuHepMC target record) -------------- #
def _write_pythia_hepmc(path, n_events=3):
    """Synthetic Pythia-style HepMC3: standard statuses (4 = incoming beam,
    1 = final state), NO status-11 target particle, GEV/MM."""
    lines = ["HepMC::Version 3.02.05", "HepMC::Asciiv3-START_EVENT_LISTING"]
    for i in range(n_events):
        enu = 500.0 + 10.0 * i
        lines.append(f"E {i} 1 4")
        lines.append("U GEV MM")
        lines.append(f"V -1 0 [1] @ 0 0 0 0")
        lines.append(f"P 1 0 14 0 0 {enu:.6f} {enu:.6f} 0 4")       # beam nu_mu
        el = 0.5 * enu
        lines.append(f"P 2 -1 13 1.0 0 {el:.6f} {el:.6f} 0.105658 1")  # CC mu-
        lines.append(f"P 3 -1 2212 -1.0 0 {0.3*enu:.6f} {0.3*enu+0.938:.6f} 0.938272 1")
        lines.append(f"P 4 -1 211 0 0.5 {0.2*enu:.6f} {0.2*enu+0.14:.6f} 0.139570 1")
    lines.append("HepMC::Asciiv3-END_EVENT_LISTING")
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_convert_pythia_hepmc_schema_and_labels(tmp_path):
    """A Pythia HepMC3 file converts to a schema-complete output.root, labelled
    Pythia8, with nu_targetZ/A supplied by target_pdg (Pythia records no
    target particle of its own)."""
    import uproot
    src = _write_pythia_hepmc(tmp_path / "pythia.hepmc")
    out = str(tmp_path / "output.root")
    achilles_convert.convert(src, out, process_label="Pythia8", target_pdg=2212)

    brs = set(io.available_branches(out))
    for b in io.SCALAR_BRANCHES + io.TRK_BRANCHES + io.STEP_BRANCHES + io.NU_BRANCHES:
        assert b in brs, f"converted file missing {b}"

    t = uproot.open(out)["tree"]
    assert t.num_entries == 3
    assert t["primaryPDG"].array(library="np")[0] == 14
    assert bool(t["nu_isCC"].array(library="np")[0]) is True      # mu- out => CC
    # free-proton target from target_pdg
    assert t["nu_targetZ"].array(library="np")[0] == 1
    assert t["nu_targetA"].array(library="np")[0] == 1
    labels = t["nu_interactionProcess"].array(library="np")
    assert labels[0] == "Pythia8"
    # three final-state particles per event, momenta present for the display
    assert t["nTracks"].array(library="np")[0] == 3
    assert len(t["trk_px"].array()[0]) == 3


def test_convert_without_target_pdg_leaves_target_unknown(tmp_path):
    """Without the fallback the target stays -1 rather than being invented."""
    import uproot
    src = _write_pythia_hepmc(tmp_path / "p.hepmc", n_events=1)
    out = str(tmp_path / "o.root")
    achilles_convert.convert(src, out, process_label="Pythia8")
    t = uproot.open(out)["tree"]
    assert t["nu_targetZ"].array(library="np")[0] == -1


def test_transport_is_the_default(repo_root, tmp_path):
    """Pythia routes through the generic Geant4 hand-off like genie/achilles --
    and, like them, does so by DEFAULT: the common output.root is meant to carry
    a Geant4 transport record whatever generated the interaction."""
    from gdmltp import run as runmod
    cfg = config.RunConfig(generator="pythia", gdml="x.gdml", pythia={})
    assert runmod._wants_transport(cfg) is True
    cfg2 = config.RunConfig(generator="pythia", gdml="x.gdml",
                            pythia={"transport": True})
    assert runmod._wants_transport(cfg2) is True
    cfg3 = config.RunConfig(generator="pythia", gdml="x.gdml",
                            pythia={"transport": False})
    assert runmod._wants_transport(cfg3) is False
