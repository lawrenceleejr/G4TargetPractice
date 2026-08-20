#!/usr/bin/env bash
# Shared dispatcher entrypoint for the GDMLTargetPractice images.
#   docker run <image>                 -> g4sim interactive session (geant4 image)
#   docker run <image> run.mac         -> g4sim run.mac        (geant4 simulation)
#   docker run <image> job.json        -> GENIE driver         (genie image)
#   docker run <image> transport -o d  -> gdmltp transport      (Geant4 stage of a
#                                         generator run: replays d/events.hepmc)
#   docker run <image> <anything else> -> gdmltp ...             (analysis / display)
#
# Dispatch is on the argument SHAPE (suffix), not a hardcoded verb list, so new
# gdmltp subcommands and flags work untouched. Each image ships only the engine it
# needs -- the geant4 image has g4sim (not the GENIE driver) and vice versa; the
# analysis path (gdmltp) is present in both, so display/analyze/info work from either.
set -e
case "$1" in
  ""|*.mac)
    exec /app/build/g4sim "$@"
    ;;
  *.json)
    # a job spec runs whichever generator driver this image ships
    if [ -f /app/genie/run_genie.py ]; then
      exec python3 /app/genie/run_genie.py "$@"
    elif [ -f /app/achilles/run_achilles.py ]; then
      exec python3 /app/achilles/run_achilles.py "$@"
    elif [ -f /app/pythia/run_pythia.py ]; then
      exec python3 /app/pythia/run_pythia.py "$@"
    else
      echo "This image ships no generator driver for $1" >&2
      exit 64
    fi
    ;;
  *)
    exec python3 -m gdmltp "$@"
    ;;
esac
