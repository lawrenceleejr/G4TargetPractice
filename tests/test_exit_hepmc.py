"""The HepMC3 exit export: g4sim writing what LEAVES a volume.

g4sim already reads HepMC3 (`/gun/hepmcFile`); writing it closes the loop, so a
run can feed the next stage or any downstream tool. The engine side is C++ (CI
builds it and round-trips a real file); these cover the YAML front-end contract
-- which macro commands a config produces, and which configs are rejected.
"""
import pytest

from gdmltp import config
from gdmltp.backends.geant4 import build_macro


def _cfg(**geant4):
    return config.RunConfig(
        gdml="water.gdml",
        beam=config.Beam(particle="proton",
                         energy=config.Energy(mode="mono", value="150 MeV")),
        run=config.RunSettings(events=10), geant4=geant4)


def test_no_export_by_default():
    """Silence unless asked: the export is opt-in."""
    assert "/analysis/exit" not in build_macro(_cfg())


def test_filename_alone_enables_it():
    lines = build_macro(_cfg(exit_hepmc="exit.hepmc")).splitlines()
    assert "/analysis/exitHepMC exit.hepmc" in lines
    # untouched knobs stay out of the macro; g4sim's own defaults apply
    assert not any(l.startswith("/analysis/exitVolume") for l in lines)
    assert not any(l.startswith("/analysis/exitMinKE") for l in lines)
    assert not any(l.startswith("/analysis/exitKill") for l in lines)


def test_all_knobs_render():
    lines = build_macro(_cfg(exit_hepmc="exit.hepmc", exit_volume="Detector",
                             exit_min_ke="1 MeV", exit_kill=True)).splitlines()
    assert lines.index("/analysis/exitHepMC exit.hepmc") < lines.index("/run/beamOn 10")
    assert "/analysis/exitVolume Detector" in lines
    assert "/analysis/exitMinKE 1 MeV" in lines
    assert "/analysis/exitKill true" in lines


def test_commands_precede_beam_on():
    """The writer opens at BeginOfRunAction, so every knob must be set before
    /run/beamOn -- a command after it would silently do nothing."""
    lines = build_macro(_cfg(exit_hepmc="e.hepmc", exit_volume="V",
                             exit_min_ke="10 keV", exit_kill=True)).splitlines()
    beam_on = lines.index("/run/beamOn 10")
    for i, line in enumerate(lines):
        if line.startswith("/analysis/exit"):
            assert i < beam_on, f"{line} comes after /run/beamOn"


def test_export_survives_a_beam_file_run():
    """A host-sampled beam replaces the gun block; the export must still be
    emitted (the two features are orthogonal)."""
    lines = build_macro(_cfg(exit_hepmc="exit.hepmc"), beam_file="beam.dat").splitlines()
    assert "/analysis/exitHepMC exit.hepmc" in lines
    assert "/gun/beamFile beam.dat" in lines


# --- configuration errors -----------------------------------------------------
@pytest.mark.parametrize("block,match", [
    ({"exit_volume": "Det"}, "only means something with"),
    ({"exit_min_ke": "1 MeV"}, "only means something with"),
    ({"exit_kill": True}, "only means something with"),
    ({"exit_hepmc": ""}, "must be a file name"),
    ({"exit_hepmc": "e.hepmc", "exit_min_ke": "plenty"}, "energy with a unit"),
    ({"exit_hepmc": "e.hepmc", "exit_kill": "yes"}, "true or false"),
])
def test_bad_configs_are_rejected(block, match):
    with pytest.raises(config.ConfigError, match=match):
        _cfg(**block).validate()


def test_good_config_validates():
    _cfg(exit_hepmc="exit.hepmc", exit_volume="Det",
         exit_min_ke="1 MeV", exit_kill=False).validate()
