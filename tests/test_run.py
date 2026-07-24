"""Orchestrator (run.run_config): backend dispatch, docker command, output rename.

subprocess is mocked so these exercise the real code path without Docker/engines.
"""
import pytest

from gdmltp import run, config


def _fake_popen(lines=(), returncode=0, on_call=None):
    """A stand-in for subprocess.Popen: streams `lines`, then exits with
    `returncode`. `on_call(cmd, kw)` fires at construction (side effects)."""
    class P:
        def __init__(self, cmd, **kw):
            if on_call is not None:
                on_call(cmd, kw)
            self.stdout = iter(list(lines))
            self.returncode = returncode

        def wait(self):
            return self.returncode
    return P


def _geant4_cfg(repo_root, **geant4_block):
    return config.RunConfig(
        gdml=str(repo_root / "gdml" / "bpe_slab.gdml"),
        beam=config.Beam(particle="neutron",
                         energy=config.Energy(mode="mono", value="1 GeV")),
        run=config.RunSettings(events=3),
        geant4=geant4_block)


def test_dry_run_docker_command(repo_root, tmp_path, capsys):
    run.run_config(_geant4_cfg(repo_root), outdir=str(tmp_path), dry_run=True)
    out = capsys.readouterr().out
    assert "docker run --rm --init" in out
    assert "g4targetpractice:main" in out          # default geant4 image
    assert "gdmltp_run.mac" in out
    assert "CELER_DISABLE" not in out               # no field -> no offload disable


def test_dry_run_field_sets_celer_disable(repo_root, tmp_path, capsys):
    run.run_config(_geant4_cfg(repo_root, field="0 0 5 tesla"),
                   outdir=str(tmp_path), dry_run=True)
    assert "-e CELER_DISABLE=1" in capsys.readouterr().out


def test_dry_run_celeritas_image(repo_root, tmp_path, capsys):
    run.run_config(_geant4_cfg(repo_root, celeritas=True),
                   outdir=str(tmp_path), dry_run=True)
    assert "g4targetpractice:main-celeritas" in capsys.readouterr().out


def test_dry_run_genie_dispatch(repo_root, tmp_path, capsys):
    cfg = config.RunConfig(
        generator="genie",
        gdml=str(repo_root / "gdml" / "liquid_argon_1m3.gdml"),
        beam=config.Beam(particle="nu_mu",
                         energy=config.Energy(mode="mono", value="2 GeV")),
        run=config.RunSettings(events=5), genie={"tune": "G18_10a_00_000"})
    run.run_config(cfg, outdir=str(tmp_path), dry_run=True)
    out = capsys.readouterr().out
    assert "g4targetpractice-genie:main" in out
    assert "genie_job.json" in out
    assert (tmp_path / "genie_job.json").exists()


def test_output_rename(repo_root, tmp_path, monkeypatch):
    """The engine always writes output.root; run.output != output.root renames it."""
    outdir = tmp_path
    monkeypatch.setattr(run.subprocess, "Popen", _fake_popen(
        lines=["--> Event 0 starts.", "--> Event 1 starts."],
        on_call=lambda cmd, kw: (outdir / "output.root").write_text("fake")))
    cfg = _geant4_cfg(repo_root)
    cfg.run.output = "custom.root"
    run.run_config(cfg, outdir=str(outdir), image="img")
    assert (outdir / "custom.root").exists()
    assert not (outdir / "output.root").exists()


def test_missing_image_gives_clear_error(repo_root, tmp_path, monkeypatch):
    """docker's 'manifest unknown' (exit 125) becomes a clear, actionable
    message naming the image, not a raw traceback."""
    monkeypatch.setattr(run.subprocess, "Popen", _fake_popen(
        lines=["docker: Error response from daemon: manifest unknown"],
        returncode=125))
    cfg = _geant4_cfg(repo_root)
    with pytest.raises(RuntimeError, match="could not obtain the container image"):
        run.run_config(cfg, outdir=str(tmp_path), image="ghcr.io/x/nope:main")


def test_engine_failure_surfaces_stderr(repo_root, tmp_path, monkeypatch):
    monkeypatch.setattr(run.subprocess, "Popen", _fake_popen(
        lines=["G4 fatal: bad macro command"], returncode=1))
    with pytest.raises(RuntimeError, match="bad macro command"):
        run.run_config(_geant4_cfg(repo_root), outdir=str(tmp_path), image="img")


def test_local_uses_engine_binary(repo_root, tmp_path, monkeypatch):
    calls = {}

    def on_call(cmd, kw):
        calls["cmd"] = cmd
        calls["cwd"] = kw.get("cwd")
        (tmp_path / "output.root").write_text("fake")

    monkeypatch.setattr(run.subprocess, "Popen",
                        _fake_popen(lines=["--> Event 0 starts."], on_call=on_call))
    run.run_config(_geant4_cfg(repo_root), outdir=str(tmp_path), local=True)
    assert "docker" not in calls["cmd"][0]
    assert calls["cmd"][-1] == "gdmltp_run.mac"


def test_run_compat_wrapper(repo_root, tmp_path, capsys):
    """The historical run.run(...) signature still works (geant4 dry-run)."""
    run.run(gdml=str(repo_root / "gdml" / "bpe_slab.gdml"), particle="mu-",
            energy="3 GeV", n=4, outdir=str(tmp_path), dry_run=True)
    mac = (tmp_path / "gdmltp_run.mac").read_text()
    assert "/gun/particle mu-" in mac and "/run/beamOn 4" in mac