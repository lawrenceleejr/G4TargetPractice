# GDMLTargetPractice

Fire a projectile of your choosing at a target described in **GDML**, and simulate
the interaction with the physics engine that fits the problem — **Geant4** for
particle transport, or **GENIE** for neutrino event generation. One common
front-end (a YAML config or CLI flags), one common output ntuple, and the same
analysis/visualization tools regardless of which engine ran. No local install —
just Docker.

> Formerly **G4TargetPractice**. The Python package moved from `g4tp` to
> `gdmltp`; `import g4tp` and the `g4tp` command still work as deprecated
> aliases.

## The idea

- **Target** — any geometry in a GDML file (`geometry.gdml`).
- **Projectile / beam** — a particle, an energy spectrum, a position and direction.
- **Generator (backend)** — pick one:
  - `geant4` — full particle transport (the `g4sim` engine). *Default.*
  - `genie` — neutrino event generation on the GDML target. *Vertex-level (v1).*
  - `achilles` — theory-driven lepton-nucleus generation ([Achilles](https://github.com/AchillesGen/Achilles)); neutrino **and** `e∓` beams. *Vertex-level (v1).*
  - `fluka` (via flugg) — *planned, not yet available.*

Every backend writes the **same** `output.root` schema, so `analyze`, `display`,
`compare`, and `info` work identically no matter which engine produced the file.

## Do anything in one line with Docker — no install

Set `IMG=ghcr.io/lawrenceleejr/g4targetpractice:main`, mount your working
directory once (`-v $PWD:/run -w /run`).

```bash
# 1) Simulate from a Geant4 macro (writes output.root)
docker run --rm -v $PWD:/run -w /run $IMG run.mac

# 2) Event display — interactive WebGL (.html) + PNG stills
docker run --rm -v $PWD:/run -w /run $IMG display output.root --gdml my_detector.gdml

# 3) Analyze — summary report + plots
docker run --rm -v $PWD:/run -w /run $IMG analyze output.root

# 4) Compare two runs
docker run --rm -v $PWD:/run -w /run $IMG compare du.root w.root --labels DU,W

# 5) Inspect a file
docker run --rm -v $PWD:/run -w /run $IMG info output.root
```

A dispatcher entrypoint routes the argument by shape: `*.mac` → the Geant4
engine, `*.json` → the GENIE driver (in the GENIE image), everything else → the
`gdmltp` analysis tools. So the same image serves the simulator **and** the
analysis suite.

Prefer your laptop? `pip install "git+https://github.com/lawrenceleejr/G4TargetPractice"`
gives the same commands without Docker (pure Python, **no ROOT needed**).

## The common front-end

You can drive a run two ways; both build the same internal config and dispatch
to the selected backend.

### A YAML config (recommended)

```yaml
# water_proton.yaml — a 150 MeV proton pencil beam into a water phantom (Geant4)
generator: geant4
geometry:
  gdml: gdml/water_phantom_30cm.gdml
beam:
  particle: proton
  energy: { mode: mono, value: "150 MeV" }
  position: "0 0 -20 cm"
  direction: "0 0 1"
run:
  events: 500
  seed: 12345
```

```yaml
# nu_argon.yaml — a 2 GeV muon-neutrino beam on liquid argon (GENIE)
generator: genie
geometry:
  gdml: gdml/liquid_argon_1m3.gdml
beam:
  particle: nu_mu
  energy: { mode: mono, value: "2.0 GeV" }
run:
  events: 1000
  seed: 12345
genie:
  tune: G18_10a_00_000
  cross_sections: auto          # baked-in splines
  target: 1000180400            # optional; else inferred from the GDML material
```

Run either with:

```bash
gdmltp run --config water_proton.yaml
gdmltp run --config nu_argon.yaml
```

`gdmltp run` reads the config, validates it, picks the backend's container image,
and executes it. Individual fields can be overridden from the command line
(`--energy "200 MeV"` beats the YAML value): **flag > YAML > default**.

Common fields: `generator`, `geometry.gdml`, `beam.{particle,position,direction,angle_sigma}`,
`beam.energy.{mode,value,sigma,min,max,bins}` (modes `mono|gauss|exp|arb`),
`run.{events,output,seed}`. Backend-specific blocks (`geant4:`, `genie:`) are
read only by their backend and ignored by the other.

The projectile can be a Geant4 **name** or a **PDG id** — `beam.particle: proton`,
`beam.particle: 2212`, or `beam.pdg: 1000060120` (a carbon-12 ion) are all valid.
PDG ids cover ions and anything outside the common name table; for GENIE the id
must be a neutrino (`±12/14/16`).

### Beam distributions & Twiss phase space

Any beam coordinate can be a **distribution** instead of a single value — a bare
scalar is fixed, a mapping picks `gauss`/`uniform`:

```yaml
beam:
  particle: proton
  position:                                  # a gaussian spot at a fixed z
    x: { dist: gauss, mean: "0 mm", sigma: "3 mm" }
    y: { dist: gauss, sigma: "3 mm" }        # mean defaults to 0
    z: "-200 mm"
  direction:                                 # angular slopes about the axis
    central: "0 0 1"
    xprime: { dist: gauss, sigma: "5 mrad" }
    yprime: { dist: gauss, sigma: "5 mrad" }
  momentum: { dist: gauss, mean: "600 MeV/c", sigma: "12 MeV/c" }   # or use beam.energy
```

Or define a **Twiss** phase space at a point and sample N particles from it
(geometric emittance in mm·mrad, β in m):

```yaml
beam:
  particle: mu-
  twiss:
    x: { alpha: -1.2, beta: 5.0, emittance: 3.0 }
    y: { alpha:  0.4, beta: 2.0, emittance: 1.5 }
    p0: "300 MeV/c"
    dp_over_p: 0.01
    reference: { position: "0 0 -20 cm", direction: "0 0 1" }
```

How it works: when any beam parameter is a distribution (or `twiss` is set), the
**host** samples N primaries deterministically (seeded by `run.seed`) into a
portable `beam.dat` (`name  x y z [mm]  px py pz [MeV/c]`), and each generator
**replays** it one primary per event — Geant4 via a `/gun/beamFile` command, GENIE
by generating one interaction per ray and placing/orienting it along that ray.
Plain energy modes with a fixed position/direction stay on the fast analytic path
(no beam file). See `examples/twiss_muon.yaml` and `examples/gauss_beam.yaml`.

### Or plain flags (no file)

```bash
gdmltp run --gdml water_phantom_30cm.gdml --particle proton --energy "150 MeV" -n 500
gdmltp run --gdml my.gdml --field "0 0 5 tesla" --display
gdmltp run --generator genie --gdml liquid_argon_1m3.gdml --particle nu_mu --energy "2 GeV" -n 1000
```

### Backends & images

| Backend | Image | Status |
|---|---|---|
| `geant4` | `ghcr.io/lawrenceleejr/g4targetpractice` | full transport |
| `genie` | `ghcr.io/lawrenceleejr/g4targetpractice-genie` | neutrino vertices (v1) |
| `achilles` | `ghcr.io/lawrenceleejr/g4targetpractice-achilles` | ν / e∓ vertices (v1) |

`gdmltp run` picks the image automatically from the `generator`; override with
`--image`. (Image repositories keep the `g4targetpractice` name until the GitHub
repository itself is renamed.)

## The GENIE backend (neutrino generator)

GENIE replaces Geant4's built-in (and physically thin) neutrino handling with a
proper neutrino event generator. **v1 is vertex-level**: GENIE generates the
interaction on the nucleus the GDML geometry selects (or `genie.target`), and the
output ntuple carries the full `nu_*` interaction block plus one `trk_*` row per
final-state particle. Because GENIE does not transport particles, `step_*` and
`totalEdep` are empty. The pipeline inside the GENIE image is
`gevgen → gntpc -f gst → genie2root`.

Roadmap: geometry-aware vertex sampling in the full GDML volume, and a
**GENIE → Geant4 hand-off** that transports the final-state particles so a single
`output.root` carries both the interaction record and the deposited energy.

## The Achilles backend (lepton-nucleus generator)

[Achilles](https://github.com/AchillesGen/Achilles) is a theory-driven
lepton-nucleus event generator covering **neutrino** and **electron/positron**
beams, with an intranuclear cascade. The backend renders an Achilles YAML run
card from the common config (target nucleus inferred from the GDML material,
e.g. liquid argon → `40Ar`), runs `achilles`, and converts its **NuHepMC**
(HepMC3) output to the common ntuple with a small pure-Python parser — full
`nu_*` block (Q²/W/x/y computed from the exact four-vectors), one `trk_*` row
per final-state particle. Backend knobs: `achilles.{cascade, nuclear_model,
processes, nucleus, options}`, or a verbatim `achilles.run_card`.

**Same display pipeline for every backend.** Vertex-level generators record no
transport, so their converters also fill optional per-track momentum branches
(`trk_px/py/pz`); the event display draws momentum-direction rays (length ∝ √|p|)
for untransported tracks. `gdmltp display output.root --gdml my.gdml [--blend]`
therefore works identically on Geant4, GENIE, and Achilles output — including the
animated Blender export.

## Output

Each run writes `output.root` (TTree `tree`, one entry per event) with **event
scalars**, **per-track vectors** `trk_*`, **per-step vectors** `step_*`, and — for
neutrino runs — a `nu_*` interaction block (CC/NC, vertex, struck nucleus,
outgoing lepton, Q²/W/x/y). Units are Geant4-internal: **mm, MeV, ns, MeV/c**.
See `macros/README.md` for the full branch reference.

## Analysis & Event Display

The `gdmltp` tool turns `output.root` into plots and 3D visualizations with **no
ROOT dependency** (it reads the file with `uproot`). Run via Docker
(`docker run --rm -v $PWD:/run -w /run $IMG <cmd> ...`) or directly if installed.

| Command | What it does |
|---|---|
| `gdmltp run` | Run a simulation (`--config run.yaml`, or flags). `--display` opens an event display after; `--field "0 0 5 tesla"` adds a field (auto-sets `CELER_DISABLE=1`). |
| `gdmltp display` | Event display from `output.root` and/or `--gdml`: self-contained **WebGL HTML**, **PNG stills**, optional **Blender** scene (`--blend`). |
| `gdmltp analyze` | Summary report + plots: primary spectrum, total Edep, depth-dose, energy leakage, secondary counts, neutrino CC/NC if present. |
| `gdmltp compare` | Overlay two runs: longitudinal shower profile, containment vs depth (d90/d95/d99), per-event leakage. |
| `gdmltp info` | Inspect a `.root` (branches, events, nu block) or `.gdml` (solids, bounding box). |

**Large files**: `analyze`/`compare`/`info` stream in batches and read only the
branches they need; `display` loads only the requested events.

## Repository structure

```
GDMLTargetPractice/
├── g4sim/                   # Geant4 engine (C++): GDML loader, particle gun, ROOT output
├── gdmltp/                  # Python package: config frontend, backends, analysis, display
│   ├── config.py            # common RunConfig (YAML + flags, validated)
│   ├── backends/            # geant4 / genie / achilles behind one Backend interface
│   │   ├── base.py, geant4.py, genie.py, genie_convert.py, achilles.py, achilles_convert.py
│   ├── run.py               # backend-agnostic orchestrator (docker/local)
│   ├── cli.py, io.py, analyze.py, compare.py, geometry.py, scene.py, render_*.py
│   └── masses.py, particles.py
├── g4tp/                    # deprecated import shim -> gdmltp
├── genie/                   # in-container GENIE driver (run_genie.py)
├── achilles/                # in-container Achilles driver (run_achilles.py)
├── docker/                  # checked-in Dockerfiles: geant4, geant4-celeritas, genie, achilles
├── examples/                # example YAML run configs
├── gdml/                    # example GDML geometries
├── macros/                  # example Geant4 macros + README (branch reference)
├── tests/                   # pytest suite (pure Python; no Geant4/GENIE/Docker needed)
└── .github/workflows/       # CI: python tests, geant4 build+integration, image builds
```

## Development & tests

The Python suite needs **no Geant4, GENIE, ROOT, or Docker** — it synthesizes
`output.root` (and synthetic GENIE `gst`) files with uproot and exercises every
command, the config frontend, both backends, and the GENIE converter:

```bash
pip install -e .[dev]
pytest
```

CI runs the unit suite across Python 3.9/3.11/3.12, builds `g4sim` and runs a
full YAML→macro→engine→analyze integration, and publishes the Geant4 image only
if both pass. The GENIE image and the Celeritas image build in separate
workflows.

## Building from source (Geant4)

Requires Geant4 ≥ 11 with GDML support and ROOT:

```bash
mkdir build && cd build
cmake ../g4sim/ && cmake --build .
./g4sim ../g4sim/run_ci.mac        # or your own macro
```

Docker images are built from the checked-in `docker/geant4.Dockerfile` (and
`docker/geant4-celeritas.Dockerfile`, `docker/genie.Dockerfile`).

## Physics

The Geant4 backend uses `FTFP_BERT` by default (hadronic + EM physics for most
HEP studies). The neutrino block for GENIE runs is filled from the GENIE
interaction record; for Geant4 neutrino runs it comes from Geant4's built-in
neutrino processes — the two agree on the schema but differ in physics fidelity
(GENIE is the authoritative neutrino generator).

## Optional: Celeritas EM offload

[Celeritas](https://celeritas-project.github.io/celeritas/) can transport
electromagnetic tracks (`e-`, `e+`, `gamma`) on GPU/CPU instead of the Geant4
stepping loop. It is a build-time option (off by default); a CPU-only image is
published with a `-celeritas` tag. Set `CELER_DISABLE=1` to run those tracks
through Geant4 instead (needed for complete step-level output, and when a
magnetic field is set). See `docker/geant4-celeritas.Dockerfile`.
