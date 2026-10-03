#!/usr/bin/env bash
# Print "NEW PHOTO: <path>" once for each new image in DIR after its size settles.
# Usage: watch_downloads.sh [DIR] [STATE_FILE]
# Reuse STATE_FILE when restarting so photos that arrived meanwhile are reported
# and no photo is reported twice.
set -euo pipefail

dir="${1:-$HOME/Downloads}"
if [ -n "${2:-}" ]; then
  state="$2"
else
  state="$(mktemp)"
  rm -f "$state"
fi
if [ ! -e "$state" ]; then
  # Write the snapshot elsewhere first so the state file appears complete.
  find "$dir" -maxdepth 1 -type f > "$state.tmp"
  mv "$state.tmp" "$state"
fi

while true; do
  while IFS= read -r path; do
    if grep -qxF -- "$path" "$state"; then
      continue
    fi
    size="$(wc -c < "$path" 2>/dev/null)" || continue
    sleep 1
    if [ ! -e "$path" ] || [ "$(wc -c < "$path" 2>/dev/null)" != "$size" ]; then
      continue
    fi
    printf '%s\n' "$path" >> "$state"
    printf 'NEW PHOTO: %s\n' "$path"
  done < <(find "$dir" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' \
    -o -iname '*.heic' -o -iname '*.png' \) | sort)
  sleep 1
done
