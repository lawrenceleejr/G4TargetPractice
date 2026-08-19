"""Achilles backend: turn the common RunConfig into an Achilles job spec.

Achilles (https://github.com/AchillesGen/Achilles) is a theory-driven
lepton-nucleus event generator covering neutrino-nucleus AND electron-nucleus
scattering. It is driven by a YAML run card and emits NuHepMC (HepMC3) events.

Like the GENIE backend, the host writes a small job JSON; the Achilles
container's driver (achilles/run_achilles.py) renders the actual run card from
it, runs `achilles`, and converts the NuHepMC output to the common
`output.root` schema (achilles_convert) -- so analyze/display/compare/Blender
work on Achilles events exactly as they do on Geant4 or GENIE ones.
"""
import json
from pathlib import Path

from .base import Backend, Prepared
from ..config import ConfigError
from .genie import infer_target, _as_pdg

ACHILLES_IMAGE = "ghcr.io/lawrenceleejr/g4targetpractice-achilles:main"
JOB_FILE = "achilles_job.json"
BEAM_FILE = "beam.dat"

# Achilles projectiles: neutrinos and (anti)electrons.
_PROBE_PDG = {
    "nu_e": 12, "anti_nu_e": -12,
    "nu_mu": 14, "anti_nu_mu": -14,
    "nu_tau": 16, "anti_nu_tau": -16,
    "e-": 11, "e+": -11,
}
_ALLOWED_PDGS = {11, -11, 12, -12, 14, -14, 16, -16}

# Z -> element symbol for the nuclei the GDML target inference can produce
# (extend alongside genie._MATERIAL_* when new targets are added).
_SYMBOL = {1: "H", 2: "He", 6: "C", 8: "O", 14: "Si", 18: "Ar", 26: "Fe"}


def probe_pdg(particle) -> int:
    """Resolve the Achilles probe from a name or PDG id (leptons only)."""
    pdg = _as_pdg(particle)
    if pdg is not None:
        if pdg not in _ALLOWED_PDGS:
            raise ConfigError(
                f"the achilles backend supports neutrino or e-/e+ projectiles, "
                f"got PDG {pdg} (one of {sorted(_ALLOWED_PDGS)})")
        return pdg
    try:
        return _PROBE_PDG[particle]
    except KeyError:
        raise ConfigError(
            f"the achilles backend supports neutrino or e-/e+ projectiles, got "
            f"{particle!r} (names: {', '.join(sorted(_PROBE_PDG))}, or a PDG id)")


def isotope_name(nucleus_pdg: int) -> str:
    """Ion PDG (10LZZZAAAI) -> Achilles isotope name, e.g. 1000060120 -> '12C'."""
    z = (abs(nucleus_pdg) // 10000) % 1000
    a = (abs(nucleus_pdg) // 10) % 1000
    sym = _SYMBOL.get(z)
    if sym is None:
        raise ConfigError(
            f"no element symbol for Z={z} (nucleus PDG {nucleus_pdg}); "
            f"set achilles.nucleus explicitly (e.g. '40Ar')")
    return f"{a}{sym}"


class AchillesBackend(Backend):
    name = "achilles"
    default_image = ACHILLES_IMAGE

    def prepare(self, cfg, outdir, image=None) -> Prepared:
        if not cfg.gdml:
            raise ConfigError("the achilles backend requires geometry.gdml")
        outdir = Path(outdir)

        nucleus = cfg.achilles.get("nucleus")
        if not nucleus:
            target = cfg.genie.get("target") or cfg.achilles.get("target")
            if target in (None, "", "auto"):
                target = infer_target(cfg.gdml)
            nucleus = isotope_name(int(target))

        e = cfg.beam.energy
        job = {
            "generator": "achilles",
            "gdml": Path(cfg.gdml).name,
            "probe": probe_pdg(cfg.beam.pdg if cfg.beam.is_pdg() else cfg.beam.particle),
            "nucleus": nucleus,
            "flux": {"mode": e.mode, "value": e.value, "sigma": e.sigma,
                     "min": e.min, "max": e.max, "bins": e.bins},
            "position": cfg.beam.position,
            "direction": cfg.beam.direction,
            "events": int(cfg.run.events),
            "output": cfg.run.output,
            "seed": cfg.run.seed,
            # backend-specific knobs, passed through to the run-card template
            "nuclear_model": cfg.achilles.get("nuclear_model"),
            "cascade": cfg.achilles.get("cascade", True),
            "processes": cfg.achilles.get("processes"),   # e.g. [[13],[14]] final-state leptons
            "run_card": cfg.achilles.get("run_card"),      # verbatim escape hatch
            "options": cfg.achilles.get("options", {}),    # raw run-card overrides
        }

        # A verbatim run card is staged next to the job for the driver.
        if job["run_card"]:
            src = Path(job["run_card"])
            if src.exists() and src.resolve().parent != outdir.resolve():
                import shutil
                shutil.copy(src, outdir / src.name)
            job["run_card"] = src.name

        # Host-sampled distributions / Twiss: per-event replay via the beam file
        # (same contract as the GENIE backend).
        if cfg.beam.needs_sampling():
            from .. import beam as beammod
            s = beammod.sample(cfg, int(cfg.run.events), seed=cfg.run.seed)
            beammod.write_beam_file(s, outdir / BEAM_FILE)
            job["beam_file"] = BEAM_FILE

        (outdir / JOB_FILE).write_text(json.dumps(job, indent=2) + "\n")
        return Prepared(argv=[JOB_FILE],
                        image=image or self.image_for(cfg),
                        env={}, output=cfg.run.output)
