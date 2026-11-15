#!/usr/bin/env bash
# Run 0x on a case folder.
# usage: ./run_case.sh samples/piazza1140 [extra 0x flags, e.g. --json or --stock-tool tip_distribution]
set -e
cd "$(dirname "$0")"
[ -d .venv ] && source .venv/bin/activate
CASE="${1:?usage: ./run_case.sh <case_folder> [extra flags]}"; shift || true
[ -d "$CASE" ] || { echo "Not a folder: $CASE"; exit 1; }
STOCK=$(ls "$CASE"/*stock*.pdf "$CASE"/*stock*.csv "$CASE"/*stock*.xlsx 2>/dev/null | head -1)
PACK=$(ls "$CASE"/*closing*.pdf 2>/dev/null | head -1)
[ -z "$STOCK" ] && { echo "No *stock* file (pdf/csv/xlsx) in $CASE"; exit 1; }
ARGS=(--stock-file "$STOCK" --full --no-nim --data "$CASE/.out")
[ -n "$PACK" ] && ARGS+=(--closing-file "$PACK")
echo ">> stock: $STOCK"; [ -n "$PACK" ] && echo ">> pack:  $PACK"
exec 0x "${ARGS[@]}" "$@"
