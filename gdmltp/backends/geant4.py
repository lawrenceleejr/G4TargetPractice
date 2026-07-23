"""Geant4 backend: render a Geant4 macro from the common RunConfig and run g4sim.

`build_macro` emits the full messenger surface g4sim exposes (energy modes,
seeds, angular spread, arbitrary spectra) -- not just the mono-energy subset the
old flag-only path produced. Every command here is one g4sim already understands
(see g4sim/PrimaryGeneratorMessenger.cc, DetectorMessenger.cc, RunActionMessenger.cc).
"""
import shutil
from pathlib import Path

from .base import Backend, Prepared

DEFAULT_IMAGE = "ghcr.io/lawrenceleejr/g4targetpractice:main"
GENERATED_MACRO = "gdmltp_run.mac"
BEAM_FILE = "beam.dat"


def _progress(events):
    try:
        return max(1, int(events) // 10)
    except (TypeError, ValueError):
        return 100


def build_macro(cfg, beam_file=None) -> str:
    """Render `cfg` to Geant4 macro text.

    Order matters only in that /analysis/neutrinoMode, the seed and the field
    must precede /run/beamOn (branches/field are set up at run start); the gun
    commands are state-flexible. We keep the historical layout:
    readGDML -> initialize -> neutrinoMode -> [seed] -> [field] -> gun -> beamOn.

    When `beam_file` is given (host-sampled distributions / Twiss), the per-event
    gun block is replaced by a single `/gun/beamFile`, and g4sim replays one
    sampled primary per event.
    """
    beam = cfg.beam
    e = beam.energy
    gdml_name = Path(cfg.gdml).name if cfg.gdml else ""
    nmode = cfg.geant4.get("neutrino_mode", "auto")

    lines = [
        f"/detector/readGDML {gdml_name}",
        "/run/initialize",
        f"/analysis/neutrinoMode {nmode}",
    ]
    if cfg.run.seed is not None:
        lines.append(f"/random/setSeeds {int(cfg.run.seed)} {int(cfg.run.seed) + 1}")
    field = cfg.geant4.get("field")
    if field:
        lines.append(f"/detector/setGlobalField {field}")

    if beam_file:
        lines.append(f"/gun/beamFile {beam_file}")
        lines.append(f"/run/printProgress {_progress(cfg.run.events)}")
        lines.append(f"/run/beamOn {int(cfg.run.events)}")
        return "\n".join(lines) + "\n"

    lines.append(f"/gun/particle {beam.particle}")
    lines.append(f"/gun/energyMode {e.mode}")
    if e.mode == "gauss" and e.sigma:
        lines.append(f"/gun/gaussSigma {e.sigma}")
    if e.mode == "exp":
        if e.min:
            lines.append(f"/gun/energyMin {e.min}")
        if e.max:
            lines.append(f"/gun/energyMax {e.max}")
    if e.mode == "arb":
        lines.append("/gun/clearEnergyBins")
        for b in e.bins:
            lines.append(f"/gun/addEnergyBin {b['value']} {b['weight']}")
    else:
        lines.append(f"/gun/energy {e.value}")

    if beam.angle_sigma:
        lines.append(f"/gun/angleSigma {beam.angle_sigma}")
    lines.append(f"/gun/position {beam.position}")
    lines.append(f"/gun/direction {beam.direction}")
    lines.append(f"/run/printProgress {_progress(cfg.run.events)}")
    lines.append(f"/run/beamOn {int(cfg.run.events)}")
    return "\n".join(lines) + "\n"


class Geant4Backend(Backend):
    name = "geant4"
    default_image = DEFAULT_IMAGE

    def image_for(self, cfg) -> str:
        img = self.default_image
        if cfg.geant4.get("celeritas"):
            # tag variant: ...:main -> ...:main-celeritas
            if ":" in img:
                repo, tag = img.rsplit(":", 1)
                return f"{repo}:{tag}-celeritas"
            return f"{img}:latest-celeritas"
        return img

    def celer_disable(self, cfg) -> bool:
        # The Celeritas EM offload assumes zero field; disable it when a field
        # is set (mirrors the historical run.py behavior).
        return bool(cfg.geant4.get("field"))

    def prepare(self, cfg, outdir, image=None) -> Prepared:
        outdir = Path(outdir)
        if cfg.mac:
            macro_name = Path(cfg.mac).name
            src = Path(cfg.mac)
            if src.resolve().parent != outdir.resolve() and src.exists():
                shutil.copy(src, outdir / macro_name)
        elif cfg.beam.needs_sampling():
            from .. import beam as beammod
            s = beammod.sample(cfg, int(cfg.run.events), seed=cfg.run.seed)
            beammod.write_beam_file(s, outdir / BEAM_FILE)
            macro_name = GENERATED_MACRO
            (outdir / macro_name).write_text(build_macro(cfg, beam_file=BEAM_FILE))
        else:
            macro_name = GENERATED_MACRO
            (outdir / macro_name).write_text(build_macro(cfg))

        env = {}
        if self.celer_disable(cfg):
            env["CELER_DISABLE"] = "1"

        return Prepared(argv=[macro_name],
                        image=image or self.image_for(cfg),
                        env=env, output="output.root")
