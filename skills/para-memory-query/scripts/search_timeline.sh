#!/bin/bash
# Search the captured notes by date, date range, or keyword.
#
# Notes land in memory/ in two shapes:
#   <date>.md                       a hand-written daily note
#   <date>-<shortid>-session.md     one captured session (save_chat_history.py)
#
# So "the notes of a day" is a prefix match on the filename, not a filename
# match. Looking for `<date>.md` verbatim finds nothing as soon as the capture
# hook is the thing writing the notes.

set -e

MEMORY_ROOT="${PARA_MEMORY_ROOT:-$HOME/para-memory}"
DAILY_NOTES_DIR="$MEMORY_ROOT/memory"

usage() {
    echo "Usage: $0 <mode> [args]"
    echo "Modes:"
    echo "  date <YYYY-MM-DD>              - Show every note captured for that day"
    echo "  range <start-date> <end-date>  - Show notes in date range"
    echo "  keyword <term>                 - Search for keyword across all notes"
    exit 1
}

MODE="${1:-}"
shift || true

case "$MODE" in
    date)
        DATE="${1:-}"
        [ -n "$DATE" ] || usage
        shopt -s nullglob
        files=("$DAILY_NOTES_DIR/$DATE"*.md)
        if [ "${#files[@]}" -eq 0 ]; then
            echo "No notes found for date: $DATE"
            exit 1
        fi
        for file in "${files[@]}"; do
            echo "=== $(basename "$file" .md) ==="
            cat "$file"
            echo ""
        done
        ;;
    range)
        START_DATE="${1:-}"
        END_DATE="${2:-}"
        [ -n "$START_DATE" ] && [ -n "$END_DATE" ] || usage
        echo "Searching notes from $START_DATE to $END_DATE..."
        shopt -s nullglob
        for file in "$DAILY_NOTES_DIR"/*.md; do
            name=$(basename "$file" .md)
            day="${name:0:10}"
            if [[ ("$day" > "$START_DATE" || "$day" = "$START_DATE") && ("$day" < "$END_DATE" || "$day" = "$END_DATE") ]]; then
                echo "=== $name ==="
                cat "$file"
                echo ""
            fi
        done
        ;;
    keyword)
        KEYWORD="${1:-}"
        [ -n "$KEYWORD" ] || usage
        echo "Searching for keyword: $KEYWORD"
        # 零命中是「查完了，没有」，不是「坏掉了」：set -e 下裸 grep 会把 1 当脚本失败，
        # 调用方分不清「没匹配」和「store 坏了」。这里显式返回 0 并说清楚。
        if matches=$(grep -rn --include="*.md" -- "$KEYWORD" "$DAILY_NOTES_DIR"); then
            echo "$matches"
        else
            echo "No matches found for: $KEYWORD"
        fi
        ;;
    *)
        usage
        ;;
esac
