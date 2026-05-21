#!/bin/bash
# cc-research-report — local install for Claude Code
#
# Creates symlinks from ~/.claude/skills/ and ~/.claude/agents/ into this repo.
# Edit in repo → restart Claude Code session → changes live.
# Idempotent: safe to re-run.

set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
AGENTS_DIR="$HOME/.claude/agents"

echo "Installing cc-research-report from $REPO_ROOT"

mkdir -p "$SKILLS_DIR" "$AGENTS_DIR"

# Skills
for skill in research-report research-loop; do
  source="$REPO_ROOT/skills/$skill"
  target="$SKILLS_DIR/$skill"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
    echo "  skill already linked: $skill"
  else
    [ -e "$target" ] && rm -rf "$target"
    ln -s "$source" "$target"
    echo "  skill: ~/.claude/skills/$skill -> $source"
  fi
done

# Agents
for f in "$REPO_ROOT/agents/"*.md; do
  name="$(basename "$f")"
  target="$AGENTS_DIR/$name"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$f" ]; then
    echo "  agent already linked: $name"
  else
    [ -e "$target" ] && rm "$target"
    ln -s "$f" "$target"
    echo "  agent: ~/.claude/agents/$name -> $f"
  fi
done

echo "Done. Restart Claude Code to load."
echo "To uninstall: ./uninstall-local.sh"
