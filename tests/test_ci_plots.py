"""The CI docker-run jobs' plotting/assertion script, against the synthetic
ntuples -- so a schema change breaks in the fast gating suite rather than an
hour into a docker-run job.

The script lives in .github/scripts (it is CI tooling, not part of the package
-- it deliberately imports no gdmltp), so it is loaded by path.
"""
import importlib.util
import sys

import pytest

from gdmltp import handoff
from gdmltp.backends import genie_convert


@pytest.fixture(scope="module")
def ci_plots(repo_root):
    path = repo_root / ".github" / "scripts" / "ci_ntuple_plots.py"
    spec = importlib.util.spec_from_file_location("ci_ntuple_plots", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def transported(synth_gst, tmp_path):
    """A generator vertex record merged onto a transport record -- what the
    genie+Geant4 docker-run job produces."""
    sys.path.insert(0, str(tmp_path.parent))
    from conftest import write_synthetic
    vertex = str(tmp_path / "vertex.root")
    genie_convert.convert(synth_gst, vertex)
    t = write_synthetic(tmp_path / "t.root", n_events=25, seed=8)
    merged = str(tmp_path / "merged.root")
    handoff.merge_nu_block(t, vertex, merged)
    return merged, vertex


def test_geant4_file_passes_and_plots(ci_plots, tmp_path):
    sys.path.insert(0, str(tmp_path.parent))
    from conftest import write_synthetic
    root = write_synthetic(tmp_path / "g4.root", n_events=20, seed=1)
    out = tmp_path / "plots"
    assert ci_plots.main([str(root), "-o", str(out), "--label", "150 MeV p -> water",
                          "--min-events", "20", "--require-steps"]) == 0
    names = {p.name for p in out.iterdir()}
    assert {"primary_energy.pdf", "total_edep.pdf", "edep_vs_depth.pdf",
            "summary.txt"} <= names
    assert "steps: total" in (out / "summary.txt").read_text()


def test_transported_nu_file_gets_the_kinematics_panels(ci_plots, transported, tmp_path):
    merged, _ = transported
    out = tmp_path / "nu_plots"
    assert ci_plots.main([merged, "-o", str(out), "--min-events", "25",
                          "--require-steps", "--require-nu"]) == 0
    names = {p.name for p in out.iterdir()}
    assert {"nu_Q2.pdf", "nu_y.pdf", "nu_W.pdf"} <= names


def test_requirements_fail_loudly(ci_plots, transported, tmp_path):
    """The requirement flags are the docker-run jobs' actual assertions: a
    vertex-level file has the nu block but no transport, and must be red."""
    merged, vertex = transported
    assert ci_plots.main([vertex, "-o", str(tmp_path / "a"),
                          "--require-nu", "--require-steps"]) == 1
    assert ci_plots.main([merged, "-o", str(tmp_path / "b"),
                          "--min-events", "1000"]) == 1
