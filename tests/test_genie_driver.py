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
