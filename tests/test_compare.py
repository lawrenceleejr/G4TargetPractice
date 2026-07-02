from g4tp import compare


def test_compare_end_to_end(synth_pair, tmp_path):
    dense, loose = synth_pair
    out = compare.compare(dense, loose, labels=("DU", "W"), outdir=tmp_path / "cmp")

    text = (out / "summary.txt").read_text()
    assert "[DU]" in text and "[W]" in text
    assert "Energy leakage" in text
    assert "contains the shower better" in text
    for f in ("shower_profile.png", "containment.png", "leakage.png"):
        assert (out / f).exists(), f


def test_compare_orders_materials_correctly(synth_pair, tmp_path):
    """Dense (x0=2.5, leak 1.2%) must beat loose (x0=3.5, leak 3.0%) on both axes."""
    from g4tp.analyze import longitudinal_profile
    dense, loose = synth_pair
    _, _, _, sd = longitudinal_profile(dense, verbose=False)
    _, _, _, sl = longitudinal_profile(loose, verbose=False)
    assert sd["d95_cm"] < sl["d95_cm"]
    assert sd["mean_leak_frac"] < sl["mean_leak_frac"]
