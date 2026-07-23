"""Run a simulation with minimal friction.

This module is the backend-agnostic orchestrator: it takes a validated RunConfig,
asks the selected backend to render its inputs into the run directory, then wraps
`docker run` (or a local engine) around them. Each backend produces the same
`output.root` schema, so everything downstream (analyze/display/compare/info)
is generator-independent.

`generate_macro` and `run` keep their historical signatures for existing callers
and tests; both now delegate to the RunConfig/backend machinery.
"""
import os
import shutil
import subprocess
from pathlib import Path

from . import config, backends
from .backends.geant4 import DEFAULT_IMAGE, build_macro

__all__ = ["DEFAULT_IMAGE", "generate_macro", "run", "run_config"]


# --------------------------------------------------------------------------- #
# Back-compat helpers
# --------------------------------------------------------------------------- #
def generate_macro(gdml, particle="e-", energy="1 GeV", position="0 0 -20 cm",
                   direction="0 0 1", n=100, nmode="auto", field=None):
    """Render a Geant4 macro from the classic mono-energy flag set.

    Retained for callers/tests that build a macro directly; internally it is just
    a thin adapter over the geant4 backend's `build_macro`.
    """
    cfg = config.RunConfig(
        generator="geant4", gdml=gdml,
        beam=config.Beam(particle=particle,
                         energy=config.Energy(mode="mono", value=energy),
                         position=position, direction=direction),
        run=config.RunSettings(events=n),
        geant4={"neutrino_mode": nmode, "field": field})
    return build_macro(cfg)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def _stage_gdml(cfg, outdir):
    """Copy the geometry next to the run so the in-container path is a basename."""
    if not cfg.gdml:
        return
    gsrc = Path(cfg.gdml)
    if gsrc.exists() and gsrc.resolve().parent != outdir.resolve():
        shutil.copy(gsrc, outdir / gsrc.name)


def run_config(cfg, image=None, outdir=".", local=False, dry_run=False):
    """Execute (or dry-run) a run described by a validated RunConfig."""
    cfg.validate()
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    _stage_gdml(cfg, outdir)

    backend = backends.get(cfg.generator)
    prep = backend.prepare(cfg, outdir, image=image)

    if not cfg.mac and (outdir / "gdmltp_run.mac").exists() and cfg.generator == "geant4":
        print(f"[gdmltp] generated {outdir / 'gdmltp_run.mac'}:\n{(outdir / 'gdmltp_run.mac').read_text()}")

    if local:
        exe = shutil.which("g4sim") or "/app/build/g4sim"
        cmd = [exe, *prep.argv]
        env = dict(os.environ)
        env.update(prep.env)
        if dry_run:
            print("[gdmltp] (dry-run)", " ".join(cmd), "in", str(outdir))
            return 0
        subprocess.run(cmd, cwd=outdir, env=env, check=True)
    else:
        cmd = ["docker", "run", "--rm", "--init", "-v", f"{outdir}:/run", "-w", "/run"]
        for k, v in prep.env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [prep.image, *prep.argv]
        if dry_run:
            print("[gdmltp] (dry-run)", " ".join(cmd))
            return 0
        subprocess.run(cmd, check=True)

    _finalize_output(cfg, prep, outdir)
    return 0


def _finalize_output(cfg, prep, outdir):
    produced = outdir / prep.output
    target = outdir / cfg.run.output
    if cfg.run.output != prep.output and produced.exists():
        produced.replace(target)
    print(f"[gdmltp] done -> {target if target.exists() else produced}")


def run(mac=None, gdml=None, particle="e-", energy="1 GeV", position="0 0 -20 cm",
        direction="0 0 1", n=100, nmode="auto", field=None, image=DEFAULT_IMAGE,
        outdir=".", local=False, celer_disable=None, dry_run=False):
    """Historical flag-driven entry point (geant4). Builds a RunConfig and runs it."""
    cfg = config.RunConfig(
        generator="geant4", gdml=gdml, mac=mac,
        beam=config.Beam(particle=particle,
                         energy=config.Energy(mode="mono", value=energy),
                         position=position, direction=direction),
        run=config.RunSettings(events=n),
        geant4={"neutrino_mode": nmode, "field": field})
    return run_config(cfg, image=image, outdir=outdir, local=local, dry_run=dry_run)
