#!/bin/bash
# Search using QMD (if available) across PARA memory collections

set -e

QUERY="$1"
COLLECTION="${2:-all}"  # Default to searching all collections

# Check if qmd is available
if ! command -v qmd &> /dev/null; then
    echo "Error: qmd command not found. Please install QMD or use built-in search tools."
    exit 1
fi

# Perform search based on collection
case "$COLLECTION" in
    knowledge|life)
        echo "Searching knowledge graph (life collection)..."
        qmd query "$QUERY" -c life
        ;;
    memory|daily)
        echo "Searching daily notes (memory collection)..."
        qmd query "$QUERY" -c memory
        ;;
    tacit|clawd)
        echo "Searching tacit knowledge (clawd collection)..."
        qmd query "$QUERY" -c clawd
        ;;
    all|*)
        echo "Searching all collections..."
        qmd query "$QUERY"
        ;;
esac
