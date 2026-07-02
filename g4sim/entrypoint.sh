#!/usr/bin/env bash
# Dispatcher entrypoint for the g4targetpractice image.
#   docker run <image>                    -> g4sim (interactive Geant4 session)
#   docker run <image> run.mac            -> g4sim run.mac  (simulation, unchanged)
#   docker run <image> <anything else>    -> g4tp ...       (analysis / event display)
# Dispatching on the .mac suffix (rather than a hardcoded verb list) means new
# g4tp subcommands and global flags (--version, --debug) work without touching
# this file, and unknown verbs get g4tp's proper usage error instead of a
# cryptic Geant4 "macro not found".
set -e
case "$1" in
  ""|*.mac)
    exec /app/build/g4sim "$@"
    ;;
  *)
    exec python3 -m g4tp "$@"
    ;;
esac
