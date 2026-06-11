# Macro Files

This directory contains example Geant4 macro files that demonstrate how to
shoot beams of different particles at the simple detector geometries included
in the repository.

## Available GDML geometries

| File | Description |
|---|---|
| `gdml/silicon_slab_1mm.gdml` | 10×10 cm silicon slab, 1 mm thick, in a 10 cm air box |
| `gdml/liquid_argon_1m3.gdml` | 1 m³ liquid-argon cube in a 2 m³ air box |
| `gdml/water_phantom_30cm.gdml` | 30×30 cm water tank, 40 cm deep, entrance face at z = 0 |
| `gdml/tissue_phantom_layered.gdml` | Layered soft-tissue/bone/lung phantom (chest-wall analogue), entrance face at z = 0 |

## Macro overview

### Electron beams on the silicon slab

| Macro | Particle | Energy distribution |
|---|---|---|
| `electrons_silicon_mono.mac` | `e-` | Monoenergetic – 1 GeV |
| `electrons_silicon_gauss.mac` | `e-` | Gaussian – mean 1 GeV, σ = 200 MeV |
| `electrons_silicon_exp.mac` | `e-` | Exponential – E₀ = 1 GeV, sampled 100 MeV–5 GeV |
| `electrons_silicon_arb.mac` | `e-` | Arbitrary histogram (user-defined weights) |

### Neutrino beams on the liquid-argon target

| Macro | Particle | Energy distribution |
|---|---|---|
| `neutrinos_lar_mono.mac` | `nu_mu` | Monoenergetic – 2 GeV |
| `neutrinos_lar_gauss.mac` | `nu_mu` | Gaussian – mean 3 GeV, σ = 500 MeV |
| `neutrinos_lar_exp.mac` | `nu_mu` | Exponential – E₀ = 2 GeV, sampled 200 MeV–20 GeV |
| `neutrinos_lar_arb.mac` | `nu_mu` | Arbitrary histogram (accelerator-flux-like weights) |
| `electron_neutrinos_lar_mono.mac` | `nu_e` | Monoenergetic – 1 GeV |

### Medical physics examples

These macros shoot therapy-like beams at the water and layered-tissue
phantoms. Both phantoms have their entrance face at z = 0, so depth in the
phantom equals z and a depth-dose curve can be made directly from the
step-level branches of `output.root` (positions are in mm, energy deposits
in MeV), e.g. in ROOT:

```cpp
tree->Draw("step_preZ>>h(200,0,400)", "step_edep");
```

| Macro | Particle | Beam | Physics illustrated |
|---|---|---|---|
| `protons_water_bragg.mac` | `proton` | 150 MeV mono | Pristine Bragg peak at ~15.6 cm depth |
| `protons_water_sobp.mac` | `proton` | 110–150 MeV weighted bins | Crude spread-out Bragg peak (range modulation) |
| `electrons_water_20MeV.mac` | `e-` | 20 MeV mono | Electron build-up and ~10 cm practical range |
| `photons_water_6MV.mac` | `gamma` | exp spectrum, E₀ = 2 MeV, 0.25–6 MeV | 6 MV-like depth dose with ~1.5 cm build-up |
| `photons_water_co60.mac` | `gamma` | 1.17 + 1.33 MeV lines | Co-60 teletherapy beam |
| `photons_tissue_6MV.mac` | `gamma` | exp spectrum, E₀ = 2 MeV, 0.25–6 MeV | Heterogeneity effects in bone and lung |

All beams are pencil beams along +z starting at z = -20 cm. Note that if
you run with a Celeritas-enabled build (see the main README), offloaded
`e-`/`e+`/`gamma` tracks do not appear in the step-level output — for dose
studies use the standard image or set `CELER_DISABLE=1`.

## How to run a macro

From the build directory run the simulation executable with the `-m` flag:

```bash
./g4sim -m /path/to/macros/electrons_silicon_mono.mac
```

The geometry path in each macro is relative to the directory from which the
executable is launched, so run from the repository root or adjust the
`/detector/readGDML` path accordingly.

## Gun commands reference

The following `/gun/` commands are available for configuring the primary
particle source:

| Command | Argument(s) | Description |
|---|---|---|
| `/gun/particle` | name | Particle type (e.g. `e-`, `nu_mu`, `nu_e`) |
| `/gun/energy` | value unit | Nominal energy (mean for `gauss`, E₀ for `exp`) |
| `/gun/position` | x y z unit | Start position of the particle |
| `/gun/direction` | x y z | Beam direction (unit vector). Use `0 0 0` for isotropic 4π. |
| `/gun/energyMode` | `mono`\|`gauss`\|`exp`\|`arb` | Energy sampling mode |
| `/gun/gaussSigma` | value unit | σ for Gaussian mode |
| `/gun/energyMin` | value unit | Lower energy bound for `exp` and `arb` modes |
| `/gun/energyMax` | value unit | Upper energy bound for `exp` mode |
| `/gun/addEnergyBin` | energy unit weight | Add a bin to the arbitrary histogram |
| `/gun/clearEnergyBins` | _(none)_ | Clear all histogram bins |

### Energy modes explained

- **`mono`** – every event fires at exactly `/gun/energy`.
- **`gauss`** – energies are drawn from a Gaussian with mean `/gun/energy` and
  sigma `/gun/gaussSigma`. Non-positive values are rejected and resampled.
- **`exp`** – energies are drawn from an exponential PDF
  *f(E) ∝ exp(−E/E₀)* where *E₀* = `/gun/energy`, sampled in the interval
  [`/gun/energyMin`, `/gun/energyMax`] using the exact inverse-CDF method.
- **`arb`** – a discrete histogram defined by one or more `/gun/addEnergyBin`
  calls. Each bin carries a representative energy and a relative weight; the
  generator picks a bin according to the weights and fires at that energy.

### Adding custom bins for the `arb` mode

```
/gun/clearEnergyBins
/gun/addEnergyBin  500 MeV 1.0
/gun/addEnergyBin    1 GeV 3.0
/gun/addEnergyBin    5 GeV 1.5
```

Weights are normalised automatically; they represent relative probabilities.
