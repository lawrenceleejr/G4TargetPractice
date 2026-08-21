"""The loud banners, and the repo-wide rule they defend: a neutrino run should
end in Geant4, and the two ways it might not (bare Geant4 doing the neutrino
interaction itself; a generator with transport disabled) must be impossible to
miss in the output.
"""
from pathlib import Path

import pytest

from gdmltp import config, run, warnings as gwarn


def _geant4_nu(**beam):
    return config.RunConfig(
        generator="geant4", gdml="lar.gdml",
        beam=config.Beam(energy=config.Energy(mode="mono", value="2 GeV"), **beam),
        run=config.RunSettings(events=1))


# --- the banner itself ---------------------------------------------------------
def test_banner_is_a_fixed_width_box_of_bangs(capsys):
    gwarn.neutrino_on_geant4("nu_mu")
    err = capsys.readouterr().err.rstrip("\n").split("\n")
    assert all(len(line) == gwarn.WIDTH for line in err), "frame is ragged"
    assert err[0] == "!" * gwarn.WIDTH and err[-1] == "!" * gwarn.WIDTH
    body = "\n".join(err)
    assert "NEUTRINO BEAM (NU_MU)" in body
    assert "generator: genie" in body          # it must say what to do instead
    assert "achilles" in body and "pythia" in body


def test_warnings_can_be_muted(capsys, monkeypatch):
    monkeypatch.setenv("GDMLTP_NO_WARNINGS", "1")
    gwarn.neutrino_on_geant4("nu_mu")
    gwarn.generator_without_transport("genie")
    assert capsys.readouterr().err == ""


# --- when they fire ------------------------------------------------------------
@pytest.mark.parametrize("beam", [{"particle": "nu_mu"}, {"particle": "anti_nu_e"},
                                  {"pdg": 16}, {"pdg": -14}])
def test_neutrino_on_geant4_warns(beam, capsys):
    run.warn_about(_geant4_nu(**beam))
    assert "ON THE BARE GEANT4 BACKEND" in capsys.readouterr().err


@pytest.mark.parametrize("beam", [{"particle": "proton"}, {"particle": "e-"},
                                  {"pdg": 2212}, {"pdg": 9900014}])
def test_non_neutrino_geant4_beams_are_quiet(beam, capsys):
    run.warn_about(_geant4_nu(**beam))
    assert capsys.readouterr().err == ""


def test_generator_neutrino_runs_are_quiet(capsys):
    """A GENIE run does the right thing by default -- no nagging."""
    cfg = config.RunConfig(generator="genie", gdml="lar.gdml",
                           beam=config.Beam(particle="nu_mu"),
                           genie={"tune": "G18_10a_00_000"})
    run.warn_about(cfg)
    assert capsys.readouterr().err == ""


def test_transport_disabled_warns_even_for_a_generator(capsys):
    cfg = config.RunConfig(generator="genie", gdml="lar.gdml",
                           beam=config.Beam(particle="nu_mu"),
                           genie={"transport": False})
    run.warn_about(cfg)
    err = capsys.readouterr().err
    assert "TRANSPORT DISABLED" in err and "NO GEANT4 IN THIS RUN" in err


def test_run_config_warns_before_it_launches_anything(repo_root, tmp_path, capsys):
    """The advice has to reach the user on a dry-run too -- it is about the
    config, not the execution."""
    cfg = config.RunConfig(
        generator="geant4", gdml=str(repo_root / "gdml" / "liquid_argon_1m3.gdml"),
        beam=config.Beam(particle="nu_mu",
                         energy=config.Energy(mode="mono", value="2 GeV")),
        run=config.RunSettings(events=2))
    run.run_config(cfg, outdir=str(tmp_path), dry_run=True)
    out = capsys.readouterr()
    assert "ON THE BARE GEANT4 BACKEND" in out.err
    assert "docker run" in out.out                    # the run still proceeds


# --- the repo-wide rule --------------------------------------------------------
def _neutrino_examples(repo_root):
    for path in sorted((repo_root / "examples").rglob("*.yaml")):
        cfg = config.from_yaml(path)
        if cfg.beam.pdg_code() in gwarn.NEUTRINO_PDGS:
            yield path, cfg


# The examples that deliberately let Geant4 itself do the neutrino interaction:
# biased all-Geant4 runs for energy deposition / detector response, each saying
# so in its own header. Everything else must go through a generator.
ALL_GEANT4_NEUTRINO_EXAMPLES = {
    "nu_slice_geant4_biased.yaml",      # the MAIA slice, as the contrast run
    "mudecay_neutrino_ip.yaml",         # the muon-collider IP, where the only
                                        # material a decay neutrino crosses is
                                        # the nozzle it happens to clip
}


def test_every_shipped_neutrino_example_ends_in_geant4(repo_root):
    """Any neutrino example must propagate its final state through the geometry:
    with a generator that means the Geant4 hand-off, and the only examples
    allowed to skip it are the deliberate all-Geant4 runs (where Geant4 is
    doing the transport anyway)."""
    checked = 0
    for path, cfg in _neutrino_examples(repo_root):
        checked += 1
        if cfg.generator == "geant4":
            assert path.name in ALL_GEANT4_NEUTRINO_EXAMPLES, (
                f"{path}: a neutrino beam on the geant4 backend is generator-free "
                f"physics; use genie/achilles/pythia")
            # and it has to have asked for the biasing explicitly, not drifted
            # into Geant4's bare neutrino model by accident
            assert cfg.geant4.get("neutrino_bias"), (
                f"{path}: an all-Geant4 neutrino run must set "
                f"geant4.neutrino_bias explicitly")
            continue
        assert run._wants_transport(cfg), f"{path}: transport is disabled"
    assert checked >= 12, f"only found {checked} neutrino examples -- glob broken?"
