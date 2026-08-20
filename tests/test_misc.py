"""particles + run-macro generation."""
from gdmltp import particles, run


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


def test_no_test_module_imports_the_tests_package():
    """`from tests.conftest import ...` resolves under `python -m pytest` (the
    repo root lands on sys.path) but NOT under CI's bare `pytest tests/`, so it
    is a green-locally / red-in-CI trap. pytest already exposes tests/conftest.py
    as the top-level module `conftest`; use that."""
    import pathlib
    offenders = []
    for f in sorted(pathlib.Path(__file__).parent.glob("test_*.py")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("from tests.", "import tests.")):
                offenders.append(f"{f.name}:{i}: {stripped}")
    assert not offenders, (
        "import from `conftest`, not `tests.conftest`:\n  " + "\n  ".join(offenders))
