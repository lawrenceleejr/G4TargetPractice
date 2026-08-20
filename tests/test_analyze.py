import numpy as np
import pytest

from gdmltp import io, analyze


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
    text = (out / "summary.txt").read_text()
    assert "neutrino: interacted 30/30" in text
    assert "CC fraction" in text
    assert "<Q2>" in text and "<W>" in text


def test_summarize_nu_writes_kinematics_panel(synth_nu, tmp_path):
    out = analyze.summarize(synth_nu, outdir=tmp_path / "nuplots")
    assert (out / "nu_kinematics.png").exists()


def test_summarize_vertex_level_generator_file(synth_gst, tmp_path):
    """A GENIE/Achilles vertex-level file has no steps: no depth-dose, but the
    neutrino panel and summary must still come out."""
    from gdmltp.backends import genie_convert
    r = tmp_path / "genie.root"
    genie_convert.convert(synth_gst, str(r))
    out = analyze.summarize(str(r), outdir=tmp_path / "ana")
    text = (out / "summary.txt").read_text()
    assert "neutrino: interacted" in text
    assert (out / "nu_kinematics.png").exists()
    assert not (out / "depth_dose.png").exists()


def test_summarize_empty(empty_root, tmp_path):
    out = analyze.summarize(empty_root, outdir=tmp_path / "empty")
    assert "events: 0" in (out / "summary.txt").read_text()


def test_spectrum_beam_normalization(tmp_path):
    """Fully-absorbing target + spectrum beam: absorbed fraction must not
    exceed 1 (a median-based normalization overshoots by ~40% here)."""
    import uproot, awkward as ak
    rng = np.random.default_rng(11)
    n, z0_mm = 60, 6500.0
    E0 = rng.exponential(1000.0, n) + 100.0          # exponential spectrum, MeV
    sz, se = [], []
    for i in range(n):
        m = 150
        sz.append((z0_mm - rng.gamma(3.0, 30.0, m)).astype(np.float64))
        w = rng.gamma(2.0, 1.0, m)
        se.append((w / w.sum() * E0[i]).astype(np.float64))  # fully absorbed
    p = tmp_path / "spec.root"
    io.write_tree(p, {"primaryE": E0, "totalEdep": E0.copy(),
                      "primaryStartZ": np.full(n, z0_mm),
                      "primaryStartPz": np.full(n, -1.0),
                      "step_z": ak.Array(sz), "step_edep": ak.Array(se)})
    _, _, absorbed, stats = analyze.longitudinal_profile(str(p), verbose=False)
    assert stats["absorbed_fraction"] <= 1.0 + 1e-9
    assert stats["absorbed_fraction"] > 0.95        # everything was deposited


def test_summarize_without_totaledep_does_not_fabricate_leakage(tmp_path):
    """A trimmed file without totalEdep must not claim '100% leakage'."""
    import uproot
    p = tmp_path / "trimmed.root"
    io.write_tree(p, {"eventID": np.arange(5, dtype=np.int32),
                      "primaryE": np.full(5, 1000.0),
                      "primaryPDG": np.full(5, 11, np.int32)})
    out = analyze.summarize(str(p), outdir=tmp_path / "out", make_plots=False)
    text = (out / "summary.txt").read_text()
    assert "leakage" not in text
    assert "totalEdep" not in text
