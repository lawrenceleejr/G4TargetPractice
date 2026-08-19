"""RunConfig: YAML parsing, defaults, validation, and flag-over-YAML merge."""
import argparse
import pytest

from gdmltp import config


def _write(tmp_path, text):
    p = tmp_path / "run.yaml"
    p.write_text(text)
    return str(p)


# --- parsing / defaults ---------------------------------------------------- #
def test_minimal_yaml_defaults(tmp_path):
    cfg = config.from_yaml(_write(tmp_path, "geometry: {gdml: g.gdml}\n"))
    cfg.validate()
    assert cfg.generator == "geant4"
    assert cfg.gdml == "g.gdml"
    assert cfg.beam.particle == "e-"
    assert cfg.beam.energy.mode == "mono"
    assert cfg.run.events == 100
    assert cfg.run.output == "output.root"


def test_geometry_string_shorthand(tmp_path):
    cfg = config.from_yaml(_write(tmp_path, "geometry: g.gdml\n"))
    assert cfg.gdml == "g.gdml"


def test_energy_string_shorthand_is_mono(tmp_path):
    cfg = config.from_yaml(_write(tmp_path,
        "geometry: {gdml: g.gdml}\nbeam: {energy: '2 GeV'}\n"))
    assert cfg.beam.energy.mode == "mono"
    assert cfg.beam.energy.value == "2 GeV"


def test_projectile_alias(tmp_path):
    cfg = config.from_yaml(_write(tmp_path,
        "geometry: {gdml: g.gdml}\nprojectile: {particle: proton}\n"))
    assert cfg.beam.particle == "proton"


def test_arb_bins_parsed(tmp_path):
    cfg = config.from_yaml(_write(tmp_path,
        "geometry: {gdml: g.gdml}\n"
        "beam:\n  energy:\n    mode: arb\n    bins:\n"
        "      - {value: '500 MeV', weight: 2.0}\n"
        "      - {value: '1 GeV'}\n"))
    cfg.validate()
    assert cfg.beam.energy.bins == [
        {"value": "500 MeV", "weight": 2.0},
        {"value": "1 GeV", "weight": 1.0},
    ]


def test_particle_by_pdg_int(tmp_path):
    cfg = config.from_yaml(_write(tmp_path, "geometry: {gdml: g.gdml}\nbeam: {particle: 2212}\n"))
    cfg.validate()
    assert cfg.beam.is_pdg() and cfg.beam.pdg == 2212
    assert cfg.beam.pdg_code() == 2212
    assert cfg.beam.identifier() == "2212"


def test_particle_by_explicit_pdg_field(tmp_path):
    cfg = config.from_yaml(_write(tmp_path, "geometry: {gdml: g.gdml}\nbeam: {pdg: 1000060120}\n"))
    cfg.validate()
    assert cfg.beam.pdg == 1000060120 and cfg.beam.is_pdg()


def test_particle_by_signed_numeric_string(tmp_path):
    cfg = config.from_yaml(_write(tmp_path, "geometry: {gdml: g.gdml}\nbeam: {particle: '-11'}\n"))
    cfg.validate()
    assert cfg.beam.pdg == -11


def test_particle_name_is_not_pdg(tmp_path):
    cfg = config.from_yaml(_write(tmp_path, "geometry: {gdml: g.gdml}\nbeam: {particle: mu-}\n"))
    cfg.validate()
    assert not cfg.beam.is_pdg()
    assert cfg.beam.pdg_code() == 13          # resolved via the name table
    assert cfg.beam.identifier() == "mu-"


def test_pdg_zero_rejected():
    c = config.RunConfig(gdml="g.gdml", beam=config.Beam(pdg=0))
    with pytest.raises(config.ConfigError, match="nonzero PDG"):
        c.validate()


def test_yaml_off_neutrino_mode_normalized(tmp_path):
    """YAML parses `off` as boolean False; it must become the string 'off'."""
    cfg = config.from_yaml(_write(tmp_path,
        "geometry: {gdml: g.gdml}\ngeant4: {neutrino_mode: off}\n"))
    cfg.validate()
    assert cfg.geant4["neutrino_mode"] == "off"
    from gdmltp.backends.geant4 import build_macro
    assert "/analysis/neutrinoMode off" in build_macro(cfg)


def test_backend_blocks_preserved(tmp_path):
    cfg = config.from_yaml(_write(tmp_path,
        "generator: genie\ngeometry: {gdml: g.gdml}\n"
        "genie: {tune: G18_10a_00_000, target: 1000180400}\n"))
    assert cfg.genie["tune"] == "G18_10a_00_000"
    assert cfg.genie["target"] == 1000180400


# --- validation ------------------------------------------------------------ #
def test_unknown_top_level_key_errors(tmp_path):
    with pytest.raises(config.ConfigError, match="unknown top-level"):
        config.from_yaml(_write(tmp_path, "geometry: {gdml: g.gdml}\nwidget: 3\n"))


def test_missing_geometry_errors():
    with pytest.raises(config.ConfigError, match="no geometry"):
        config.RunConfig().validate()


def test_bad_generator_errors():
    with pytest.raises(config.ConfigError, match="unknown generator"):
        config.RunConfig(generator="fluka", gdml="g.gdml").validate()


def test_gauss_requires_sigma():
    cfg = config.RunConfig(gdml="g.gdml",
                           beam=config.Beam(energy=config.Energy(mode="gauss")))
    with pytest.raises(config.ConfigError, match="sigma"):
        cfg.validate()


def test_exp_requires_range():
    cfg = config.RunConfig(gdml="g.gdml",
                           beam=config.Beam(energy=config.Energy(mode="exp", min="1 GeV")))
    with pytest.raises(config.ConfigError, match="min and .*max"):
        cfg.validate()


def test_arb_requires_bins():
    cfg = config.RunConfig(gdml="g.gdml",
                           beam=config.Beam(energy=config.Energy(mode="arb")))
    with pytest.raises(config.ConfigError, match="arb"):
        cfg.validate()


def test_mac_only_for_geant4():
    cfg = config.RunConfig(generator="genie", gdml="g.gdml", mac="x.mac")
    with pytest.raises(config.ConfigError, match="verbatim macro"):
        cfg.validate()


# --- flag / merge ---------------------------------------------------------- #
def _run_ns(**kw):
    """A Namespace resembling the run subparser's args."""
    base = dict(config=None, generator="geant4", gdml=None, mac=None,
                particle="e-", energy="1 GeV", position="0 0 -20 cm",
                direction="0 0 1", n=100, neutrino_mode="auto", field=None)
    base.update(kw)
    return argparse.Namespace(**base)


_DEFAULTS = {n: _run_ns().__dict__[n] for n in config._FLAG_FIELDS}


def test_load_from_flags_only():
    cfg = config.load(_run_ns(gdml="g.gdml", particle="neutron", n=7), _DEFAULTS)
    assert cfg.gdml == "g.gdml"
    assert cfg.beam.particle == "neutron"
    assert cfg.run.events == 7


def test_flag_overrides_yaml(tmp_path):
    path = _write(tmp_path,
        "geometry: {gdml: g.gdml}\nbeam: {particle: proton, energy: '150 MeV'}\n")
    # user explicitly passed --energy "200 MeV"; everything else left default
    cfg = config.load(_run_ns(config=path, energy="200 MeV"), _DEFAULTS)
    assert cfg.beam.particle == "proton"          # from YAML (flag left at default)
    assert cfg.beam.energy.value == "200 MeV"     # flag wins


def test_yaml_kept_when_flag_at_default(tmp_path):
    path = _write(tmp_path, "geometry: {gdml: g.gdml}\nbeam: {particle: proton}\n")
    cfg = config.load(_run_ns(config=path), _DEFAULTS)
    assert cfg.beam.particle == "proton"          # flag default must not clobber YAML
