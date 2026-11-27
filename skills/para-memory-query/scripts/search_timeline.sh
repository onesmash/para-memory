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
#
# Exit codes: 0 = answered (including "no match" for keyword), 1 = bad request
# (missing/invalid argument, unknown mode), 2 = the store itself is missing or
# unreadable. Keeping 2 separate matters: "the folder was moved" must never be
# reported as "there is nothing for that day".

set -e

MEMORY_ROOT="${PARA_MEMORY_ROOT:-$HOME/para-memory}"
DAILY_NOTES_DIR="$MEMORY_ROOT/memory"

usage() {
    echo "Usage: $0 <mode> [args]" >&2
    echo "Modes:" >&2
    echo "  date <YYYY-MM-DD>              - Show every note captured for that day" >&2
    echo "  range <start-date> <end-date>  - Show notes in date range" >&2
    echo "  keyword <term>                 - Search for keyword across all notes" >&2
    exit 1
}

require_store() {
    if [ ! -d "$DAILY_NOTES_DIR" ]; then
        echo "Memory store not found: $DAILY_NOTES_DIR" >&2
        echo "  PARA_MEMORY_ROOT=${PARA_MEMORY_ROOT:-<unset>} — 目录被移动、删除或还没 init 时都会这样。" >&2
        exit 2
    fi
    if [ ! -r "$DAILY_NOTES_DIR" ]; then
        echo "Memory store is not readable: $DAILY_NOTES_DIR" >&2
        exit 2
    fi
}

MODE="${1:-}"
shift || true

case "$MODE" in
    date)
        DATE="${1:-}"
        [ -n "$DATE" ] || usage
        # 短日期（2026-11-2）当前缀会漏到 20 号，元字符（*）会把全部笔记当成「这一天」。
        if ! [[ "$DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
            echo "Invalid date: ${DATE}（需要 YYYY-MM-DD）" >&2
            exit 1
        fi
        require_store
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
        shopt -u nullglob
        ;;
    range)
        START_DATE="${1:-}"
        END_DATE="${2:-}"
        [ -n "$START_DATE" ] && [ -n "$END_DATE" ] || usage
        for value in "$START_DATE" "$END_DATE"; do
            if ! [[ "$value" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
                echo "Invalid date: ${value}（需要 YYYY-MM-DD）" >&2
                exit 1
            fi
        done
        require_store
        echo "Searching notes from $START_DATE to $END_DATE..."
        shopt -s nullglob
        for file in "$DAILY_NOTES_DIR"/*.md; do
            name=$(basename "$file" .md)
            day="${name:0:10}"
            # 只认日期前缀；memory/ 里非日期命名的文件（README、MEMORY…）不进任何区间。
            if ! [[ "$day" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
                continue
            fi
            if [[ ("$day" > "$START_DATE" || "$day" = "$START_DATE") && ("$day" < "$END_DATE" || "$day" = "$END_DATE") ]]; then
                echo "=== $name ==="
                cat "$file"
                echo ""
            fi
        done
        shopt -u nullglob
        ;;
    keyword)
        KEYWORD="${1:-}"
        [ -n "$KEYWORD" ] || usage
        require_store
        echo "Searching for keyword: $KEYWORD"
        # 零命中是「查完了，没有」，不是「坏掉了」；但目录不存在 / 读不了（grep rc>=2）
        # 必须与零命中分开报，否则「store 坏了」会被伪装成「没有匹配」。
        rc=0
        matches=$(grep -rn --include="*.md" -- "$KEYWORD" "$DAILY_NOTES_DIR") || rc=$?
        case "$rc" in
            0) echo "$matches" ;;
            1) echo "No matches found for: $KEYWORD" ;;
            *) echo "Search failed for: $KEYWORD (grep rc=$rc)" >&2; exit 2 ;;
        esac
        ;;
    *)
        usage
        ;;
esac
