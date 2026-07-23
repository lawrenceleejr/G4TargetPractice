#!/usr/bin/env bash
# Shared dispatcher entrypoint for the GDMLTargetPractice images.
#   docker run <image>                 -> g4sim interactive session (geant4 image)
#   docker run <image> run.mac         -> g4sim run.mac        (geant4 simulation)
#   docker run <image> job.json        -> GENIE driver         (genie image)
#   docker run <image> <anything else> -> g4tp ...             (analysis / display)
#
# Dispatch is on the argument SHAPE (suffix), not a hardcoded verb list, so new
# g4tp subcommands and flags work untouched. Each image ships only the engine it
# needs -- the geant4 image has g4sim (not the GENIE driver) and vice versa; the
# analysis path (g4tp) is present in both, so display/analyze/info work from either.
set -e
case "$1" in
  ""|*.mac)
    exec /app/build/g4sim "$@"
    ;;
  *.json)
    exec python3 /app/genie/run_genie.py "$@"
    ;;
  *)
    exec python3 -m g4tp "$@"
    ;;
esac
