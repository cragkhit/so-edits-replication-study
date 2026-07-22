#!/bin/bash
# Watches the Matcha indexing log and prints only the file-count progress lines.
# Usage: ./watch_index_progress.sh [path-to-log]

LOG_FILE="${1:-/Users/chaiyong/Downloads/matcha/1_matcha/index_python_files.log}"

if [ ! -f "$LOG_FILE" ]; then
  echo "Log file not found: $LOG_FILE" >&2
  exit 1
fi

# show the latest progress line so far, then keep watching for new ones
grep "^Indexed " "$LOG_FILE" | tail -1
tail -n 0 -f "$LOG_FILE" | grep --line-buffered "^Indexed \|Successfully creating index\|ERROR: Indexed zero"
