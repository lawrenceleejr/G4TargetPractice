#!/usr/bin/env python3
"""
transmission_fraction.py

Compute the fraction of primary beta electrons that punch all the way through
the three-sheet silicon stack defined in gdml/silicon_3layer_300um.gdml.

A primary (trackID == 1, parentID == 0) is counted as "through" if it reaches
the far side of the third sheet, i.e. its trajectory crosses z = +0.750 mm
(the back face of layer 3).

Two equivalent estimators are reported:
  1. finalZ           -- the primary's final position (simple, robust for a
                         forward beam: a punched-through e- ends downstream).
  2. max primary step -- the largest post-step z reached by the primary track
                         (robust even against rare back-scatter).

The script reads the ROOT tree written by g4sim. It uses `uproot` if it is
installed (pip install uproot awkward numpy); otherwise it falls back to
PyROOT, which is available inside the prebuilt Docker image.

Usage:
    python3 macros/transmission_fraction.py [output.root] [--zback 0.750]

    # inside the container (PyROOT is already present):
    docker run --rm -it --init -v $PWD:/run/ -w /run/ \
        ghcr.io/lawrenceleejr/g4targetpractice:main \
        python3 macros/transmission_fraction.py output.root
"""

import argparse
import math
import sys


def binom_err(p, n):
    """Binomial (statistical) uncertainty on a fraction p from n trials."""
    return math.sqrt(p * (1.0 - p) / n) if n else 0.0


def report(label, n_through, n_total):
    p = n_through / n_total if n_total else 0.0
    print(f"  {label:<24} {n_through:>8d} / {n_total:<8d}"
          f"  =  {p:.4f} +/- {binom_err(p, n_total):.4f}  ({100.0 * p:.2f}%)")


def analyze_uproot(filename, zback):
    """Vectorised read with uproot + awkward + numpy."""
    import uproot
    import numpy as np
    import awkward as ak

    with uproot.open(filename) as f:
        tree = f["tree"]
        finalZ = tree["finalZ"].array(library="np")
        track_id = tree["step_trackID"].array()
        post_z = tree["step_postZ"].array()

    n_total = len(finalZ)

    # Estimator 1: primary's final z position.
    n_final = int(np.count_nonzero(finalZ > zback))

    # Estimator 2: largest post-step z reached by the primary track (id == 1).
    primary_z = ak.where(track_id == 1, post_z, -np.inf)
    z_max = ak.fill_none(ak.max(primary_z, axis=1), -np.inf)  # empty -> -inf
    n_step = int(np.count_nonzero(ak.to_numpy(z_max) > zback))

    return n_total, n_final, n_step


def analyze_pyroot(filename, zback):
    """Entry-by-entry read with PyROOT (no extra pip packages needed)."""
    import ROOT

    f = ROOT.TFile.Open(filename)
    if not f or f.IsZombie():
        sys.exit(f"ERROR: could not open {filename}")
    tree = f.Get("tree")
    if not tree:
        sys.exit(f"ERROR: TTree 'tree' not found in {filename}")

    n_total = 0
    n_final = 0
    n_step = 0
    for ev in tree:
        n_total += 1

        if ev.finalZ > zback:
            n_final += 1

        z_max = -1e30
        post_z = ev.step_postZ
        track_id = ev.step_trackID
        for s in range(len(post_z)):
            if track_id[s] == 1 and post_z[s] > z_max:
                z_max = post_z[s]
        if z_max > zback:
            n_step += 1

    f.Close()
    return n_total, n_final, n_step


def main():
    ap = argparse.ArgumentParser(
        description="Fraction of beta electrons that punch through the "
                    "3 x 300 um silicon stack.")
    ap.add_argument("filename", nargs="?", default="output.root",
                    help="g4sim ROOT output file (default: output.root)")
    ap.add_argument("--zback", type=float, default=0.750,
                    help="z of the back face of layer 3, in mm "
                         "(default: 0.750)")
    args = ap.parse_args()

    try:
        import uproot  # noqa: F401
        backend = "uproot"
        n_total, n_final, n_step = analyze_uproot(args.filename, args.zback)
    except ImportError:
        try:
            import ROOT  # noqa: F401
            backend = "PyROOT"
            n_total, n_final, n_step = analyze_pyroot(args.filename, args.zback)
        except ImportError:
            sys.exit("ERROR: need either 'uproot' (pip install uproot awkward "
                     "numpy) or PyROOT (run inside the g4sim container).")

    line = "=" * 74
    print(f"\n{line}")
    print(f"Beta transmission through 3 x 300 um Si  (through = z > "
          f"{args.zback:.3f} mm)   [{backend}]")
    print(line)
    report("by finalZ:", n_final, n_total)
    report("by max primary step:", n_step, n_total)
    print(line + "\n")


if __name__ == "__main__":
    main()
