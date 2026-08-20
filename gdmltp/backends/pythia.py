"""Pythia 8 backend: turn the common RunConfig into a Pythia job spec.

Pythia 8 (https://pythia.org) is a general-purpose collision generator with a
complete parton-shower + hadronization chain. Here it fills the niche the
nuclear generators cannot: **TeV-scale deep-inelastic scattering with no
cross-section splines to precompute** (unlike GENIE/HEDIS, whose `gmkspl` step
costs hours on a heavy nucleus), plus hadron-nucleon minimum-bias and hard-QCD
collisions.

Like the GENIE/Achilles backends the host writes a small job JSON; the Pythia
container's driver (pythia/run_pythia.py) renders the actual Pythia command
('.cmnd') file from it, runs the generator, and converts the HepMC3 output to
the common `output.root` schema -- so analyze/display/compare work unchanged.

Pythia is a *free-nucleon* generator: it collides the beam with a proton or
neutron at rest, with no nuclear medium, Fermi motion or final-state cascade.
For nuclear effects at GeV energies use the genie or achilles backends; the
value here is the high-energy shower/hadronization and the speed.

Because Pythia stops at the nuclear exit state (like GENIE and Achilles), the
generic Geant4 hand-off applies: `pythia: {transport: true}` replays the final
state through g4sim so the output carries both the interaction record and the
full detector transport (step_*/totalEdep/real trk_end*).
"""
import json
from pathlib import Path

from .base import Backend, Prepared
from ..config import ConfigError, PYTHIA_PROCESSES
from .genie import infer_target, _as_pdg, flux_emax_gev

PYTHIA_IMAGE = "ghcr.io/lawrenceleejr/gdmltargetpractice-pythia:main"
JOB_FILE = "pythia_job.json"
BEAM_FILE = "beam.dat"
CMND_FILE = "pythia_run.cmnd"

# Beam particles Pythia can shoot at a nucleon here. Neutrinos and charged
# leptons scatter via weak-boson exchange (the `dis` preset); hadrons via the
# QCD presets. Pythia itself accepts more, so an explicit PDG is also allowed.
_PROBE_PDG = {
    "nu_e": 12, "anti_nu_e": -12,
    "nu_mu": 14, "anti_nu_mu": -14,
    "nu_tau": 16, "anti_nu_tau": -16,
    "e-": 11, "e+": -11,
    "mu-": 13, "mu+": -13,
    "proton": 2212, "anti_proton": -2212,
    "neutron": 2112,
    "pi+": 211, "pi-": -211,
    "gamma": 22,
}

_NEUTRINOS = {12, -12, 14, -14, 16, -16}
_CHARGED_LEPTONS = {11, -11, 13, -13, 15, -15}


def probe_pdg(particle) -> int:
    """Resolve the Pythia beam PDG from a name or an explicit PDG id."""
    pdg = _as_pdg(particle)
    if pdg is not None:
        return pdg
    try:
        return _PROBE_PDG[particle]
    except KeyError:
        raise ConfigError(
            f"the pythia backend does not know the particle name {particle!r} "
            f"(known: {', '.join(sorted(_PROBE_PDG))}); give a PDG id instead, "
            f"e.g. beam.pdg: 14")


def nucleon_pdg(target) -> int:
    """The struck free nucleon. Pythia collides with a single nucleon, so a
    nuclear target PDG (10LZZZAAAI) is reduced to a proton or neutron -- the
    more abundant one in that nucleus, which is the honest single-nucleon
    stand-in for a nuclear target."""
    t = int(target)
    if t in (2212, 2112):
        return t
    if abs(t) > 1_000_000_000:
        z = (abs(t) // 10000) % 1000
        a = (abs(t) // 10) % 1000
        return 2212 if z * 2 >= a else 2112      # p if Z >= N, else n
    raise ConfigError(
        f"pythia.target must be a nucleon (2212/2112) or a nuclear PDG id, "
        f"got {target!r}")


def preset_settings(process, probe, pt_min=None, q2_min=None):
    """Pythia settings lines for a process preset.

    `dis` uses WeakBosonExchange t-channel: the W piece is the CC process (the
    only one open for a neutrino beam) and the gamma*/Z piece the NC one. The W
    mass regulates the CC t-channel, but the photon piece needs a Q2 cut, so a
    default Q2Min is applied (override with pythia.q2_min or raw settings).
    """
    if process == "none":
        return []
    if process == "dis":
        lines = ["WeakBosonExchange:ff2ff(t:W) = on"]
        # A neutrino beam has no photon coupling; including gmZ for it would add
        # the NC channel, which Pythia does support -- keep both so CC+NC are
        # generated, matching what the nuclear generators produce.
        lines.append("WeakBosonExchange:ff2ff(t:gmZ) = on")
        lines.append(f"PhaseSpace:Q2Min = {float(q2_min) if q2_min else 1.0}")
        return lines
    if process == "softqcd":
        return ["SoftQCD:inelastic = on"]
    if process == "hardqcd":
        return ["HardQCD:all = on",
                f"PhaseSpace:pTHatMin = {float(pt_min) if pt_min else 20.0}"]
    raise ConfigError(f"unknown pythia.process {process!r}; "
                      f"choose one of {', '.join(PYTHIA_PROCESSES)}")


class PythiaBackend(Backend):
    name = "pythia"
    default_image = PYTHIA_IMAGE

    def prepare(self, cfg, outdir, image=None) -> Prepared:
        if not cfg.gdml:
            raise ConfigError("the pythia backend requires geometry.gdml")
        outdir = Path(outdir)
        p = cfg.pythia

        probe = probe_pdg(cfg.beam.pdg if cfg.beam.is_pdg() else cfg.beam.particle)
        target = p.get("target")
        if target in (None, "", "auto"):
            # same GDML material inference the other neutrino backends use,
            # reduced to the single nucleon Pythia actually collides with
            target = infer_target(cfg.gdml)
        nucleon = nucleon_pdg(target)

        process = p.get("process", "dis")
        e = cfg.beam.energy
        job = {
            "generator": "pythia",
            "gdml": Path(cfg.gdml).name,
            "probe": probe,
            "nucleon": nucleon,
            "process": process,
            "settings": list(p.get("settings") or []),
            "q2_min": p.get("q2_min"),
            "pt_min": p.get("pt_min"),
            "flux": {"mode": e.mode, "value": e.value, "sigma": e.sigma,
                     "min": e.min, "max": e.max, "bins": e.bins},
            "flux_emax_gev": flux_emax_gev({
                "mode": e.mode, "value": e.value, "sigma": e.sigma,
                "min": e.min, "max": e.max, "bins": e.bins}),
            "position": cfg.beam.position,
            "direction": cfg.beam.direction,
            "events": int(cfg.run.events),
            "output": cfg.run.output,
            "seed": cfg.run.seed,
            "length_units": p.get("length_units", "mm"),
            "cmnd": p.get("cmnd"),                  # verbatim card escape hatch
        }

        # A verbatim command file is staged next to the job for the driver.
        if job["cmnd"]:
            src = Path(job["cmnd"])
            if src.exists() and src.resolve().parent != outdir.resolve():
                import shutil
                shutil.copy(src, outdir / src.name)
            job["cmnd"] = src.name

        # Host-sampled distributions / Twiss: per-event replay via the beam file
        # (same contract as the GENIE and Achilles backends).
        if cfg.beam.needs_sampling():
            from .. import beam as beammod
            s = beammod.sample(cfg, int(cfg.run.events), seed=cfg.run.seed)
            beammod.write_beam_file(s, outdir / BEAM_FILE)
            job["beam_file"] = BEAM_FILE

        (outdir / JOB_FILE).write_text(json.dumps(job, indent=2) + "\n")
        return Prepared(argv=[JOB_FILE],
                        image=image or self.image_for(cfg),
                        env={}, output=cfg.run.output)
