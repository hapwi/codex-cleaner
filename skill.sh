#!/usr/bin/env sh
set -eu

COMMAND="${1:-install}"
if [ "$#" -gt 0 ]; then
  shift
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/skills/codex-cleaner"
TARGET_ROOT="${AGENTS_HOME:-$HOME/.agents}"
TARGET_DIR="$TARGET_ROOT/skills/codex-cleaner"
FORCE="0"

for arg in "$@"; do
  case "$arg" in
    --force)
      FORCE="1"
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

case "$COMMAND" in
  install)
    if [ ! -d "$SOURCE_DIR" ]; then
      echo "missing bundled skill: $SOURCE_DIR" >&2
      exit 1
    fi
    if [ -e "$TARGET_DIR" ] && [ "$FORCE" != "1" ]; then
      echo "skill already exists: $TARGET_DIR"
      echo "rerun with --force to replace it"
      exit 0
    fi
    mkdir -p "$TARGET_ROOT/skills"
    if [ -e "$TARGET_DIR" ]; then
      rm -rf "$TARGET_DIR"
    fi
    mkdir -p "$TARGET_DIR"
    cp -R "$SOURCE_DIR"/. "$TARGET_DIR"/
    echo "installed $TARGET_DIR"
    echo "start a new Codex chat and invoke \$codex-cleaner"
    ;;
  *)
    echo "usage: skill.sh install [--force]" >&2
    exit 2
    ;;
esac
