# Macro Files

This directory contains example Geant4 macro files that demonstrate how to
shoot beams of different particles at the simple detector geometries included
in the repository.

## Available GDML geometries

| File | Description |
|---|---|
| `gdml/silicon_slab_1mm.gdml` | 10×10 cm silicon slab, 1 mm thick, in a 10 cm air box |
| `gdml/silicon_3layer_300um.gdml` | Three 4×4 cm silicon sheets, each 300 µm thick, separated by 300 µm air gaps |
| `gdml/liquid_argon_1m3.gdml` | 1 m³ liquid-argon cube in a 2 m³ air box |

## Macro overview

### Electron beams on the silicon slab

| Macro | Particle | Energy distribution |
|---|---|---|
| `electrons_silicon_mono.mac` | `e-` | Monoenergetic – 1 GeV |
| `electrons_silicon_gauss.mac` | `e-` | Gaussian – mean 1 GeV, σ = 200 MeV |
| `electrons_silicon_exp.mac` | `e-` | Exponential – E₀ = 1 GeV, sampled 100 MeV–5 GeV |
| `electrons_silicon_arb.mac` | `e-` | Arbitrary histogram (user-defined weights) |

### Beta decay through the three-layer silicon stack

| Macro | Particle | Energy distribution |
|---|---|---|
| `beta_silicon_3layer.mac` | `e-` | Beta spectrum (Y-90, 2.28 MeV endpoint, allowed shape) |

This example fires beta-decay electrons at `gdml/silicon_3layer_300um.gdml`
(three 300 µm Si sheets, 300 µm gaps) and is set up to answer *what fraction of
the betas punch all the way through the stack*. The continuous beta spectrum is
reproduced with the `arb` energy mode (a weighted histogram of `e-` energies
sampling `N(E) ∝ p·E_tot·(E₀−E)²`).

After running, compute the through-fraction with the bundled Python script:

```bash
python3 macros/transmission_fraction.py output.root
```

It uses `uproot` if installed (`pip install uproot awkward numpy`), otherwise
falls back to PyROOT (already present in the Docker image, e.g.
`docker run ... ghcr.io/lawrenceleejr/g4targetpractice:main python3 macros/transmission_fraction.py output.root`).
A primary is counted as "through" when it reaches the back face of the third
sheet (z > +0.750 mm), recorded per event as `finalZ` in the output tree.

### Neutrino beams on the liquid-argon target

| Macro | Particle | Energy distribution |
|---|---|---|
| `neutrinos_lar_mono.mac` | `nu_mu` | Monoenergetic – 2 GeV |
| `neutrinos_lar_gauss.mac` | `nu_mu` | Gaussian – mean 3 GeV, σ = 500 MeV |
| `neutrinos_lar_exp.mac` | `nu_mu` | Exponential – E₀ = 2 GeV, sampled 200 MeV–20 GeV |
| `neutrinos_lar_arb.mac` | `nu_mu` | Arbitrary histogram (accelerator-flux-like weights) |
| `electron_neutrinos_lar_mono.mac` | `nu_e` | Monoenergetic – 1 GeV |

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
