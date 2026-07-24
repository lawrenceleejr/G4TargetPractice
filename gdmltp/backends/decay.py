"""Decay backend: long-lived BSM projectiles decayed in flight, on the host.

Unlike geant4/genie/achilles this backend has no container stage of its own --
gdmltp.decay generates the vertex-level events right in prepare() (pure numpy,
fast, deterministic) and writes the schema output.root. With decay.transport
on, the orchestrator's existing hand-off then replays the daughters through
the GDML detector in the Geant4 image, so "see the HNL decay in the detector"
is a one-config, two-stage run.
"""
from pathlib import Path

from .base import Backend, Prepared


class DecayBackend(Backend):
    name = "decay"
    default_image = ""          # host-run: no container stage
    host = True

    def prepare(self, cfg, outdir, image=None) -> Prepared:
        from .. import decay as decaymod

        outdir = Path(outdir)
        n = int(cfg.run.events)
        ev = decaymod.generate(cfg, n, seed=cfg.run.seed)
        decaymod.write_output(ev, outdir / cfg.run.output)

        import numpy as np
        lam_note = ""
        w = np.asarray(ev["weight"], float)
        if cfg.decay.get("fiducial"):
            lam_note = (f"; fiducial decay weight <w> = {w.mean():.3g} "
                        f"(survival probability into the window)")
        print(f"[gdmltp] decay: generated {n} {cfg.beam.identifier()} decay(s) "
              f"on the host -> {outdir / cfg.run.output}{lam_note}")

        return Prepared(argv=[], image="", env={}, output=cfg.run.output)
