"""Common run configuration: a generator-agnostic front-end shared by every backend.

A run is described by a small tree of dataclasses (`RunConfig`) that can be built
two ways:

  * from a YAML file (`from_yaml`) -- the documented `--config run.yaml` frontend, or
  * from CLI flags (`from_flags`) -- the historical `g4tp run --gdml ... --particle ...`.

`load` combines them with the precedence **CLI flag > YAML value > schema default**,
so `g4tp run --config r.yaml --energy "200 MeV"` overrides just that one field.

The config is deliberately backend-agnostic in its core (`geometry`, `beam`, `run`);
backend-specific knobs live in namespaced blocks (`geant4:` / `genie:`) that the
other backend ignores. This is the single place YAML is parsed and validated, so
backends receive an already-validated object and never touch raw user input.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


GENERATORS = ("geant4", "genie")
ENERGY_MODES = ("mono", "gauss", "exp", "arb")


class ConfigError(ValueError):
    """A user-facing configuration problem (bad/missing field). cli.py renders
    these as a friendly one-liner (they are a subclass of ValueError)."""


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
@dataclass
class Energy:
    """Beam energy spectrum. Values are strings with a unit (e.g. "150 MeV"),
    passed verbatim to the backend just like the Geant4 macro expects."""
    mode: str = "mono"            # mono | gauss | exp | arb
    value: str = "1 GeV"         # nominal (mono) / mean (gauss) / E0 (exp)
    sigma: Optional[str] = None  # gauss only
    min: Optional[str] = None    # exp / arb range
    max: Optional[str] = None    # exp / arb range
    bins: list = field(default_factory=list)  # arb: list of {"value","weight"}


@dataclass
class Beam:
    particle: str = "e-"
    energy: Energy = field(default_factory=Energy)
    position: str = "0 0 -20 cm"
    direction: str = "0 0 1"     # "0 0 0" -> isotropic (geant4 only)
    angle_sigma: Optional[str] = None  # gaussian angular spread, e.g. "10 deg"


@dataclass
class RunSettings:
    events: int = 100
    output: str = "output.root"
    seed: Optional[int] = None


@dataclass
class RunConfig:
    generator: str = "geant4"
    gdml: Optional[str] = None
    mac: Optional[str] = None    # geant4 escape hatch: run this macro verbatim
    beam: Beam = field(default_factory=Beam)
    run: RunSettings = field(default_factory=RunSettings)
    geant4: dict = field(default_factory=dict)  # field, neutrino_mode, celeritas, physics_list
    genie: dict = field(default_factory=dict)   # tune, cross_sections, target, ...

    def validate(self):
        if self.generator not in GENERATORS:
            raise ConfigError(
                f"unknown generator {self.generator!r}; choose one of {', '.join(GENERATORS)}")
        if not self.gdml and not self.mac:
            raise ConfigError("no geometry: set geometry.gdml (or, for geant4, a macro via --mac)")
        if self.mac and self.generator != "geant4":
            raise ConfigError("a verbatim macro (mac) is only meaningful for the geant4 backend")
        e = self.beam.energy
        if e.mode not in ENERGY_MODES:
            raise ConfigError(
                f"unknown energy mode {e.mode!r}; choose one of {', '.join(ENERGY_MODES)}")
        if e.mode == "gauss" and not e.sigma:
            raise ConfigError("energy mode 'gauss' requires energy.sigma")
        if e.mode == "exp" and not (e.min and e.max):
            raise ConfigError("energy mode 'exp' requires energy.min and energy.max")
        if e.mode == "arb" and not e.bins:
            raise ConfigError("energy mode 'arb' requires a non-empty energy.bins list")
        nm = self.geant4.get("neutrino_mode")
        if nm is not None and nm not in ("auto", "on", "off"):
            raise ConfigError(
                f"geant4.neutrino_mode must be auto/on/off, got {nm!r}")
        try:
            int(self.run.events)
        except (TypeError, ValueError):
            raise ConfigError(f"run.events must be an integer, got {self.run.events!r}")
        return self


# --------------------------------------------------------------------------- #
# YAML front-end
# --------------------------------------------------------------------------- #
_TOP_KEYS = {"generator", "geometry", "beam", "projectile", "run", "geant4", "genie", "mac"}


def _energy_from(raw) -> Energy:
    """Accept either a bare string (shorthand for mono at that value) or the
    full {mode, value, sigma, min, max, bins} mapping."""
    if raw is None:
        return Energy()
    if isinstance(raw, str):
        return Energy(mode="mono", value=raw)
    if not isinstance(raw, dict):
        raise ConfigError("beam.energy must be a string or a mapping")
    bins = []
    for b in raw.get("bins", []) or []:
        if not isinstance(b, dict) or "value" not in b:
            raise ConfigError("each energy.bins entry needs a 'value' (and optional 'weight')")
        bins.append({"value": str(b["value"]), "weight": float(b.get("weight", 1.0))})
    return Energy(
        mode=str(raw.get("mode", "mono")),
        value=str(raw.get("value", "1 GeV")),
        sigma=_opt_str(raw.get("sigma")),
        min=_opt_str(raw.get("min")),
        max=_opt_str(raw.get("max")),
        bins=bins,
    )


def _opt_str(v):
    return None if v is None else str(v)


def from_dict(data: dict) -> RunConfig:
    """Build a RunConfig from a parsed YAML/JSON mapping (no flag merge)."""
    if not isinstance(data, dict):
        raise ConfigError("config file must contain a top-level mapping")
    unknown = set(data) - _TOP_KEYS
    if unknown:
        raise ConfigError(f"unknown top-level key(s): {', '.join(sorted(unknown))}")

    geometry = data.get("geometry") or {}
    if isinstance(geometry, str):           # tolerate `geometry: my.gdml` shorthand
        geometry = {"gdml": geometry}
    beam_raw = data.get("beam", data.get("projectile")) or {}

    cfg = RunConfig(
        generator=str(data.get("generator", "geant4")),
        gdml=_opt_str(geometry.get("gdml")),
        mac=_opt_str(data.get("mac")),
        beam=Beam(
            particle=str(beam_raw.get("particle", "e-")),
            energy=_energy_from(beam_raw.get("energy")),
            position=str(beam_raw.get("position", "0 0 -20 cm")),
            direction=str(beam_raw.get("direction", "0 0 1")),
            angle_sigma=_opt_str(beam_raw.get("angle_sigma")),
        ),
        run=_run_from(data.get("run") or {}),
        geant4=dict(data.get("geant4") or {}),
        genie=dict(data.get("genie") or {}),
    )
    # YAML 1.1 parses `on`/`off` as booleans, so `neutrino_mode: off` arrives as
    # Python False; map it back to the auto/on/off vocabulary g4sim expects.
    nm = cfg.geant4.get("neutrino_mode")
    if isinstance(nm, bool):
        cfg.geant4["neutrino_mode"] = "on" if nm else "off"
    return cfg


def _run_from(raw: dict) -> RunSettings:
    seed = raw.get("seed")
    return RunSettings(
        events=int(raw.get("events", 100)),
        output=str(raw.get("output", "output.root")),
        seed=None if seed is None else int(seed),
    )


def from_yaml(path) -> RunConfig:
    import yaml  # lazy: only the --config path needs PyYAML
    text = Path(path).read_text()
    data = yaml.safe_load(text)
    if data is None:
        raise ConfigError(f"config file is empty: {path}")
    return from_dict(data)


# --------------------------------------------------------------------------- #
# Flag front-end + merge
# --------------------------------------------------------------------------- #
# Maps argparse dest -> where it lands in the config. Only these run-subcommand
# flags participate in config (image/local/outdir/display/dry_run are
# orchestration, handled separately by the caller).
_FLAG_FIELDS = ("generator", "gdml", "mac", "particle", "energy",
                "position", "direction", "n", "neutrino_mode", "field")


def _apply_flag(cfg: RunConfig, name: str, value):
    if name == "generator":
        cfg.generator = value
    elif name == "gdml":
        cfg.gdml = value
    elif name == "mac":
        cfg.mac = value
    elif name == "particle":
        cfg.beam.particle = value
    elif name == "energy":
        cfg.beam.energy.value = value  # flags only drive the mono/nominal value
    elif name == "position":
        cfg.beam.position = value
    elif name == "direction":
        cfg.beam.direction = value
    elif name == "n":
        cfg.run.events = int(value)
    elif name == "neutrino_mode":
        cfg.geant4["neutrino_mode"] = value
    elif name == "field":
        cfg.geant4["field"] = value


def from_flags(args) -> RunConfig:
    """Build a RunConfig purely from CLI flags (the historical interface)."""
    cfg = RunConfig()
    for name in _FLAG_FIELDS:
        if hasattr(args, name):
            _apply_flag(cfg, name, getattr(args, name))
    return cfg


def load(args, defaults=None) -> RunConfig:
    """Resolve the final RunConfig for a `run` invocation.

    Without --config, the config is built entirely from flags (identical to the
    historical behavior). With --config, the YAML is the base and any flag whose
    value differs from its parser default is overlaid on top (flag > YAML >
    default). `defaults` maps flag dest -> parser default, used to detect which
    flags were explicitly given; when omitted, every present flag overrides.
    """
    cfg_path = getattr(args, "config", None)
    if not cfg_path:
        return from_flags(args).validate()

    cfg = from_yaml(cfg_path)
    defaults = defaults or {}
    for name in _FLAG_FIELDS:
        if not hasattr(args, name):
            continue
        value = getattr(args, name)
        # Only overlay flags the user actually set (value != parser default).
        if name in defaults and value == defaults[name]:
            continue
        if value is None:
            continue
        _apply_flag(cfg, name, value)
    return cfg.validate()
