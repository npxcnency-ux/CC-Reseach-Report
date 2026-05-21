---
name: research-report
description: Two-step workflow — research-loop (verified research) → research-html-formatter (HTML rendering). Use when the user wants a research task saved as an HTML report. Decouples research quality validation from presentation formatting so the critic only reviews claims, not markup.
---

# research-report skill

Orchestrate a two-step pipeline:

```
User request
    ↓
Step 1: research-loop   → validated Markdown research
    ↓
Step 2: research-html-formatter → HTML file on disk
```

## Step 0 — Cache check (resume detection)

Before starting research-loop, check whether a recent cached research output exists for this question.

**Slug computation** (same rule as Step 1.5):
  slugified-title = take inferred title from user request → replace whitespace with `-` → strip filesystem-unsafe chars → truncate to 50 chars

**Check command** (run via Bash):
```bash
ls -t ~/.claude/cache/research-loop/${slug}*.md 2>/dev/null | grep -v "\-query\.md" | head -3
```

**Decision logic**:
1. If no matching file → proceed directly to Step 1 (normal research).
2. If matching file(s) found:
   a. Extract timestamp from filename (`YYYYMMDD-HHMMSS`), compute days since creation.
   b. If **≤ 7 days old**:
      - Check whether a companion `*-query.md` file exists; if so, Read it and display the original question to user for confirmation.
      - Use AskUserQuestion with two options:
        - Option A (Recommended): Reuse existing research (`{filename}`, generated on `{date}`) — skip to HTML formatting
        - Option B: Re-research from scratch (ignore cache, run research-loop fresh)
   c. If **> 7 days old**: proceed directly to Step 1 (cache expired, no prompt).

**Option A path**:
- Read the matched markdown file as `research_output`
- Set `markdown_path` = path of the matched file
- Skip Step 1 entirely, proceed to Step 2

**Option B path**: proceed to Step 1 normally.

**Note**: slug-based matching may find files from similar-sounding questions. The companion `*-query.md` (if present) shows the exact original question — use this to confirm relevance before offering Option A.

## Step 1 — Run research-loop (research only)

Extract the research question from the user's request. Strip any mention of HTML/report/file output.

Invoke the `research-loop` **skill** (not an agent — the loop's orchestration runs in this main session so it can spawn `research-worker` and `research-critic` subagents). Call `Skill` with `skill="research-loop"` and pass the following content as `args`:

```
{research_question}

## Output format

Produce a structured Markdown research report only. Do NOT generate HTML, CSS, or any markup.
Your output must follow the research-worker format exactly:
- # Answer (prose with labeled claims)
- # Evidence Table (markdown table)
- # What I Don't Know
- # Assumptions Made
- # Search Log
```

The skill will execute the worker↔critic loop in this session and produce a `# Final Answer` followed by `# Loop Summary`. Save the entire returned output (including Loop Summary) as `research_output`.

**Why skill, not agent**: research-loop must spawn subagents. Agents (subagents) cannot spawn further subagents in Claude Code — only the main session can. Loading research-loop as a skill keeps the orchestration in the main session where the `Agent` tool is available.

## Step 1.5 — Persist research-loop output to disk

Before invoking the HTML formatter, write `research_output` to disk using the Write tool. This serves three purposes:

1. **Token efficiency**: passing the full markdown content as an Agent prompt would cost ~1× markdown tokens on the main session output side (the prompt string serialization). Using a file path reduces the Agent prompt to ~50 tokens.
2. **Re-render without re-research**: if HTML rendering fails or the user wants a different style, the markdown is preserved on disk and Step 2 can be re-run independently.
3. **Audit trail**: users can inspect the verified research markdown directly without parsing HTML.

Determine `markdown_path`:
- Directory: `~/.claude/cache/research-loop/` (create with `mkdir -p` if missing)
- Filename: `{slugified-title}-{timestamp}.md`
  - `slugified-title`: take inferred or user-provided title, replace whitespace with `-`, strip filesystem-unsafe chars (`/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`), truncate to 50 chars
  - `timestamp`: `YYYYMMDD-HHMMSS` in local time (matches what user sees in `ls -l`)
  - Example: `代数据分析商业模式可行性-20260520-143022.md`

Use the Write tool to save `research_output` (the entire `# Final Answer` + `# Loop Summary` block, byte-for-byte) to `markdown_path`.

Additionally, write the original research question to a companion query file:
- Path: `~/.claude/cache/research-loop/{slugified-title}-{timestamp}-query.md`
  - Same `{slugified-title}` and `{timestamp}` as the main markdown file
- Content: the verbatim research question passed to research-loop (the exact text from the user's request, not reformatted)

If this Write fails (e.g., directory permission, disk full), skip silently — do not block the pipeline. The query file is supplementary metadata.

If Write fails (e.g., directory permission, disk full), fall back to inline-prompt format in Step 2 and warn the user; do not block the pipeline.

## Step 2 — Format as HTML

Determine `output_path`:
- If the user specified a file path, use it.
- Otherwise default to `./{slugified-title}-report.html` in the current working directory.

Call `Agent` with `subagent_type="research-html-formatter"` and this prompt:

```
Transform the verified research at the file below into an HTML report.

input_path: {markdown_path from Step 1.5}
output_path: {output_path}
title: {inferred or user-provided title}
language: {zh|en based on research content}

The input file contains a complete markdown research report (Final Answer + Loop Summary). Use the Read tool to load its content before producing HTML — do not assume the markdown is inline in this prompt.

## Mandatory tool sequence (orchestrator-enforced)

Your tool calls MUST follow this order:

1. **FIRST tool call**: `Skill` with `skill: "frontend-design"` (no args). This loads the design philosophy that drives your typography/color/layout choices. Skipping this step produces generic SaaS-dashboard HTML — the orchestrator will detect this and reject your output.

2. **SECOND tool call**: `Read` on `input_path` to load the markdown content.

3. **THIRD tool call**: `Write` to `output_path` with the complete HTML.

## Mandatory return format (orchestrator-enforced)

Your final response message MUST begin with a line in this exact format:

`Design direction: {one-line description of the aesthetic chosen, e.g. "editorial / serif display + monospace caption / muted ochre & ink"}`

The orchestrator greps for this literal prefix (`Design direction:`). If absent, your output is rejected and you must redo. The line forces deliberate aesthetic commitment — without it, LLMs default to generic Tailwind-grays + system-ui-fonts.

If the report topic is industrial/historical (like Victorian-era subjects, factory-floor history), DO NOT pick "modern minimal". Match the aesthetic to the topic's tone — see frontend-design skill for the menu of directions.
```

**Fallback (if Step 1.5 Write failed)**: instead of `input_path`, include the full markdown inline under `## research_markdown` heading (legacy format). Note this in the Step 2 prompt: `inline_fallback: true (Step 1.5 disk write failed: {reason})`.

## Step 2.5 — Mechanical Design enforcement gate

After the formatter Agent returns, run two checks on the agent's return message string:

**D1 — Design direction line present**: scan the return message for a line matching the regex `^Design direction:\s+\S` (the line must start with literal `Design direction:` followed by non-whitespace content). Match anywhere in the return message, but the content after the colon must be ≥ 20 chars and contain at least one specific aesthetic descriptor (font family name, color name, era/style keyword like `editorial`, `art-deco`, `industrial`, `magazine`, `retro-futuristic`, `brutalist`, `pastel`, `monospace`, `serif`, `display`, `ochre`, `ink`, etc.).

If absent or too generic (< 20 chars or no descriptor) → redo with this addendum prepended to the original Step 2 prompt:

```
## Previous attempt rejected by Step 2.5 Design enforcement gate

Reason: {missing | too-generic | both}

Your previous return did not include a valid `Design direction:` line. The orchestrator requires this line to confirm you (a) called the frontend-design skill and (b) committed to a specific aesthetic. Generic descriptions like "clean and modern" or "professional" are rejected — the line must name a specific direction (e.g., "editorial / serif display + monospace caption / muted ochre & ink", "industrial brutalist / IBM Plex Mono + steel grey / decorative rules", "art-deco editorial / Cinzel + ivory + gold accents").

Redo: call Skill('frontend-design') first, choose a direction matching the report topic, rewrite the HTML, and start your final response message with `Design direction: ...`.
```

**D2 — Generic-default font-family detection (secondary signal)**: read the written HTML file (output_path), find the body's `font-family:` declaration. If the primary font (first in stack) is one of `system-ui`, `-apple-system`, `Segoe UI`, `Inter`, `Roboto`, `Arial`, `sans-serif`, OR if the entire stack consists only of these generic fallbacks with no named display/serif/mono font, this is a strong signal the design skill was ignored.

D2 is **advisory only** (not auto-redo) because some legitimate minimal designs use system stacks. Surface it in the Step 2 result report as: `D2 advisory: body font-family uses only generic system stack — design may be off-the-shelf.`

**Max redos**: 2. After 2 failed redos on D1, accept the output but flag in the user-facing summary: `WARNING: Design enforcement gate failed after 2 redos. Output may be visually generic.`

## After both steps complete

Report to the user:
- File path of the HTML report
- File path of the persisted markdown (from Step 1.5 — useful for re-rendering or audit)
- Turns used by research-loop (from Loop Summary)
- Final verdict path (e.g., REVISE → PASS)
- Token/time note if available

## Why this split matters

| Concern | research-loop | research-html-formatter |
|---------|--------------|------------------------|
| Does WebSearch | Yes | Never |
| Critic reviews | Research claims | (not invoked) |
| Context window cost | High (multi-turn) | Low (single pass) |
| Can be rerun cheaply | No | Yes (markdown on disk from Step 1.5) |

If the HTML output is unsatisfactory, re-run Step 2 only — no need to re-research; just point research-html-formatter at the existing `markdown_path` from `~/.claude/cache/research-loop/`.
If the research quality is questioned, re-run Step 1 only — the formatter is not the bottleneck.
