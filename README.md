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
- **Propagation** — **always Geant4**. The generators below produce the
  interaction; their final state is handed to Geant4 as **HepMC3** and
  transported through the same GDML geometry, so every run's `output.root`
  carries a Geant4 transport record (`transport: false` opts out per backend).
- **Neutrinos** — use a **generator** (`genie`/`achilles`/`pythia`), never the
  bare `geant4` backend. Firing a neutrino beam at Geant4 asks a transport
  engine to do interaction physics it barely models, so both the front-end and
  the engine print a loud banner telling you to switch (`GDMLTP_NO_WARNINGS=1`
  mutes it).
- **Generator (backend)** — pick one:
  - `geant4` — full particle transport (the `g4sim` engine). *Default.*
  - `genie` — neutrino event generation on the GDML target, then Geant4 transport.
  - `achilles` — theory-driven lepton-nucleus generation ([Achilles](https://github.com/AchillesGen/Achilles)); neutrino **and** `e∓` beams, then Geant4 transport.
  - `pythia` — [Pythia 8](https://pythia.org) collisions off a **free nucleon**: TeV-scale DIS with **no cross-section splines to precompute**, plus min-bias/hard-QCD. Shower + hadronization, then Geant4 transport. *No nuclear medium/cascade — use genie/achilles for those.*
  - `decay` — long-lived **BSM projectiles** (HNLs, dark photons, ALPs), decayed **by Geant4** (`G4DecayTable`/`G4Decay`) with lifetime-importance reweighting: displaced vertex + full detector response in one stage. See [docs/bsm.md](docs/bsm.md).
  - `external` — bring **HepMC3 events from a real generator** (Pythia8, MadGraph) into the same schema/transport pipeline. See [docs/bsm.md](docs/bsm.md).
  - `fluka` (via flugg) — *planned, not yet available.*

Every backend writes the **same** `output.root` schema, so `analyze`, `display`,
`compare`, and `info` work identically no matter which engine produced the file.

**Doing neutrino physics?** Start with the
[neutrino quickstart](docs/neutrino.md): νμ on liquid argon through GENIE,
Achilles, and Geant4 — generate, validate, compare kinematics, transport, and
display in a handful of commands.

## Run it with Docker — no install, no compiling

You describe a run in a **YAML file** (a target + a beam + a backend) and run it
with `docker run`. No macros, no local build. Clone the repo (so you have the
example YAMLs and geometries) and run from its root.

```bash
git clone https://github.com/lawrenceleejr/GDMLTargetPractice && cd GDMLTargetPractice

# one image per backend (all on GHCR; :main is the released tag)
GEANT4=ghcr.io/lawrenceleejr/gdmltargetpractice:main
GENIE=ghcr.io/lawrenceleejr/gdmltargetpractice-genie:main
ACHILLES=ghcr.io/lawrenceleejr/gdmltargetpractice-achilles:main
PYTHIA=ghcr.io/lawrenceleejr/gdmltargetpractice-pythia:main

# a tiny wrapper: mounts the repo, and runs as YOU so outputs are owned by you
# (not root), with a writable HOME for in-container caches
gtp() { docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
                   -v "$PWD:/run" -w /run "$@"; }
```

**Simulate — always from a YAML, one command per run:**

```bash
# Geant4 — 150 MeV protons into a water phantom
gtp $GEANT4   run --config examples/water_proton.yaml -o out

# BSM decay — an HNL decaying in flight inside a detector (Geant4 decays AND transports)
gtp $GEANT4   run --config examples/maia/hnl_decay.yaml -o out

# GENIE — 2 GeV muon-neutrinos on liquid argon, then Geant4 through the detector.
# The GENIE image CONTAINS the Geant4 engine, so one container runs both stages.
gtp $GENIE    run --config examples/nu_argon.yaml -o out
```

Each writes `out/output.root` in one common schema, **owned by you**, always
with a Geant4 transport record. Override any field on the command line, e.g.
`gtp $GENIE run --config examples/nu_argon.yaml --energy "5 GeV" -n 2000 -o out`.

**Achilles and Pythia runs take two commands from bare Docker** — those images
carry only their generator, and a container cannot start a sibling container:
stage 1 writes the interaction as **HepMC3**, then a Geant4-carrying image
(`$GEANT4` or `$GENIE`) propagates it.

```bash
gtp $ACHILLES run --config examples/nu_argon_achilles.yaml -o out --stage generator
gtp $GEANT4   transport -o out
```

The same split works for GENIE (`--stage generator`, then `transport`) when you
want to inspect or re-transport the hand-off (`out/events.hepmc`,
`out/vertex_level.root`) between the stages.

> These commands (`--stage generator`, `transport`) need images built from this
> version of the repo — the `:main` tags are rebuilt on every push to the default
> branch, so `docker pull` first if yours are old.

> Prefer one command for the two-image backends too? Install the front-end
> (`pip install "gdmltp @ git+https://github.com/lawrenceleejr/GDMLTargetPractice"`)
> and `gdmltp run --config <config> -o out` launches the containers itself.
> And a generator-only (vertex-level) run is a deliberate choice, not the
> default: put `transport: false` in the backend block.

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

Each event becomes **one Blender object** — a single curve holding every track
(colored per particle) — so it builds fast (thousands of tracks in one
datablock) and you can select/move/parent a whole event as a unit; `--all`
gives one object for the entire overlay. Add `--animate` for the time-reveal
animation instead (one object per track, slower). Progress is printed as the
scene builds.

The `.blend` build needs Blender or Docker on the host, so it happens on the
**host** path (`gdmltp display …`, or `--image`); inside a plain `docker run`
the display writes `scene.json` + `build_blend.py` and prints the one command
to turn them into the `.blend`. `display --image $GEANT4 …` runs the whole
display in the container for you.

**Prefer your laptop?** `pip install "gdmltp @ git+https://github.com/lawrenceleejr/GDMLTargetPractice"`
installs the thin front-end (pure Python, **no ROOT**). Then `gdmltp run
--config …` launches the right container for you and handles multi-stage runs
(e.g. generator→Geant4 transport); `gdmltp display …` builds the Blender scene
directly. Add `[geometry]` for the accurate pyg4ometry GDML reader.

## The pipeline: generator → HepMC3 → Geant4 → one ntuple

Whatever produces the interaction, **Geant4 does the final propagation**:

```
GENIE ┐
Achilles ┤                                    g4sim              output.root
Pythia   ├─►  events.hepmc  ─────────────►  transport   ─────►  generator record
HepMC3 file ┘  (HepMC3 ASCII, the one     through the GDML      + step_*/totalEdep
Geant4/decay ──────────────────────────────► interchange)        in one schema
```

The generator stage writes `vertex_level.root` (its own record in the common
schema) plus **`events.hepmc`** — every final-state particle, one production
vertex per event with its position and time, written with the official HepMC3
library. `g4sim` reads it back with `HepMC3::ReaderAscii` (`/gun/hepmcFile`),
transports each event, and the generator's `nu_*` block and primary identity are
grafted onto the transported file. The `geant4` and `decay` backends are
single-stage — Geant4 is already doing everything.

This is the default for every generator; `<backend>: {transport: false}` opts a
run out and leaves it vertex-level (for generator-only cross-section/kinematics
studies). A generator run that cannot reach Geant4 fails loudly rather than
leaving an untransported file behind. The run directory keeps the whole chain —
`events.hepmc`, `gdmltp_transport.mac`, `gdmltp_transport.json`,
`vertex_level.root` — so stage 2 is re-runnable and inspectable.

### Exporting what leaves: HepMC3 out of Geant4

The interchange runs both ways. `g4sim` reads HepMC3 (`/gun/hepmcFile`) and can
also **write** the particles *leaving* a volume — a scoring-plane / phase-space
file — so one run can feed the next stage, or any downstream tool that speaks
HepMC3:

```yaml
geant4:
  exit_hepmc: exit.hepmc        # enables the export
  exit_volume: WaterPhantom_vol # default World = everything that escapes
  exit_min_ke: "1 MeV"          # skip soft crossings (a shower exit is mostly them)
  exit_kill: true               # stop tracks at the surface (staged runs)
```

Then replay it as the primaries of the next run — different geometry, different
physics list, whatever the stage needs:

```bash
gtp $GEANT4 run --config stage1.yaml -o stage1     # writes stage1/exit.hepmc
# stage 2: a macro with /gun/hepmcFile stage1/exit.hepmc, or external backend
```

One `GenEvent` per event, one vertex **per crossing** at the point and time that
particle crossed (they are not all the same place, and the reader honours each
particle's own vertex), the primary as an incoming status-4 leg for provenance,
and the source volume as an event attribute. `exit_kill` matters for staging: it
stops the track at the surface so the next stage, which continues from there,
does not double count.

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
| `geant4` | `ghcr.io/lawrenceleejr/gdmltargetpractice` | full transport |
| `genie` | `…-genie` (built **on top of** the geant4 image — both engines aboard) | neutrino vertices + Geant4 transport, one container |
| `achilles` | `…-achilles` **+ the geant4 image** | ν / e∓ vertices, then Geant4 transport |
| `pythia` | `…-pythia` **+ the geant4 image** | Pythia 8 free-nucleon collisions (TeV DIS, no splines), then Geant4 transport |
| `decay` | the geant4 image | BSM decay-in-flight **by Geant4** (G4DecayTable + G4Decay), one stage incl. transport |
| `external` | host conversion **+ the geant4 image** | HepMC3 events from Pythia8/MadGraph etc., then Geant4 transport |

`gdmltp run` picks the image automatically from the `generator`; override with
`--image`. (Image repositories follow the GitHub repository name, so they moved
from `g4targetpractice*` to `gdmltargetpractice*` with the rename.)

> **Nobody compiles generators.** GENIE, Achilles and Pythia 8 are built **from source in
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
proper neutrino event generator. GENIE generates the interaction on the nucleus
the GDML geometry selects (or `genie.target`), and the output ntuple carries the
full `nu_*` interaction block plus one `trk_*` row per final-state particle. The
pipeline inside the GENIE image is `gevgen → gntpc -f gst → genie2root`; the
final state then goes to **Geant4** through the hand-off below, which is what
fills `step_*`/`totalEdep` (GENIE itself transports nothing). With
`genie: {transport: false}` the run stops at the vertex level and those branches
stay empty.

Roadmap: geometry-aware vertex sampling in the full GDML volume, and a
single-pass flux driver for large per-event beam replays.

## Generator → Geant4 transport hand-off

GENIE and Achilles model the **interaction** — the nuclear initial state, the
hard process, and the intranuclear cascade (what the struck hadrons do inside
the nucleus) — but stop at the nuclear surface: nothing is transported through
the detector. Geant4's own neutrino interaction code is, by contrast, physically
thin (it needs ~10¹² bias factors to interact at all). The right division of
labor is both: **the generator makes the vertex, Geant4 transports it**.

This happens **by default** — nothing in the YAML asks for it:

```yaml
generator: genie          # or achilles, pythia, external
geometry: { gdml: gdml/liquid_argon_1m3.gdml }
beam: { particle: nu_mu, energy: {mode: mono, value: "2 GeV"} }
run: { events: 1000, seed: 1 }
genie: { tune: G18_10a_00_000 }
```

Two stages, always: (1) the generator image produces the interaction and its
final state is exported to **`events.hepmc`** (HepMC3 ASCII, via the official
`pyhepmc` library — the one interchange every backend uses); (2) the Geant4
image reads it with `HepMC3::ReaderAscii` and replays each event via
`/gun/hepmcFile` (one multi-particle vertex per event, at its vertex position
and time, full transport through the GDML detector), then the generator's `nu_*`
interaction record + primary identity are grafted onto the transported file.
`output.root` carries **both** the generator-quality interaction physics and the
Geant4 `step_*`/`totalEdep` transport record — analyze/display/Blender all just
work.

For **GENIE** both stages run in its one image (it is built on top of the
Geant4 image), so a bare `docker run $GENIE run --config … -o out` finishes the
whole pipeline. For **Achilles/Pythia** — generator-only images — it is two
commands, and the run directory holds the whole chain between them:

```bash
gtp $ACHILLES run --config examples/nu_argon_achilles.yaml -o out --stage generator
#   -> out/vertex_level.root, out/events.hepmc, out/gdmltp_transport.{mac,json}
gtp $GEANT4   transport -o out
#   -> out/output.root  (Geant4 transport + the interaction record)
```

Ask an image with no Geant4 engine for the full run and it stops with an error
naming that second command: a result that never reached Geant4 is a failure,
not a quiet half-result. `<backend>: {transport: false}` is how you *choose* a
vertex-level run; `gdmltp transport -o out` can also be re-run on its own
(different field, different seed) without regenerating the events.

## Biasing knobs

- **geant4**: a neutrino beam here prints an unmissable warning banner (from
  `gdmltp run` *and* from g4sim itself, so a raw `docker run <image> my.mac`
  gets it too) recommending `genie`/`achilles`/`pythia`; mute it with
  `GDMLTP_NO_WARNINGS=1` when the Geant4-only run is deliberate
  (`examples/maia/nu_slice_geant4_biased.yaml` is exactly that case).
  `geant4.neutrino_bias` — Geant4's built-in neutrino cross sections
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

**Same display pipeline for every backend.** The generator converters also fill
optional per-track momentum branches (`trk_px/py/pz`) — that is what the Geant4
hand-off exports to HepMC3, and what lets the event display draw
momentum-direction rays (length ∝ √|p|) for a `transport: false` run, whose
tracks were never propagated. `gdmltp display output.root --gdml my.gdml [--blend]`
therefore works identically on Geant4, GENIE, and Achilles output — including the
animated Blender export.

## Output

Each run writes `output.root` (**a classic ROOT TTree** named `tree`, one entry
per event) with **event scalars**, **per-track vectors** `trk_*`, **per-step
vectors** `step_*`, and — for neutrino runs — a `nu_*` interaction block (CC/NC,
vertex, struck nucleus, outgoing lepton, Q²/W/x/y). Units are Geant4-internal:
**mm, MeV, ns, MeV/c**. See `macros/README.md` for the full branch reference.

**Always a TTree, never an RNTuple.** `root output.root` and RDataFrame open
every file this project writes, whichever engine produced it. (uproot ≥ 5.7
writes an RNTuple for the natural `f["tree"] = data` spelling — readable by
uproot, but `Unknown class ROOT::RNTuple` in ROOT — so the Python writers go
through `gdmltp.io.write_tree`, which uses `mktree`. CI opens the output with
real ROOT to keep it that way.)

**Process names.** uproot cannot write `std::vector<std::string>` into a TTree,
so in files written on the Python side (generator vertex records and the merged
generator+transport output) `trk_creatorProcess` and `step_process` hold **int32
codes**, with a small `gdmltp_strings` legend tree in the same file mapping
(branch, code) → name. Files written by g4sim keep real strings. Either way
`gdmltp` decodes transparently — `io.read_string_branch(path, name)` and
`io.load_events` return names — and from ROOT you read the codes plus the
legend:

```cpp
root output.root
tree->Scan("trk_creatorProcess")        // codes
gdmltp_strings->Scan("branch:code:value")   // what they mean
```

## Analysis & Event Display

The `gdmltp` tool turns `output.root` into plots and 3D visualizations with **no
ROOT dependency** (it reads the file with `uproot`). Run via Docker with the
`gtp` wrapper from the top of this README (`gtp $GEANT4 <cmd> ...`, which runs
as you so outputs aren't root-owned) or directly if installed.

| Command | What it does |
|---|---|
| `gdmltp run` | Run a simulation from a YAML config (`--config run.yaml`; or quick flags). `--display` opens an event display after; `--field "0 0 5 tesla"` adds a field (auto-sets `CELER_DISABLE=1`). |
| `gdmltp transport` | The **Geant4 stage** of a generator run: replays `events.hepmc` through the GDML geometry and merges the generator's interaction record in. `gdmltp run` does it automatically; run it by hand to finish, in the Geant4 image, a run a generator image started. |
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
└── .github/                 # CI: workflows/, plus ci/ + scripts/ for the docker-run tests
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

**Docker-run tests.** After each image is published, CI runs it the way this
README does — `docker run <image> run --config <yaml>`, then `validate` and
`analyze` — and plots the resulting ntuple, keeping the plots + reports as job
artifacts:

| Job | What it runs |
|---|---|
| `docker-run-geant4` (Build, Test, Deploy) | pure Geant4: `examples/water_proton.yaml` on the image just pushed |
| `docker-run-genie-geant4` (Build GENIE Image) | the two-stage hand-off: GENIE vertex + Geant4 transport (`.github/ci/nu_water_transport.yaml`), driven by the front-end chaining both images |

Plots come from `.github/scripts/ci_ntuple_plots.py`, which reads `output.root`
with uproot only (no `gdmltp` import) so it checks the shipped image's ntuple
independently of the library that wrote it.

## Building from source (Geant4)

Requires Geant4 ≥ 11 with GDML support and ROOT:

```bash
mkdir build && cd build
cmake ../g4sim/ && cmake --build .
./g4sim ../g4sim/run_ci.mac        # or your own macro
```

Docker images are built from the checked-in `docker/geant4.Dockerfile` (and
`docker/geant4-celeritas.Dockerfile`, `docker/genie.Dockerfile`).

**Pinning images.** `gdmltp run --image IMG` sets the image of the *first*
stage. To pin every stage — including the Geant4 transport stage of a two-stage
two-stage generator run — set `GDMLTP_IMAGE_GEANT4` / `GDMLTP_IMAGE_GENIE` /
`GDMLTP_IMAGE_ACHILLES` / `GDMLTP_IMAGE_PYTHIA`:

```bash
export GDMLTP_IMAGE_GEANT4=ghcr.io/lawrenceleejr/gdmltargetpractice:my-branch
gdmltp run --config examples/nu_argon_nubig_g1802a.yaml -o out   # both stages pinned
```

That is how the docker-run CI jobs test a freshly built image pair instead of
the published `:main` defaults.

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
