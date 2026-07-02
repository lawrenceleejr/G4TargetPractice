"""particles + run-macro generation."""
from g4tp import particles, run


def test_particle_names():
    assert particles.name_for(11) == "e-"
    assert particles.name_for(-11) == "e+"
    assert particles.name_for(2112) == "neutron"
    assert particles.name_for(1000922380) == "ion(Z=92,A=238)"   # U-238
    assert particles.name_for(424242) == "pdg424242"


def test_particle_colors():
    assert particles.color_for(22).startswith("#")
    assert particles.color_for(999999) == "#888888"
    assert particles.color_for(1000922380) == "#b5651d"          # ion fallback


def test_generate_macro_field_and_order():
    mac = run.generate_macro("geo.gdml", particle="mu-", energy="3 GeV",
                             n=50, field="0 0 5 tesla")
    assert "/detector/readGDML geo.gdml" in mac
    assert "/detector/setGlobalField 0 0 5 tesla" in mac
    assert "/gun/particle mu-" in mac
    assert "/run/beamOn 50" in mac
    # field must be set after initialize, before the gun block
    assert mac.index("/run/initialize") < mac.index("setGlobalField") < mac.index("/gun/particle")


def test_generate_macro_no_field():
    mac = run.generate_macro("geo.gdml")
    assert "setGlobalField" not in mac
