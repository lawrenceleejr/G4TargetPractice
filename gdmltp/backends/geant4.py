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
    # print progress often enough for a smooth host-side bar (~100 updates),
    # but never every-single-event on very large runs
    try:
        return max(1, int(events) // 100)
    except (TypeError, ValueError):
        return 100


_NEUTRINO_PDGS = {12, -12, 14, -14, 16, -16}
DEFAULT_NU_BIAS = 5.0e12          # matches the repo's hand-written neutrino macros


def _neutrino_bias_lines(cfg):
    """Geant4's built-in neutrino processes have cross sections so small that
    unbiased runs record essentially no interactions; g4sim's /gdmltp/neutrinoBias
    command enables them and scales the cross sections via the G4EmParameters C++
    API. (Earlier this emitted the /physics_lists/em/Nu* UI commands, but those
    are not registered in every Geant4 build -- and an unknown command aborts the
    batch regardless of /control/suppressAbortion -- so we drive the API through
    our own always-present command instead.)

    geant4.neutrino_bias: auto (default: on when the primary is a neutrino),
    on/off, or a mapping {enable, factor, cc_bias, nc_bias, nucleus_bias,
    detector_name, region_pattern}.

    `detector_name` is a **G4Region** name, not a logical-volume name -- the
    bias applies only to volumes in that region. g4sim builds a region called
    "target" out of every non-world volume (narrow it with `region_pattern`,
    a substring the volume name must contain), so `detector_name: target`
    works out of the box; the default "DefaultRegionForTheWorld" biases
    everything including the world.
    """
    raw = cfg.geant4.get("neutrino_bias", "auto")
    if isinstance(raw, bool):                     # YAML 1.1: on/off arrive as bools
        raw = {"enable": "on" if raw else "off"}
    elif isinstance(raw, str):
        raw = {"enable": raw}
    elif not isinstance(raw, dict):
        raw = {"enable": "auto"}

    enable = raw.get("enable", "auto")
    if isinstance(enable, bool):
        enable = "on" if enable else "off"
    if enable == "off":
        return []
    if enable == "auto":
        # an explicit `geant4.neutrino` block is the user driving every term
        # themselves -- do not also fire the blunt shortcut behind their back
        if cfg.geant4.get("neutrino"):
            return []
        pdg = cfg.beam.pdg_code()
        if pdg not in _NEUTRINO_PDGS:
            return []

    factor = float(raw.get("factor", DEFAULT_NU_BIAS))
    cc = float(raw.get("cc_bias", factor))
    nc = float(raw.get("nc_bias", factor))
    nuc = float(raw.get("nucleus_bias", factor))
    det = raw.get("detector_name", "DefaultRegionForTheWorld")
    lines = []
    pattern = raw.get("region_pattern")
    if pattern:
        lines.append(f"/detector/targetRegionPattern {pattern}")
    lines.append(f"/gdmltp/neutrinoBias {cc:g} {nc:g} {nuc:g} {det}")
    return lines


# --- the full Geant4 neutrino knob surface -------------------------------------
# One entry per biasing term g4sim's /gdmltp/nu/<group>/ commands expose. The
# YAML key is snake_case; the UI command is camelCase. See NeutrinoPhysics.hh
# for what each term does -- they are genuinely independent, not aliases.
_NU_TERMS = {
    "enable":        ("enable", "bool"),
    "region":        ("region", "str"),
    "mfp_bias":      ("mfpBias", "num"),      # region-scoped mean-free-path scale
    "cc_bias":       ("ccBias", "num"),       # + uniform vertex spread when > 1
    "nc_bias":       ("ncBias", "num"),
    "xsec_bias":     ("xsecBias", "num"),     # scales the tabulated cross section
    "lowest_energy": ("lowestEnergy", "raw"), # "10 MeV" -> value + unit
}
# Oscillation has its own term names (its bias is a distance bias, not a
# mean-free-path bias) but the same enable/region/lowest_energy.
_NU_OSC_TERMS = dict(_NU_TERMS, distance_bias=("distanceBias", "num"))
for _k in ("mfp_bias", "cc_bias", "nc_bias", "xsec_bias"):
    _NU_OSC_TERMS.pop(_k)

# Emission order matters: Geant4 executes macro lines in sequence, so the
# broad groups must come first for the specific ones to be able to override
# them. "all"/"nucleus" are convenience aliases over the same process objects.
NU_GROUPS = ["all", "nucleus", "electron", "nucleus_e", "nucleus_mu", "nucleus_tau"]
_NU_GROUP_CMD = {
    "all": "all", "nucleus": "nucleus", "electron": "electron",
    "nucleus_e": "nucleusE", "nucleus_mu": "nucleusMu", "nucleus_tau": "nucleusTau",
}


def _fmt_nu_value(kind, value):
    if kind == "bool":
        if isinstance(value, str):
            return "true" if value in ("on", "true") else "false"
        return "true" if value else "false"
    if kind == "num":
        return f"{float(value):g}"
    return str(value)          # "str" and "raw" (a value+unit string) go verbatim


def _neutrino_knob_lines(cfg):
    return neutrino_knob_lines(cfg.geant4.get("neutrino"))


def neutrino_knob_lines(raw):
    """Render a `geant4.neutrino` block -- the complete, explicit knob surface.

    Every biasing term Geant4's neutrino processes implement gets its own key,
    per process family, because in Geant4 the four families are separate process
    objects with separate factors:

        geant4:
          neutrino:
            region: target                  # shorthand: all four families
            region_pattern: LAr             # which volumes make up "target"
            nucleus_mu: {mfp_bias: 1.0e9}
            electron:   {cc_bias: 10, nc_bias: 1}
            oscillation: {enable: true, region: target, distance_bias: 1.0e8}

    Groups: electron, nucleus_e, nucleus_mu, nucleus_tau (the four process
    objects), nucleus (the three nucleus ones at once), all (all four), plus
    oscillation. Bare `region`/`enable`/... at the top of the block are
    shorthand for the `all` group.
    """
    if not raw:
        return []
    if not isinstance(raw, dict):
        raise ValueError(f"must be a mapping, got {raw!r}")

    groups = {g: dict(raw[g]) for g in NU_GROUPS if isinstance(raw.get(g), dict)}
    osc = dict(raw["oscillation"]) if isinstance(raw.get("oscillation"), dict) \
        else raw.get("oscillation")
    # Which logical volumes make up the regions the physics knobs point at.
    # These are geometry commands (DetectorConstruction builds the regions), so
    # they are emitted first -- before anything under /gdmltp/nu/.
    lines = []
    if raw.get("region_pattern"):
        lines.append(f"/detector/targetRegionPattern {raw['region_pattern']}")
    if isinstance(osc, dict) and osc.get("region_pattern"):
        lines.append(f"/detector/oscRegionPattern {osc.pop('region_pattern')}")
    # bare terms at the top level are shorthand for the `all` group; they are
    # emitted first so a per-family entry can still override them
    bare = {k: v for k, v in raw.items() if k in _NU_TERMS}
    if bare:
        groups.setdefault("all", {})
        merged = dict(bare)
        merged.update(groups["all"])
        groups["all"] = merged

    unknown = (set(raw) - set(NU_GROUPS) - set(_NU_TERMS)
               - {"oscillation", "region_pattern"})
    if unknown:
        raise ValueError(
            "unknown key(s): "
            f"{', '.join(sorted(unknown))}; expected one of "
            f"{', '.join(NU_GROUPS + ['oscillation', 'region_pattern'] + list(_NU_TERMS))}")

    for g in NU_GROUPS:
        terms = groups.get(g)
        if not terms:
            continue
        for key, value in terms.items():
            if key not in _NU_TERMS:
                raise ValueError(
                    f"unknown key {key!r} under {g}; expected "
                    f"one of {', '.join(_NU_TERMS)}")
            cmd, kind = _NU_TERMS[key]
            lines.append(f"/gdmltp/nu/{_NU_GROUP_CMD[g]}/{cmd} "
                         f"{_fmt_nu_value(kind, value)}")
    if osc is not None:
        if isinstance(osc, bool) or isinstance(osc, str):
            osc = {"enable": osc}
        if not isinstance(osc, dict):
            raise ValueError(
                f"oscillation must be on/off or a mapping, got {osc!r}")
        for key, value in osc.items():
            if key not in _NU_OSC_TERMS:
                raise ValueError(
                    f"unknown key {key!r} under oscillation; "
                    f"expected one of {', '.join(_NU_OSC_TERMS)}")
            cmd, kind = _NU_OSC_TERMS[key]
            lines.append(f"/gdmltp/nu/oscillation/{cmd} "
                         f"{_fmt_nu_value(kind, value)}")
    return lines


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

    lines = [f"/detector/readGDML {gdml_name}"]
    lines += _neutrino_bias_lines(cfg)     # must precede /run/initialize
    lines += _neutrino_knob_lines(cfg)     # ditto: all /gdmltp/nu/* are PreInit
    lines += [
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

    if beam.is_pdg():
        lines.append(f"/gun/particlePDG {beam.pdg}")
    else:
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
