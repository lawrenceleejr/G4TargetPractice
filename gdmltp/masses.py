"""PDG code -> rest mass in MeV.

GENIE reports total energies (GeV); the g4sim schema stores *kinetic* energy
(MeV), so the GENIE->schema converter subtracts the rest mass. A compact table
covers the particles that show up in neutrino final states; nuclei (ion PDG
codes 10LZZZAAAI) fall back to A * atomic-mass-unit, which is accurate to the
~MeV level -- fine for the vertex-level kinematics recorded here.
"""

ATOMIC_MASS_UNIT_MEV = 931.49410242

# Rest masses in MeV (PDG values, rounded to the eV where it matters).
_MASS_MEV = {
    22: 0.0,          # gamma
    11: 0.51099895,   # e-
    -11: 0.51099895,  # e+
    13: 105.6583755,  # mu-
    -13: 105.6583755, # mu+
    15: 1776.86,      # tau-
    -15: 1776.86,     # tau+
    12: 0.0, -12: 0.0, 14: 0.0, -14: 0.0, 16: 0.0, -16: 0.0,  # neutrinos
    111: 134.9768,    # pi0
    211: 139.57039,   # pi+
    -211: 139.57039,  # pi-
    221: 547.862,     # eta
    311: 497.611,     # K0
    321: 493.677,     # K+
    -321: 493.677,    # K-
    130: 497.611,     # K0L
    310: 497.611,     # K0S
    2112: 939.5654205,  # neutron
    2212: 938.2720882,  # proton
    -2212: 938.2720882, # antiproton
    -2112: 939.5654205, # antineutron
    3122: 1115.683,   # Lambda
    3222: 1189.37,    # Sigma+
    3112: 1197.449,   # Sigma-
    3322: 1314.86,    # Xi0
    3312: 1321.71,    # Xi-
}


def mass_mev(pdg) -> float:
    """Rest mass in MeV for a PDG code. Nuclei use A * u; unknowns return 0."""
    pdg = int(pdg)
    if pdg in _MASS_MEV:
        return _MASS_MEV[pdg]
    if abs(pdg) > 1_000_000_000:  # ion code 10LZZZAAAI
        a = (abs(pdg) // 10) % 1000
        return a * ATOMIC_MASS_UNIT_MEV
    return 0.0


def kinetic_mev(pdg, total_e_mev) -> float:
    """Kinetic energy = total - rest mass, clamped at 0 (guards rounding)."""
    return max(0.0, float(total_e_mev) - mass_mev(pdg))
