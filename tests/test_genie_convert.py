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
    # first particle of first event: kinetic = Ef*1000 - mass
    p0 = int(pdg[0][0]); e0_tot = float(Ef[0][0]) * 1000.0
    assert float(startE[0][0]) == pytest.approx(max(0.0, e0_tot - mass_mev(p0)), abs=1e-3)


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
    assert float(pz_conv[0][0]) == pytest.approx(float(pz_gst[0][0]) * 1000.0, rel=1e-9)


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


def test_event_weight_is_carried_from_gst(tmp_path):
    """GENIE's per-event weight must reach the ntuple: with a flux driver or any
    reweighting knob it is not 1, and every rate computed downstream is wrong if
    it is dropped."""
    import uproot
    from tests.conftest import write_synthetic_gst

    gst = write_synthetic_gst(tmp_path / "w.gst.root", n_events=12, seed=3)
    with uproot.open(gst) as f:
        want = f["gst"]["wght"].array(library="np")
    out = tmp_path / "out.root"
    genie_convert.convert(gst, out)
    with uproot.open(out) as f:
        got = f["tree"]["eventWeight"].array(library="np")
    assert got.shape == want.shape
    np.testing.assert_allclose(got, want)
    assert not np.allclose(got, 1.0), "fixture should have non-trivial weights"


def test_event_weight_defaults_to_one_without_a_wght_branch(tmp_path):
    """An unweighted gst has no wght branch; that means weight 1, not 0 -- a
    zero would silently annihilate every event downstream."""
    import uproot
    from tests.conftest import write_synthetic_gst

    gst = write_synthetic_gst(tmp_path / "nw.gst.root", n_events=5, seed=4,
                              weights=False)
    out = tmp_path / "out.root"
    genie_convert.convert(gst, out)
    with uproot.open(out) as f:
        got = f["tree"]["eventWeight"].array(library="np")
    np.testing.assert_allclose(got, 1.0)


def test_fixed_ray_places_and_orients_the_events(tmp_path):
    """beam.position / beam.direction for an aggregate-flux run: gevgen's point
    mode always vertexes at (0,0,0) along +z, so the converter has to move and
    rotate the event. The interaction KINEMATICS must be untouched."""
    import uproot
    from tests.conftest import write_synthetic_gst

    gst = write_synthetic_gst(tmp_path / "r.gst.root", n_events=8, seed=11)
    plain, moved, turned = (tmp_path / f"{n}.root" for n in ("plain", "moved", "turned"))
    genie_convert.convert(gst, plain)
    genie_convert.convert(gst, moved, origin="0 0 -60 cm")
    genie_convert.convert(gst, turned, origin="10 0 -60 cm", direction="1 0 0")

    def read(f, *names):
        with uproot.open(f) as h:
            return h["tree"].arrays(list(names), library="np")

    kin = ["nu_Q2", "nu_W", "nu_x", "nu_y", "nu_q0", "primaryE"]
    a, b, c = (read(f, *(kin + ["nu_vertexX", "nu_vertexY", "nu_vertexZ",
                                "primaryStartPx", "primaryStartPy", "primaryStartPz"]))
               for f in (plain, moved, turned))

    # the vertex moves to the requested point (mm), every event
    np.testing.assert_allclose(b["nu_vertexX"], 0.0)
    np.testing.assert_allclose(b["nu_vertexZ"], -600.0)
    np.testing.assert_allclose(c["nu_vertexX"], 100.0)
    np.testing.assert_allclose(c["nu_vertexZ"], -600.0)
    # ... and the untouched run keeps gst's own vertex
    assert not np.allclose(a["nu_vertexZ"], -600.0)

    # direction: the probe momentum turns onto +x, magnitude preserved
    np.testing.assert_allclose(c["primaryStartPy"], 0.0, atol=1e-9)
    np.testing.assert_allclose(c["primaryStartPz"], 0.0, atol=1e-6)
    np.testing.assert_allclose(c["primaryStartPx"], b["primaryStartPz"], rtol=1e-9)
    # a +z request is the identity -- placement only
    np.testing.assert_allclose(b["primaryStartPz"], a["primaryStartPz"], rtol=1e-9)

    # kinematics are invariant under placement AND rotation
    for k in kin:
        np.testing.assert_allclose(b[k], a[k], rtol=1e-9)
        np.testing.assert_allclose(c[k], a[k], rtol=1e-9)
