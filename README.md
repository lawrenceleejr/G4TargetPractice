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
  - `decay` — long-lived **BSM projectiles** (HNLs, dark photons, ALPs), decayed **by Geant4** (`G4DecayTable`/`G4Decay`) with lifetime-importance reweighting: displaced vertex + full detector response in one stage. See [docs/bsm.md](docs/bsm.md).
  - `external` — bring **HepMC3 events from a real generator** (Pythia8, MadGraph) into the same schema/transport pipeline. See [docs/bsm.md](docs/bsm.md).
  - `fluka` (via flugg) — *planned, not yet available.*

Every backend writes the **same** `output.root` schema, so `analyze`, `display`,
`compare`, and `info` work identically no matter which engine produced the file.

**Doing neutrino physics?** Start with the
[neutrino quickstart](docs/neutrino.md): νμ on liquid argon through GENIE,
Achilles, and Geant4 — generate, validate, compare kinematics, transport, and
display in a handful of commands.

## Run it in one line with Docker — no install, no compiling

You describe a run in a **YAML file** (a target + a beam + a backend) and run it
with a single `docker run`. No macros, no local build. Clone the repo (so you
have the example YAMLs and geometries) and run from its root.

```bash
git clone https://github.com/lawrenceleejr/G4TargetPractice && cd G4TargetPractice

# one image per backend (all on GHCR; :main is the released tag)
GEANT4=ghcr.io/lawrenceleejr/g4targetpractice:main
GENIE=ghcr.io/lawrenceleejr/g4targetpractice-genie:main
ACHILLES=ghcr.io/lawrenceleejr/g4targetpractice-achilles:main

# a tiny wrapper: mounts the repo, and runs as YOU so outputs are owned by you
# (not root), with a writable HOME for in-container caches
gtp() { docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
                   -v "$PWD:/run" -w /run "$@"; }
```

**Simulate — one command per generator, always from a YAML:**

```bash
# Geant4 — 150 MeV protons into a water phantom (particle transport)
gtp $GEANT4   run --config examples/water_proton.yaml -o out

# GENIE — 2 GeV muon-neutrinos on liquid argon (neutrino event generator)
gtp $GENIE    run --config examples/nu_argon.yaml -o out

# Achilles — 2 GeV muon-neutrinos on argon (theory-driven lepton-nucleus)
gtp $ACHILLES run --config examples/nu_argon_achilles.yaml -o out

# BSM decay — an HNL decaying in flight inside a detector (Geant4 does the decay)
gtp $GEANT4   run --config examples/maia/hnl_decay.yaml -o out
```

Each writes `out/output.root` in one common schema, **owned by you**. The
container renders the engine inputs from the YAML and runs the engine itself —
one self-contained command, no nested Docker. Override any field on the command
line, e.g. `gtp $GENIE run --config examples/nu_argon.yaml --energy "5 GeV" -n 2000 -o out`.

**Then analyze / validate / display / compare the output — same pattern, any
image (the `gdmltp` tools ship in all of them):**

```bash
# physics + schema sanity check (exit 0 = PASS)
gtp $GEANT4 validate out/output.root

# summary report + plots (spectra, depth-dose, neutrino kinematics, ...)
gtp $GEANT4 analyze out/output.root -o out/analysis

# event display: PNG stills + interactive WebGL + a Blender scene (see below)
gtp $GEANT4 display out/output.root --gdml gdml/liquid_argon_1m3.gdml -o out/display

# overlay two runs (shower containment, and neutrino Q²/W/x/y across generators)
gtp $GEANT4 compare a/output.root b/output.root --labels A,B -o cmp

# inspect any .root or .gdml
gtp $GEANT4 info out/output.root
```

### Picking the event to display

`display` writes a Blender scene by default (plus PNG stills and WebGL HTML).
With no event chosen it shows the **richest event** (most steps, else most
final-state tracks) — so a neutrino run doesn't default to a non-interacting
event 0. To choose:

```bash
# a specific event
gtp $GEANT4 display out/output.root --event 12 -o out/display

# a range (all embedded in the HTML / first N in the Blender scene)
gtp $GEANT4 display out/output.root --events 0:20 -o out/display

# overlay EVERY event into one scene (great for a whole neutrino slice at once)
gtp $GEANT4 display out/output.root --all -o out/display

# turn outputs on/off: --no-blend / --no-png / --no-html
```

The `.blend` build needs Blender or Docker on the host, so it happens on the
**host** path (`gdmltp display …`, or `--image`); inside a plain `docker run`
the display writes `scene.json` + `build_blend.py` and prints the one command
to turn them into the `.blend`. `display --image $GEANT4 …` runs the whole
display in the container for you.

**Prefer your laptop?** `pip install "gdmltp @ git+https://github.com/lawrenceleejr/G4TargetPractice"`
installs the thin front-end (pure Python, **no ROOT**). Then `gdmltp run
--config …` launches the right container for you and handles multi-stage runs
(e.g. generator→Geant4 transport); `gdmltp display …` builds the Blender scene
directly. Add `[geometry]` for the accurate pyg4ometry GDML reader.

## The YAML front-end

Every run is a YAML file: a **target** (a GDML geometry), a **beam**, and a
**backend**. The same file works from a bare `docker run` (above) or the
`gdmltp` CLI, and drives whichever generator you name.

```yaml
# examples/water_proton.yaml — 150 MeV protons into a water phantom (Geant4)
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
# examples/nu_argon.yaml — 2 GeV muon-neutrinos on liquid argon (GENIE)
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
  cross_sections: auto          # cross-section splines built on demand, cached
  target: 1000180400            # optional; else inferred from the GDML material
```

Run either the bare-Docker way shown above, or — with the front-end installed —
`gdmltp run --config examples/nu_argon.yaml -o out`, which validates the config,
picks the backend's image, and runs it. Individual fields can be overridden from
the command line (`--energy "200 MeV"` beats the YAML value): **flag > YAML >
default**.

Common fields: `generator`, `geometry.gdml`, `beam.{particle,position,direction,angle_sigma}`,
`beam.energy.{mode,value,sigma,min,max,bins}` (modes `mono|gauss|exp|arb|mudecay_numu|mudecay_nue`
— the `mudecay_*` modes are the exact neutrino spectra from in-flight muon decay,
with `value` the parent muon energy; see `examples/maia/`),
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

### Quick one-offs with flags (no YAML)

For a throwaway run you can skip the file and pass flags instead (same
precedence rules); a YAML config is the recommended, reproducible form.

```bash
gdmltp run --gdml gdml/water_phantom_30cm.gdml --particle proton --energy "150 MeV" -n 500
gdmltp run --generator genie --gdml gdml/liquid_argon_1m3.gdml --particle nu_mu --energy "2 GeV" -n 1000
```

### Backends & images

| Backend | Image | Status |
|---|---|---|
| `geant4` | `ghcr.io/lawrenceleejr/g4targetpractice` | full transport |
| `genie` | `ghcr.io/lawrenceleejr/g4targetpractice-genie` | neutrino vertices (v1) |
| `achilles` | `ghcr.io/lawrenceleejr/g4targetpractice-achilles` | ν / e∓ vertices (v1) |
| `decay` | the geant4 image | BSM decay-in-flight **by Geant4** (G4DecayTable + G4Decay), one stage incl. transport |
| `external` | *(none — host conversion)* | HepMC3 events from Pythia8/MadGraph etc.; `transport: true` uses the geant4 image |

`gdmltp run` picks the image automatically from the `generator`; override with
`--image`. (Image repositories keep the `g4targetpractice` name until the GitHub
repository itself is renamed.)

> **Nobody compiles generators.** GENIE and Achilles are built **from source in
> CI** into dedicated base images (`docker/genie-base.Dockerfile`: Pythia6 →
> ROOT-with-Pythia6 → LHAPDF → GENIE; `docker/achilles-base.Dockerfile`),
> published by the `Build Generator Base Images` workflow as
> `…-genie-base` / `…-achilles-base`. The fast per-push app images just layer
> `gdmltp` + the drivers on top. GENIE cross-section splines are generated **on
> demand** on first use of a probe/target pair and cached in your mounted run
> directory — so a fresh image runs with zero manual setup. Override the bases
> with the repo variables `GENIE_BASE_IMAGE` / `ACHILLES_BASE_IMAGE` or each
> workflow's dispatch inputs (GENIE tag, ROOT version, Achilles ref).

## The GENIE backend (neutrino generator)

GENIE replaces Geant4's built-in (and physically thin) neutrino handling with a
proper neutrino event generator. **v1 is vertex-level**: GENIE generates the
interaction on the nucleus the GDML geometry selects (or `genie.target`), and the
output ntuple carries the full `nu_*` interaction block plus one `trk_*` row per
final-state particle. Because GENIE does not transport particles, `step_*` and
`totalEdep` are empty. The pipeline inside the GENIE image is
`gevgen → gntpc -f gst → genie2root`.

Roadmap: geometry-aware vertex sampling in the full GDML volume, and a
single-pass flux driver for large per-event beam replays.

## Generator → Geant4 transport hand-off

GENIE and Achilles model the **interaction** — the nuclear initial state, the
hard process, and the intranuclear cascade (what the struck hadrons do inside
the nucleus) — but stop at the nuclear surface: nothing is transported through
the detector. Geant4's own neutrino interaction code is, by contrast, physically
thin (it needs ~10¹² bias factors to interact at all). The right division of
labor is both: **the generator makes the vertex, Geant4 transports it**.

Set `transport: true` in the backend block:

```yaml
generator: genie          # or achilles
geometry: { gdml: gdml/liquid_argon_1m3.gdml }
beam: { particle: nu_mu, energy: {mode: mono, value: "2 GeV"} }
run: { events: 1000, seed: 1 }
genie: { tune: G18_10a_00_000, transport: true }
```

`gdmltp run` then executes two stages: (1) the generator image produces the
vertex-level events; (2) the host writes each event's final-state particles to a
**HepMC3 file** (the standard interchange, via the official `pyhepmc` library),
the Geant4 image reads it with `HepMC3::ReaderAscii` and replays each event via
`/gun/hepmcFile` (one multi-particle vertex per event, full transport through
the GDML detector), and the generator's `nu_*` interaction record + neutrino
primary are grafted onto the transported file. The final `output.root` carries **both** the
generator-quality interaction physics and the Geant4 `step_*`/`totalEdep`
transport record — analyze/display/Blender all just work.

## Biasing knobs

- **geant4**: `geant4.neutrino_bias` — Geant4's built-in neutrino cross sections
  are so small that unbiased runs record nothing; when the primary is a neutrino
  the generated macro auto-enables the stock `/physics_lists/em/Nu*` biasing
  (factor 5×10¹², as in the shipped macros). Tune with
  `{factor, cc_bias, nc_bias, nucleus_bias, detector_name}` or disable with
  `neutrino_bias: off`. (Guarded with `/control/suppressAbortion` so Geant4
  builds lacking these commands warn instead of aborting.) Prefer the `genie`
  or `achilles` backends for real neutrino physics — event generators produce an
  interaction in every event by construction, so they need no cross-section bias.
- **genie**: `genie.event_generator_list` restricts the interaction channels
  (e.g. `CC`, `CCQE`); `genie.tune` selects the model set.
- **achilles**: `achilles.processes` selects the final-state lepton channels
  (default: CC + NC); hard cuts and model options pass through
  `achilles.options`.

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
ROOT dependency** (it reads the file with `uproot`). Run via Docker with the
`gtp` wrapper from the top of this README (`gtp $GEANT4 <cmd> ...`, which runs
as you so outputs aren't root-owned) or directly if installed.

| Command | What it does |
|---|---|
| `gdmltp run` | Run a simulation from a YAML config (`--config run.yaml`; or quick flags). `--display` opens an event display after; `--field "0 0 5 tesla"` adds a field (auto-sets `CELER_DISABLE=1`). |
| `gdmltp display` | Event display from `output.root` and/or `--gdml`: a **Blender** scene (default), **PNG stills**, and **WebGL HTML**. Shows the richest event by default; pick with `--event N`, `--events A:B`, or overlay all with `--all`. Toggle outputs with `--no-blend`/`--no-png`/`--no-html`. |
| `gdmltp analyze` | Summary report + plots: primary spectrum, total Edep, depth-dose, energy leakage, secondary counts; for neutrino files also interacted/CC fractions, ⟨Q²⟩/⟨W⟩, and a Q²/W/x/y kinematics panel. |
| `gdmltp compare` | Overlay two runs: longitudinal shower profile, containment vs depth (d90/d95/d99), per-event leakage. For neutrino files it also overlays Q²/W/x/y — the cross-generator check (GENIE vs Achilles vs Geant4 on the same target). |
| `gdmltp validate` | Schema + physics sanity checks on any backend's `output.root` (branch completeness, count/energy bookkeeping, nu-block invariants like y∈[0,1], CC lepton flavor, q0=Eν−Eℓ). Exit code 0 = PASS; `--strict` also fails on warnings — CI-friendly. |
| `gdmltp info` | Inspect a `.root` (branches, events, nu block) or `.gdml` (solids, bounding box). |

**Large files**: `analyze`/`compare`/`info` stream in batches and read only the
branches they need; `display` loads only the requested events.

**GDML parsing**: geometry for the display/`info` is read with
[pyg4ometry](https://github.com/g4edge/pyg4ometry) (the standard tool —
accurate solids, transforms, and mesh bounding boxes) when it is installed
(`pip install gdmltp[geometry]`; it ships in the Geant4 image). Without it, a
built-in lightweight parser handles the common solids and falls back to a
coarse bounding box for the rest. Force either with
`GDMLTP_GDML_PARSER=pyg4ometry|lightweight`. Physics generators and the
generator→Geant4 hand-off use **HepMC3** (via `pyhepmc` / the HepMC3 library)
as the interchange format — no bespoke event formats.

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
├── docs/                    # topic guides (neutrino quickstart, BSM decay backend)
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

CI runs the unit suite across Python 3.10/3.11/3.12, builds `g4sim` and runs a
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
