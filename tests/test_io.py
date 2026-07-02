import numpy as np
import pytest

from g4tp import io


def test_num_events(synth_root):
    assert io.num_events(synth_root) == 30


def test_available_branches(synth_root):
    brs = io.available_branches(synth_root)
    for b in ("primaryE", "totalEdep", "trk_pdg", "step_z", "step_edep"):
        assert b in brs


def test_load_events_full(synth_root):
    events = io.load_events(synth_root)
    assert len(events) == 30
    e = events[0]
    assert e.scalars["primaryPDG"] == 11
    assert e.scalars["primaryE"] == pytest.approx(50000.0)
    assert len(e.trk["trk_id"]) == 20
    assert len(e.step["step_z"]) == 200
    # strings decode to str
    assert e.trk["trk_creatorProcess"][0] in ("Primary", b"Primary")


def test_load_events_slice(synth_root):
    events = io.load_events(synth_root, entry_start=5, entry_stop=8)
    assert len(events) == 3
    assert events[0].scalars["eventID"] == 5


def test_read_scalars(synth_root):
    sc = io.read_scalars(synth_root, ["primaryE", "totalEdep", "not_a_branch"])
    assert set(sc) == {"primaryE", "totalEdep"}
    assert len(sc["primaryE"]) == 30
    # leakage bookkeeping: totalEdep strictly below primaryE (synthetic leaks >0)
    assert np.all(sc["totalEdep"] < sc["primaryE"])


def test_iterate_flat(synth_root):
    n_seen, edep_sum = 0, 0.0
    for n, cols in io.iterate_flat(synth_root, ["step_z", "step_edep"], step_size="1 MB"):
        n_seen += n
        assert cols["step_z"].ndim == 1
        assert len(cols["step_z"]) == len(cols["step_edep"])
        edep_sum += cols["step_edep"].sum()
    assert n_seen == 30
    # step_edep sums to sum(totalEdep) by construction
    sc = io.read_scalars(synth_root, ["totalEdep"])
    assert edep_sum == pytest.approx(sc["totalEdep"].sum(), rel=1e-6)


def test_iterate_flat_missing_branch(synth_root):
    with pytest.raises(ValueError, match="missing branch"):
        next(iter(io.iterate_flat(synth_root, ["no_such_branch"])))


def test_iterate_flat_preserves_dtype(synth_root):
    """Integer branches must come back integral (no float64 round trip)."""
    _, cols = next(iter(io.iterate_flat(synth_root, ["trk_pdg"])))
    assert np.issubdtype(cols["trk_pdg"].dtype, np.integer)


def test_synthetic_schema_is_complete(synth_root, synth_nu):
    """Guard against fixture/schema drift: the synthetic files must carry every
    branch io.py declares (which mirrors RunAction.cc), so new branches added
    to the sim + io lists force the fixture to keep up."""
    brs = set(io.available_branches(synth_root))
    for b in io.SCALAR_BRANCHES + io.TRK_BRANCHES + io.STEP_BRANCHES:
        assert b in brs, f"fixture missing {b}"
    nu_brs = set(io.available_branches(synth_nu))
    for b in io.NU_BRANCHES:
        assert b in nu_brs, f"nu fixture missing {b}"


def test_empty_file(empty_root):
    assert io.num_events(empty_root) == 0
    assert io.load_events(empty_root) == []


def test_positions_are_mm(synth_root):
    """Guard the unit contract: the ntuple stores mm (z0 = 650 cm = 6500 mm)."""
    sc = io.read_scalars(synth_root, ["primaryStartZ"])
    assert np.median(sc["primaryStartZ"]) == pytest.approx(6500.0)
    assert io.MM_PER_CM == 10.0
