import numpy as np
import pytest

from gdmltp import geometry


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


def test_nozzles_polycone_extent(repo_root):
    """Six nozzle polycones placed; extent reaches the meters z-scale. With
    pyg4ometry they are faithful meshes, with the lightweight parser a bbox
    fallback -- either way the placements and overall span must be right."""
    prims = geometry.parse_gdml(repo_root / "gdml" / "nozzles_tungsten.gdml")
    assert len(prims) >= 6                            # 6 nozzle volumes placed
    bb = geometry.bounding_box(prims)
    assert bb is not None
    lo, hi = bb
    # nozzles span z = -595..595 cm; must reach meters scale
    assert hi[2] - lo[2] > 2000.0


def test_boolean_solids_decompose_to_their_positive_parts(tmp_path):
    """No CSG in the lightweight parser: a subtraction shows as its first
    operand, a union as all of its parts, an intersection as the tighter of the
    two. Converter output that is entirely boolean must not parse to nothing."""
    (tmp_path / "bool.gdml").write_text("""<?xml version="1.0"?>
<gdml><define/><materials/>
 <solids>
  <box name="w" x="1000" y="1000" z="1000" lunit="mm"/>
  <box name="big" x="400" y="400" z="400" lunit="mm"/>
  <box name="small" x="100" y="100" z="100" lunit="mm"/>
  <box name="hole" x="50" y="50" z="50" lunit="mm"/>
  <subtraction name="cut"><first ref="big"/><second ref="hole"/></subtraction>
  <intersection name="both"><first ref="big"/><second ref="small"/></intersection>
  <union name="pair"><first ref="small"/><second ref="small"/>
    <position name="off" x="200" unit="mm"/></union>
 </solids>
 <structure>
  <volume name="cut_lv"><materialref ref="A"/><solidref ref="cut"/></volume>
  <volume name="both_lv"><materialref ref="B"/><solidref ref="both"/></volume>
  <volume name="pair_lv"><materialref ref="C"/><solidref ref="pair"/></volume>
  <volume name="wl"><materialref ref="V"/><solidref ref="w"/>
   <physvol><volumeref ref="cut_lv"/></physvol>
   <physvol><volumeref ref="both_lv"/></physvol>
   <physvol><volumeref ref="pair_lv"/></physvol>
  </volume>
 </structure>
 <setup name="Default" version="1.0"><world ref="wl"/></setup></gdml>
""")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prims = geometry.parse_gdml(tmp_path / "bool.gdml")
    by_mat = {}
    for p in prims:
        by_mat.setdefault(p.material, []).append(p)
    assert len(by_mat["A"]) == 1                       # subtraction -> the first
    assert by_mat["A"][0].params["sx"] == pytest.approx(400.0)
    assert len(by_mat["B"]) == 1                       # intersection -> the tighter
    assert by_mat["B"][0].params["sx"] == pytest.approx(100.0)
    assert len(by_mat["C"]) == 2                       # union -> both parts
    assert sorted(p.transform[0, 3] for p in by_mat["C"]) == pytest.approx([0.0, 200.0])


def test_solids_outside_the_world_are_clipped_away(tmp_path):
    """Geant4 tracks nothing past the world, so neither do we: a daughter that
    dwarfs the world must not set the scale of the scene, and one entirely
    outside it must not appear at all."""
    (tmp_path / "huge.gdml").write_text("""<?xml version="1.0"?>
<gdml><define/><materials/>
 <solids>
  <box name="w" x="1000" y="1000" z="1000" lunit="mm"/>
  <box name="ok" x="100" y="100" z="100" lunit="mm"/>
  <box name="huge" x="900000" y="900000" z="900000" lunit="mm"/>
 </solids>
 <structure>
  <volume name="ok_lv"><materialref ref="A"/><solidref ref="ok"/></volume>
  <volume name="huge_lv"><materialref ref="B"/><solidref ref="huge"/></volume>
  <volume name="gone_lv"><materialref ref="C"/><solidref ref="ok"/></volume>
  <volume name="wl"><materialref ref="V"/><solidref ref="w"/>
   <physvol><volumeref ref="ok_lv"/></physvol>
   <physvol><volumeref ref="huge_lv"/></physvol>
   <physvol><volumeref ref="gone_lv"/>
     <position name="far" z="50000" unit="mm"/></physvol>
  </volume>
 </structure>
 <setup name="Default" version="1.0"><world ref="wl"/></setup></gdml>
""")
    prims = geometry.parse_gdml(tmp_path / "huge.gdml")
    mats = [p.material for p in prims]
    assert "C" not in mats                             # 50 m away: dropped
    assert mats.count("A") == 1 and mats.count("B") == 1
    huge = next(p for p in prims if p.material == "B")
    assert huge.params["sx"] == pytest.approx(1000.0)  # clipped to the world
    lo, hi = geometry.bounding_box(prims)
    assert np.allclose(lo, -500.0) and np.allclose(hi, 500.0)


def test_mucoll_ip_region(repo_root):
    """The extracted muon-collider interaction region: the IP on the origin,
    the nozzle materials present, everything inside the world. (The raw
    v0.8 export it comes from satisfies none of this -- see
    examples/mucoll/README.md and gdml/mucoll_ip_extract.py.)"""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prims = geometry.parse_gdml(repo_root / "gdml" / "mucoll_mdi_v0p8_ip.gdml")
    mats = {p.material for p in prims}
    assert {"INERM180", "BORETH", "G4_Be"} <= mats     # nozzle alloy, liner, chamber

    # the beryllium chamber marks the interaction point: r 24 mm, 316 mm long
    chamber = [p for p in prims if p.material == "G4_Be"]
    assert len(chamber) == 1
    assert np.allclose(chamber[0].transform[:3, 3], 0.0, atol=1.0)
    assert chamber[0].params["rmax"] == pytest.approx(24.0, abs=0.01)

    # the nozzles reach out to metres either side of it, and nothing escapes
    # the 16 x 16 x 14 m world
    lo, hi = geometry.bounding_box(prims)
    assert hi[2] > 5000.0 and lo[2] < -5000.0
    assert np.all(lo >= [-8000.0, -8000.0, -7000.0])
    assert np.all(hi <= [8000.0, 8000.0, 7000.0])


def test_mucoll_ip_extract_is_up_to_date(repo_root, tmp_path):
    """The committed IP file must be what the script makes from the committed
    lattice export -- otherwise the two drift and the derivation stops being
    checkable."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mucoll_ip_extract", repo_root / "gdml" / "mucoll_ip_extract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    regenerated = mod.main(tmp_path / "regenerated.gdml")
    assert regenerated.read_bytes() == \
        (repo_root / "gdml" / "mucoll_mdi_v0p8_ip.gdml").read_bytes(), (
            "gdml/mucoll_mdi_v0p8_ip.gdml is stale; "
            "re-run python3 gdml/mucoll_ip_extract.py")


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


def test_generic_polycone_rzpoint_bbox(tmp_path):
    """genericPolycone stores geometry in <rzpoint>, not <zplane>; it must get
    a bbox fallback, not vanish."""
    import warnings
    gdml = """<?xml version="1.0"?>
<gdml>
  <solids>
    <box name="wb" x="2000" y="2000" z="2000" lunit="mm"/>
    <genericPolycone name="gp" startphi="0" deltaphi="360" aunit="deg" lunit="mm">
      <rzpoint r="100" z="50"/>
      <rzpoint r="300" z="400"/>
      <rzpoint r="50"  z="900"/>
    </genericPolycone>
  </solids>
  <structure>
    <volume name="inner"><solidref ref="gp"/></volume>
    <volume name="World"><solidref ref="wb"/>
      <physvol><volumeref ref="inner"/></physvol>
    </volume>
  </structure>
  <setup name="Default" version="1.0"><world ref="World"/></setup>
</gdml>"""
    p = tmp_path / "gp.gdml"
    p.write_text(gdml)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prims = geometry.parse_gdml(p)
    assert len(prims) == 1
    bb = geometry.bounding_box(prims)
    lo, hi = bb
    assert hi[2] - lo[2] == pytest.approx(850.0)     # z spans 50..900
    assert hi[0] - lo[0] == pytest.approx(600.0)     # r max 300
    assert 0.5 * (lo[2] + hi[2]) == pytest.approx(475.0)  # offset applied


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


def test_tissue_phantom_lead_filter_sits_in_front_of_an_unmoved_phantom(repo_root):
    """The lead-filtered phantom is the layered one plus a 1 mm G4_Pb slab
    flush against the entrance face: the lead spans z = -1..0 mm and every
    tissue layer keeps the position it has in the unshielded file, so the two
    geometries stay comparable bin for bin (see macros/README.md)."""
    def layers(name):
        prims = geometry.parse_gdml(repo_root / "gdml" / name)
        return sorted(((p.material, round(float(p.transform[2, 3]), 6),
                        round(p.params["sz"], 6)) for p in prims),
                      key=lambda l: l[1])

    bare = layers("tissue_phantom_layered.gdml")
    shielded = layers("tissue_phantom_lead_1mm.gdml")

    lead = shielded[0]
    assert lead[0] == "G4_Pb"
    assert lead[2] == pytest.approx(1.0)               # 1 mm thick
    assert lead[1] == pytest.approx(-0.5)              # spanning z = -1..0 mm
    assert shielded[1:] == bare                        # nothing else moved

    pb = next(p for p in geometry.parse_gdml(repo_root / "gdml" / "tissue_phantom_lead_1mm.gdml")
              if p.material == "G4_Pb")
    assert (pb.params["sx"], pb.params["sy"]) == pytest.approx((300.0, 300.0))
