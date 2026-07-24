"""The pyg4ometry-backed GDML parser (the standard tool, used when installed).

Skipped when pyg4ometry is absent (it is an optional [geometry] extra, since it
pulls in vtk). Verifies it produces the same Primitive contract as the built-in
parser on the shipped geometries, extracts material names for target inference,
and gives an accurate mesh bounding box for a polycone (the win over the
lightweight bbox heuristic).
"""
import numpy as np
import pytest

pytest.importorskip("pyg4ometry")

from gdmltp import geometry as G


@pytest.fixture(autouse=True)
def _use_pyg4ometry(monkeypatch):
    monkeypatch.setenv("GDMLTP_GDML_PARSER", "pyg4ometry")


def _gdml(repo_root, name):
    return str(repo_root / "gdml" / name)


@pytest.mark.parametrize("name", ["water_phantom_30cm.gdml", "silicon_3layer.gdml",
                                  "liquid_argon_1m3.gdml", "water_phantom_tumor.gdml"])
def test_matches_lightweight_bbox(repo_root, name):
    """Same primitive count and bounding box as the built-in parser, to ~1 mm."""
    p = _gdml(repo_root, name)
    pg = G._parse_pyg4ometry(p)
    lw = G._parse_lightweight(p)
    assert len(pg) == len(lw)
    (plo, phi), (llo, lhi) = G.bounding_box(pg), G.bounding_box(lw)
    assert np.allclose(plo, llo, atol=1.0) and np.allclose(phi, lhi, atol=1.0)


def test_dispatch_prefers_pyg4ometry(repo_root):
    assert G._use_pyg4ometry(_gdml(repo_root, "liquid_argon_1m3.gdml")) is True
    prims = G.parse_gdml(_gdml(repo_root, "silicon_3layer.gdml"))
    assert prims and all(p.type in ("box", "orb", "tube", "bbox") for p in prims)


def test_material_names_for_target_inference(repo_root):
    """pyg4ometry exposes the NIST material ref names the genie backend needs."""
    prims = G._parse_pyg4ometry(_gdml(repo_root, "liquid_argon_1m3.gdml"))
    assert any(p.material == "G4_lAr" for p in prims)
    from gdmltp.backends.genie import infer_target
    import os
    os.environ["GDMLTP_GDML_PARSER"] = "pyg4ometry"
    try:
        assert infer_target(_gdml(repo_root, "liquid_argon_1m3.gdml")) == 1000180400
    finally:
        del os.environ["GDMLTP_GDML_PARSER"]


def test_polycone_gets_accurate_extent(repo_root):
    """The real win: a polycone's bounding box comes from its mesh (true z-span
    and radius), not the lightweight crude fallback."""
    prims = G._parse_pyg4ometry(_gdml(repo_root, "nozzles_depleted_uranium.gdml"))
    assert prims
    lo, hi = G.bounding_box(prims)
    span = hi - lo
    # the DU nozzle polycone is long in z and narrower transverse (mm scale)
    assert span[2] > span[0] and span[2] > 100.0
