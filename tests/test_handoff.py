"""Generator -> Geant4 transport hand-off: event file, macro, nu-block merge,
and the two-stage orchestration (subprocess mocked; no Docker/engines)."""
import sys

import numpy as np
import pytest

from gdmltp import io, config, handoff, run
from gdmltp.backends import genie_convert


@pytest.fixture()
def vertex_root(synth_gst, tmp_path):
    """A vertex-level ntuple as the genie backend would produce (25 events)."""
    out = str(tmp_path / "vertex.root")
    genie_convert.convert(synth_gst, out)
    return out


# --- event file --------------------------------------------------------------
def test_write_event_file_roundtrip(vertex_root, tmp_path):
    path = tmp_path / "events.hepmc"
    n = handoff.write_event_file(vertex_root, path)
    assert n == 25
    events = handoff.read_event_file(path)
    assert len(events) == 25
    ev0 = io.load_events(vertex_root, entry_start=0, entry_stop=1)[0]
    vtx, parts = events[0]
    assert vtx[0] == pytest.approx(float(ev0.nu["nu_vertexX"]), rel=1e-5)
    assert len(parts) == int(ev0.scalars["nTracks"])
    assert parts[0][0] == int(ev0.trk["trk_pdg"][0])
    assert parts[0][1][2] == pytest.approx(float(ev0.trk["trk_pz"][0]), rel=1e-5)


def test_transport_macro():
    mac = handoff.build_transport_macro("lar.gdml", 25, seed=3, field="0 0 2 tesla")
    assert "/detector/readGDML lar.gdml" in mac
    assert "/gun/hepmcFile events.hepmc" in mac
    assert "/run/beamOn 25" in mac
    assert "/analysis/neutrinoMode off" in mac       # nu block comes from the merge
    assert "/random/setSeeds 3 4" in mac
    assert "/detector/setGlobalField 0 0 2 tesla" in mac


# --- merge -------------------------------------------------------------------
def test_merge_nu_block(vertex_root, tmp_path):
    sys.path.insert(0, str(tmp_path.parent))
    from conftest import write_synthetic
    transported = write_synthetic(tmp_path / "transported.root", n_events=25, seed=5)
    out = str(tmp_path / "merged.root")
    handoff.merge_nu_block(transported, vertex_root, out)

    brs = set(io.available_branches(out))
    for b in io.SCALAR_BRANCHES + io.TRK_BRANCHES + io.STEP_BRANCHES + io.NU_BRANCHES:
        assert b in brs, f"merged file missing {b}"

    import uproot
    t = uproot.open(out)["tree"]
    tv = uproot.open(vertex_root)["tree"]
    tt = uproot.open(transported)["tree"]
    # nu block + primary identity from the generator
    assert np.array_equal(t["nu_Q2"].array(library="np"), tv["nu_Q2"].array(library="np"))
    assert np.all(t["primaryPDG"].array(library="np") == 14)
    # transport record intact
    assert np.array_equal(t["totalEdep"].array(library="np"),
                          tt["totalEdep"].array(library="np"))
    assert t["nSteps"].array(library="np").sum() > 0


def test_merge_event_count_mismatch(vertex_root, tmp_path):
    sys.path.insert(0, str(tmp_path.parent))
    from conftest import write_synthetic
    transported = write_synthetic(tmp_path / "t.root", n_events=10, seed=5)
    with pytest.raises(ValueError, match="25"):
        handoff.merge_nu_block(transported, vertex_root, str(tmp_path / "m.root"))


# --- two-stage orchestration ---------------------------------------------------
def test_run_config_transport_two_stages(repo_root, synth_gst, tmp_path, monkeypatch):
    """genie.transport runs the generator image, then the geant4 image with the
    transport macro, and merges -- verified with docker mocked."""
    sys.path.insert(0, str(tmp_path.parent))
    from conftest import write_synthetic
    calls = []

    def fake_popen(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:           # generator stage: emit vertex-level output
            genie_convert.convert(synth_gst, tmp_path / "output.root")
        else:                          # transport stage: emit transported output
            write_synthetic(tmp_path / "output.root", n_events=25, seed=6)

        class P:  # noqa
            stdout = iter(["--> Event 0 starts."])
            returncode = 0
            def wait(self):  # noqa
                return 0
        return P()

    monkeypatch.setattr(run.subprocess, "Popen", fake_popen)
    cfg = config.RunConfig(
        generator="genie",
        gdml=str(repo_root / "gdml" / "liquid_argon_1m3.gdml"),
        beam=config.Beam(particle="nu_mu",
                         energy=config.Energy(mode="mono", value="2 GeV")),
        run=config.RunSettings(events=25),
        genie={"tune": "G18_10a_00_000", "transport": True})
    run.run_config(cfg, outdir=str(tmp_path))

    assert len(calls) == 2
    assert any("gdmltargetpractice-genie" in c for c in calls[0])
    assert any("gdmltargetpractice:main" in c for c in calls[1])   # geant4 image
    assert calls[1][-1] == handoff.TRANSPORT_MACRO
    assert (tmp_path / handoff.EVENT_FILE).exists()

    import uproot
    t = uproot.open(tmp_path / "output.root")["tree"]
    assert np.all(t["primaryPDG"].array(library="np") == 14)     # nu from generator
    assert t["nSteps"].array(library="np").sum() > 0             # steps from transport


def test_run_config_transport_dry_run(repo_root, tmp_path, capsys):
    cfg = config.RunConfig(
        generator="genie",
        gdml=str(repo_root / "gdml" / "liquid_argon_1m3.gdml"),
        beam=config.Beam(particle="nu_mu",
                         energy=config.Energy(mode="mono", value="2 GeV")),
        run=config.RunSettings(events=5),
        genie={"transport": True})
    run.run_config(cfg, outdir=str(tmp_path), dry_run=True)
    out = capsys.readouterr().out
    assert "dry-run" in out and "transport" in out


# --- event weight ------------------------------------------------------------
def test_event_weight_survives_the_handoff_roundtrip(vertex_root, tmp_path):
    """The generator's per-event weight must reach the final ntuple: it rides the
    HepMC event weight into g4sim and is grafted back by the merge. Anything that
    drops it silently rescales every rate the transported file is used for."""
    import uproot
    with uproot.open(vertex_root) as f:
        want = f["tree"]["eventWeight"].array(library="np")
    assert not np.allclose(want, 1.0), "fixture should have non-trivial weights"

    # 1. host -> HepMC: the weight becomes the HepMC event weight
    path = tmp_path / "events.hepmc"
    handoff.write_event_file(vertex_root, path)
    import pyhepmc
    got = []
    with pyhepmc.open(str(path)) as reader:
        for ev in reader:
            got.append(ev.weights[0])
    np.testing.assert_allclose(got, want, rtol=1e-6)

    # 2. merge: the transported file (whose own weights are irrelevant) takes the
    #    generator's values
    sys.path.insert(0, str(tmp_path.parent))
    from conftest import write_synthetic
    transported = write_synthetic(tmp_path / "transported.root", n_events=25, seed=9)
    merged = str(tmp_path / "merged.root")
    handoff.merge_nu_block(transported, vertex_root, merged)
    with uproot.open(merged) as f:
        np.testing.assert_allclose(f["tree"]["eventWeight"].array(library="np"), want)


def test_pseudo_particles_are_left_out_of_the_handoff(vertex_root, tmp_path, capsys):
    """GENIE final-state lists carry internal pseudo-particles (hadronic blob /
    bindino at 2000000xxx) that Geant4 has no definition for. They must not reach
    the hand-off file: g4sim cannot transport them, and the run must not hinge on
    the engine tolerating them."""
    import uproot
    import awkward as ak

    with uproot.open(vertex_root) as f:
        t = f["tree"]
        data = {k.split(";")[0]: t[k].array() for k in t.keys()}
    n_real = len(ak.to_list(data["trk_pdg"])[0])

    # splice a hadronic blob and a zero PDG onto event 0's final state, padding
    # every per-track branch so the jagged lengths stay consistent
    for name, arr in list(data.items()):
        if not name.startswith("trk_"):
            continue
        vals = ak.to_list(arr)
        pad = [2000000001, 0] if name == "trk_pdg" else (
            ["x", "x"] if isinstance(vals[0][0], str) else [1.0, 1.0])
        vals[0] = vals[0] + pad
        data[name] = ak.Array(vals)
    doctored = tmp_path / "with_pseudo.root"
    with uproot.recreate(doctored) as f:
        f["tree"] = data

    path = tmp_path / "events.hepmc"
    handoff.write_event_file(doctored, path)
    out = capsys.readouterr().out
    assert "pseudo-particle" in out and "2000000001" in out

    events = handoff.read_event_file(path)
    written = [p[0] for p in events[0][1]]
    assert 2000000001 not in written and 0 not in written
    assert len(written) == n_real          # the real particles all survive
