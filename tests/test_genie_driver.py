"""The in-container GENIE driver (genie/run_genie.py) builds the right gevgen/
gntpc commands. subprocess and the converter are mocked, so no GENIE needed."""
import importlib.util
import json

import pytest


def _load_driver(repo_root):
    path = repo_root / "genie" / "run_genie.py"
    spec = importlib.util.spec_from_file_location("run_genie", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_job(tmp_path, **over):
    job = {
        "generator": "genie", "gdml": "liquid_argon_1m3.gdml",
        "probe": 14, "target": 1000180400,
        "flux": {"mode": "mono", "value": "2 GeV", "min": None, "max": None, "bins": []},
        "position": "0 0 -50 cm", "direction": "0 0 1",
        "events": 100, "output": "output.root",
        "tune": "G18_10a_00_000", "cross_sections": "auto",
        "event_generator_list": "Default", "length_units": "cm", "seed": 42,
    }
    job.update(over)
    p = tmp_path / "genie_job.json"
    p.write_text(json.dumps(job))
    return p


def test_driver_builds_gevgen_and_converts(repo_root, tmp_path, monkeypatch):
    mod = _load_driver(repo_root)
    monkeypatch.setenv("GENIE_XSEC_FILE", "/opt/splines.xml")   # skip on-demand gmkspl
    calls = []
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})())

    converted = {}
    import gdmltp.backends.genie_convert as gc
    monkeypatch.setattr(gc, "convert",
                        lambda gst, out, **kw: converted.update(gst=gst, out=out, kw=kw))

    job = _write_job(tmp_path)
    assert mod.run(str(job)) == 0

    gevgen = calls[0]
    assert gevgen[0] == "gevgen"
    assert "-p" in gevgen and gevgen[gevgen.index("-p") + 1] == "14"
    assert "-t" in gevgen and gevgen[gevgen.index("-t") + 1] == "1000180400"
    assert "-n" in gevgen and gevgen[gevgen.index("-n") + 1] == "100"
    assert "--tune" in gevgen and gevgen[gevgen.index("--tune") + 1] == "G18_10a_00_000"
    assert "-e" in gevgen and gevgen[gevgen.index("-e") + 1] == "2"     # 2 GeV mono
    assert "--seed" in gevgen and gevgen[gevgen.index("--seed") + 1] == "42"

    gntpc = calls[1]
    assert gntpc[0] == "gntpc" and "gst" in gntpc

    # conversion invoked with the geometry's length units
    assert converted["kw"].get("vtx_units") == "cm"
    assert converted["out"].endswith("output.root")


def test_driver_exp_flux(repo_root, tmp_path, monkeypatch):
    mod = _load_driver(repo_root)
    monkeypatch.setenv("GENIE_XSEC_FILE", "/opt/splines.xml")
    calls = []
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})())
    import gdmltp.backends.genie_convert as gc
    monkeypatch.setattr(gc, "convert", lambda *a, **k: None)

    job = _write_job(tmp_path, flux={"mode": "exp", "value": "2 GeV",
                                     "min": "200 MeV", "max": "20 GeV", "bins": []})
    mod.run(str(job))
    gevgen = calls[0]
    assert gevgen[gevgen.index("-e") + 1] == "0.2,20"
    assert gevgen[gevgen.index("-f") + 1] == "exp(-x/2)"


def test_driver_generates_splines_on_demand(repo_root, tmp_path, monkeypatch):
    """With no explicit splines and no $GENIE_XSEC_FILE, the driver runs gmkspl
    once (nu + antinu on the target), caches the XML in the run dir, and points
    gevgen at it -- so a fresh image needs zero manual setup."""
    mod = _load_driver(repo_root)
    monkeypatch.delenv("GENIE_XSEC_FILE", raising=False)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "gmkspl":                       # gmkspl writes its output
            (tmp_path / cmd[cmd.index("-o") + 1].split("/")[-1]).write_text("<xml/>")
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    import gdmltp.backends.genie_convert as gc
    monkeypatch.setattr(gc, "convert", lambda *a, **k: None)

    assert mod.run(str(_write_job(tmp_path))) == 0
    gmkspl = calls[0]
    assert gmkspl[0] == "gmkspl"
    assert gmkspl[gmkspl.index("-p") + 1] == "14,-14"
    assert gmkspl[gmkspl.index("-t") + 1] == "1000180400"
    assert "--tune" in gmkspl
    gevgen = calls[1]
    assert gevgen[0] == "gevgen"
    xsec = gevgen[gevgen.index("--cross-sections") + 1]
    assert "gxspl_14_1000180400" in xsec

    # second run: spline file exists -> no second gmkspl
    calls.clear()
    assert mod.run(str(_write_job(tmp_path))) == 0
    assert calls[0][0] == "gevgen"
