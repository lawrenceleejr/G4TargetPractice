"""Run a simulation with minimal friction: wrap `docker run` (or a local g4sim),
optionally generating the macro from flags so no .mac is needed.
"""
import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_IMAGE = "ghcr.io/lawrenceleejr/g4targetpractice:main"

MACRO_TEMPLATE = """/detector/readGDML {gdml}
/run/initialize
/analysis/neutrinoMode {nmode}
{field}/gun/particle {particle}
/gun/energyMode mono
/gun/energy {energy}
/gun/position {position}
/gun/direction {direction}
/run/printProgress {progress}
/run/beamOn {n}
"""


def generate_macro(gdml, particle="e-", energy="1 GeV", position="0 0 -20 cm",
                   direction="0 0 1", n=100, nmode="auto", field=None):
    field_line = f"/detector/setGlobalField {field}\n" if field else ""
    return MACRO_TEMPLATE.format(
        gdml=Path(gdml).name, particle=particle, energy=energy, position=position,
        direction=direction, n=n, nmode=nmode, field=field_line,
        progress=max(1, int(n) // 10) if str(n).isdigit() else 100)


def run(mac=None, gdml=None, particle="e-", energy="1 GeV", position="0 0 -20 cm",
        direction="0 0 1", n=100, nmode="auto", field=None, image=DEFAULT_IMAGE,
        outdir=".", local=False, celer_disable=None, dry_run=False):
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    # stage the gdml into the run dir if needed
    if gdml:
        gsrc = Path(gdml)
        if gsrc.resolve().parent != outdir and gsrc.exists():
            shutil.copy(gsrc, outdir / gsrc.name)

    if mac:
        macro_name = Path(mac).name
        if Path(mac).resolve().parent != outdir and Path(mac).exists():
            shutil.copy(mac, outdir / macro_name)
    else:
        if not gdml:
            raise SystemExit("Provide --mac, or --gdml (+ optional gun flags) to generate one.")
        macro_text = generate_macro(gdml, particle, energy, position, direction, n, nmode, field)
        macro_name = "g4tp_run.mac"
        (outdir / macro_name).write_text(macro_text)
        print(f"[g4tp] generated {outdir/macro_name}:\n{macro_text}")

    if celer_disable is None:
        celer_disable = field is not None

    if local:
        exe = shutil.which("g4sim") or "/app/build/g4sim"
        cmd = [exe, macro_name]
        env = dict(os.environ)
        if celer_disable:
            env["CELER_DISABLE"] = "1"
        if dry_run:
            print("[g4tp] (dry-run)", " ".join(cmd), "in", outdir)
            return
        subprocess.run(cmd, cwd=outdir, env=env, check=True)
    else:
        cmd = ["docker", "run", "--rm", "--init", "-v", f"{outdir}:/run", "-w", "/run"]
        if celer_disable:
            cmd += ["-e", "CELER_DISABLE=1"]
        cmd += [image, macro_name]
        if dry_run:
            print("[g4tp] (dry-run)", " ".join(cmd))
            return
        subprocess.run(cmd, check=True)
    print(f"[g4tp] done -> {outdir/'output.root'}")
