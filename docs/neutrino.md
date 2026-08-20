# Neutrino physics quickstart

GDMLTargetPractice runs **four engines against the same GDML target through
one YAML frontend**, and every engine writes the same `output.root` schema —
so generating, validating, and comparing neutrino interactions is a
three-command workflow. This page walks the canonical study: **2 GeV νμ on
liquid argon**.

Requirements: Docker + `pip install "git+https://github.com/lawrenceleejr/GDMLTargetPractice"`
(the frontend is pure Python — no ROOT, no Geant4, no GENIE on your machine;
the engines run in containers that `gdmltp run` pulls automatically).

## 1. Generate: the same beam and target, four engines

```bash
# GENIE (neutrino event generator; the reference for oscillation-experiment physics)
gdmltp run --config examples/nu_argon.yaml -o genie_out

# Achilles (theory-driven lepton-nucleus generator with intranuclear cascade)
gdmltp run --config examples/nu_argon_achilles.yaml -o achilles_out

# Pythia 8 (high-energy DIS off a free nucleon; no cross-section splines needed)
gdmltp run --config examples/nu_argon_pythia.yaml -o pythia_out

# Geant4's built-in neutrino handling (thin; kept for contrast/completeness)
gdmltp run --gdml gdml/liquid_argon_1m3.gdml --particle nu_mu \
           --energy "2 GeV" -n 1000 -o g4_out
```

These YAML files differ only in the `generator:` line and the backend block —
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
Geant4 replays each event's final-state particles (`/gun/hepmcFile`, one
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

## TeV energies: the HEDIS tune

The standard `G18_10a` tune's DIS model and cross-section splines top out
around ~1 TeV — `gmkspl` refuses to build splines above the tune's validity,
so the 5 TeV muon-collider slice (`nu_slice_numu.yaml`) can't make splines
with it. For multi-TeV you must switch tune **families** to GENIE's
high-energy DIS (HEDIS): `examples/maia/nu_slice_numu_hedis.yaml` uses
`GHE19_00a_00_000` (the BGR18 NLO model, valid to ~10⁹ GeV) with
`event_generator_list: HEDIS`. The driver builds the HEDIS structure-function
tables (`gmkhedissf`) and passes `--event-generator-list HEDIS` to both the
spline build and generation automatically.

**HEDIS is not out-of-the-box** — it needs a HEDIS-provisioned GENIE image:
GENIE built with APFEL (for the NLO structure functions), the tune's LHAPDF
grid (`NNPDF31sx_nlo_as_0118_LHCb_nf_6`), and the structure-function tables.
Build one with the base-image workflow's `enable_hedis: 1` dispatch input (or
`docker build -f docker/genie-base.Dockerfile --build-arg ENABLE_HEDIS=1 …`);
the default GENIE image does not include APFEL and will fail at the
`gmkhedissf` step with a clear error. (`GHE19_00c_00_000` is a LO variant that
needs no APFEL, only the `cteq6` grid — a lighter alternative.)

### The HEDIS cross-section splines are the expensive part

The image bakes the structure-function tables **and** the xsec spline for the
reference configuration (νμ on W-184 to 5 TeV), so the shipped MAIA HEDIS
example needs no spline build. Any *other* probe/target/energy still calls
`gmkspl`, and at TeV energies on a heavy nucleus that is genuinely slow:
measured here, a coarse 500 GeV free-proton spline took ~80 minutes. This is
inherent to high-energy DIS, not a quirk of this tool — FASER, doing the same
νμ-on-W-184 physics, states plainly that "the default GENIE doesn't have the
cross section splines above 100 GeV. The cross section splines should be
calculated in advance", and generates them on a batch farm with
`gmkspl -p 14 -t 1000741840 -n 200 -e 10000`.

Your options, best first:

1. **Point at a spline you already have.** `genie.cross_sections: /path/to/gxspl.xml`
   in the YAML is honored verbatim. If you have CVMFS, the HEDIS splines are
   published there and work directly:
   ```yaml
   genie:
     cross_sections: /cvmfs/fermilab.opensciencegrid.org/products/genie/externals/pochoarus-genie_he_data/splines/GHE19_00a_00_000.xml
   ```
   (mount `/cvmfs` into the container with `--docker-arg` / your runner's
   equivalent). There is **no public HTTP download** of these files — the
   `GENIE-HEDIS` fork that once shipped XML/ROOT tables is gone and
   `tunes.genie-mc.org` is offline, so CVMFS is the only pre-computed source.
2. **Use the baked one.** The HEDIS base image **already ships** the spline for
   νμ(+ν̄μ) on **W-184 up to 5 TeV** (`GHE19_00c` / HEDIS) in `$HEDIS_XSEC_DIR`,
   and the driver finds it automatically — so
   `examples/maia/nu_slice_numu_hedis.yaml` starts generating immediately.
   Verified: `gevgen` runs straight off it with no metafile mismatch. Other
   probe/target/energy combinations fall back to on-demand generation. To bake a
   different one, `--build-arg HEDIS_XSEC_URL=<url>` fetches a spline you host,
   or adjust `HEDIS_XSEC_{PROBE,TARGET,EMAX,KNOTS}` in
   `docker/genie-base.Dockerfile`.
3. **Let it build on demand** (`cross_sections: auto`, the default) for any
   combination that is not baked. Slow once (hours for a heavy nucleus at TeV),
   then cached in the run directory.

### Other TeV-scale options

HEDIS is not the only way to get TeV DIS. **Pythia 8 is wired up as a first-class
backend** precisely because it needs no splines — see below. For reference,
**CSMS**, **BGR18** (the model behind GHE19), **CTW** and **GQRS** are
cross-section calculations only, with no final states; **Sherpa** and **Herwig**
can do νN DIS but bring no nuclear/FSI modeling and are not integrated here;
**NEUT**, **NuWro** and **Achilles** are accelerator/GeV-scale and are not valid
at TeV.

## Pythia 8: TeV DIS with no spline cost, handed to Geant4

The `pythia` backend generates the collision with Pythia 8 (full parton shower +
hadronization) and hands every final-state particle to Geant4 for transport:

```yaml
generator: pythia
geometry: {gdml: gdml/MAIA_v0.gdml}
beam:
  particle: nu_mu
  energy: {mode: mudecay_numu, value: "5 TeV"}
pythia:
  process: dis             # weak-boson exchange: CC (W) + NC (gamma*/Z)
  target: 1000741840       # W-184 -> reduced to its majority nucleon
  transport: true          # Geant4 transports the final state through the GDML
```

`examples/nu_argon_pythia.yaml` (simple) and
`examples/maia/nu_slice_pythia.yaml` (the TeV MAIA slice) are ready to run.

**Why reach for it.** No cross-section splines: where the HEDIS route spends
hours in `gmkspl` before the first event, Pythia starts generating immediately,
at any energy. The image is correspondingly cheap to build (Pythia 8 + HepMC3
compile in minutes, versus hours for the GENIE base).

**What you give up — state this in any writeup.** Pythia collides the beam with a
single **free nucleon**: no nuclear medium, no Fermi motion, no intranuclear
cascade, and no nuclear A-scaling of the rate. A nuclear target from the GDML is
reduced to its majority nucleon (W-184 → a neutron). When nuclear effects
matter, use `genie` (HEDIS at TeV) or `achilles` (GeV, with a cascade).

**Knobs.** `process:` selects a preset — `dis` (weak-boson exchange), `softqcd`
(inelastic minimum bias), `hardqcd` (2→2 jets, with `pt_min`), or `none`.
`q2_min` sets the DIS phase-space cut. Raw `settings:` are appended to the
generated card **after** the preset, so they override anything it set:

```yaml
pythia:
  process: dis
  settings: ["PDF:pSet = 8", "PartonLevel:MPI = off"]
```

For total control, `cmnd: my_card.cmnd` supplies a verbatim Pythia command file
and the presets are bypassed entirely. Card grammar is release-sensitive; the
rendered card is checked by the unit tests and exercised for real by the
(non-gating) pythia CI smoke, which runs a generation and asserts the resulting
`output.root`.

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
