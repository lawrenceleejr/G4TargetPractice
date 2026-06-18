"""PDG code -> (name, hex color). Shared by every emitter so legends match."""

# Common particles with HEP-ish color conventions.
_PARTICLES = {
    22: ("gamma", "#ffd700"),
    11: ("e-", "#1f77b4"),
    -11: ("e+", "#9467bd"),
    13: ("mu-", "#d62728"),
    -13: ("mu+", "#ff7f0e"),
    15: ("tau-", "#8c564b"),
    -15: ("tau+", "#c49c94"),
    2212: ("proton", "#2ca02c"),
    -2212: ("antiproton", "#98df8a"),
    2112: ("neutron", "#7f7f7f"),
    211: ("pi+", "#e377c2"),
    -211: ("pi-", "#bcbd22"),
    111: ("pi0", "#17becf"),
    321: ("K+", "#aec7e8"),
    -321: ("K-", "#ffbb78"),
    311: ("K0", "#c5b0d5"),
    130: ("K0L", "#dbdb8d"),
    310: ("K0S", "#9edae5"),
    1000020040: ("alpha", "#8c564b"),
    12: ("nu_e", "#cccccc"),
    -12: ("anti_nu_e", "#cccccc"),
    14: ("nu_mu", "#bbbbbb"),
    -14: ("anti_nu_mu", "#bbbbbb"),
    16: ("nu_tau", "#aaaaaa"),
    -16: ("anti_nu_tau", "#aaaaaa"),
}

_FALLBACK_COLOR = "#888888"


def _decode_ion(pdg):
    """Geant4/PDG ion code 10LZZZAAAI -> 'ion(Z,A)' or None."""
    if pdg > 1_000_000_000:
        z = (pdg // 10000) % 1000
        a = (pdg // 10) % 1000
        return f"ion(Z={z},A={a})"
    return None


def name_for(pdg):
    pdg = int(pdg)
    if pdg in _PARTICLES:
        return _PARTICLES[pdg][0]
    ion = _decode_ion(pdg)
    if ion:
        return ion
    return f"pdg{pdg}"


def color_for(pdg):
    pdg = int(pdg)
    if pdg in _PARTICLES:
        return _PARTICLES[pdg][1]
    if pdg > 1_000_000_000:
        return "#b5651d"  # ions
    return _FALLBACK_COLOR
