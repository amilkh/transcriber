#!/usr/bin/env bash
set -euo pipefail

# Forwards local :19001 to takelab :19001.
exec ssh -N -L 19001:127.0.0.1:19001 takelab
