# Neutrino physics quickstart

GDMLTargetPractice runs **three engines against the same GDML target through
one YAML frontend**, and every engine writes the same `output.root` schema —
so generating, validating, and comparing neutrino interactions is a
three-command workflow. This page walks the canonical study: **2 GeV νμ on
liquid argon**.

Requirements: Docker + `pip install "git+https://github.com/lawrenceleejr/G4TargetPractice"`
(the frontend is pure Python — no ROOT, no Geant4, no GENIE on your machine;
the engines run in containers that `gdmltp run` pulls automatically).

## 1. Generate: the same beam and target, three engines

```bash
# GENIE (neutrino event generator; the reference for oscillation-experiment physics)
gdmltp run --config examples/nu_argon.yaml -o genie_out

# Achilles (theory-driven lepton-nucleus generator with intranuclear cascade)
gdmltp run --config examples/nu_argon_achilles.yaml -o achilles_out

# Geant4's built-in neutrino handling (thin; kept for contrast/completeness)
gdmltp run --gdml gdml/liquid_argon_1m3.gdml --particle nu_mu \
           --energy "2 GeV" -n 1000 -o g4_out
```

The two YAML files differ only in the `generator:` line and the backend block —
beam and geometry are shared. Anything in the YAML can be overridden per run
from the command line (`--energy "5 GeV"`, `--particle nu_e`, `-n 10000`).
Particles can be given by name (`nu_mu`) or PDG id (`14`).

First GENIE run on a new probe/target pair: cross-section splines are computed
**on demand** (`gmkspl`) and cached in your run directory, so the first run is
slower and every later run reuses the cache. Restrict channels with
`genie.event_generator_list: CC` (or `CCQE`, …); pick model sets with
`genie.tune`. For Achilles, `achilles.processes` selects the final-state
lepton channels, and `achilles.cascade` toggles the intranuclear cascade.

**Why a generator at all, when Geant4 exists?** GENIE/Achilles model the
nuclear initial state, the hard process, and the intranuclear cascade — the
physics that decides what actually leaves the nucleus — but stop at the
nuclear surface. Geant4 transports particles superbly but its built-in
neutrino interactions are physically thin (they need ~10¹² cross-section bias
to interact at all; `gdmltp` auto-applies that bias for you). Use a generator
for the vertex, Geant4 for the detector — or both together (§4).

## 2. Validate every file before trusting it

```bash
gdmltp validate genie_out/output.root
gdmltp validate achilles_out/output.root --strict   # warnings also fail
```

`validate` checks the schema contract (branch completeness, per-event counts)
and physics invariants: CC/NC exclusivity, y ∈ [0, 1], Q² ≥ 0, the CC outgoing
lepton flavor against the beam neutrino, q₀ = Eν − Eℓ, and **median kinematic
closures** (y ≈ q₀/Eν, Q² ≈ 2M·q₀·x, W ≈ √(M² + 2M·q₀ − Q²)) that catch
MeV-vs-GeV unit-scaling bugs between backends immediately. Exit code 0 = PASS, so it drops straight
into scripts and CI.

## 3. Compare generators — the physics payoff

```bash
gdmltp compare genie_out/output.root achilles_out/output.root \
               --labels GENIE,Achilles -o nu_cmp
```

For neutrino files, `compare` reports interacted/CC fractions and ⟨Q²⟩/⟨W⟩
per generator, and writes `nu_cmp/nu_kinematics.png`: normalized Q²/W/x/y
overlays across interacting events. Vertex-level files carry no steps, so the
shower-profile section is skipped with a note — the kinematics overlay **is**
the comparison. `gdmltp analyze <file>` produces the same panel plus the
interaction summary for a single run.

## 4. Full detector record: generator vertex + Geant4 transport

Add `transport: true` to the backend block:

```yaml
generator: genie
geometry: { gdml: gdml/liquid_argon_1m3.gdml }
beam: { particle: nu_mu, energy: {mode: mono, value: "2 GeV"} }
run: { events: 1000, seed: 1 }
genie: { tune: G18_10a_00_000, transport: true }
```

`gdmltp run` chains the two images: the generator makes vertex-level events,
Geant4 replays each event's final-state particles (`/gun/eventFile`, one
multi-particle vertex per event) through the GDML detector, and the
generator's `nu_*` interaction record is grafted onto the transported file.
The result carries generator-quality interaction physics **and** the full
`step_*`/`totalEdep` transport record — `analyze`, `validate`, `compare`, and
the event display all just work.

## 5. Look at events

```bash
gdmltp display genie_out/output.root --gdml gdml/liquid_argon_1m3.gdml          # WebGL + PNG
gdmltp display genie_out/output.root --gdml gdml/liquid_argon_1m3.gdml --blend  # Blender scene
```

Vertex-level events (no transport) draw momentum-direction rays per
final-state particle (length ∝ √|p|), so GENIE/Achilles events are as visible
as transported ones.

## Muon collider: the neutrino slice

Muons decaying in a collider ring flood the detector with a plane-confined
ribbon of neutrinos (arXiv:2412.14115). The `mudecay_numu` / `mudecay_nue`
energy modes sample the exact muon-decay neutrino spectra (`energy: {mode:
mudecay_numu, value: "5 TeV"}` — value is the parent muon energy), and
`examples/maia/` ships a full config set aiming that flux into the MAIA
detector concept (`gdml/MAIA_v0.gdml`): all four flavor components, both
collider stages, slice phase-space painting in the tungsten nozzles, and a
fast spectrum-only variant. See `examples/maia/README.md`.

## Realistic beams

Everything above uses a pencil beam. The frontend also samples **distributions
on any beam parameter** (position, direction slopes, energy or |p|) and full
correlated **Twiss phase space** (α, β, geometric emittance in mm·mrad, dp/p)
host-side into a `beam.dat` that every backend replays per event — GENIE and
Achilles events are placed and rotated onto each sampled ray. See
`examples/twiss_muon.yaml` and `examples/gauss_beam.yaml`, and the beam section
of the main README.

## Output schema (what you analyze)

One TTree `tree`, one entry per event; units mm / MeV / ns / MeV/c. Neutrino
runs fill the `nu_*` block: `nu_isCC/isNC`, `nu_interactionProcess`
(QES/RES/DIS/COH/MEC), vertex, struck nucleus (Z, A), outgoing lepton
(PDG, E, p), and Q²/W/x/y/q₀ (Q² in MeV²). Final-state particles are `trk_*`
rows (kinetic `trk_startE`, production momenta `trk_px/py/pz`);
transported files add `step_*` and `totalEdep`. Full branch reference:
`macros/README.md`.
