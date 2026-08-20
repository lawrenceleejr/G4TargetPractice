"""The decay backend delegates to GEANT4: this framework renders /bsm/* macro
commands and reweights Geant4's output -- it generates nothing itself. These
tests cover the macro contract, the config validation, and the exact
lifetime-importance arithmetic (against analytic values on a fabricated file).
The C++ side (/bsm/define -> G4DecayTable -> G4Decay) is exercised against the
real engine by the CI geant4 job's BSM smoke.
"""
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
  ctau: "1 km"
  ctau_sample: "10 cm"
  channels:
    - {to: [13, 211], br: 0.6}
    - {to: [14, 13, -13], br: 0.4}
run: {events: 500, seed: 7}
"""


# --- macro contract (what we hand to Geant4) -------------------------------- #

def test_bsm_macro_lines():
    cfg = _cfg(HNL)
    lines = decay.bsm_macro_lines(cfg)
    assert lines[0] == "/bsm/define bsm9900014 9900014 1000 0 100"
    assert lines[1] == "/bsm/channel 0.6 13 211"
    assert lines[2] == "/bsm/channel 0.4 14 13 -13"


def test_bsm_macro_custom_name_and_charge():
    cfg = _cfg(HNL)
    cfg.decay["name"] = "N1"
    cfg.decay["charge"] = -1
    assert decay.bsm_macro_lines(cfg)[0].startswith("/bsm/define N1 9900014 1000 -1 ")


def test_branching_ratios_normalized():
    cfg = _cfg(HNL)
    cfg.decay["channels"] = [{"to": [13, 211], "br": 3.0},
                             {"to": [14, 13, -13], "br": 1.0}]
    chans = decay.resolve_channels(cfg.decay, 1000.0)
    assert [br for _, br in chans] == pytest.approx([0.75, 0.25])


def test_backend_prepare_renders_single_stage_macro(tmp_path):
    from gdmltp.backends.decay import DecayBackend, DECAY_MACRO
    cfg = _cfg(HNL)
    gdml = tmp_path / "g.gdml"
    gdml.write_text("<gdml/>")
    cfg.gdml = str(gdml)
    prep = DecayBackend().prepare(cfg, tmp_path)
    mac = (tmp_path / DECAY_MACRO).read_text()
    # /bsm/* must precede /run/initialize (PreInit commands)
    assert mac.index("/bsm/define") < mac.index("/run/initialize")
    assert "/gun/particlePDG 9900014" in mac
    assert "/run/beamOn 500" in mac
    assert prep.argv == [DECAY_MACRO]
    assert "gdmltargetpractice" in prep.image      # the geant4 image, a real tool
    assert prep.post is not None


def test_backend_with_sampled_beam_writes_beam_file(tmp_path):
    from gdmltp.backends.decay import DecayBackend, DECAY_MACRO
    cfg = _cfg(HNL.replace('position: "0 0 -50 m"', """position:
    x: {dist: gauss, sigma: "1 cm"}
    y: {dist: gauss, sigma: "1 cm"}
    z: {dist: fixed, value: "-50 m"}"""))
    gdml = tmp_path / "g.gdml"
    gdml.write_text("<gdml/>")
    cfg.gdml = str(gdml)
    DecayBackend().prepare(cfg, tmp_path)
    assert (tmp_path / "beam.dat").exists()
    assert "/gun/beamFile" in (tmp_path / DECAY_MACRO).read_text()


# --- config validation -------------------------------------------------------- #

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


def test_removed_knobs_are_rejected_with_pointers():
    base = """
generator: decay
geometry: {gdml: g.gdml}
beam: {pdg: 9900014, mass: "1 GeV"}
decay:
  ctau: "1 m"
  channels: [{to: [13, 211]%s}]
%s
"""
    with pytest.raises(ConfigError, match="external"):
        _cfg(base % (", model: vA", ""))
    with pytest.raises(ConfigError, match="ctau_sample"):
        _cfg(base % ("", "  fiducial: {z: [\"-1 m\", \"1 m\"]}"))
    with pytest.raises(ConfigError, match="single"):
        _cfg(base % ("", "  transport: true"))


def test_five_body_rejected():
    with pytest.raises(ConfigError, match="2-4"):
        _cfg("""
generator: decay
geometry: {gdml: g.gdml}
beam: {pdg: 9900014, mass: "1 GeV"}
decay:
  ctau: "1 m"
  channels: [{to: [11, -11, 11, -11, 22]}]
""")


def test_daughters_heavier_than_parent_rejected():
    cfg = _cfg("""
generator: decay
geometry: {gdml: g.gdml}
beam: {pdg: 9900014, mass: "0.2 GeV"}
decay:
  ctau: "1 m"
  channels: [{to: [13, -13]}]
""")
    with pytest.raises(ConfigError, match="parent mass"):
        decay.bsm_macro_lines(cfg)


def test_unknown_parent_mass_rejected():
    cfg = _cfg("""
generator: decay
geometry: {gdml: g.gdml}
beam: {pdg: 9900014}
decay:
  ctau: "1 m"
  channels: [{to: [13, 211]}]
""")
    with pytest.raises(ConfigError, match="beam.mass"):
        decay.bsm_macro_lines(cfg)


def test_lifetime_alternative_to_ctau():
    assert decay.ctau_mm({"lifetime": "3.335640952 ns"}) == pytest.approx(1000.0, rel=1e-6)
    assert decay.ctau_mm({"ctau": "1 m"}) == 1000.0


# --- post-run reweighting (arithmetic on Geant4's branches) -------------------- #

def _fake_decay_output(path, s_mm, decayed, p_mev=5e5, n_extra_tracks=1):
    """A minimal-but-schema-shaped file imitating what g4sim records for a
    decay run: primary flying +z from origin, ending at s (decay or exit)."""
    import awkward as ak
    import uproot
    n = len(s_mm)
    s_mm = np.asarray(s_mm, float)
    trk_parent, trk_proc = [], []
    for d in decayed:
        trk_parent.append([1, 1] if d else [1])
        trk_proc.append(["Decay", "Decay"] if d else ["Transportation"])
    data = {
        "eventID": np.arange(n, dtype=np.int32),
        "primaryPDG": np.full(n, 9900014, np.int32),
        "primaryE": np.full(n, p_mev),
        "primaryStartX": np.zeros(n), "primaryStartY": np.zeros(n),
        "primaryStartZ": np.zeros(n),
        "primaryStartPx": np.zeros(n), "primaryStartPy": np.zeros(n),
        "primaryStartPz": np.full(n, p_mev),
        "primaryEndE": np.zeros(n),
        "primaryEndX": np.zeros(n), "primaryEndY": np.zeros(n),
        "primaryEndZ": s_mm,
        "primaryEndPx": np.zeros(n), "primaryEndPy": np.zeros(n),
        "primaryEndPz": np.zeros(n),
        "totalEdep": np.zeros(n),
        "nSteps": np.zeros(n, np.int32),
        "nTracks": np.array([len(p) for p in trk_parent], np.int32),
        "trk_parentID": ak.Array(trk_parent),
        "trk_creatorProcess": ak.Array(trk_proc),
    }
    with uproot.recreate(path) as f:
        f["tree"] = data
    return str(path)


def test_postprocess_weights_match_analytic(tmp_path):
    cfg = _cfg(HNL)          # true ctau 1 km, sampled 10 cm, m 1 GeV, p 500 GeV
    m, p = 1000.0, 5e5
    lam_t = (p / m) * 1e6                 # betagamma * 1 km  [mm]
    lam_g = (p / m) * 100.0               # betagamma * 10 cm [mm]
    s = np.array([10.0, 5000.0, 60000.0])
    decayed = [True, True, False]
    path = _fake_decay_output(tmp_path / "out.root", s, decayed, p_mev=p)
    decay.postprocess(path, cfg)

    import uproot
    with uproot.open(path) as f:
        t = f["tree"]
        w = t["eventWeight"].array(library="np")
        dt = t["decayT"].array(library="np")
    expect = np.exp(s / lam_g - s / lam_t)
    expect[:2] *= lam_g / lam_t           # decayed events get the density ratio
    assert np.allclose(w, expect, rtol=1e-12)
    beta = p / np.sqrt(p * p + m * m)
    assert np.allclose(dt, s / (beta * decay.C_MM_PER_NS))


def test_postprocess_without_sampling_gives_unit_weights(tmp_path):
    cfg = _cfg(HNL)
    del cfg.decay["ctau_sample"]
    path = _fake_decay_output(tmp_path / "out.root", [100.0, 200.0], [True, False])
    decay.postprocess(path, cfg)
    import uproot
    with uproot.open(path) as f:
        w = f["tree"]["eventWeight"].array(library="np")
    assert np.all(w == 1.0)


# --- external backend (real-generator events in) ------------------------------ #

def test_external_convert_and_validate(synth_nuhepmc, tmp_path):
    """Any HepMC3 ASCII file converts to a schema-complete vertex-level file
    (the NuHepMC fixture doubles as a generic HepMC3 sample)."""
    from gdmltp.backends import external
    from gdmltp import validate as val
    out = tmp_path / "output.root"
    n = external.convert(synth_nuhepmc, str(out))
    assert n == 6
    report, code = val.validate(str(out), strict=True)
    assert code == 0, report


def test_external_backend_end_to_end(synth_nuhepmc, tmp_path):
    """generator: external runs host-side through run_config (no Docker) and
    the result carries the beam particle as primary + weights/time."""
    from gdmltp import run as runmod
    import uproot
    gdml = tmp_path / "g.gdml"
    gdml.write_text("<gdml/>")
    cfg = _cfg(f"""
generator: external
geometry: {{gdml: g.gdml}}
external: {{file: {synth_nuhepmc}}}
""")
    cfg.gdml = str(gdml)
    runmod.run_config(cfg, outdir=tmp_path)
    with uproot.open(tmp_path / "output.root") as f:
        t = f["tree"]
        assert t["primaryPDG"].array(library="np")[0] == 14
        assert "eventWeight" in {k.split(";")[0] for k in t.keys()}


def test_external_requires_file():
    with pytest.raises(ConfigError, match="external.file"):
        _cfg("""
generator: external
geometry: {gdml: g.gdml}
""")


def test_external_transport_handoff(synth_nuhepmc, tmp_path):
    """external + transport: the hand-off event file must come out of the
    converted file (vertex, momenta, time) ready for the Geant4 stage."""
    from gdmltp.backends import external
    from gdmltp import handoff
    out = tmp_path / "output.root"
    external.convert(synth_nuhepmc, str(out))
    n = handoff.write_event_file(str(out), tmp_path / "events.hepmc")
    assert n == 6
    parsed = handoff.read_event_file(tmp_path / "events.hepmc")
    assert len(parsed) == 6 and len(parsed[0][1]) == 3    # 3 FS particles/event


def test_cli_generator_choices():
    from gdmltp import cli
    p, _ = cli._build_parser()
    for gen in ("decay", "external"):
        assert p.parse_args(["run", "--generator", gen, "--gdml", "g.gdml"]).generator == gen
