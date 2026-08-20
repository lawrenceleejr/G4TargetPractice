"""GENIE gst -> output.root conversion + genie backend job spec.

All of this runs with zero GENIE dependency: the converter reads a synthetic
gst fixture and must emit a file that satisfies the same schema-completeness
guard as the Geant4 output, and reads back identically through io.py.
"""
import json
import numpy as np
import pytest

from gdmltp import io, config
from gdmltp.backends import genie, genie_convert
from gdmltp.masses import mass_mev, kinetic_mev


# --- masses ---------------------------------------------------------------- #
def test_masses_basic():
    assert kinetic_mev(2212, 1000.0) == pytest.approx(1000.0 - 938.272, abs=1e-2)
    assert kinetic_mev(22, 500.0) == 500.0            # massless
    assert kinetic_mev(2212, 900.0) == 0.0            # clamp below rest mass
    # ion: mass ~ A * u
    assert mass_mev(1000180400) == pytest.approx(40 * 931.494, rel=1e-4)


# --- converter ------------------------------------------------------------- #
def test_convert_schema_complete(synth_gst, tmp_path):
    out = str(tmp_path / "output.root")
    genie_convert.convert(synth_gst, out, vtx_units="cm")
    brs = set(io.available_branches(out))
    for b in io.SCALAR_BRANCHES + io.TRK_BRANCHES + io.STEP_BRANCHES + io.NU_BRANCHES:
        assert b in brs, f"converted file missing {b}"


def test_convert_reads_back_through_io(synth_gst, tmp_path):
    out = str(tmp_path / "output.root")
    genie_convert.convert(synth_gst, out, vtx_units="cm")
    n = io.num_events(out)
    assert n == 25
    events = io.load_events(out)
    e0 = events[0]
    # one trk row per final-state particle; nTracks matches
    assert e0.scalars["nTracks"] == len(e0.trk["trk_pdg"])
    # GENIE vertex-only: no steps, no deposited energy
    assert e0.scalars["nSteps"] == 0
    assert e0.scalars["totalEdep"] == 0.0
    assert len(e0.step["step_z"]) == 0
    # nu block present and populated
    assert e0.nu, "nu_* block should be present"
    assert e0.scalars["primaryPDG"] == 14


def test_convert_units_and_kinematics(synth_gst, tmp_path):
    """Energies MeV, Q2 MeV^2, vertex cm->mm; consistent with the gst inputs."""
    import uproot
    out = str(tmp_path / "output.root")
    genie_convert.convert(synth_gst, out, vtx_units="cm")
    gst = uproot.open(synth_gst)["gst"]
    conv = uproot.open(out)["tree"]

    Ev_gev = gst["Ev"].array(library="np")
    primaryE = conv["primaryE"].array(library="np")
    assert np.allclose(primaryE, Ev_gev * 1000.0)

    q2_gev2 = gst["Q2"].array(library="np")
    nu_q2 = conv["nu_Q2"].array(library="np")
    assert np.allclose(nu_q2, q2_gev2 * 1e6)

    vtxz_cm = gst["vtxz"].array(library="np")
    vz_mm = conv["nu_vertexZ"].array(library="np")
    assert np.allclose(vz_mm, vtxz_cm * 10.0)          # cm -> mm


def test_convert_trk_start_energy_is_kinetic(synth_gst, tmp_path):
    import uproot, awkward as ak
    out = str(tmp_path / "output.root")
    genie_convert.convert(synth_gst, out)
    conv = uproot.open(out)["tree"]
    pdg = conv["trk_pdg"].array()
    startE = conv["trk_startE"].array()
    gst = uproot.open(synth_gst)["gst"]
    Ef = gst["Ef"].array()
    # track 0 is the prepended outgoing lepton: kinetic = El*1000 - mass
    p0 = int(pdg[0][0]); lep_tot = float(gst["El"].array()[0]) * 1000.0
    assert float(startE[0][0]) == pytest.approx(max(0.0, lep_tot - mass_mev(p0)), abs=1e-3)
    # track 1 is the first hadron from gst: kinetic = Ef*1000 - mass
    p1 = int(pdg[0][1]); e1_tot = float(Ef[0][0]) * 1000.0
    assert float(startE[0][1]) == pytest.approx(max(0.0, e1_tot - mass_mev(p1)), abs=1e-3)


def test_convert_vtx_units_scale(synth_gst, tmp_path):
    import uproot
    a = str(tmp_path / "a.root"); b = str(tmp_path / "b.root")
    genie_convert.convert(synth_gst, a, vtx_units="cm")
    genie_convert.convert(synth_gst, b, vtx_units="m")
    za = uproot.open(a)["tree"]["nu_vertexZ"].array(library="np")
    zb = uproot.open(b)["tree"]["nu_vertexZ"].array(library="np")
    assert np.allclose(zb, za * 100.0)                 # m is 100x cm


# --- genie backend --------------------------------------------------------- #
def test_probe_pdg():
    assert genie.probe_pdg("nu_mu") == 14
    assert genie.probe_pdg("anti_nu_e") == -12
    with pytest.raises(config.ConfigError, match="neutrino"):
        genie.probe_pdg("proton")


def test_probe_pdg_by_id():
    assert genie.probe_pdg("14") == 14        # numeric string
    assert genie.probe_pdg(-12) == -12        # int
    with pytest.raises(config.ConfigError, match="neutrino"):
        genie.probe_pdg("2212")               # proton PDG rejected
    with pytest.raises(config.ConfigError, match="neutrino"):
        genie.probe_pdg(1000060120)           # ion rejected


def test_infer_target_argon(repo_root):
    t = genie.infer_target(str(repo_root / "gdml" / "liquid_argon_1m3.gdml"))
    assert t == 1000180400            # Ar-40


def test_infer_target_unknown_errors(repo_root, tmp_path):
    gdml = tmp_path / "unobtainium.gdml"
    gdml.write_text(
        '<?xml version="1.0"?><gdml><solids>'
        '<box name="WorldBox" x="10" y="10" z="10" lunit="cm"/>'
        '<box name="B" x="5" y="5" z="5" lunit="cm"/></solids><structure>'
        '<volume name="Blob"><materialref ref="G4_UNOBTAINIUM"/><solidref ref="B"/></volume>'
        '<volume name="World"><materialref ref="G4_AIR"/><solidref ref="WorldBox"/>'
        '<physvol><volumeref ref="Blob"/></physvol></volume>'
        '</structure><setup name="Default" version="1.0"><world ref="World"/></setup></gdml>')
    with pytest.raises(config.ConfigError, match="target"):
        genie.infer_target(str(gdml))


def test_genie_prepare_writes_job(repo_root, tmp_path):
    from gdmltp import backends
    cfg = config.RunConfig(
        generator="genie", gdml=str(repo_root / "gdml" / "liquid_argon_1m3.gdml"),
        beam=config.Beam(particle="nu_mu",
                         energy=config.Energy(mode="mono", value="2.0 GeV")),
        run=config.RunSettings(events=1000, seed=12345),
        genie={"tune": "G18_10a_00_000"})
    cfg.validate()
    b = backends.get("genie")
    prep = b.prepare(cfg, tmp_path)
    assert prep.argv == [genie.JOB_FILE]
    assert prep.image.endswith("-genie:main")
    job = json.loads((tmp_path / genie.JOB_FILE).read_text())
    assert job["probe"] == 14
    assert job["target"] == 1000180400
    assert job["events"] == 1000
    assert job["tune"] == "G18_10a_00_000"
    assert job["flux"]["value"] == "2.0 GeV"


def test_genie_backend_registered():
    from gdmltp import backends
    assert backends.get("genie").name == "genie"


# --- per-event beam replay (vertex + direction rotation) ------------------- #
def test_convert_with_beam_places_vertex_and_rotates(synth_gst, tmp_path):
    """A beam replay overrides each event's vertex and orients the +z GENIE
    event along the ray. Give every ray a +x direction and check the outgoing
    lepton momentum rotated from +z into +x, and the vertex is the ray's."""
    import uproot
    n = io.num_events(synth_gst)
    entries = [("nu_mu", (7.0, 0.0, -3.0), (500.0, 0.0, 0.0)) for _ in range(n)]
    out = str(tmp_path / "output.root")
    genie_convert.convert(synth_gst, out, beam=entries)
    conv = uproot.open(out)["tree"]
    vx = conv["nu_vertexX"].array(library="np")
    vz = conv["nu_vertexZ"].array(library="np")
    assert np.allclose(vx, 7.0) and np.allclose(vz, -3.0)
    assert np.allclose(conv["primaryStartPx"].array(library="np"), 500.0)
    assert np.allclose(conv["primaryStartPz"].array(library="np"), 0.0)
    # outgoing lepton rotated: its old +z component lands on +x
    gst = uproot.open(synth_gst)["gst"]
    pzl = gst["pzl"].array(library="np") * 1000.0
    assert np.allclose(conv["nu_outLeptonPx"].array(library="np"), pzl, atol=1e-6)
    tx = conv["trk_startX"].array()
    assert all(np.allclose(np.asarray(row), 7.0) for row in tx if len(row))


def test_convert_beam_length_mismatch_errors(synth_gst, tmp_path):
    with pytest.raises(ValueError, match="entries but gst"):
        genie_convert.convert(synth_gst, str(tmp_path / "o.root"),
                              beam=[("nu_mu", (0, 0, 0), (1, 0, 0))])


# --- momentum branches + display integration -------------------------------- #
def test_convert_fills_track_momenta(synth_gst, tmp_path):
    import uproot
    out = str(tmp_path / "output.root")
    genie_convert.convert(synth_gst, out)
    t = uproot.open(out)["tree"]
    gst = uproot.open(synth_gst)["gst"]
    pz_conv = t["trk_pz"].array()
    pz_gst = gst["pzf"].array()
    # track 0 is the outgoing lepton (prepended); the hadrons follow in gst order
    assert float(pz_conv[0][0]) == pytest.approx(
        float(gst["pzl"].array()[0]) * 1000.0, rel=1e-9)
    assert float(pz_conv[0][1]) == pytest.approx(float(pz_gst[0][0]) * 1000.0, rel=1e-9)


def test_converted_events_display_with_momentum_rays(synth_gst, tmp_path):
    """GENIE output flows through io -> scene with visible momentum rays."""
    from gdmltp import scene
    out = str(tmp_path / "output.root")
    genie_convert.convert(synth_gst, out)
    ev = io.load_events(out, entry_start=0, entry_stop=1)[0]
    sc = scene.build_scene([], ev)
    assert len(sc.tracks) > 0
    for trk in sc.tracks:
        assert np.linalg.norm(trk.polyline[-1] - trk.polyline[0]) > 1.0


def test_convert_multiple_gst_files_concatenate(synth_gst, tmp_path):
    import sys
    sys.path.insert(0, str(tmp_path.parent))
    from conftest import write_synthetic_gst
    import uproot
    second = write_synthetic_gst(tmp_path / "more.gst.root", n_events=4, seed=9)
    out = str(tmp_path / "cat.root")
    genie_convert.convert([synth_gst, second], out)
    assert io.num_events(out) == 25 + 4
    eid = uproot.open(out)["tree"]["eventID"].array(library="np")
    assert list(eid) == list(range(29))          # renumbered sequentially


# --- flux mapping (driver logic, pure python) ------------------------------ #
def test_parse_energy_gev():
    assert genie.parse_energy_gev("2.0 GeV") == pytest.approx(2.0)
    assert genie.parse_energy_gev("500 MeV") == pytest.approx(0.5)
    assert genie.parse_energy_gev("3") == pytest.approx(3.0)   # bare -> GeV


def test_flux_mono_and_exp_exact():
    a, approx = genie.flux_gevgen_args({"mode": "mono", "value": "2 GeV"})
    assert a == ["-e", "2"] and approx is False
    a, approx = genie.flux_gevgen_args(
        {"mode": "exp", "value": "2 GeV", "min": "200 MeV", "max": "20 GeV"})
    assert a == ["-e", "0.2,20", "-f", "exp(-x/2)"] and approx is False


def test_flux_gauss_is_approximate():
    a, approx = genie.flux_gevgen_args({"mode": "gauss", "value": "3 GeV", "sigma": "500 MeV"})
    assert approx is True
    assert a == ["-e", "3"]


# --- regressions: the complete final state, beam placement, event weight ----- #
def test_convert_prepends_outgoing_lepton(synth_gst, tmp_path):
    """Real gst keeps the primary lepton out of pdgf; the converter must add it
    back, or the Geant4 hand-off never transports the CC muon."""
    import uproot
    out = str(tmp_path / "o.root")
    genie_convert.convert(synth_gst, out)
    t = uproot.open(out)["tree"]
    gst = uproot.open(synth_gst)["gst"]
    pdg = t["trk_pdg"].array()
    nf = gst["nf"].array(library="np")
    fspl = gst["fspl"].array(library="np")
    ntracks = t["nTracks"].array(library="np")
    # exactly one extra track per event, and it is the outgoing lepton, first
    assert list(ntracks) == list(nf + 1)
    assert [int(row[0]) for row in pdg] == list(fspl)
    # every CC event carries its charged lepton
    cc = gst["cc"].array(library="np").astype(bool)
    assert cc.sum() > 0
    for i in np.nonzero(cc)[0]:
        assert 13 in [int(v) for v in pdg[i]]


def test_convert_applies_position_offset(synth_gst, tmp_path):
    """beam.position must move the vertex; gevgen point mode always sits at 0."""
    import uproot, awkward as ak
    a = str(tmp_path / "a.root"); b = str(tmp_path / "b.root")
    genie_convert.convert(synth_gst, a)
    genie_convert.convert(synth_gst, b, position="0 0 -50 cm")
    ta, tb = uproot.open(a)["tree"], uproot.open(b)["tree"]
    za = ta["nu_vertexZ"].array(library="np")
    zb = tb["nu_vertexZ"].array(library="np")
    assert np.allclose(zb - za, -500.0)                      # -50 cm = -500 mm
    # the offset has to follow through to the track/primary start points
    assert np.allclose(tb["primaryStartZ"].array(library="np") - za, -500.0)
    sa = ak.to_numpy(ak.flatten(ta["trk_startZ"].array()))
    sb = ak.to_numpy(ak.flatten(tb["trk_startZ"].array()))
    assert np.allclose(sb - sa, -500.0)


def test_convert_applies_direction_rotation(synth_gst, tmp_path):
    """beam.direction must orient the event; gevgen point mode shoots along +z."""
    import uproot
    out = str(tmp_path / "o.root")
    genie_convert.convert(synth_gst, out, direction="1 0 0")
    t = uproot.open(out)["tree"]
    px = t["primaryStartPx"].array(library="np")
    pz = t["primaryStartPz"].array(library="np")
    E = t["primaryE"].array(library="np")
    assert np.allclose(px, E, rtol=1e-9)      # all momentum now along +x
    assert np.allclose(pz, 0.0, atol=1e-6)


def test_convert_direction_plus_z_is_a_noop(synth_gst, tmp_path):
    import uproot
    a = str(tmp_path / "a.root"); b = str(tmp_path / "b.root")
    genie_convert.convert(synth_gst, a)
    genie_convert.convert(synth_gst, b, direction="0 0 1")
    for k in ("primaryStartPx", "primaryStartPz", "nu_outLeptonPz"):
        assert np.allclose(uproot.open(a)["tree"][k].array(library="np"),
                           uproot.open(b)["tree"][k].array(library="np"))


def test_convert_beam_replay_ignores_position(synth_gst, tmp_path):
    """The replay path carries its own per-event vertex; position must not
    double-apply on top of it."""
    import uproot
    gst = uproot.open(synth_gst)["gst"]
    n = int(gst.num_entries)
    entries = [("nu_mu", (1.0, 2.0, 3.0), (0.0, 0.0, 1000.0))] * n
    out = str(tmp_path / "o.root")
    genie_convert.convert(synth_gst, out, beam=entries, position="0 0 -50 cm")
    z = uproot.open(out)["tree"]["nu_vertexZ"].array(library="np")
    assert np.allclose(z, 3.0)


def test_convert_writes_event_weight(synth_gst, tmp_path):
    import uproot
    out = str(tmp_path / "o.root")
    genie_convert.convert(synth_gst, out)
    t = uproot.open(out)["tree"]
    assert "eventWeight" in [k.split(";")[0] for k in t.keys()]
    w_out = t["eventWeight"].array(library="np")
    w_gst = uproot.open(synth_gst)["gst"]["wght"].array(library="np")
    assert np.allclose(w_out, w_gst)
    assert w_out.min() != w_out.max()        # the fixture varies it


def test_convert_event_weight_defaults_to_one(tmp_path):
    """A gst without a wght column still gets a usable weight."""
    import uproot
    from conftest import write_synthetic_gst
    src = write_synthetic_gst(tmp_path / "g.root", n_events=5, seed=3)
    with uproot.open(src) as f:
        data = {k.split(";")[0]: f["gst"][k.split(";")[0]].array()
                for k in f["gst"].keys() if k.split(";")[0] != "wght"}
    stripped = str(tmp_path / "nowght.root")
    io.write_tree(stripped, data, tree="gst")
    out = str(tmp_path / "o.root")
    genie_convert.convert(stripped, out)
    w = uproot.open(out)["tree"]["eventWeight"].array(library="np")
    assert np.allclose(w, 1.0)
