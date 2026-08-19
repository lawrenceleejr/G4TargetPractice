import pytest

from gdmltp import cli


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "gdmltp 0." in capsys.readouterr().out


def test_no_args_prints_help_and_signals_misuse(capsys):
    assert cli.main([]) == 2
    assert "usage: gdmltp" in capsys.readouterr().out


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


def test_display_auto_picks_richest_event(tmp_path, capsys):
    """No --event: show the event with the most content, not (empty) event 0."""
    import uproot, awkward as ak, numpy as np
    p = tmp_path / "vary.root"
    # 4 events; event 2 has by far the most tracks (the "interesting" one)
    pdg = ak.Array([[13], [13], [13, 211, 2212, 111, 22], [13]])
    zero = ak.Array([[0.0]] * 3 + [[0.0]])
    with uproot.recreate(p) as f:
        f["tree"] = {
            "eventID": np.arange(4, dtype=np.int32),
            "nSteps": np.zeros(4, np.int32),
            "nTracks": np.array([1, 1, 5, 1], np.int32),
            "trk_id": ak.Array([[1], [1], [1, 2, 3, 4, 5], [1]]),
            "trk_pdg": pdg,
            "trk_startX": ak.Array([[0.0], [0.0], [0.0, 1, 2, 3, 4], [0.0]]),
            "trk_startY": ak.Array([[0.0], [0.0], [0.0, 0, 0, 0, 0], [0.0]]),
            "trk_startZ": ak.Array([[0.0], [0.0], [0.0, 0, 0, 0, 0], [0.0]]),
            "trk_endX": ak.Array([[0.0], [0.0], [0.0, 1, 2, 3, 4], [0.0]]),
            "trk_endY": ak.Array([[0.0], [0.0], [0.0, 0, 0, 0, 0], [0.0]]),
            "trk_endZ": ak.Array([[1.0], [1.0], [1.0, 1, 1, 1, 1], [1.0]]),
            "trk_parentID": ak.Array([[0], [0], [0, 1, 1, 1, 1], [0]]),
            "trk_creatorProcess": ak.Array([["Primary"], ["Primary"],
                                            ["Primary", "x", "x", "x", "x"], ["Primary"]]),
        }
    assert cli.main(["display", str(p), "--no-png", "--no-blend",
                     "-o", str(tmp_path / "d")]) == 0
    assert "event 2 (richest)" in capsys.readouterr().out


def test_display_all_events_overlay(synth_root, tmp_path, capsys):
    """--all overlays every event into one scene (opt-in, not the default)."""
    assert cli.main(["display", synth_root, "--all", "--no-blend", "--no-png",
                     "-o", str(tmp_path / "all")]) == 0
    out = capsys.readouterr().out
    assert "overlaying all 30 events" in out
    assert "combined 30 events" in out


def test_display_blend_default_is_graceful(synth_root, tmp_path, monkeypatch, capsys):
    """Blend is on by default; if the Blender step fails it must not sink the
    PNG/HTML that already succeeded."""
    import gdmltp.render_blender as rb
    monkeypatch.setattr(rb, "render_blend",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no blender")))
    assert cli.main(["display", synth_root, "--no-html",
                     "-o", str(tmp_path / "b")]) == 0
    assert (tmp_path / "b" / "event_iso.png").exists()
    assert "Blender export skipped" in capsys.readouterr().err


def test_run_dry_run_generates_macro(repo_root, tmp_path, capsys):
    gdml = str(repo_root / "gdml" / "bpe_slab.gdml")
    assert cli.main(["run", "--gdml", gdml, "--particle", "neutron",
                     "--energy", "1 GeV", "-n", "7",
                     "-o", str(tmp_path), "--dry-run"]) == 0
    mac = (tmp_path / "gdmltp_run.mac").read_text()
    assert "/gun/particle neutron" in mac
    assert "/gun/energy 1 GeV" in mac
    assert "/run/beamOn 7" in mac
    assert "docker run" in capsys.readouterr().out


def test_unknown_command_exits_2():
    with pytest.raises(SystemExit) as exc:
        cli.main(["frobnicate"])
    assert exc.value.code == 2


def test_run_config_yaml_dry_run(repo_root, tmp_path, capsys):
    """The YAML frontend generates the same macro the flags would."""
    cfg = tmp_path / "run.yaml"
    cfg.write_text(
        "generator: geant4\n"
        f"geometry: {{gdml: {repo_root / 'gdml' / 'bpe_slab.gdml'}}}\n"
        "beam:\n  particle: neutron\n"
        "  energy: {mode: exp, value: '2 GeV', min: '200 MeV', max: '20 GeV'}\n"
        "run: {events: 9, seed: 7}\n")
    assert cli.main(["run", "--config", str(cfg), "-o", str(tmp_path), "--dry-run"]) == 0
    mac = (tmp_path / "gdmltp_run.mac").read_text()
    assert "/gun/particle neutron" in mac
    assert "/gun/energyMode exp" in mac
    assert "/gun/energyMin 200 MeV" in mac
    assert "/random/setSeeds 7 8" in mac
    assert "/run/beamOn 9" in mac
    assert "docker run" in capsys.readouterr().out


def test_run_config_flag_override(repo_root, tmp_path):
    cfg = tmp_path / "run.yaml"
    cfg.write_text(
        f"geometry: {{gdml: {repo_root / 'gdml' / 'bpe_slab.gdml'}}}\n"
        "beam: {particle: proton, energy: '150 MeV'}\n")
    assert cli.main(["run", "--config", str(cfg), "--energy", "200 MeV",
                     "-o", str(tmp_path), "--dry-run"]) == 0
    mac = (tmp_path / "gdmltp_run.mac").read_text()
    assert "/gun/particle proton" in mac        # kept from YAML
    assert "/gun/energy 200 MeV" in mac         # overridden by flag


def test_run_numeric_particle_is_pdg(repo_root, tmp_path):
    gdml = str(repo_root / "gdml" / "bpe_slab.gdml")
    assert cli.main(["run", "--gdml", gdml, "--particle", "2212", "--energy", "1 GeV",
                     "-o", str(tmp_path), "--dry-run"]) == 0
    mac = (tmp_path / "gdmltp_run.mac").read_text()
    assert "/gun/particlePDG 2212" in mac
    assert "/gun/particle " not in mac


def test_run_config_bad_generator_is_friendly(repo_root, tmp_path, capsys):
    cfg = tmp_path / "run.yaml"
    cfg.write_text(f"generator: fluka\ngeometry: {{gdml: {repo_root / 'gdml' / 'bpe_slab.gdml'}}}\n")
    assert cli.main(["run", "--config", str(cfg), "-o", str(tmp_path), "--dry-run"]) == 1
    assert "unknown generator" in capsys.readouterr().err
