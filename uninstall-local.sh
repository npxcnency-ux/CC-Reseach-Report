#!/bin/bash
# cc-research-report — uninstall (removes symlinks from ~/.claude/)

set -e

SKILLS_DIR="$HOME/.claude/skills"
AGENTS_DIR="$HOME/.claude/agents"

for skill in research-report research-loop; do
  target="$SKILLS_DIR/$skill"
  [ -L "$target" ] && rm "$target" && echo "  removed skill: $skill" || echo "  no symlink: $skill"
done

for name in research-worker.md research-html-formatter.md research-critic-instruction.md research-critic-dialectic.md research-critic-depth.md research-critic-width.md; do
  target="$AGENTS_DIR/$name"
  [ -L "$target" ] && rm "$target" && echo "  removed agent: $name" || echo "  no symlink: $name"
done

echo "Done. Restart Claude Code to take effect."
