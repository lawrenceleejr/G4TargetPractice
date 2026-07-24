"""Run a simulation with minimal friction.

This module is the backend-agnostic orchestrator: it takes a validated RunConfig,
asks the selected backend to render its inputs into the run directory, then wraps
`docker run` (or a local engine) around them. Each backend produces the same
`output.root` schema, so everything downstream (analyze/display/compare/info)
is generator-independent.

`generate_macro` and `run` keep their historical signatures for existing callers
and tests; both now delegate to the RunConfig/backend machinery.
"""
import collections
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import config, backends
from .backends.geant4 import DEFAULT_IMAGE, build_macro

# Geant4 prints "--> Event N" (or "Event N starts") per printProgress modulo;
# we parse N to drive a host-side progress bar over the requested event count.
_EVENT_RE = re.compile(r"[Ee]vent[:\s]+(\d+)")

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


def _local_cmd(argv):
    """The command to run an engine stage WITHOUT spawning a container -- either
    on a dev host (g4sim on PATH) or, crucially, INSIDE a generator image so a
    single `docker run <image> run --config x.yaml --local` renders and runs
    end-to-end with no nested docker. Inside an image we defer to
    /app/entrypoint.sh, which dispatches the rendered input to the right engine
    (*.mac -> g4sim, *.json -> the generator driver) exactly as a bare
    `docker run` would."""
    entry = "/app/entrypoint.sh"
    if os.path.exists(entry):
        return [entry, *argv]
    exe = shutil.which("g4sim") or "/app/build/g4sim"   # host dev fallback (geant4)
    return [exe, *argv]


def _exec_stage(argv, image, env, outdir, local, dry_run, label="", events=None):
    """Run one container (or local-engine) stage; returns True if executed.

    Engine output is streamed live (with a tqdm progress bar over `events` when
    the engine reports per-event progress), so a run never sits silent; failures
    are turned into clear messages instead of raw tracebacks.
    """
    if local:
        cmd = _local_cmd(argv)
        run_env = dict(os.environ)
        run_env.update(env)
        if dry_run:
            print(f"[gdmltp] (dry-run{label})", " ".join(cmd), "in", str(outdir))
            return False
        print(f"[gdmltp] running the in-container engine{label} in {outdir}; "
              f"output follows:", flush=True)
        _stream_run(cmd, image=cmd[0], cwd=outdir, env=run_env,
                    events=events, is_docker=False)
    else:
        cmd = ["docker", "run", "--rm", "--init", "-v", f"{outdir}:/run", "-w", "/run"]
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [image, *argv]
        if dry_run:
            print(f"[gdmltp] (dry-run{label})", " ".join(cmd))
            return False
        print(f"[gdmltp] launching container{label}:\n    {image}\n"
              f"[gdmltp] (first run pulls the image -- this can take a few minutes "
              f"with no output); engine output follows:", flush=True)
        _stream_run(cmd, image=image, cwd=None, env=None,
                    events=events, is_docker=True)
    return True


def _open_progress(events, label):
    """A tqdm bar over `events`, or None (no tqdm / no count / non-positive)."""
    if not events or events <= 0:
        return None
    try:
        from tqdm import tqdm
    except ImportError:
        return None
    return tqdm(total=int(events), desc=f"[gdmltp] transport{label}".strip(),
                unit="evt", dynamic_ncols=True, mininterval=0.5)


def _stream_run(cmd, image, cwd, env, events=None, is_docker=True, label=""):
    """Popen a stage, stream its output live, drive a progress bar off per-event
    lines, keep a tail for diagnostics, and raise a clear error on failure."""
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, bufsize=1,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        if is_docker:
            raise RuntimeError(
                "docker was not found on PATH. Install Docker, or use --local to "
                "run a g4sim already on PATH.")
        raise RuntimeError("g4sim was not found on PATH (needed for --local).")

    tail = collections.deque(maxlen=40)
    bar = _open_progress(events, label)
    t0 = time.perf_counter()
    emit = bar.write if bar is not None else (lambda s: print(s, flush=True))
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            tail.append(line)
            m = bar is not None and _EVENT_RE.search(line)
            if m:
                n = int(m.group(1)) + 1
                if n > bar.n:
                    bar.update(min(n, bar.total) - bar.n)
            else:
                emit(line)
    finally:
        proc.wait()
        if bar is not None:
            if proc.returncode == 0:
                bar.update(bar.total - bar.n)
            bar.close()

    if proc.returncode == 0:
        print(f"[gdmltp] stage finished in {time.perf_counter() - t0:.1f}s", flush=True)
        return

    joined = "\n".join(tail)
    low = joined.lower()
    if is_docker and (proc.returncode == 125 or "manifest unknown" in low
                      or "pull access denied" in low or "unauthorized" in low
                      or "no such image" in low):
        raise RuntimeError(
            f"could not obtain the container image:\n    {image}\n"
            f"This usually means the image tag is not published or the package is "
            f"private. Try one of:\n"
            f"  - authenticate:  docker login ghcr.io\n"
            f"  - pick a tag that exists (branch builds are tagged by branch name), "
            f"e.g.  --image <repo>:<tag>\n"
            f"  - make the GHCR package public, or merge to the default branch so "
            f"the ':main'/':latest' tag publishes")
    if "command not found" in low:
        # a macro command the CLI emitted is absent from the engine -> the image
        # is older than this gdmltp checkout (a new /gun or /gdmltp command was
        # added after the image was built)
        cmd_line = next((l for l in tail if "COMMAND NOT FOUND" in l), "")
        raise RuntimeError(
            f"the engine rejected a command this gdmltp emitted:\n    {cmd_line.strip()}\n"
            f"The container image is OLDER than your gdmltp checkout -- it was "
            f"built before that command existed. Use an image built from your "
            f"current commit:\n"
            f"  - pull the branch tag (updated on every push), not a pinned "
            f"'-<sha>' tag:  --image {_repo_of(image)}:<branch>\n"
            f"  - or build it locally:  docker build -f docker/geant4.Dockerfile "
            f"-t g4sim-local . && gdmltp run ... --image g4sim-local")
    tail_txt = "\n".join(list(tail)[-15:]) or "(no output captured)"
    raise RuntimeError(
        f"the '{image}' stage exited with status {proc.returncode}:\n{tail_txt}")


def _repo_of(image):
    return image.rsplit(":", 1)[0] if ":" in image else image


def _wants_transport(cfg):
    # decay is NOT here: it is a single-stage Geant4 run (Geant4 both decays
    # and transports); external files opt in like the vertex-level generators.
    return cfg.generator in ("genie", "achilles", "external") and \
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
              f"through {g4.image_for(cfg)} via /gun/hepmcFile and merge the "
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
                outdir, local, dry_run=False, label=":transport", events=n)

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

    # Inside a gdmltp engine image, run the engine here rather than spawning a
    # nested container -- so a single `docker run <image> run --config x.yaml`
    # renders inputs AND runs end-to-end. On a host (no /app/entrypoint.sh) this
    # is a no-op and runs default to Docker as before.
    if not local and os.path.exists("/app/entrypoint.sh"):
        local = True

    _stage_gdml(cfg, outdir)

    backend = backends.get(cfg.generator)
    prep = backend.prepare(cfg, outdir, image=image)

    if not cfg.mac and (outdir / "gdmltp_run.mac").exists() and cfg.generator == "geant4":
        print(f"[gdmltp] generated {outdir / 'gdmltp_run.mac'}:\n"
              f"{(outdir / 'gdmltp_run.mac').read_text()}")

    if backend.host:
        # host backends (external) produce their output in prepare(); there
        # is no container stage to run
        executed = True
    else:
        events = int(cfg.run.events) if cfg.generator in ("geant4", "decay") else None
        executed = _exec_stage(prep.argv, prep.image, prep.env, outdir, local,
                               dry_run, events=events)

    if executed and prep.post is not None and not dry_run:
        prep.post()

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
