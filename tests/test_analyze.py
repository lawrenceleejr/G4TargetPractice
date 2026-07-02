import numpy as np
import pytest

from g4tp import analyze


def test_longitudinal_profile_units_and_shape(synth_root):
    """Depth must come out in cm: profile is Gamma(3, x0=3.0 cm) -> mode 6 cm."""
    centers, dEdz, absorbed, stats = analyze.longitudinal_profile(synth_root, verbose=False)
    assert stats["n_events"] == 30
    assert stats["E0_MeV"] == pytest.approx(50000.0)
    # peak of Gamma(shape=3, scale=x0) is at 2*x0 = 6 cm (energy-weighted, binned)
    assert 4.0 < stats["peak_depth_cm"] < 8.0
    # d90 of Gamma(3, 3.0) is ~16 cm; well under 40 cm, well over 10 cm
    assert 10.0 < stats["d90_cm"] < 40.0
    assert stats["d90_cm"] <= stats["d95_cm"] <= stats["d99_cm"]
    # curves are consistent
    assert len(centers) == len(dEdz) == len(absorbed)
    assert np.all(np.diff(absorbed) >= -1e-12)          # cumulative
    assert 0.9 < stats["absorbed_fraction"] <= 1.0      # ~98% recorded in window


def test_longitudinal_profile_leakage(synth_root):
    _, _, _, stats = analyze.longitudinal_profile(synth_root, verbose=False)
    # injected mean_leak=0.02 with 30 events: loose tolerance
    assert 0.005 < stats["mean_leak_frac"] < 0.05
    assert len(stats["leak_frac"]) == 30
    assert stats["mean_leak_MeV"] == pytest.approx(
        stats["mean_leak_frac"] * 50000.0, rel=1e-6)


def test_profile_beam_sign(tmp_path):
    """+z beam must give the same depths as the -z default."""
    from conftest import write_synthetic
    p = write_synthetic(tmp_path / "plus.root", pz_sign=+1.0, z0_cm=-650.0, seed=5)
    _, _, _, stats = analyze.longitudinal_profile(p, verbose=False)
    assert 4.0 < stats["peak_depth_cm"] < 8.0


def test_summarize(synth_root, tmp_path):
    out = analyze.summarize(synth_root, outdir=tmp_path / "ana")
    text = (out / "summary.txt").read_text()
    assert "events: 30" in text
    assert "primary: e- (PDG 11)" in text
    assert "energy leakage" in text
    assert "particles (all tracks, summed):" in text
    for f in ("primary_energy.png", "total_edep.png", "depth_dose.png"):
        assert (out / f).exists(), f
    assert "neutrino" not in text


def test_summarize_no_plots(synth_root, tmp_path):
    out = analyze.summarize(synth_root, outdir=tmp_path / "ana2", make_plots=False)
    assert (out / "summary.txt").exists()
    assert not (out / "depth_dose.png").exists()


def test_summarize_nu(synth_nu, tmp_path):
    out = analyze.summarize(synth_nu, outdir=tmp_path / "nu", make_plots=False)
    assert "neutrino: CC=" in (out / "summary.txt").read_text()


def test_summarize_empty(empty_root, tmp_path):
    out = analyze.summarize(empty_root, outdir=tmp_path / "empty")
    assert "events: 0" in (out / "summary.txt").read_text()
