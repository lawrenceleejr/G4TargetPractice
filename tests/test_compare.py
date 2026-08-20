from gdmltp import io, compare


def test_compare_end_to_end(synth_pair, tmp_path):
    dense, loose = synth_pair
    out = compare.compare(dense, loose, labels=("DU", "W"), outdir=tmp_path / "cmp")

    text = (out / "summary.txt").read_text()
    assert "[DU]" in text and "[W]" in text
    assert "Energy leakage" in text
    assert "contains the shower better" in text
    for f in ("shower_profile.png", "containment.png", "leakage.png"):
        assert (out / f).exists(), f


def test_compare_negative_leakage_does_not_crash(tmp_path):
    """totalEdep > primaryE is physical (e+ annihilation, exothermic capture):
    the leakage histogram must span negative values, not crash on them."""
    import numpy as np
    from conftest import write_synthetic
    import uproot

    a = write_synthetic(tmp_path / "a.root", n_events=10, seed=7)
    b = write_synthetic(tmp_path / "b.root", n_events=10, seed=8)
    # rewrite b's totalEdep above primaryE -> negative leakage everywhere
    with uproot.open(str(b)) as f:
        data = {k.split(";")[0]: f["tree"][k.split(";")[0]].array()
                for k in f["tree"].keys()}
    data["totalEdep"] = np.asarray(data["primaryE"]) * 1.02
    io.write_tree(b, data)
    out = compare.compare(a, str(b), labels=("A", "B"), outdir=tmp_path / "cmp")
    assert (out / "leakage.png").exists()


def test_compare_vertex_level_files(tmp_path):
    """Two vertex-level generator files (no steps at all): compare must not
    crash on the missing shower, and must emit the nu kinematics overlay --
    this IS the cross-generator neutrino comparison workflow."""
    from conftest import write_synthetic_gst
    from gdmltp.backends import genie_convert
    ga = write_synthetic_gst(tmp_path / "a.gst.root", seed=21)
    gb = write_synthetic_gst(tmp_path / "b.gst.root", seed=22)
    ra, rb = tmp_path / "a.root", tmp_path / "b.root"
    genie_convert.convert(ga, str(ra))
    genie_convert.convert(gb, str(rb))
    out = compare.compare(str(ra), str(rb), labels=("tuneA", "tuneB"),
                          outdir=tmp_path / "cmp")
    text = (out / "summary.txt").read_text()
    assert "no shower comparison" in text
    assert "Neutrino interaction comparison" in text
    assert "[tuneA] interacted" in text
    assert (out / "nu_kinematics.png").exists()
    assert not (out / "shower_profile.png").exists()


def test_compare_nu_transport_files_get_both(synth_nu, tmp_path):
    """Files with steps AND a nu block get the shower plots and the nu overlay."""
    out = compare.compare(synth_nu, synth_nu, labels=("A", "B"),
                          outdir=tmp_path / "cmp")
    assert (out / "shower_profile.png").exists()
    assert (out / "nu_kinematics.png").exists()


def test_compare_orders_materials_correctly(synth_pair, tmp_path):
    """Dense (x0=2.5, leak 1.2%) must beat loose (x0=3.5, leak 3.0%) on both axes."""
    from gdmltp.analyze import longitudinal_profile
    dense, loose = synth_pair
    _, _, _, sd = longitudinal_profile(dense, verbose=False)
    _, _, _, sl = longitudinal_profile(loose, verbose=False)
    assert sd["d95_cm"] < sl["d95_cm"]
    assert sd["mean_leak_frac"] < sl["mean_leak_frac"]
