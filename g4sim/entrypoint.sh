#!/usr/bin/env bash
# Dispatcher entrypoint for the g4targetpractice image.
#   docker run <image> run.mac                  -> g4sim run.mac  (simulation, unchanged)
#   docker run <image> display|analyze|info ... -> g4tp <verb> ... (analysis / event display)
# Anything else falls through to g4sim, preserving the original behavior.
set -e
case "$1" in
  display|analyze|info)
    exec python3 -m g4tp "$@"
    ;;
  *)
    exec /app/build/g4sim "$@"
    ;;
esac
