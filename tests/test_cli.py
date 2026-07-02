import pytest

from g4tp import cli


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "g4tp 0." in capsys.readouterr().out


def test_no_args_prints_help_and_signals_misuse(capsys):
    assert cli.main([]) == 2
    assert "usage: g4tp" in capsys.readouterr().out


def test_missing_file_is_friendly(capsys):
    assert cli.main(["analyze", "/definitely/not/here.root"]) == 1
    err = capsys.readouterr().err
    assert "no such file" in err
    assert "Traceback" not in err


def test_debug_reraises():
    with pytest.raises(FileNotFoundError):
        cli.main(["--debug", "analyze", "/definitely/not/here.root"])


def test_debug_works_after_subcommand_too():
    """The error hint says 'add --debug' -- it must work in either position."""
    with pytest.raises(FileNotFoundError):
        cli.main(["analyze", "/definitely/not/here.root", "--debug"])


def test_display_missing_root_falls_back_to_geometry(repo_root, tmp_path, capsys):
    """Documented preview workflow: display before the sim has run."""
    gdml = str(repo_root / "gdml" / "bpe_slab.gdml")
    assert cli.main(["display", "not_yet_produced.root", "--gdml", gdml,
                     "--no-png", "-o", str(tmp_path / "pre")]) == 0
    assert "rendering geometry only" in capsys.readouterr().err
    assert (tmp_path / "pre" / "event.html").exists()


def test_display_missing_root_without_gdml_errors(capsys):
    assert cli.main(["display", "not_here.root"]) == 1
    assert "no such file" in capsys.readouterr().err


def test_info_root(synth_root, capsys):
    assert cli.main(["info", synth_root]) == 0
    out = capsys.readouterr().out
    assert "30 event(s)" in out
    assert "nu_* block: absent" in out


def test_info_gdml(repo_root, capsys):
    assert cli.main(["info", str(repo_root / "gdml" / "bpe_slab.gdml")]) == 0
    assert "placed primitive(s)" in capsys.readouterr().out


def test_analyze_cli(synth_root, tmp_path):
    assert cli.main(["analyze", synth_root, "-o", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "summary.txt").exists()
    assert (tmp_path / "out" / "depth_dose.png").exists()


def test_compare_cli(synth_pair, tmp_path):
    a, b = synth_pair
    assert cli.main(["compare", a, b, "--labels", "DU,W",
                     "-o", str(tmp_path / "cmp")]) == 0
    text = (tmp_path / "cmp" / "summary.txt").read_text()
    assert "[DU]" in text and "leakage" in text.lower()
    assert (tmp_path / "cmp" / "leakage.png").exists()


def test_display_cli(synth_root, repo_root, tmp_path):
    assert cli.main(["display", synth_root,
                     "--gdml", str(repo_root / "gdml" / "bpe_slab.gdml"),
                     "-o", str(tmp_path / "disp")]) == 0
    assert (tmp_path / "disp" / "event.html").exists()
    assert (tmp_path / "disp" / "event_xy.png").exists()
    assert (tmp_path / "disp" / "event_iso.png").exists()


def test_display_geometry_only(repo_root, tmp_path):
    assert cli.main(["display", "--gdml", str(repo_root / "gdml" / "bpe_slab.gdml"),
                     "--no-png", "-o", str(tmp_path / "geo")]) == 0
    assert (tmp_path / "geo" / "event.html").exists()


def test_run_dry_run_generates_macro(repo_root, tmp_path, capsys):
    gdml = str(repo_root / "gdml" / "bpe_slab.gdml")
    assert cli.main(["run", "--gdml", gdml, "--particle", "neutron",
                     "--energy", "1 GeV", "-n", "7",
                     "-o", str(tmp_path), "--dry-run"]) == 0
    mac = (tmp_path / "g4tp_run.mac").read_text()
    assert "/gun/particle neutron" in mac
    assert "/gun/energy 1 GeV" in mac
    assert "/run/beamOn 7" in mac
    assert "docker run" in capsys.readouterr().out


def test_unknown_command_exits_2():
    with pytest.raises(SystemExit) as exc:
        cli.main(["frobnicate"])
    assert exc.value.code == 2
