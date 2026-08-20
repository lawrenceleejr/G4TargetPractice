"""The ntuple writer: a classic TTree, not an RNTuple.

uproot 5.7 made RNTuple the default for `file["tree"] = data`, which silently
turned every file this package writes into something plain ROOT cannot open:

    root [1] TFile f("output.root")
    Error in <TKey::ReadObj>: Unknown class ROOT::RNTuple

uproot itself reads RNTuples, so nothing in our own tooling noticed. These
tests pin the format at the boundary where it matters -- what ends up in the
file -- for every writer in the package.
"""
import numpy as np
import awkward as ak
import pytest
import uproot

from gdmltp import io, handoff
from gdmltp.backends import genie_convert, achilles_convert, external


def classnames(path):
    with uproot.open(str(path)) as f:
        return f.classnames()


def test_writer_produces_a_ttree(tmp_path):
    p = tmp_path / "t.root"
    io.write_tree(p, {"eventID": np.arange(3, dtype=np.int32),
                      "totalEdep": np.array([1.0, 2.0, 3.0]),
                      "trk_pdg": ak.Array([[11, 22], [2212], []])})
    assert classnames(p) == {"tree;1": "TTree"}
    with uproot.open(p) as f:
        assert f["tree"].num_entries == 3                 # written once, not twice
        assert ak.to_list(f["tree"]["trk_pdg"].array()) == [[11, 22], [2212], []]


def test_every_backend_converter_writes_a_ttree(synth_gst, synth_nuhepmc, tmp_path):
    """The files a user actually downloads: vertex-level from each converter,
    and the merged generator+transport output."""
    import sys
    sys.path.insert(0, str(tmp_path.parent))
    from conftest import write_synthetic

    genie_convert.convert(synth_gst, str(tmp_path / "genie.root"))
    achilles_convert.convert(synth_nuhepmc, str(tmp_path / "achilles.root"))
    external.convert(synth_nuhepmc, str(tmp_path / "external.root"))
    transported = write_synthetic(tmp_path / "g4.root", n_events=25, seed=3)
    handoff.merge_nu_block(transported, str(tmp_path / "genie.root"),
                           str(tmp_path / "merged.root"))

    for name in ("genie", "achilles", "external", "merged", "g4"):
        cls = classnames(tmp_path / f"{name}.root")
        assert cls["tree;1"] == "TTree", f"{name}.root is {cls['tree;1']}"
        assert "ROOT::RNTuple" not in cls.values()


# --- process names: int codes + legend ----------------------------------------
def test_string_branches_round_trip_through_codes(tmp_path):
    p = tmp_path / "s.root"
    names = ak.Array([["Primary", "eBrem"], ["Decay"], []])
    io.write_tree(p, {"trk_creatorProcess": names,
                      "step_process": ak.Array([["eIoni"], [], ["msc", "eIoni"]])})

    with uproot.open(p) as f:
        assert f.classnames() == {"tree;1": "TTree", "gdmltp_strings;1": "TTree"}
        stored = f["tree"]["trk_creatorProcess"].array()
    assert str(ak.type(stored)).endswith("int32"), "should be stored as codes"

    assert io.string_legend(p)["trk_creatorProcess"] == ["Decay", "Primary", "eBrem"]
    assert ak.to_list(io.read_string_branch(p, "trk_creatorProcess")) == ak.to_list(names)
    assert ak.to_list(io.read_string_branch(p, "step_process")) == [["eIoni"], [], ["msc", "eIoni"]]


def test_empty_string_branch_is_still_declared(tmp_path):
    """A vertex-level file has no steps at all: the branch must survive as an
    (empty) encoded branch, not decay into an untyped numeric one."""
    p = tmp_path / "e.root"
    empty = ak.unflatten(np.array([], dtype="<U1"), np.zeros(3, int))
    io.write_tree(p, {"eventID": np.arange(3, dtype=np.int32), "step_process": empty})
    assert "step_process" in io.string_legend(p)
    assert ak.to_list(io.read_string_branch(p, "step_process")) == [[], [], []]


def test_native_geant4_strings_read_back_unchanged(tmp_path):
    """g4sim writes real vector<string>; the same reader must handle those."""
    p = tmp_path / "native.root"
    with uproot.recreate(p) as f:                 # RNTuple: the only way to get
        f["tree"] = {"trk_creatorProcess":        # jagged strings out of uproot
                     ak.Array([["Decay"], ["eIoni", "msc"]])}
    assert io.string_legend(p) == {}              # no legend -> stored as strings
    assert ak.to_list(io.read_string_branch(p, "trk_creatorProcess")) == \
        [["Decay"], ["eIoni", "msc"]]


def test_load_events_gives_names_whichever_encoding(synth_root):
    ev = io.load_events(synth_root, entry_stop=1)[0]
    assert ev.trk["trk_creatorProcess"][0] == "Primary"


def test_flat_string_branches_are_left_alone(tmp_path):
    """One string per event is writable as-is; only the jagged case is encoded."""
    p = tmp_path / "flat.root"
    io.write_tree(p, {"label": ak.Array(["a", "b"]), "eventID": np.arange(2, dtype=np.int32)})
    assert io.string_legend(p) == {}
    with uproot.open(p) as f:
        assert [x for x in f["tree"]["label"].array(library="np")] == ["a", "b"]
