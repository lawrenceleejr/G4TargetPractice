"""Backend registry + Geant4Backend macro rendering and run plan."""
import pytest

from gdmltp import config, backends
from gdmltp.backends import geant4


def _cfg(**geant4_block):
    return config.RunConfig(gdml="gdml/water_phantom_30cm.gdml", geant4=geant4_block)


# --- registry -------------------------------------------------------------- #
def test_registry_returns_geant4():
    b = backends.get("geant4")
    assert b.name == "geant4"


def test_registry_unknown_raises():
    with pytest.raises(ValueError, match="unknown generator"):
        backends.get("fluka")


def test_default_image_and_celeritas_variant():
    b = backends.get("geant4")
    assert b.image_for(_cfg()) == geant4.DEFAULT_IMAGE
    assert b.image_for(_cfg(celeritas=True)).endswith("-celeritas")


# --- macro rendering ------------------------------------------------------- #
def test_macro_mono_basics():
    mac = geant4.build_macro(config.RunConfig(
        gdml="water.gdml",
        beam=config.Beam(particle="proton",
                         energy=config.Energy(mode="mono", value="150 MeV")),
        run=config.RunSettings(events=500, seed=42)))
    assert "/detector/readGDML water.gdml" in mac
    assert "/gun/energyMode mono" in mac
    assert "/gun/energy 150 MeV" in mac
    assert "/random/setSeeds 42 43" in mac
    assert "/run/beamOn 500" in mac


def test_macro_particle_by_pdg():
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="2212", pdg=2212)))
    assert "/gun/particlePDG 2212" in mac
    assert "/gun/particle " not in mac        # name form not emitted


def test_macro_particle_by_name_unchanged():
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="mu-")))
    assert "/gun/particle mu-" in mac
    assert "/gun/particlePDG" not in mac


def test_macro_gauss_emits_sigma():
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml",
        beam=config.Beam(energy=config.Energy(mode="gauss", value="3 GeV", sigma="500 MeV"))))
    assert "/gun/energyMode gauss" in mac
    assert "/gun/gaussSigma 500 MeV" in mac


def test_macro_exp_emits_range():
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml",
        beam=config.Beam(energy=config.Energy(mode="exp", value="2 GeV",
                                              min="200 MeV", max="20 GeV"))))
    assert "/gun/energyMin 200 MeV" in mac
    assert "/gun/energyMax 20 GeV" in mac


def test_macro_arb_emits_bins():
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml",
        beam=config.Beam(energy=config.Energy(mode="arb", bins=[
            {"value": "500 MeV", "weight": 2.0}, {"value": "1 GeV", "weight": 1.0}]))))
    assert "/gun/clearEnergyBins" in mac
    assert "/gun/addEnergyBin 500 MeV 2.0" in mac
    assert "/gun/addEnergyBin 1 GeV 1.0" in mac
    assert "/gun/energy " not in mac          # arb does not set a single energy


def test_macro_neutrino_bias_auto():
    """A neutrino primary auto-enables biasing before /run/initialize via our own
    /gdmltp/neutrinoBias command (unbiased Geant4 neutrino runs record almost no
    interactions), driving the G4EmParameters API rather than the /physics_lists/
    em/Nu* UI commands that some Geant4 builds don't register."""
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="nu_mu")))
    assert "/gdmltp/neutrinoBias 5e+12 5e+12 5e+12 DefaultRegionForTheWorld" in mac
    assert mac.index("/gdmltp/neutrinoBias") < mac.index("/run/initialize")
    # no dependence on optional UI commands that abort the batch when absent
    assert "/physics_lists/em/Nu" not in mac
    assert "/control/suppressAbortion" not in mac


def test_macro_neutrino_bias_off_and_custom():
    off = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="nu_mu"),
        geant4={"neutrino_bias": "off"}))
    assert "/gdmltp/neutrinoBias" not in off
    custom = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="nu_e"),
        geant4={"neutrino_bias": {"factor": 1e10, "nc_bias": 3e9}}))
    # cc/nucleus take the factor, nc overridden: "cc nc nuc region"
    assert "/gdmltp/neutrinoBias 1e+10 3e+09 1e+10 DefaultRegionForTheWorld" in custom


def test_macro_neutrino_bias_region_pattern():
    """detector_name names a G4Region, and region_pattern chooses which logical
    volumes make up g4sim's "target" region -- both must land before
    /run/initialize, since the regions are built during initialization."""
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="nu_mu"),
        geant4={"neutrino_bias": {
            "cc_bias": 1, "nc_bias": 1, "nucleus_bias": 1e9,
            "detector_name": "target", "region_pattern": "LAr"}}))
    assert "/detector/targetRegionPattern LAr" in mac
    assert "/gdmltp/neutrinoBias 1 1 1e+09 target" in mac
    assert mac.index("/detector/targetRegionPattern") < mac.index("/run/initialize")
    assert mac.index("/gdmltp/neutrinoBias") < mac.index("/run/initialize")
    # an empty pattern means "all non-world volumes" -- nothing to emit
    default = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="nu_mu"),
        geant4={"neutrino_bias": {"detector_name": "target", "region_pattern": ""}}))
    assert "/detector/targetRegionPattern" not in default
    assert "/gdmltp/neutrinoBias 5e+12 5e+12 5e+12 target" in default


def test_macro_neutrino_knobs_full_surface():
    """Every Geant4 biasing term gets its own command, per process family, and
    the region-membership commands come first (DetectorConstruction builds the
    regions the physics knobs name)."""
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="nu_mu"),
        geant4={"neutrino": {
            "region": "target",
            "region_pattern": "LAr",
            "nucleus": {"lowest_energy": "1 MeV"},
            "nucleus_mu": {"mfp_bias": 1.0e9, "xsec_bias": 2},
            "electron": {"enable": False, "cc_bias": 10, "nc_bias": 1,
                         "xsec_cc_bias": 5},
            "oscillation": {"enable": True, "region": "tgtosc",
                            "region_pattern": "LAr", "distance_bias": 1.0e8},
        }}))
    lines = mac.splitlines()
    for expected in [
        "/detector/targetRegionPattern LAr",
        "/detector/oscRegionPattern LAr",
        "/gdmltp/nu/all/region target",
        "/gdmltp/nu/nucleus/lowestEnergy 1 MeV",
        "/gdmltp/nu/nucleusMu/mfpBias 1e+09",
        "/gdmltp/nu/nucleusMu/xsecBias 2",
        "/gdmltp/nu/electron/enable false",
        "/gdmltp/nu/electron/ccBias 10",
        "/gdmltp/nu/electron/xsecCcBias 5",
        "/gdmltp/nu/oscillation/enable true",
        "/gdmltp/nu/oscillation/region tgtosc",
        "/gdmltp/nu/oscillation/distanceBias 1e+08",
    ]:
        assert expected in lines, expected
    # geometry before physics, and everything before /run/initialize
    assert lines.index("/detector/targetRegionPattern LAr") < \
        lines.index("/gdmltp/nu/all/region target")
    # broad groups first so a per-family line can override them
    assert lines.index("/gdmltp/nu/all/region target") < \
        lines.index("/gdmltp/nu/nucleusMu/mfpBias 1e+09")
    assert max(i for i, l in enumerate(lines) if l.startswith("/gdmltp/nu/")) < \
        lines.index("/run/initialize")
    # an explicit block means the user drives every term: the blunt auto
    # shortcut must stand down rather than silently re-pointing the region
    assert "/gdmltp/neutrinoBias" not in mac


def test_macro_neutrino_knobs_absent_by_default():
    """No neutrino block -> no /gdmltp/nu/ lines at all, and Geant4's own
    defaults (oscillation on, unscoped) are left alone."""
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="nu_mu")))
    assert "/gdmltp/nu/" not in mac
    assert "/gdmltp/neutrinoBias" in mac      # the auto shortcut still fires


def test_macro_no_bias_for_charged_primaries():
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="proton")))
    assert "/physics_lists" not in mac


def test_macro_field_and_angle_sigma():
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml",
        beam=config.Beam(angle_sigma="10 deg"),
        geant4={"field": "0 0 5 tesla"}))
    assert "/detector/setGlobalField 0 0 5 tesla" in mac
    assert "/gun/angleSigma 10 deg" in mac
    # field set after initialize, before the gun block
    assert mac.index("/run/initialize") < mac.index("setGlobalField") < mac.index("/gun/particle")


# --- prepare (run plan) ---------------------------------------------------- #
def test_prepare_generates_macro(tmp_path):
    b = backends.get("geant4")
    prep = b.prepare(_cfg(), tmp_path)
    assert prep.argv == [geant4.GENERATED_MACRO]
    assert (tmp_path / geant4.GENERATED_MACRO).exists()
    assert prep.env == {}                       # no field -> no CELER_DISABLE
    assert prep.image == geant4.DEFAULT_IMAGE


def test_prepare_field_sets_celer_disable(tmp_path):
    b = backends.get("geant4")
    prep = b.prepare(_cfg(field="0 0 5 tesla"), tmp_path)
    assert prep.env.get("CELER_DISABLE") == "1"


def test_prepare_sampled_beam_writes_beamfile(tmp_path):
    """A distribution beam makes the geant4 macro use /gun/beamFile + writes beam.dat."""
    b = backends.get("geant4")
    cfg = config.RunConfig(
        gdml="gdml/water_phantom_30cm.gdml",
        beam=config.Beam(particle="mu-",
                         momentum=config.Distribution(kind="fixed", value="500 MeV/c"),
                         position_dist={"x": config.Distribution(kind="gauss", sigma="2 mm"),
                                        "y": config.Distribution(kind="fixed", value="0"),
                                        "z": config.Distribution(kind="fixed", value="-200 mm")}),
        run=config.RunSettings(events=25, seed=1))
    cfg.validate()
    prep = b.prepare(cfg, tmp_path)
    assert (tmp_path / geant4.BEAM_FILE).exists()
    macro = (tmp_path / prep.argv[0]).read_text()
    assert "/gun/beamFile beam.dat" in macro
    assert "/run/beamOn 25" in macro
    # 25 sampled primaries in the beam file
    from gdmltp import beam as beammod
    assert len(beammod.read_beam_file(tmp_path / geant4.BEAM_FILE)) == 25


def test_prepare_verbatim_mac_is_copied(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    mac = src / "my.mac"
    mac.write_text("/run/beamOn 1\n")
    out = tmp_path / "out"
    out.mkdir()
    cfg = config.RunConfig(gdml=None, mac=str(mac))
    prep = backends.get("geant4").prepare(cfg, out)
    assert prep.argv == ["my.mac"]
    assert (out / "my.mac").exists()


def test_macro_neutrino_cc_nc_xsec_terms_are_electron_only():
    """G4NeutrinoElectronTotXsc is the only cross-section data set with separate
    CC and NC objects, so xsec_cc_bias/xsec_nc_bias exist only for the electron
    group -- offering them on a nucleus family would be a knob that does nothing."""
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="nu_mu"),
        geant4={"neutrino": {"electron": {"xsec_cc_bias": 10, "xsec_nc_bias": 2}}}))
    assert "/gdmltp/nu/electron/xsecCcBias 10" in mac
    assert "/gdmltp/nu/electron/xsecNcBias 2" in mac

    with pytest.raises(ValueError) as exc:
        geant4.build_macro(config.RunConfig(
            gdml="g.gdml", beam=config.Beam(particle="nu_mu"),
            geant4={"neutrino": {"nucleus_mu": {"xsec_cc_bias": 10}}}))
    assert "exist only for electron/all" in str(exc.value)


def test_macro_neutrino_bias_shortcut_never_touches_the_xsec_table():
    """The blunt shortcut must stay safe at any factor: biasing the nu+e- CROSS-
    SECTION TABLE aborts Geant4 (G4NeutrinoElectronTotXsc has no isotope-level
    cross section), so the shortcut may only drive process-level factors."""
    mac = geant4.build_macro(config.RunConfig(
        gdml="g.gdml", beam=config.Beam(particle="nu_mu"),
        geant4={"neutrino_bias": {"factor": 1e12}}))
    assert "/gdmltp/neutrinoBias 1e+12 1e+12 1e+12 DefaultRegionForTheWorld" in mac
    for forbidden in ("xsecBias", "xsecCcBias", "xsecNcBias"):
        assert forbidden not in mac


def test_transport_image_is_the_generator_image_sibling():
    """A generator hand-off runs stage 2 in the ENGINE image built from the same
    commit as the generator image. Deriving it from --image is what makes
    `--image <repo>-genie:<branch>` work end to end -- the default engine tag can
    easily be older than the /gun/hepmcFile hand-off itself."""
    cfg = config.RunConfig(gdml="g.gdml", beam=config.Beam(particle="nu_mu"))
    g4 = geant4.Geant4Backend()

    assert g4.image_for(cfg, generator_image="ghcr.io/o/g4targetpractice-genie:brnch") \
        == "ghcr.io/o/g4targetpractice:brnch"
    assert g4.image_for(cfg, generator_image="ghcr.io/o/g4targetpractice-achilles:v2") \
        == "ghcr.io/o/g4targetpractice:v2"
    assert g4.image_for(cfg, generator_image="ghcr.io/o/g4targetpractice-pythia:main") \
        == "ghcr.io/o/g4targetpractice:main"
    # untagged, and a registry with a port (the ":" is not a tag separator)
    assert g4.image_for(cfg, generator_image="myrepo/thing-genie") == "myrepo/thing"
    assert g4.image_for(cfg, generator_image="reg:5000/thing-genie") == "reg:5000/thing"
    # unrecognizable / absent -> the backend default, not a wrong guess
    assert g4.image_for(cfg, generator_image="some/local-build:latest") == \
        g4.default_image
    assert g4.image_for(cfg) == g4.default_image
    # an explicit geant4.image always wins
    pinned = config.RunConfig(gdml="g.gdml", geant4={"image": "my/engine:1"})
    assert g4.image_for(
        pinned, generator_image="ghcr.io/o/g4targetpractice-genie:x") == "my/engine:1"
    # celeritas still applies its tag variant on top of the derived image
    celer = config.RunConfig(gdml="g.gdml", geant4={"celeritas": True})
    assert g4.image_for(celer, generator_image="ghcr.io/o/g4targetpractice-genie:b") \
        == "ghcr.io/o/g4targetpractice:b-celeritas"
