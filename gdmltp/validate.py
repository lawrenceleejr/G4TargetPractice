"""Physics + schema validation of an output.root, from any backend.

`gdmltp validate output.root` checks that a file honors the schema contract and
basic physics invariants, so users can trust a file before analyzing it and
catch converter/generator misconfigurations early. Checks are graded:

  FAIL -- the file violates the schema or an exact invariant (bug somewhere)
  WARN -- physically suspicious but not impossible (e.g. Bjorken x > 1 from
          Fermi motion, totalEdep above primaryE from exothermic capture)
  ok   -- check passed

Exit code is 0 when nothing FAILs (use --strict to also fail on warnings).
"""
from pathlib import Path

import numpy as np

from . import io

# Tolerances
_REL_TOL = 1e-6
_EDEP_OVER_BEAM_WARN = 1.02      # totalEdep may exceed primaryE a little (capture, e+ ann.)
_BJORKEN_X_WARN = 1.2            # x > 1 possible on nuclei (Fermi motion); flag if large
_Q0_REL_TOL = 1e-3               # nu_q0 vs primaryE - outLeptonE (CC)

_NU_FLAVORS = {12, 14, 16}


class Result:
    def __init__(self):
        self.lines = []
        self.n_fail = 0
        self.n_warn = 0

    def ok(self, msg):
        self.lines.append(f"  ok    {msg}")

    def warn(self, msg):
        self.n_warn += 1
        self.lines.append(f"  WARN  {msg}")

    def fail(self, msg):
        self.n_fail += 1
        self.lines.append(f"  FAIL  {msg}")

    def check(self, cond, msg_ok, msg_fail):
        if cond:
            self.ok(msg_ok)
        else:
            self.fail(msg_fail)


def _frac(mask):
    mask = np.asarray(mask, bool)
    return f"{int(mask.sum())}/{mask.size}"


def validate(path, strict=False, max_events=20000):
    """Validate `path`. Returns (report_text, exit_code)."""
    r = Result()
    path = str(path)
    r.lines.append(f"gdmltp validate: {path}")

    # --- schema ---------------------------------------------------------- #
    present = set(io.available_branches(path))
    missing = [b for b in io.SCALAR_BRANCHES + io.TRK_BRANCHES + io.STEP_BRANCHES
               if b not in present]
    r.check(not missing, "schema: all required branches present",
            f"schema: missing required branch(es): {', '.join(missing)}")

    nu_present = [b for b in io.NU_BRANCHES if b in present]
    if nu_present and len(nu_present) != len(io.NU_BRANCHES):
        r.fail(f"schema: partial nu_* block ({len(nu_present)}/{len(io.NU_BRANCHES)} branches)")
    elif nu_present:
        r.ok("schema: full nu_* block present")
    else:
        r.ok("schema: no nu_* block (not a neutrino run)")

    n = int(io.num_events(path))
    r.lines.append(f"  info  events: {n}" + (f" (validating first {max_events})"
                                             if n > max_events else ""))
    if n == 0:
        return _finish(r, strict)
    stop = min(n, max_events)

    # --- per-event consistency (counts) ----------------------------------- #
    t = io.open_tree(path)
    sc = {b: t[b].array(library="np", entry_stop=stop)
          for b in ("nTracks", "nSteps", "primaryPDG", "primaryE") if b in present}
    if "trk_id" in present and "nTracks" in sc:
        import awkward as ak
        counts = np.asarray(ak.num(t["trk_id"].array(entry_stop=stop), axis=1))
        r.check(bool(np.array_equal(counts, sc["nTracks"])),
                "counts: nTracks matches len(trk_*) in every event",
                f"counts: nTracks mismatch in {_frac(counts != sc['nTracks'])} events")
    if "step_trackID" in present and "nSteps" in sc:
        import awkward as ak
        counts = np.asarray(ak.num(t["step_trackID"].array(entry_stop=stop), axis=1))
        r.check(bool(np.array_equal(counts, sc["nSteps"])),
                "counts: nSteps matches len(step_*) in every event",
                f"counts: nSteps mismatch in {_frac(counts != sc['nSteps'])} events")

    # --- energy bookkeeping ------------------------------------------------ #
    if "primaryE" in sc:
        primE = np.asarray(sc["primaryE"], float)
        r.check(bool((primE >= 0).all()), "energy: primaryE >= 0",
                f"energy: negative primaryE in {_frac(primE < 0)} events")
        if "totalEdep" in present:
            edep = t["totalEdep"].array(library="np", entry_stop=stop)
            over = edep > primE * _EDEP_OVER_BEAM_WARN
            if over.any():
                r.warn(f"energy: totalEdep > primaryE in {_frac(over)} events "
                       f"(possible for capture/annihilation; check units otherwise)")
            else:
                r.ok("energy: totalEdep <= primaryE (within tolerance)")

    # --- per-track / per-step positivity (streamed, capped) ---------------- #
    for branch, name in (("trk_startE", "track start kinetic energy"),
                         ("step_edep", "step energy deposit"),
                         ("step_time", "step global time")):
        if branch not in present:
            continue
        bad = 0
        seen = 0
        try:
            for nev, cols in io.iterate_flat(path, [branch]):
                v = cols[branch]
                bad += int((v < -_REL_TOL).sum())
                seen += nev
                if seen >= stop:
                    break
        except ValueError:
            continue
        r.check(bad == 0, f"positivity: {name} >= 0",
                f"positivity: {bad} negative values of {name}")

    # --- neutrino block physics -------------------------------------------- #
    if nu_present and len(nu_present) == len(io.NU_BRANCHES):
        nu = {b: t[b].array(library="np", entry_stop=stop) for b in io.NU_BRANCHES}
        cc = np.asarray(nu["nu_isCC"], bool)
        nc = np.asarray(nu["nu_isNC"], bool)
        r.check(not (cc & nc).any(), "nu: CC and NC are exclusive",
                f"nu: events flagged both CC and NC: {_frac(cc & nc)}")

        y = np.asarray(nu["nu_y"], float)
        act = cc | nc                      # only interacted events carry kinematics
        bad_y = act & ((y < -_REL_TOL) | (y > 1 + _REL_TOL))
        r.check(not bad_y.any(), "nu: inelasticity y in [0, 1]",
                f"nu: y outside [0,1] in {_frac(bad_y)} interacting events")

        q2 = np.asarray(nu["nu_Q2"], float)
        bad_q2 = act & (q2 < -1.0)         # MeV^2; tiny negatives ~ rounding
        r.check(not bad_q2.any(), "nu: Q2 >= 0",
                f"nu: negative Q2 in {_frac(bad_q2)} interacting events")

        x = np.asarray(nu["nu_x"], float)
        big_x = act & (x > _BJORKEN_X_WARN)
        if big_x.any():
            r.warn(f"nu: Bjorken x > {_BJORKEN_X_WARN} in {_frac(big_x)} events "
                   f"(possible from Fermi motion; check kinematics otherwise)")
        else:
            r.ok(f"nu: Bjorken x <= {_BJORKEN_X_WARN}")

        # Checks that relate the nu block to the primary only make sense when
        # the primary IS the neutrino (vertex-level generator files, g4sim
        # neutrino mode) -- is_nu gates them per event.
        if "primaryPDG" in sc:
            pdg0 = np.asarray(sc["primaryPDG"], np.int64)
            is_nu = np.isin(np.abs(pdg0), list(_NU_FLAVORS))

            # CC => outgoing lepton is the charged partner of the primary flavor
            lep = np.asarray(nu["nu_outLeptonPDG"], np.int64)
            expect_cc = np.sign(pdg0) * (np.abs(pdg0) - 1)
            bad_cc = cc & is_nu & (lep != expect_cc)
            r.check(not bad_cc.any(),
                    "nu: CC outgoing lepton flavor matches the primary neutrino",
                    f"nu: wrong CC lepton flavor in {_frac(bad_cc)} events")

            # q0 = Enu - Elep in the schema convention
            if "primaryE" in sc:
                q0 = np.asarray(nu["nu_q0"], float)
                el = np.asarray(nu["nu_outLeptonE"], float)
                expect = np.asarray(sc["primaryE"], float) - el
                scale = np.maximum(np.abs(expect), 1.0)
                bad_q0 = cc & is_nu & (np.abs(q0 - expect) / scale > _Q0_REL_TOL)
                r.check(not bad_q0.any(),
                        "nu: q0 == primaryE - outLeptonE (CC)",
                        f"nu: q0 inconsistent with primaryE - outLeptonE "
                        f"in {_frac(bad_q0)} CC events")

    return _finish(r, strict)


def _finish(r, strict):
    verdict = "FAIL" if r.n_fail else ("WARN" if (strict and r.n_warn) else "PASS")
    r.lines.append(f"result: {verdict}  ({r.n_fail} failure(s), {r.n_warn} warning(s))")
    code = 0 if verdict == "PASS" else 1
    return "\n".join(r.lines), code
