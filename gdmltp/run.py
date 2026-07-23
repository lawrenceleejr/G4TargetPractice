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


def _exec_stage(argv, image, env, outdir, local, dry_run, label=""):
    """Run one container (or local-engine) stage; returns True if executed."""
    if local:
        exe = shutil.which("g4sim") or "/app/build/g4sim"
        cmd = [exe, *argv]
        run_env = dict(os.environ)
        run_env.update(env)
        if dry_run:
            print(f"[gdmltp] (dry-run{label})", " ".join(cmd), "in", str(outdir))
            return False
        subprocess.run(cmd, cwd=outdir, env=run_env, check=True)
    else:
        cmd = ["docker", "run", "--rm", "--init", "-v", f"{outdir}:/run", "-w", "/run"]
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [image, *argv]
        if dry_run:
            print(f"[gdmltp] (dry-run{label})", " ".join(cmd))
            return False
        subprocess.run(cmd, check=True)
    return True


def _wants_transport(cfg):
    return cfg.generator in ("genie", "achilles") and \
        bool(getattr(cfg, cfg.generator).get("transport"))


def _transport_stage(cfg, outdir, local, dry_run):
    """Stage 2 of the generator->Geant4 hand-off: replay the vertex-level
    events through g4sim (fills step_*/totalEdep/trk_end*), then graft the
    generator's nu_* block + primary identity back on."""
    from . import handoff
    from .backends.geant4 import Geant4Backend

    g4 = Geant4Backend()
    if dry_run:
        print(f"[gdmltp] (dry-run:transport) would replay the generator events "
              f"through {g4.image_for(cfg)} via /gun/eventFile and merge the "
              f"nu_* block into {cfg.run.output}")
        return

    produced = outdir / cfg.run.output
    vertex = outdir / handoff.VERTEX_FILE
    produced.replace(vertex)

    n = handoff.write_event_file(vertex, outdir / handoff.EVENT_FILE)
    macro = handoff.build_transport_macro(
        Path(cfg.gdml).name, n, seed=cfg.run.seed, field=cfg.geant4.get("field"))
    (outdir / handoff.TRANSPORT_MACRO).write_text(macro)
    print(f"[gdmltp] transport: replaying {n} generator event(s) through Geant4 ...")

    env = {"CELER_DISABLE": "1"} if cfg.geant4.get("field") else {}
    _exec_stage([handoff.TRANSPORT_MACRO], g4.image_for(cfg), env,
                outdir, local, dry_run=False, label=":transport")

    transported = outdir / "output.root"
    handoff.merge_nu_block(transported, vertex, outdir / cfg.run.output)
    if (outdir / cfg.run.output) != transported and transported.exists():
        transported.unlink()
    print(f"[gdmltp] transport done -> {outdir / cfg.run.output} "
          f"(generator interaction record + Geant4 transport)")


def run_config(cfg, image=None, outdir=".", local=False, dry_run=False):
    """Execute (or dry-run) a run described by a validated RunConfig.

    With genie.transport / achilles.transport set, this is a two-stage run:
    the generator produces the vertex-level events, then g4sim transports the
    final-state particles through the GDML detector and the outputs merge.
    """
    cfg.validate()
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    _stage_gdml(cfg, outdir)

    backend = backends.get(cfg.generator)
    prep = backend.prepare(cfg, outdir, image=image)

    if not cfg.mac and (outdir / "gdmltp_run.mac").exists() and cfg.generator == "geant4":
        print(f"[gdmltp] generated {outdir / 'gdmltp_run.mac'}:\n"
              f"{(outdir / 'gdmltp_run.mac').read_text()}")

    executed = _exec_stage(prep.argv, prep.image, prep.env, outdir, local, dry_run)

    if _wants_transport(cfg):
        _transport_stage(cfg, outdir, local, dry_run)
        return 0

    if executed:
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
