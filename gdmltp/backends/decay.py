"""Decay backend: long-lived BSM projectiles, decayed by GEANT4.

This backend generates nothing itself. It renders `/bsm/define` +
`/bsm/channel` macro commands that define the particle (mass, charge, ctau,
channels) to Geant4, and Geant4 does everything in ONE stage of the standard
geant4 image: flies the parent (any beam spec, incl. distributions/Twiss via
the beam file), decays it in flight with its own G4Decay +
G4PhaseSpaceDecayChannel, and transports the daughters through the GDML
detector -- displaced vertex, timing, and energy deposits all from Geant4.

After the run, `gdmltp.decay.postprocess` adds two derived scalars from the
recorded branches: decayT (flight time) and eventWeight (the analytic
lifetime-importance weight when decay.ctau_sample != decay.ctau).
"""
from pathlib import Path

from .base import Backend, Prepared
from .geant4 import DEFAULT_IMAGE, Geant4Backend, BEAM_FILE

DECAY_MACRO = "gdmltp_decay.mac"


class DecayBackend(Backend):
    name = "decay"
    default_image = DEFAULT_IMAGE          # it IS a geant4 run

    def image_for(self, cfg) -> str:
        return Geant4Backend().image_for(cfg)

    def prepare(self, cfg, outdir, image=None) -> Prepared:
        from .. import decay as decaymod
        from .geant4 import build_macro

        outdir = Path(outdir)
        bsm = decaymod.bsm_macro_lines(cfg)   # also runs the early physics checks

        beam_file = None
        if cfg.beam.needs_sampling():
            from .. import beam as beammod
            s = beammod.sample(cfg, int(cfg.run.events), seed=cfg.run.seed)
            beammod.write_beam_file(s, outdir / BEAM_FILE)
            beam_file = BEAM_FILE

        # /bsm/* must precede /run/initialize; build_macro starts with
        # /detector/readGDML which is also PreInit, so prepending is correct.
        macro = "\n".join(bsm) + "\n" + build_macro(cfg, beam_file=beam_file)
        (outdir / DECAY_MACRO).write_text(macro)

        g4 = Geant4Backend()
        env = {"CELER_DISABLE": "1"} if g4.celer_disable(cfg) else {}

        def post():
            decaymod.postprocess(outdir / cfg.run.output, cfg)
            print(f"[gdmltp] decay: added decayT/eventWeight to "
                  f"{outdir / cfg.run.output} (ctau = "
                  f"{decaymod.ctau_mm(cfg.decay):g} mm, sampled at "
                  f"{decaymod.sampling_ctau_mm(cfg):g} mm)")

        return Prepared(argv=[DECAY_MACRO],
                        image=image or self.image_for(cfg),
                        env=env, output="output.root", post=post)
