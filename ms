#!/usr/bin/env bash
# The parameters you keep typing. Anything you pass overrides them -- argparse
# takes the last value, so `./ms --shape multispan --span 30` just works.
#
#   ./ms                         the usual roof, dashboard window
#   ./ms --shape sawtooth        same, different profile
#   ./ms --out out --no-show     PNGs instead of a window
#   ./ms design --cost           let it pick the sections and price them
#   ./ms serve --http --show     MCP on :8000, driving that same window
#   ./ms snow --depth 1.0        subcommands with no defaults pass straight through
set -euo pipefail
cd "$(dirname "$0")"

CMD=roof
case "${1:-}" in
    roof | design | beam | snow | sections | serve) CMD=$1; shift ;;
esac

# Size and load, shared by the two commands that build a roof. Sections are
# roof-only: design chooses them for you.
COMMON=(--span 12 --length 20 --pitch 20 --snow-depth 1.0 --snow-state wet
        --lang sk --country SK)
case $CMD in
    roof)   defaults=("${COMMON[@]}" --rafter IPE450 --column HEB240
                      --purlin SHS140x140x5) ;;
    design) defaults=("${COMMON[@]}") ;;
    *)      defaults=() ;;  # beam, snow, sections and serve take none of it
esac

# --show unless you say otherwise, and only where a window is the point. serve
# is headless unless you ask for the dashboard, since it usually is not.
show=--show
[[ $CMD == roof || $CMD == design ]] || show=
args=()
for a in "$@"; do
    [[ $a == --no-show ]] && { show=; continue; }
    args+=("$a")
done

exec uv run python -m metal_strength.cli "$CMD" \
    "${defaults[@]}" ${show:+$show} ${args[@]+"${args[@]}"}
