import numpy as np
import pytest

from g4tp import geometry


def test_bpe_slab(repo_root):
    """60x60x50 cm box + world; GDML cm must convert to mm."""
    prims = geometry.parse_gdml(repo_root / "gdml" / "bpe_slab.gdml", include_world=True)
    assert len(prims) == 2
    slab = [p for p in prims if not p.is_world]
    assert len(slab) == 1
    bb = geometry.bounding_box(slab)
    lo, hi = bb
    assert hi[0] - lo[0] == pytest.approx(600.0)      # 60 cm -> 600 mm
    assert hi[2] - lo[2] == pytest.approx(500.0)      # 50 cm -> 500 mm


def test_nozzles_polycone_bbox(repo_root):
    """Polycones are unsupported solids -> bbox fallback, extents sane."""
    prims = geometry.parse_gdml(repo_root / "gdml" / "nozzles_tungsten.gdml")
    assert len(prims) >= 6                            # 6 nozzle volumes placed
    bb = geometry.bounding_box(prims)
    assert bb is not None
    lo, hi = bb
    # nozzles span z = -595..595 cm; the bbox fallback must reach meters scale
    assert hi[2] - lo[2] > 2000.0


def test_all_repo_gdmls_parse(repo_root):
    """Every shipped geometry parses without raising."""
    import warnings
    for g in sorted((repo_root / "gdml").glob("*.gdml")):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            prims = geometry.parse_gdml(g, include_world=True)
        assert isinstance(prims, list), g.name
        assert prims, f"{g.name} produced no primitives"


def test_world_flag(repo_root):
    with_world = geometry.parse_gdml(repo_root / "gdml" / "bpe_slab.gdml", include_world=True)
    without = geometry.parse_gdml(repo_root / "gdml" / "bpe_slab.gdml", include_world=False)
    assert sum(p.is_world for p in with_world) == 1
    assert all(not p.is_world for p in without)


def test_unit_conversion_rotation():
    """Inline GDML: 90 deg rotation about z applied to a placed box."""
    import tempfile, os
    gdml = """<?xml version="1.0"?>
<gdml>
  <solids>
    <box name="wb" x="1000" y="1000" z="1000" lunit="mm"/>
    <box name="b" x="40" y="10" z="10" lunit="mm"/>
  </solids>
  <structure>
    <volume name="inner"><solidref ref="b"/></volume>
    <volume name="World"><solidref ref="wb"/>
      <physvol><volumeref ref="inner"/>
        <position x="1" y="2" z="3" unit="cm"/>
        <rotation z="90" aunit="deg"/>
      </physvol>
    </volume>
  </structure>
  <setup name="Default" version="1.0"><world ref="World"/></setup>
</gdml>"""
    with tempfile.NamedTemporaryFile("w", suffix=".gdml", delete=False) as f:
        f.write(gdml)
        path = f.name
    try:
        prims = geometry.parse_gdml(path)
        assert len(prims) == 1
        p = prims[0]
        assert p.transform[:3, 3] == pytest.approx([10.0, 20.0, 30.0])  # cm -> mm
        # 90 deg about z sends x-hat to y-hat
        assert p.transform[:3, :3] @ np.array([1, 0, 0]) == pytest.approx([0, 1, 0], abs=1e-12)
    finally:
        os.unlink(path)
