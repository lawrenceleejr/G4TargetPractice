"""gdmltp validate: schema + physics sanity checks on any backend's output.

Corruption tests copy a good synthetic file and break exactly one thing, so
each check is exercised both ways (PASS on the honest file, FAIL on the broken
one) and a regression can't hide behind another check tripping first.
"""
import numpy as np
import uproot

from gdmltp import validate as val
from conftest import write_synthetic_gst


def _rewrite(src, dst, drop=(), **overrides):
    """Copy a tree, dropping and/or overriding branches (corruption helper)."""
    with uproot.open(str(src)) as f:
        t = f["tree"]
        data = {k.split(";")[0]: t[k].array() for k in t.keys()}
    for k in drop:
        data.pop(k, None)
    data.update(overrides)
    with uproot.recreate(str(dst)) as f:
        f["tree"] = data
    return str(dst)


def _scalars(path, *names):
    with uproot.open(str(path)) as f:
        return [f["tree"][n].array(library="np") for n in names]


# --- honest files pass -------------------------------------------------- #

def test_pass_on_shower_file(synth_root):
    report, code = val.validate(synth_root)
    assert code == 0, report
    assert "result: PASS" in report
    assert "no nu_* block" in report


def test_pass_on_nu_file(synth_nu):
    report, code = val.validate(synth_nu)
    assert code == 0, report
    assert "full nu_* block" in report


def test_pass_on_converted_genie(synth_gst, tmp_path):
    from gdmltp.backends import genie_convert
    out = tmp_path / "genie.root"
    genie_convert.convert(synth_gst, str(out))
    # strict: converted generator output must be warning-free, closures included
    report, code = val.validate(str(out), strict=True)
    assert code == 0, report
    # vertex-level neutrino files exercise every nu check incl. q0/flavor/closure
    assert "q0 == primaryE - outLeptonE" in report
    assert "y ~= q0/Enu" in report
    assert "Q2 ~= 2*M*q0*x" in report


def test_pass_on_converted_achilles(synth_nuhepmc, tmp_path):
    from gdmltp.backends import achilles_convert
    out = tmp_path / "ach.root"
    achilles_convert.convert(synth_nuhepmc, str(out))
    report, code = val.validate(str(out), strict=True)
    assert code == 0, report


def test_event_cap_is_reported(synth_root):
    report, code = val.validate(synth_root, max_events=5)
    assert code == 0
    assert "validating first 5" in report


def test_empty_schema_fails_without_crashing(empty_root):
    report, code = val.validate(empty_root)
    assert code == 1
    assert "missing required branch" in report
    assert "events: 0" in report


# --- schema corruption -------------------------------------------------- #

def test_fail_on_missing_branch(synth_root, tmp_path):
    p = _rewrite(synth_root, tmp_path / "m.root", drop=["totalEdep"])
    report, code = val.validate(p)
    assert code == 1
    assert "missing required branch" in report and "totalEdep" in report


def test_fail_on_partial_nu_block(synth_nu, tmp_path):
    p = _rewrite(synth_nu, tmp_path / "p.root", drop=["nu_W"])
    report, code = val.validate(p)
    assert code == 1
    assert "partial nu_* block" in report


def test_fail_on_count_mismatch(synth_root, tmp_path):
    (nt,) = _scalars(synth_root, "nTracks")
    p = _rewrite(synth_root, tmp_path / "c.root",
                 nTracks=(np.asarray(nt) + 1).astype(np.int32))
    report, code = val.validate(p)
    assert code == 1
    assert "nTracks mismatch" in report


# --- physics corruption ------------------------------------------------- #

def test_edep_over_beam_warns_and_strict_fails(synth_root, tmp_path):
    (pe,) = _scalars(synth_root, "primaryE")
    p = _rewrite(synth_root, tmp_path / "w.root",
                 totalEdep=np.asarray(pe, float) * 1.10)
    report, code = val.validate(p)
    assert code == 0                      # a warning alone is not a failure
    assert "WARN" in report and "totalEdep > primaryE" in report
    report, code = val.validate(p, strict=True)
    assert code == 1
    assert "result: WARN" in report


def test_fail_on_negative_step_edep(synth_root, tmp_path):
    import awkward as ak
    with uproot.open(synth_root) as f:
        lst = ak.to_list(f["tree"]["step_edep"].array())
    lst[0] = [-abs(v) for v in lst[0]]
    p = _rewrite(synth_root, tmp_path / "neg.root", step_edep=ak.Array(lst))
    report, code = val.validate(p)
    assert code == 1
    assert "negative values of step energy deposit" in report


def test_fail_on_cc_nc_overlap(synth_nu, tmp_path):
    (cc,) = _scalars(synth_nu, "nu_isCC")
    p = _rewrite(synth_nu, tmp_path / "o.root",
                 nu_isNC=np.ones(len(cc), bool))
    report, code = val.validate(p)
    assert code == 1
    assert "flagged both CC and NC" in report


def test_fail_on_bad_inelasticity(synth_nu, tmp_path):
    (y,) = _scalars(synth_nu, "nu_y")
    y = np.asarray(y, float)
    y[0] = 1.5
    p = _rewrite(synth_nu, tmp_path / "y.root", nu_y=y)
    report, code = val.validate(p)
    assert code == 1
    assert "y outside [0,1]" in report


def test_fail_on_very_negative_q2(synth_nu, tmp_path):
    (q2,) = _scalars(synth_nu, "nu_Q2")
    q2 = np.asarray(q2, float)
    q2[0] = -5000.0
    p = _rewrite(synth_nu, tmp_path / "q2.root", nu_Q2=q2)
    report, code = val.validate(p)
    assert code == 1
    assert "negative Q2" in report


def test_nu_primary_q0_and_flavor_checks(synth_nu, tmp_path):
    """With a neutrino primary the q0/lepton-flavor cross-checks engage:
    consistent file passes, wrong flavor or broken q0 fails."""
    pe, el, cc, lep = _scalars(synth_nu, "primaryE", "nu_outLeptonE",
                               "nu_isCC", "nu_outLeptonPDG")
    n = len(pe)
    q0 = np.asarray(pe, float) - np.asarray(el, float)
    good = _rewrite(synth_nu, tmp_path / "good.root",
                    primaryPDG=np.full(n, 14, np.int32), nu_q0=q0)
    report, code = val.validate(good)
    assert code == 0, report

    bad_lep = np.where(np.asarray(cc, bool), -13,
                       np.asarray(lep)).astype(np.int32)
    p = _rewrite(good, tmp_path / "badlep.root", nu_outLeptonPDG=bad_lep)
    report, code = val.validate(p)
    assert code == 1
    assert "wrong CC lepton flavor" in report

    p = _rewrite(good, tmp_path / "badq0.root", nu_q0=q0 + 500.0)
    report, code = val.validate(p)
    assert code == 1
    assert "q0 inconsistent" in report


def test_q2_unit_bug_trips_x_closure(synth_gst, tmp_path):
    """nu_Q2 accidentally left in GeV^2 (off by 1e6): the Bjorken-x closure
    must warn -- this is exactly the class of converter bug it exists for."""
    from gdmltp.backends import genie_convert
    out = tmp_path / "genie.root"
    genie_convert.convert(synth_gst, str(out))
    (q2,) = _scalars(out, "nu_Q2")
    p = _rewrite(out, tmp_path / "gev2.root", nu_Q2=np.asarray(q2, float) * 1e-6)
    report, code = val.validate(p)
    assert code == 0                       # WARN-level: suspicious, not impossible
    assert "check Q2/x units" in report
    _, code = val.validate(p, strict=True)
    assert code == 1


def test_y_unit_bug_trips_y_closure(synth_gst, tmp_path):
    from gdmltp.backends import genie_convert
    out = tmp_path / "genie.root"
    genie_convert.convert(synth_gst, str(out))
    (y,) = _scalars(out, "nu_y")
    p = _rewrite(out, tmp_path / "milli.root", nu_y=np.asarray(y, float) * 1e-3)
    report, code = val.validate(p)
    assert "check y/q0 units" in report
    _, code = val.validate(p, strict=True)
    assert code == 1


def test_non_neutrino_primary_skips_flavor_check(synth_nu):
    """synth_nu has primaryPDG=11 with an (independently random) nu block:
    the q0/flavor checks must be gated on a neutrino primary, not trip."""
    report, code = val.validate(synth_nu)
    assert code == 0, report


# --- CLI wiring ---------------------------------------------------------- #

def test_cli_validate_pass(synth_root, capsys):
    from gdmltp import cli
    assert cli.main(["validate", synth_root]) == 0
    assert "result: PASS" in capsys.readouterr().out


def test_cli_validate_fail_exit_code(synth_root, tmp_path, capsys):
    from gdmltp import cli
    p = _rewrite(synth_root, tmp_path / "m.root", drop=["totalEdep"])
    assert cli.main(["validate", p]) == 1
    assert "result: FAIL" in capsys.readouterr().out


def test_cli_validate_missing_file(tmp_path, capsys):
    from gdmltp import cli
    assert cli.main(["validate", str(tmp_path / "nope.root")]) == 1
    assert "no such file" in capsys.readouterr().err


def test_cli_validate_strict_flag(synth_root, tmp_path, capsys):
    from gdmltp import cli
    (pe,) = _scalars(synth_root, "primaryE")
    p = _rewrite(synth_root, tmp_path / "w.root",
                 totalEdep=np.asarray(pe, float) * 1.10)
    assert cli.main(["validate", p]) == 0
    capsys.readouterr()
    assert cli.main(["validate", p, "--strict"]) == 1


def test_two_generator_outputs_both_validate(tmp_path):
    """The cross-generator promise: gst-converted and (rotated-beam) files from
    different seeds all pass the same validator."""
    from gdmltp.backends import genie_convert
    for seed in (21, 22):
        g = write_synthetic_gst(tmp_path / f"{seed}.gst.root", seed=seed)
        out = tmp_path / f"{seed}.root"
        genie_convert.convert(g, str(out))
        report, code = val.validate(str(out))
        assert code == 0, report
