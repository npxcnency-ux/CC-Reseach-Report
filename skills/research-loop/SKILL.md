---
name: research-loop
description: Iterative worker↔critic research loop with rigorous adversarial validation. Use when a research task needs more than a first-draft answer — spawns research-worker and research-critic subagents repeatedly until critic passes or max_turns reached. Returns the final vetted Markdown report. Caller MUST be the main session (subagent contexts cannot spawn further subagents).
---

# research-loop skill

Orchestrate a worker-critic loop for rigorous research. The session loading this skill executes the routing; the actual research is done by spawned `research-worker` and `research-critic` subagents.

## Preflight check

This skill spawns subagents via the `Agent` tool. If `Agent` is **not** in the tool inventory of the session loading this skill — i.e. this skill was loaded from inside a subagent context, where Claude Code does not allow nested spawning — stop immediately and emit:

```
VERDICT: FAIL — research-loop requires the Agent tool. The current context does not provide it (likely because this skill was loaded inside a subagent). Re-invoke from the main session.
```

Do not fall back to executing the research directly. That defeats the loop's entire purpose (worker↔critic adversarial validation).

## Loop specification

```
# Main loop (no Turn 0 — Coverage Matrix is generated inside Critic Turn 1)
MAX_TURNS = 10
for turn in 1..MAX_TURNS:
    # Step 1: invoke worker (receives coverage_matrix on Turn 2+ once it exists)
    worker_input = { task, previous_draft?, critic_feedback?, coverage_matrix? }
    current_draft = call Worker(worker_input)

    # Step 2: invoke critic (receives coverage_matrix on Turn 2+ to avoid regenerating)
    critic_output = call Critic(task, current_draft, prev_url_verified?, coverage_matrix?)

    # Step 3: parse verdict
    verdict = first_line_of(critic_output)
    if verdict == "VERDICT: PASS": break
    if verdict == "VERDICT: FAIL": break
    # else REVISE: save feedback, continue
    critic_feedback = critic_output
```

## Execution

Parse `MAX_TURNS` from the task: if the task contains a line `max_turns: N` (integer 1–20), use N; otherwise default to 10. Then:

## Turn-internal redo invariants (used by step b and step c.5)

When step b or step c.5 triggers a redo, the redo prompt must carry forward all content from the prior attempt that wasn't itself the source of the gate failure, and the redo result must preserve those contents verbatim. Without this, a Critic asked to add a missing column may regenerate the entire Coverage Matrix with different sub-questions (breaking downstream Coverage Verification logic across turns); a Worker asked to fix one URL may drift other URLs that weren't part of the failure. Empirically observed in the 1880-1930 electrification test: Critic Turn 1 redo #1 produced one Coverage Matrix; redo #2 produced a different Coverage Matrix despite the orchestrator's "preserve" instruction in prose. Mechanical preservation closes that gap.

### Invariants by actor

**Worker invariants** (carried from prior Worker attempt → next Worker attempt within same turn):
- `## Self Coverage Plan` table content (Turn 1 only — once generated, sub-question rows are locked; orchestrator extracts at end of Turn 1 for Critic prompt)
- `# Search Log` query rows (queries actually run; Worker may not fabricate new query history in redo)
- `# Answer` section content (if not failing the gate)
- `# Evidence Table` rows whose Source URL passed W3 (only blacklist-hit URLs may change; other rows stay)
- `# Rebuttals` sub-headings + valid Stance lines (Turn 2+; only invalid stances and missing entries need fixing)

**Critic invariants** (carried from prior Critic attempt → next Critic attempt within same turn):
- `# Coverage Matrix` table (Turn 1 only — locked once generated; downstream turns depend on this exact text)
- `# Reasoning Audit` sub-check assessments (Y/N + quote/example for each of 4 checks)
- `# Issues` (titles, where-quote, problem, severity, fix direction)
- `# Research Directions` (titles, Critic's contribution body, Worker's task)
- `# Critic WebFetch Audit` rows for URLs Critic personally fetched in any prior attempt this turn (status, content support — don't re-fetch unless claim text changed)
- `# URL Verification Report` rows for URLs already analyzed (status, supports-claim assessment, action)
- `# Worker Rebuttal Adjudication` rulings already issued (Turn 2+)

### Mechanical preservation procedure

When triggering redo:

1. **Extract**: parse the prior attempt's output, extract each invariant section. If a section is empty/missing in prior attempt, it's not yet an invariant (may legitimately be added in redo).

2. **Inject in redo prompt**: under a top-level heading `## Cached invariants from prior attempt — preserve verbatim`, paste each extracted section verbatim. Add the literal instruction:

   > "The orchestrator caches the sections below from your prior attempt. Your redo MUST include each cached section character-for-character (modulo trailing whitespace and minor markdown formatting). The orchestrator runs a normalized comparison on these sections after your redo and rejects drift. If the gate failure was caused by content within one of these cached sections (e.g., the Coverage Matrix has malformed columns), the orchestrator marks that specific section as 'non-invariant for this redo' and excludes it from the cache — only those sections explicitly listed as cached must be preserved."

3. **Validate after redo**: for each cached invariant section, normalize whitespace (collapse spaces/tabs, trim line ends) on both prior and current attempt content, then compare. Mismatch in any cached section → gate fail with reason `Invariant drift: {section name}`. Trigger another redo (counts toward max 2).

4. **Carry forward across redos**: after a successful redo passes all gates, the post-redo content becomes the new "prior attempt" for any subsequent redo logic and the source for step e extraction. The invariant cache is rebuilt from the latest passing attempt.

### When invariants legitimately change

If the gate failure cause IS the invariant content itself (e.g., Coverage Matrix has missing columns, Reasoning Audit lacks one of the 4 sub-checks), the orchestrator marks that section as "non-invariant for this redo" and excludes it from the cache. The redo prompt still lists OTHER cached sections to preserve, but allows the failing section to be regenerated correctly. After the regeneration passes, that section enters the invariant cache for any subsequent redos.

In other words: **cached invariants = sections from prior attempt that weren't the cause of the current gate failure**.

1. **Receive** the research task from the skill's args (or from the user prompt if invoked directly via `/research-loop`).

2. **Initialize**: `current_draft = null`, `critic_feedback = null`, `coverage_matrix = null`, `prev_dq = null`, `prev_url_verified_critic_only = null`, `worker_rebuttals = null`, `prev_issue_titles = []`, `verdict_path = []`, `critic_summaries = []`, `reasoning_audit_results = []`, `severity_history = []`, `prev_depth_rds = null`, `dialectic_issues_summary = null`, `turn = 0`.

3. **Loop** while `turn < MAX_TURNS`:

   a. Increment `turn`.

   b. **Invoke worker**: call the Agent tool with `subagent_type="research-worker"`.
      - On turn 1, prompt = the user's research task + a section that **literally injects an empty Self Coverage Plan template** as the very start of the worker's required output. Use this exact wrapper text (with `{user_research_task}` substituted):

        ```
        Research task: {user_research_task}

        ---

        ## STRICT OUTPUT START — fill in the template below verbatim

        Your response MUST begin with the following heading and table structure as the very first characters. Do NOT write any preamble, acknowledgment, or commentary before this heading — not "Acknowledged", not "I'll begin by", not a single word. The orchestrator runs a literal regex match `^## Self Coverage Plan\n` on the first non-whitespace line of your output. Any text before this heading triggers W1 gate failure and forces a full Turn 1 redo.

        Fill in the `[...]` placeholders with your own sub-questions BEFORE running any WebSearch — the plan drives the search, not the other way around. Sub-questions must be specific to this research task (if you can swap the topic and the sub-question still applies, it is too generic — replace it). Adequacy criteria must include at least one of: a specific number, a named entity, a required comparison, a required failure-case, or a time-anchor.

        Begin your response by completing exactly this template:

        ## Self Coverage Plan

        | # | 子问题 | 充分覆盖标准 |
        |---|--------|--------------|
        | C1 | [specific sub-question 1] | [adequacy criterion with verifier] |
        | C2 | [specific sub-question 2] | [adequacy criterion with verifier] |
        | C3 | [specific sub-question 3] | [adequacy criterion with verifier] |
        | C4 | [specific sub-question 4] | [adequacy criterion with verifier] |
        | C5 | [specific sub-question 5] | [adequacy criterion with verifier] |

        (rows C6, C7, C8 optional — total row count must be in [5, 8])

        After completing the SCP table, continue with `# Search Log`, `# Answer`, `# Evidence Table`, `# Source Contradictions`, `# What I Don't Know`, `# Assumptions Made` per your standard Turn 1 output format.

        **HARD GATE reminders (orchestrator-enforced)**:
        - W1: first heading must be exactly `## Self Coverage Plan` — no preamble.
        - W6: SCP table data rows must be in [5, 8].
        - W3: every FACT-labeled Evidence Table row must have a fetchable `https://` URL with a page path.
        ```

      - On turn > 1, prompt = the user's research task + a section "## Previous draft" containing `current_draft` + a section "## Critic feedback to address" containing `critic_feedback` + (if `coverage_matrix` is not null) a section "## Coverage Matrix (items still MISSING or PARTIAL must be addressed)" containing `coverage_matrix` + the instruction: "**HARD GATE**: your output MUST contain a top-level `# Rebuttals` section that explicitly takes a stance (ACCEPT / CHALLENGE / PARTIAL) on every Critic Issue and every Critic RD. The orchestrator will reject your output and require redo if `# Rebuttals` is absent."
      - Save the worker's returned output as the new `current_draft`.
      - **Mechanical Worker output gate (sanity check before invoking Critic)**: run W1–W6 in order. Any failure triggers redo (max 2 redos per turn). On final failure after 2 redos, manually annotate the deficiency in the Loop Summary and proceed (so the loop can continue and Critic can flag it).

        **Gate invocation (Bash tool)**: before running W1, write `current_draft` to `/tmp/rl-draft-t{turn}.md` via Bash tool (one write per turn, reused across all W-checks). Each gate below runs: `python3 ~/.claude/skills/research-loop/gates.py <gate> /tmp/rl-draft-t{turn}.md [turn]`. Parse output: first line `PASS` → gate passes; first line `FAIL` → lines 2+ are violation details, use them verbatim in the redo prompt's `[list of offending...]` placeholder. Blacklist patterns and allowed values are maintained in `gates.py` — no need to apply them manually.

      **Worker redo invariant injection** (when any W check triggers redo): build a "Cached invariants from prior attempt — preserve verbatim" block by extracting from the prior Worker output:
      - Self Coverage Plan table content (Turn 1; if it existed and isn't itself the failure source)
      - Search Log rows (queries actually run)
      - Answer section (if not failing)
      - Evidence Table rows whose Source URL is NOT on the W3 blacklist (only blacklist-hit rows may change)
      - Rebuttals sub-headings with already-valid Stance lines (Turn 2+)

      Prepend this block to the redo prompt with the standard preservation instruction (see "Turn-internal redo invariants" section above). After redo, run normalized comparison on each cached section: drift in any → another redo (counts toward max 2).

        **W1 — Self Coverage Plan heading (Turn 1 only)**: `gates.py w1 /tmp/rl-draft-t{turn}.md`. If `FAIL` → redo with prompt: "Your previous output was rejected because it did not start with `## Self Coverage Plan`. Redo Turn 1. Your output's very first heading must be `## Self Coverage Plan` — anything else fails the orchestrator gate. Here is your previous draft for reference (you may reuse the research, but you must add the Self Coverage Plan section at the top): \n\n[paste previous current_draft]". On final failure: prepend a stub `## Self Coverage Plan\n[Worker omitted this section despite gate; Critic should flag]` and proceed.

        **W2 — Rebuttals heading (Turn 2+)**: `gates.py w2 /tmp/rl-draft-t{turn}.md`. If `FAIL` → redo with: "Your previous output was rejected because it did not contain a `# Rebuttals` section. Redo this turn — you must take an explicit stance (ACCEPT/CHALLENGE/PARTIAL) on every prior Critic Issue and RD. Here is your previous draft: [paste]".

        **W3 — Source URL blacklist scan (every turn)**: `gates.py w3 /tmp/rl-draft-t{turn}.md`. Blacklist patterns (bare domain root, grounding redirects, SERP URLs, placeholder strings) and exempt labels (`[领域共识]`/`[DOMAIN]`/`[INFERENCE]`/`[推断]`) are defined in `gates.py`. Violations are returned as output lines 2+.

        If any non-exempt row hits the blacklist → redo with: "Your previous output was rejected because the following Source URLs in your Evidence Table are not valid (bare domain root, grounding redirect, SERP URL, or 'search summary' placeholder): [use lines 2+ from gates.py output verbatim]. For each, choose one: (a) replace with the actual page URL returned by WebSearch — character-for-character, no path infilling; (b) downgrade the claim to `[推断]` or `[领域共识]` with explicit scope and remove the URL; (c) if you cannot do either, drop the data point entirely (per Anti-pattern #8). Do NOT just relabel the existing URL with a different label and keep the same URL. Here is your previous draft: [paste]".

        **W4 — Rebuttals Stance per Issue/RD (Turn 2+)**: `gates.py w4 /tmp/rl-draft-t{turn}.md {turn}`. Valid stances: `## Issue [N]:` entries → `ACCEPT|CHALLENGE|PARTIAL`; `## RD [N]:` entries → `ACCEPT (...)|REJECT (...)`. Missing or invalid stance lines are returned as output lines 2+.

        If any sub-heading is missing the `Stance:` line OR the value doesn't match the allowed set → redo with: "Your previous output was rejected because the following Rebuttals entries are missing or malformed Stance lines: [use lines 2+ from gates.py output verbatim]. Each `## Issue [N]:` must have `- Stance: ACCEPT|CHALLENGE|PARTIAL`. Each `## RD [N]:` must have `- Stance: ACCEPT (mode)|REJECT (reason)`. Here is your previous draft: [paste]".

        **W5 — Track B engagement count (Turn 2+)**: `gates.py w5 /tmp/rl-draft-t{turn}.md {turn}`. Counts accepted RDs (ACCEPT stances) across `# Rebuttals` and `# Revision Log`, deduplicated; total must be ≥ 2.

        If count < 2 → redo with: "Your previous output was rejected because you engaged with fewer than 2 Critic Research Directions (Track B requires engaging at least 2 of the prior turn's RDs via INTEGRATE/CHALLENGE/EXPAND). Detected: [count from gate output] engagement(s). Add explicit engagement entries to your `# Rebuttals` and `# Revision Log` sections for the missing RDs. Here is your previous draft: [paste]".

        **W6 — Self Coverage Plan sub-question count (Turn 1 only)**: `gates.py w6 /tmp/rl-draft-t{turn}.md`. SCP table data rows must be in [5, 8] inclusive.

        If count < 5 or count > 8 → redo with: "Your previous output was rejected because the `## Self Coverage Plan` table has [N from gate output] sub-questions, but the required range is 5-8. A plan with fewer than 5 sub-questions is too coarse to act as a meaningful coverage standard; more than 8 dilutes the planning function and signals lack of synthesis. Re-issue Turn 1 with exactly 5-8 specific, verifiable sub-questions. Here is your previous draft: [paste]".

      - **Immediately extract `worker_rebuttals`** from `current_draft`: locate the `# Rebuttals` top-level section and capture its full body. If turn ≥ 2 and the section is missing (after the gate redo failed), set `worker_rebuttals = "MISSING — Worker did not produce a # Rebuttals section even after orchestrator gate redo. Critic must flag this as a critical Issue per its Worker Rebuttal Adjudication rule."` If the section exists but is empty, set `worker_rebuttals = "EMPTY — Worker explicitly accepted all prior Critic feedback. No challenges to adjudicate."` If turn = 1, `worker_rebuttals` remains null (Critic Turn 1 prompt does not include it).

   c. **Invoke 4 critics in parallel**: call the Agent tool four times simultaneously (all four calls in a single message):

      - **critic_instruction**: `subagent_type="research-critic-instruction"`, prompt:
        - On turn 1: `"Original task:\n\n" + <user task> + "\n\n---\n\nReview this draft:\n\n" + current_draft + "\n\n---\n\n**Note**: Worker submitted a \`## Self Coverage Plan\` at the top of the draft. Use it as input when generating your authoritative \`# Coverage Matrix\`."`
        - On turn 2+: `"Original task:\n\n" + <user task> + "\n\n---\n\n## Coverage Matrix (do not regenerate — use this for Coverage Verification)\n\n" + coverage_matrix + "\n\n---\n\n## Previous Deepening Questions (check whether Worker addressed ALL of these)\n\n" + prev_dq + "\n\n---\n\n## Previously verified URLs (Critic-self-verified prior turns ONLY)\n\n" + prev_url_verified_critic_only + "\n\n---\n\n## Worker Rebuttals this turn\n\n" + worker_rebuttals + "\n\n---\n\nReview this draft:\n\n" + current_draft`

      - **critic_dialectic**: `subagent_type="research-critic-dialectic"`, prompt:
        - All turns: `"Original task:\n\n" + <user task> + "\n\n---\n\nReview this draft for reasoning failures only:\n\n" + current_draft`

      - **critic_depth**: `subagent_type="research-critic-depth"`, prompt:
        - Turn 1: `"Original task:\n\n" + <user task> + "\n\n---\n\nReview this draft for depth gaps and write Research Directions:\n\n" + current_draft`
        - Turn 2+: `"Original task:\n\n" + <user task> + "\n\n---\n\n## Prior Research Directions (do not repeat these topics — write new directions):\n\n" + prev_depth_rds + "\n\n---\n\n" + (if dialectic_issues_summary is not null: "## Reasoning gaps found by dialectic critic (optional context for RD direction):\n\n" + dialectic_issues_summary + "\n\n---\n\n") + "Review this draft for depth gaps and write Research Directions:\n\n" + current_draft`

      - **critic_width**: `subagent_type="research-critic-width"`, prompt:
        - All turns: `"Original task:\n\n" + <user task> + "\n\n---\n\nReview this draft's Search Log for width gaps:\n\n" + current_draft`

      Wait for all four to complete. Save outputs as `critic_instruction_output`, `critic_dialectic_output`, `critic_depth_output`, `critic_width_output`.

      **Merge step** — build `critic_output` from the four outputs:
      1. Start with `critic_instruction_output` as the base (it contains VERDICT, Coverage Matrix, Coverage Verification, Deepening Questions, Critic WebFetch Audit, URL Verification Report, Worker Rebuttal Adjudication, instruction-level Issues with `I-` prefix, and 1-2 RDs)
      2. Find the `# Reasoning Audit` section in `critic_dialectic_output` and INSERT it into `critic_output` immediately before the `# Coverage Verification` section
      3. Find the `# Issues` section in `critic_dialectic_output`; append its `## Issue D-N:` sub-headings to the end of `critic_output`'s `# Issues` section
      4. Find the `# Issues` section in `critic_depth_output`; append its `## Issue E-N:` sub-headings to the end of `critic_output`'s `# Issues` section
      5. Find the `# Research Directions` section in `critic_depth_output`; append its RD entries to the end of `critic_output`'s `# Research Directions` section
      6. Find the `# Width Audit` section in `critic_width_output`; INSERT it into `critic_output` immediately after the `# Coverage Verification` section
      7. Find the `# Issues` section in `critic_width_output` (if present); append its `## Issue W-N:` sub-headings to the end of `critic_output`'s `# Issues` section

      The first line of `critic_output` remains `critic_instruction_output`'s VERDICT line (authoritative).

      **Extract dialectic issues summary** (for next turn's depth-critic context):
      From `critic_dialectic_output`, extract Issue titles and one-line problems from the `# Issues` section. Store as `dialectic_issues_summary` (compact format, 3-5 lines max).

      Save the merged result as `critic_output`.

   c.5. **Mechanical Critic gate (sanity check before parsing verdict)**:

      Run five checks against `critic_output` in order. Each failure triggers a redo (maximum 2 redos per turn). Check 1 (schema) runs first — without a valid output structure, the other checks have nothing meaningful to operate on. Check 5 (invariant drift) runs last — it only applies when a redo cache exists from a prior attempt this turn.

      **Critic redo invariant injection** (when any Check 1-4 triggers redo): build a "Cached invariants from prior attempt — preserve verbatim" block by extracting from the prior Critic output (the most recent attempt within this turn that produced the section):
      - `# Coverage Matrix` table (Turn 1 only; lock once generated)
      - `# Reasoning Audit` sub-checks (Y/N + quote/example for Specificity / Survivorship / Inference / Internal consistency)
      - `# Issues` (titles, where-quote, problem, severity, fix direction)
      - `# Research Directions` (titles, Critic's contribution body, Worker's task)
      - `# Critic WebFetch Audit` rows for URLs already Critic-fetched in prior attempt
      - `# URL Verification Report` rows for URLs already analyzed
      - `# Worker Rebuttal Adjudication` rulings already issued (Turn 2+)

      Exclude any section that IS the cause of the current gate failure (e.g., if Check 1 triggered because `# Coverage Matrix` was missing or malformed, do NOT include it in the cache — let the redo regenerate it correctly). For Check 2 (NOT FETCHED), exclude only the specific WebFetch Audit rows that were missing/incorrect; keep rows for already-fetched URLs cached.

      Prepend this block to the redo prompt with the standard preservation instruction (see "Turn-internal redo invariants" section above). After redo, Check 5 (below) runs the drift comparison.

      **Per-critic caching for Phase B redos**: When Phase B triggers a redo for a specific specialized critic (dialectic/depth/width), the redo prompt for THAT critic uses only that critic's own prior output as cached invariants. The other critics' outputs are not included in the redo prompt. Format the cached invariants heading as:

      `## Cached invariants from prior attempt (research-critic-{dialectic|depth|width}) — preserve verbatim`

      This scopes the invariant preservation to the individual critic's work, preventing cross-contamination.

      **Check 1 — Critic output schema completeness**:
      The Critic must produce all required top-level sections AND the required tables must have the right columns AND every Issue must have a parseable Severity. If any of these fails, the rest of the orchestrator pipeline (steps d/e/f) silently degrades — Worker receives empty/broken feedback, severity history loses signal, the Provenance filter in step e matches nothing, etc. Mechanical schema validation closes that gap.

      Required for **every turn** (heading must appear at the start of a line, exact match):
      - First non-empty line of `critic_output` must be exactly `VERDICT: PASS`, `VERDICT: REVISE`, or `VERDICT: FAIL` (no trailing punctuation, no leading prose, no inline qualifiers like "PASS conditional")
      - `# Reasoning Audit` heading must be present, AND the section must contain a line matching `Reasoning Audit result: CLEAN` or `Reasoning Audit result: ISSUES FOUND`
      - `# Coverage Verification` heading must be present
      - `# Issues` heading must be present (may contain "No issues this turn" content if PASS, but the heading itself is non-optional — this is what step e extracts)
      - `# Deepening Questions` heading must be present
      - `# Research Directions` heading must be present
      - `# Summary` heading must be present (1-2 sentence content; step f extracts a line from here)
      - `# Critic WebFetch Audit` heading must be present
      - `# URL Verification Report` heading must be present

      Required on **Turn 1 only** (additionally):
      - `# Coverage Matrix` heading must be present (consumed in step e to set `coverage_matrix` for all subsequent turns — missing it breaks every later turn)
      - **Coverage Matrix three-phase structure**: Critic Turn 1 must visibly produce three phases before the Final Coverage Matrix (per critic.md):
        - `## Stage A — Brainstorm` heading with ≥ 10 candidate sub-questions, each tagged `[Worker SCP C#]` or `[Critic add]`. **Mechanical count check**: count list items matching regex `^-\s+\[(Worker SCP C\d+|Critic add)\]` within the Stage A section; must be ≥ 10. Fewer than 10 → gate fail with reason `Stage A insufficient brainstorm: only N candidates listed, ≥ 10 required to force divergent thinking before commit`.
        - `## Stage B — Critique` heading with a markdown table running specificity + survivorship tests on each Stage A candidate. **Mechanical row check**: count data rows in the Stage B table; must equal Stage A candidate count (every Stage A candidate must appear in Stage B critique). Mismatch → gate fail.
        - `## Retention Map` heading with table mapping every Worker SCP row to RETAIN-AS-IS / RETAIN-REFINED / REJECT, plus a `Retention count: N retained / M rejected` line
        - `## Final Coverage Matrix` heading with the 5-8 row table

        Missing any of the four sub-headings → gate fail with reason `Missing Coverage Matrix phase: {Stage A | Stage B | Retention Map | Final Coverage Matrix}`. Forces Critic to do the brainstorm-critique-commit work visibly rather than skipping straight to a possibly-shallow final matrix.

      - **Coverage Matrix Worker SCP retention count**: parse the `## Retention Map` table; count rows whose Action column is `RETAIN-AS-IS` or `RETAIN-REFINED`. Count MUST be ≥ 3. Exception: if Critic provides a ≥ 100-character `Retention rationale` paragraph below the Retention Map explaining why fewer than 3 of Worker SCP rows were retainable, the orchestrator allows the lower count (otherwise Critic would never be able to override truly poor Worker SCPs). Without that explanation paragraph, retention < 3 is gate fail.

      - **Coverage Matrix adequacy verifier tags**: parse the `## Final Coverage Matrix` table. The schema must have a `Verifier tags` column. For each row:
        - The `充分覆盖标准 / adequacy` column must contain at least one of these mechanically-detectable verifier signatures:
          - **数字 / number**: any digit `\d` paired with a quantifier word (`至少`, `≥`, `≥=`, `>=`, `不少于`, `at least`, `minimum`)
          - **命名 / named**: phrase like `命名 ≥`, `列出 ≥`, `name ≥`, `list ≥`, or proper-noun list pattern
          - **比较 / comparison**: keywords `对比`, `比较`, `差异`, `vs`, `between`, `versus`
          - **反例 / failure-case**: keywords `失败案例`, `反例`, `反方`, `反驳`, `failure mode`, `counter`, `counterexample`
          - **时间锚 / time-anchor**: explicit year regex `\d{4}` or quarter `Q\d` or "至少 N 个时间节点"
        - The `Verifier tags` column must list ≥ 1 of `[数字]`, `[number]`, `[命名]`, `[named]`, `[比较]`, `[comparison]`, `[反例]`, `[failure-case]`, `[时间锚]`, `[time-anchor]` matching what's actually in the adequacy column.
        - If a row's adequacy column has no detectable verifier signature → gate fail with reason `Coverage Matrix row C{N} adequacy criteria has no mechanical verifier — must include at least one of [数字]/[命名]/[比较]/[反例]/[时间锚]`. Forces Critic to write measurable criteria.

        Also verify the table has the 5-column schema: `| # | 子问题 | 充分覆盖标准 | Origin | Verifier tags |`. Missing `Origin` or `Verifier tags` column → gate fail.

      Required on **Turn 2+ only** (additionally):
      - `# Worker Rebuttal Adjudication` heading must be present (no longer tolerated as "if present" — Critic must always adjudicate Turn 2+, even if the content is just "No rebuttals submitted." for an empty Worker `# Rebuttals` section)

      **Required table column structures** (parse the table immediately under each heading; verify the header row contains the named column literal — case-insensitive match):
      - `# Critic WebFetch Audit` table MUST have a `Tool used` column. The orchestrator's Check 4 (Playwright escalation) parses this column to detect missed escalations — if the column is absent, Check 4 is silently disabled. Missing this column is a gate fail.
      - `# URL Verification Report` table MUST have a `Provenance` column. The orchestrator's step e filter (`prev_url_verified_critic_only`) uses this column to drop Worker-claimed rows and pass only Critic-verified rows to the next turn — if the column is absent, the filter degrades to either passing all rows (allowing Worker-self-fetch laundering) or matching nothing (forcing wasteful re-fetch). Missing this column is a gate fail.

      **Required Issue severity labels**:
      - For each `## Issue [N]:` (or `## Issue X:`) sub-heading inside the `# Issues` section, the body must contain a line matching `Severity:` followed by exactly one of: `critical`, `major`, `minor` (case-insensitive). Other values (`blocker`, `trivial`, `low`, `high`, etc.) are gate fail.
      - This is consumed by step f to build `severity_history`, which step g2 (early-exit on diminishing returns) uses to decide auto-PASS. Malformed or missing Severity → severity counts default to 0 → step g2 may spuriously trigger. Mechanical validation prevents this.
      - Exemption: if the `# Issues` section explicitly contains the literal text "No material issues this turn" or "No issues this turn" with no `## Issue` sub-headings beneath it, Severity validation is skipped (zero issues by design).

      **Required content quality (P2 quality gates — these prevent skinny / placeholder content from passing)**:

      - **Coverage Verification quote per COVERED row**: parse the `# Coverage Verification` table. For each row whose Status column is `COVERED`, the Evidence column (last column) must contain a non-trivial direct quote: at least 10 non-whitespace, non-dash characters AND must contain either a `"..."` quote or `"..."` (Chinese quotes) pair OR an explicit phrase reference. A row with Evidence value of `—`, `-`, `n/a`, `N/A`, empty string, or only generic descriptive text without a quoted anchor is gate fail. Rows with Status `PARTIAL` or `MISSING` are exempt (they legitimately have no quote — they describe the gap).

      - **Deepening Questions count**: parse the `# Deepening Questions` section. Count items matching `^- DQ\d+:` or `^- DQ-T\d+-\d+:` or numbered list `^\d+\.` that look like questions. Count MUST be in [2, 3] inclusive. Fewer than 2 means Critic isn't pushing depth; more than 3 typically indicates list-padding rather than genuine probing.

      - **Research Directions count and substance**: parse the `# Research Directions` section. Count `**RD\d+:` or `## RD\d+:` sub-headings. Count MUST be in [2, 3] inclusive. For each RD, the "Critic's contribution" body (text between `**Critic's contribution**:` and the next sub-heading or `**Worker's task**:`) must be ≥ 300 non-whitespace characters AND must contain at least one specific concrete reference (number, named entity, technical term, or year). Skinny RDs (< 300 chars or generic abstract descriptions like "explore the trade-offs further") are gate fail — Critic's Role 2 (Research Accelerator) requires substantive content, not task assignments.

      - **Reasoning Audit four sub-checks**: parse the `# Reasoning Audit` section. The body MUST contain all four of these literal sub-check headings (substring match, case-insensitive):
        - `Check 1 — Specificity test` (or `Check 1: Specificity`)
        - `Check 2 — Survivorship bias` (or `Check 2: Survivorship`)
        - `Check 3 — Inference chain completeness` (or `Check 3: Inference chain`)
        - `Check 4 — Internal consistency` (or `Check 4: Internal consistency`)
        Each sub-check must be followed by an assessment line (e.g., `- Assessment: Y/N + ...` or `- Gap found: Y/N`). Missing any of the four sub-checks is gate fail — the result line `Reasoning Audit result: CLEAN/ISSUES FOUND` alone is insufficient evidence the audit was actually performed.

      Optional (no gate fail on absence):
      - `# Meta-concerns` (only present when cross-cutting patterns exist)
      - `# What's actually solid` (helpful but not consumed by orchestrator)

      If any required heading is missing, table column missing, Severity malformed, Coverage quote missing on COVERED rows, DQ count outside [2,3], RD count outside [2,3] or RD body too skinny, Reasoning Audit sub-checks missing, OR the first-line VERDICT is malformed: gate fail. Build a list of all problems and proceed to gate fail action with Check 1 hits populated.

      **Check 1 Phase B — Validate 3 specialized critics' raw outputs** (independent of merged critic_output):

      Run these checks on the raw outputs BEFORE the merge step. Each failure triggers redo of ONLY the failing critic (max 2 redos for that critic independently).

      **Phase B.1 — dialectic-critic output**:
      - Must contain `# Reasoning Audit` heading with all four sub-checks (`Check 1 — Specificity test`, `Check 2 — Survivorship bias`, `Check 3 — Inference chain completeness`, `Check 4 — Internal consistency`) and a `Reasoning Audit result:` line
      - Must contain `# Issues` heading (may contain "No reasoning issues found." but heading is non-optional)
      - Every `## Issue D-N:` sub-heading must have `Severity:` line with `critical | major | minor`
      - Failure → re-invoke `critic_dialectic` with redo prompt; do NOT re-run other critics

      **Phase B.2 — depth-critic output**:
      - Must contain `# Research Directions` heading with 2-3 RD entries
      - Each RD's `**Critic's contribution**:` body must be ≥ 300 non-whitespace characters
      - Must contain `# Issues` heading (may be empty)
      - Failure → re-invoke `critic_depth` with redo prompt; do NOT re-run other critics

      **Phase B.3 — width-critic output**:
      - Must contain `# Width Audit` heading (content may be "No width gaps" — heading is non-optional)
      - Failure → re-invoke `critic_width` with redo prompt; do NOT re-run other critics

      Phase B redo prompts follow the same cached-invariants pattern as Phase A (inject prior output's non-failing sections as cached invariants). Maximum 2 redos per failing critic per turn.

      After all Phase B checks pass, proceed with the merge step (above), then continue to Check 2.

      **Required headings updated** (in merged `critic_output` after merge): the following headings are now expected in merged output and must be verified by the existing Phase A heading check:
      - `# Reasoning Audit` (merged from dialectic — if merge step ran correctly, this must appear)
      - `# Width Audit` (merged from width — same)

      **Check 2 — Critic WebFetch Audit completeness**:
      1. Parse `# Critic WebFetch Audit` table from `critic_output`. (Heading existence already verified by Check 1; Check 2 verifies the table contents.)
      2. Build the set of "first-encounter URLs this turn":
         - From `current_draft`'s Evidence Table, take every row whose Source URL is `https://...` with a page path (i.e., contains `/` after the domain and the path is not just `/`)
         - Exclude URLs in the source-string blacklist (grounding redirects, SERP, "search summary" placeholders, vendor home roots — see Critic's blacklist)
         - Exclude URLs that appear in `prev_url_verified_critic_only` AND whose surrounding claim text in `current_draft` is unchanged (these are legitimately skippable)
         - The remaining URLs are first-encounter for this turn
      3. For each first-encounter URL, find its row in the Critic WebFetch Audit table. The row's status column must start with `Yes — Turn {current_turn}` (Critic personally fetched). Any of the following are gate fail:
         - URL is missing from the Audit table
         - Status starts with `No — NOT FETCHED`
         - Status starts with `Skipped` but the URL is NOT in `prev_url_verified_critic_only` (Skipped is only legal for already-Critic-verified URLs)

      **Check 3 — Prose self-admission of fetch failure**:
      Scan `critic_output` for any of these phrases (case-insensitive substring match):
      - "本应抓未抓" / "本应 fetch 但未 fetch" / "本应 fetch 未 fetch"
      - "Critic 自身失职" / "Critic 失职" / "Critic-self-failure" / "Critic should have fetched"
      - "下一轮必须补" / "下次必须补"（in context of fetching）
      - "未抓 — Critic" / "未 fetch — Critic"

      If any match: gate fail. Critic admitted in prose what it didn't do in the audit table — same effect as Check 2.

      **Check 4 — Suspicious WebFetch result not escalated to Playwright**:
      For each row in the Critic WebFetch Audit table, check whether the row exhibits a "soft failure" signal that should have triggered Playwright escalation:
      1. Parse the row's "Content supports claim?" column for these patterns (case-insensitive substring):
         - "Page not found" / "Article not found" / "Not Found"
         - "正在加载" / "数据不存在" / "已被删除" / "404"
         - "Please enable JavaScript" / "noscript" / "Loading..."
         - "currently being developed" / "coming soon" / "placeholder"
         - "Bulk Material Handling" or other obviously-unrelated SEO landing words (when the claim was about a different topic)
         - Body length explicitly noted as <500 chars or `body = ""` or "empty body"
      2. If any of these patterns matches AND the row's "Tool used" column does NOT contain "Playwright" (i.e., Critic used WebFetch only and got a suspicious result, but didn't escalate): gate fail.
      3. Exclusions (do NOT trigger gate fail):
         - HTTP status is hard ✗ 404 / ✗ 500 (real server failure, Playwright won't help)
         - Tool used already shows "WebFetch + Playwright (escalated)" with both attempts failing (escalation was attempted)
         - URL is on the source-string blacklist (no point fetching either way)

      **Check 5 — Invariant drift detection (only applies when a redo cache exists from prior attempt this turn)**:

      If this Critic attempt is a redo (i.e., orchestrator triggered redo for Checks 1-4 and injected cached invariants in the redo prompt), verify each cached section was preserved verbatim in the current output.

      **Core comparison rule** (applies to all cached sections):

      1. For each cached invariant section, extract the corresponding section from the current `critic_output`.
      2. Normalize whitespace on both cached and current content (collapse multiple spaces/tabs to single space, trim trailing whitespace per line, strip leading/trailing blank lines from sections).
      3. Compare the normalized strings.
      4. If any cached section differs from current section beyond minor markdown formatting tolerance (e.g., bold markers, table alignment changes are OK; sub-question text changes, severity changes, RD body content changes, fetched URL status changes are NOT OK):
         - Gate fail with reason: `Invariant drift detected: {section name}. Prior attempt content differs from current attempt content. Critic regenerated instead of preserving.`
         - Trigger redo (counts toward max 2).

      **Specific drift cases that always trigger fail (extends the core rule)**:

      ### 5a — Reasoning Audit structural stability

      Check that `# Reasoning Audit` section is present and contains all four sub-check headings (`Check 1`/`Check 2`/`Check 3`/`Check 4` lines). Do **NOT** compare exact content, quotes, or Y/N assessments across redos — Critic may legitimately refine findings when fixing an adjacent gate failure.

      Drift fail if: `# Reasoning Audit` section disappears entirely, OR the count of sub-check headings drops below 4.

      ### 5b — URL Verification Report URL-set preservation

      Check that every URL present in the cached `# URL Verification Report` still appears in the current report. Do **NOT** check that HTTP Status, Provenance, or Action fields are unchanged — Critic may legitimately update these fields when re-fetching or fixing Check 2/3/4 failures.

      Drift fail if: any URL from the cached set is absent from the current attempt (URL removed or replaced with a different URL). Adding new URLs to the report is always allowed.

      ### 5c — Issues heading stability

      Check that every `## Issue N` heading from the cached attempt is still present in the current attempt (unchanged or annotated with `Withdrawn:`). Do **NOT** check body content — Critic may update Fix Direction, refine severity wording, or expand the Problem description when addressing another gate failure.

      Drift fail if: a cached `## Issue N` heading disappears entirely without a `Withdrawn:` annotation. Adding new `## Issue N+1` headings is always allowed.

      ### Existing specific drift cases (preserved from prior patch)

      - Coverage Matrix sub-question text changed (Turn 1 only; affects all downstream turns)
      - Issue severity changed without explicit Worker rebuttal acceptance
      - RD body's substantive content changed (e.g., named entity / number / framework switched)
      - Already-Critic-verified URL status changed from `Yes — Turn N` to anything else

      ### When Check 5 has no cached invariants to verify

      If this is the first Critic attempt this turn (no prior cache), Check 5 is a no-op pass.

      ### Override hatch — `## Cached invariant override`

      Critic may have a legitimate reason to revise cached content (e.g., discovered prior analysis was wrong, found new evidence that contradicts a prior Issue, realized a URL verification was based on misreading the page). For these cases, Critic adds a `## Cached invariant override` section to the output explicitly listing each override:

      ```
      ## Cached invariant override

      - Section: # Reasoning Audit, Check 4 (Internal consistency)
        Cached content: "Contradiction found: N"
        Current content: "Contradiction found: Y — Ford 12.5h vs history.com 9h54min unreconciled"
        Reason: re-fetched history.com this turn, discovered numeric mismatch missed in prior attempt
      - Section: # URL Verification Report, row 7 (history.com)
        Cached content: "Yes — 12.5h confirmed"
        Current content: "No — page actually says 9h54min, not 12.5h"
        Reason: more careful read on re-fetch revealed prior fetch result was misread
      ```

      Each override entry must specify: section name, cached vs current excerpt, **specific reason** (not "I changed my mind" — must reference new information / re-fetch / explicit error correction).

      **Override quality validation** (mechanical):
      - Each override entry's Reason field must be ≥ 30 characters AND contain at least one specific signal:
        - Re-fetch evidence (`re-fetch`, `re-fetched`, `重新 fetch`, `WebFetch returned`)
        - New information (`discovered`, `found that`, `realized`, `发现`, `新证据`)
        - Error correction (`misread`, `误读`, `wrong page`, `prior fetch was incorrect`)
        - Worker rebuttal acceptance (`Worker rebuttal ACCEPTED`, `Worker pointed out`)
      - Reason fields lacking these signals (e.g., `on reflection`, `I think this is better`, `更合理`, `重新考虑后`) are weak overrides → orchestrator treats them as silent drift, rejects override, redo triggered.

      Check 5 processing with overrides:
      1. Build the standard cached vs current comparison report (5a/5b/5c).
      2. For each detected drift, look up whether it's covered by a `## Cached invariant override` entry with valid quality signal.
      3. If covered with valid override: accept the drift, mark `Override accepted: {reason snippet}` in turn log.
      4. If covered but Reason lacks quality signal: reject override, treat as drift fail.
      5. If not covered at all: drift fail as before.

      This prevents two failure modes:
      - **Silent drift** (Critic regenerates without flagging): Check 5 catches; redo required.
      - **Excessive lock-in** (orchestrator rejects legitimate revision): Override hatch provides explicit channel; reasonable revisions accepted.

      ### Implementation note for orchestrator

      For each of 5a / 5b / 5c, build a structured comparison report listing:
      - Section/URL/Issue identifier
      - Cached content excerpt (first 80 chars)
      - Current content excerpt (first 80 chars)
      - Match status (PASS / DRIFT / OVERRIDE-ACCEPTED)

      Report DRIFT entries (without accepted overrides) in the redo prompt under a `## Check 5 drift findings` block so Critic sees specifically what to restore. Report OVERRIDE-ACCEPTED entries in the turn log only (no redo trigger).

      **Gate fail action (any of Checks 1–5)**: do NOT proceed to step d (verdict parsing). Re-invoke Critic with this redo prompt:

      ```
      **ORCHESTRATOR CRITIC GATE FAILURE — your previous output had verification, schema, or invariant-drift gaps.**

      The orchestrator detected the following issues:
      {Check 1 hits, if any: list of missing required sections / column structures / Severity / quality issues}
      {Check 2 hits, if any: list of unfetched URLs}
      {Check 3 hits, if any: quoted prose admission}
      {Check 4 hits, if any: list of URLs where WebFetch returned suspicious content but Playwright escalation was skipped}
      {Check 5 hits, if any: list of cached invariant sections that drifted from prior attempt — Critic regenerated instead of preserving}

      ## Cached invariants from prior attempt — preserve verbatim

      The orchestrator caches the sections below from your prior attempt. **These are NOT suggestions or starting points — they are required content that must appear in your redo character-for-character (modulo trailing whitespace and minor markdown formatting like bold markers / table alignment).**

      The following sections were marked NON-INVARIANT for this redo because they were the source of the gate failure: {list e.g., "# Coverage Matrix" if Check 1 found it malformed}. You may regenerate ONLY these specific sections.

      All OTHER sections below MUST be preserved verbatim. Specifically:

      **What "preserve verbatim" means in practice (read carefully)**:

      - `# Reasoning Audit`: if your prior attempt had `Specificity test - Claim A: "Highland Park 1913 流水线..." Claim B: "Model T 装配..." Claim C: "Paul David 1990..."`, your redo MUST list THE SAME 3 claims. Do not pick different claims to test. Do not change Y/N assessments. Do not switch which sub-check found issues. The Reasoning Audit is your analysis of the Worker draft — it doesn't change just because you needed to add a missing column elsewhere.

      - `# URL Verification Report`: if your prior attempt verified URLs A, B, C, D, your redo MUST include A, B, C, D with the same HTTP Status / Provenance / Supports claim? / Action. You may ADD URLs E, F, G if you fetched additional ones in this redo, but you cannot REPLACE A with A' (e.g., jstor.org/stable/2120991 → jstor.org/stable/2120731 is replacement, not addition). Each cached URL row's content must match — only the Provenance column may upgrade from "Worker-claimed" to "Critic-verified Turn N" if you re-fetched.

      - `# Issues`: if your prior attempt had `## Issue 1: 福特数字与可验证来源不符` and `## Issue 2: F23 URL 失效`, your redo MUST keep `## Issue 1` and `## Issue 2` with the same titles, severity, and body content. New issues found this redo go to `## Issue N+1`, `## Issue N+2` ... — never renumber existing ones. If you want to withdraw a cached Issue, mark it `Withdrawn: <reason>` rather than deleting.

      - `# Research Directions`: cached RD titles + Critic's contribution body + Worker's task must remain. Substantive content (named authors / works / years / numbers / mechanisms) cannot be swapped for different ones.

      - `# Coverage Matrix` (Turn 1): the Final Coverage Matrix table is the cross-turn anchor. Every row's sub-question text and adequacy criteria must be preserved. Same for Stage A / Stage B / Retention Map (these are also cached unless Coverage Matrix itself was the failure source).

      - `# Critic WebFetch Audit`: cached rows for already-fetched URLs preserved; you may add rows for newly-fetched URLs.

      **Test for whether you're regenerating instead of preserving**: ask yourself "if I had access to the prior attempt's text and wanted to copy this section, would I copy it character-for-character?" If your redo's section reads differently, you're regenerating.

      The orchestrator runs Check 5 (drift detection) on your redo, with sub-checks 5a (Reasoning Audit content), 5b (URL Verification row preservation), 5c (Issues numbering/content). Drift in any of these triggers another redo (counts toward max 2). If you have a substantive reason to override cached content (e.g., you discovered prior analysis was wrong), explicitly add a section `## Cached invariant override` listing what you changed and why — this signals intentional revision rather than careless drift, and the orchestrator will accept your reasoning if specific.

      Cached sections (preserve verbatim unless listed as NON-INVARIANT above):

      {Cached # Coverage Matrix content, if applicable}
      {Cached # Reasoning Audit content, if applicable}
      {Cached # Issues content, if applicable}
      {Cached # Research Directions content, if applicable}
      {Cached # Critic WebFetch Audit rows for already-fetched URLs, if applicable}
      {Cached # URL Verification Report rows for already-analyzed URLs, if applicable}
      {Cached # Worker Rebuttal Adjudication rulings, if applicable (Turn 2+)}

      ## Action required for the gate failures
      ```

      ```
      **ORCHESTRATOR CRITIC GATE FAILURE — your previous output had verification or schema gaps.**

      The orchestrator detected the following issues:
      {Check 1 hits, if any: list of missing required sections — each section must appear in the redo with non-empty content}
      {Check 2 hits, if any: list of unfetched URLs}
      {Check 3 hits, if any: quoted prose admission}
      {Check 4 hits, if any: list of URLs where WebFetch returned suspicious content but Playwright escalation was skipped}

      Action required:
      1. For Check 1 hits (schema/column/severity/quality gaps): re-issue your full critic_output addressing each specific problem:
         - Missing required headings: re-issue with EVERY required heading present. Even sections with nothing to report (e.g., `# Issues` when verdict is PASS) must appear with explicit content like "No material issues this turn." A bare heading with no body is acceptable; a missing heading is not.
         - Malformed first-line VERDICT: ensure the very first non-empty line is exactly `VERDICT: PASS`, `VERDICT: REVISE`, or `VERDICT: FAIL` — no preamble, no qualifier, no trailing punctuation.
         - Missing `Tool used` column in `# Critic WebFetch Audit` table: re-issue the table with the 6-column schema: `| # | URL | Tool used | WebFetch/Playwright called by Critic in this session? | Raw HTTP status | Content supports claim? |`
         - Missing `Provenance` column in `# URL Verification Report` table: re-issue with the 5-column schema including `Provenance` (values: `Critic-verified Turn N`, `Worker-claimed (NOT yet Critic-verified)`, or `Critic-verified Turn N-X (skipped this turn, claim unchanged)`).
         - Malformed Issue Severity: each `## Issue` sub-heading must have a `Severity:` line with value `critical`, `major`, or `minor`. Replace any other values (e.g., `blocker`, `trivial`, `low`, `high`) with the closest valid option.
         - Coverage Verification rows missing quotes on COVERED items: each COVERED row's Evidence column must contain a real direct quote from the draft (≥10 chars + quote marks or specific phrase reference). Replace `—` / `n/a` / generic descriptions with the actual quoted anchor.
         - DQ count outside [2,3]: produce exactly 2 or 3 Deepening Questions — fewer than 2 means insufficient depth probing; more than 3 means list-padding. Pick the most-substantive 2-3.
         - RD count outside [2,3] or RD body skinny: produce exactly 2 or 3 Research Directions, each with ≥300 chars of substantive content (concrete numbers, named entities, technical mechanisms). Generic task descriptions like "explore X further" do not count — Role 2 requires actual research content.
         - Reasoning Audit sub-checks missing: include all four sub-headings (Check 1 — Specificity test, Check 2 — Survivorship bias, Check 3 — Inference chain completeness, Check 4 — Internal consistency), each with an assessment line. The result line alone is insufficient — orchestrator needs evidence each check was actually performed.
         - Coverage Matrix three-phase structure missing (Turn 1): produce the four sub-headings in order — `## Stage A — Brainstorm` (≥10 candidates), `## Stage B — Critique` (specificity + survivorship table), `## Retention Map` (Worker SCP disposition table + count line), `## Final Coverage Matrix` (5-column table including `Origin` and `Verifier tags`).
         - Coverage Matrix Worker retention < 3 (Turn 1): preserve at least 3 of Worker's SCP sub-questions as RETAIN-AS-IS or RETAIN-REFINED. If you genuinely think Worker's plan is unusable, write a ≥ 100-character `Retention rationale` paragraph explaining why; without it, you must increase retention.
         - Coverage Matrix adequacy missing verifier (Turn 1): every row's `充分覆盖标准` column must contain at least one mechanically-detectable verifier ([数字]/[命名]/[比较]/[反例]/[时间锚]). Replace vague phrases like "深入讨论" / "充分覆盖" / "给出关键问题" with measurable criteria like "至少 3 个具体年份事件" / "命名 ≥ 2 家代表玩家" / "对比 ≥ 2 个相反框架" / "≥ 1 个具名失败案例及死因".
         The orchestrator scans heading literals, table column headers, Severity values, Coverage quotes, DQ count, RD count + body length, Reasoning Audit sub-check presence, Coverage Matrix three-phase headings, retention count, and adequacy verifier tags on redo — any of these missing again triggers another redo (max 2).
      2. For Check 2/3 hits (URL fetch gaps): call WebFetch on each unfetched URL (one fetch per URL). If unreachable, mark `✗ 404` / `✗ 500` / `✗ timeout` and corroborate via alternative source.
      3. For Check 4 hits (suspicious WebFetch): WebFetch returned a soft-failure signal (placeholder text, JS shell, "Not Found" body with HTTP 200, etc.) for these URLs. Use Playwright to re-verify:
         - `mcp__plugin_playwright_playwright__browser_navigate` to the URL
         - `mcp__plugin_playwright_playwright__browser_wait_for` for 2-3 seconds (let JS render)
         - `mcp__plugin_playwright_playwright__browser_snapshot` to get rendered accessibility tree
         - Check if the rendered content actually matches the claim's expected anchor
         - If Playwright also shows missing content: the URL is genuinely fabricated/dead — mark `✗ content mismatch (verified by Playwright)` and downgrade the claim
         - If Playwright recovers the content: mark `✓ Playwright-recovered` and update the row's Tool used to `WebFetch + Playwright (escalated)`
      4. Re-issue your full critic_output with the updated `# Critic WebFetch Audit` and `# URL Verification Report` tables. Provenance for newly verified URLs should be `Critic-verified Turn {current_turn}`.

      The orchestrator will run all four gates again on your redo. Maximum 2 redos per turn.

      Original task: {original task}
      Worker draft: {current_draft}
      ```

      Replace `critic_output` with the redo result and re-run all four gates. Maximum 2 redo attempts per turn — if any gate still fails after 2 redos, manually annotate the orchestrator's turn log with `Critic-gate-failed-after-2-redos: {description of which gate(s) and what failed}` and proceed to step d (so the loop can continue), but treat this turn's verdict as REVISE regardless of what Critic wrote.

      **Why the four-gate design**: empirically observed failure modes — (Check 1) Critic returning malformed output with missing required sections, causing orchestrator step e to build degraded critic_feedback that propagates broken state to next turn; (Check 2) Critic inheriting Worker's "I fetched it" claims without independent verification; (Check 3) Critic admitting in prose it didn't fetch but issuing PASS anyway; (Check 4) Critic using WebFetch only, getting a soft 404 / JS shell / SEO rotation page, recording it as failed but not trying Playwright when the URL might be genuinely valid behind JS rendering. Each gate closes one mode; together they make the verdict process tamper-resistant against LLM shortcuts and structural omissions.

   d. **Parse verdict**: read the first non-empty line of `critic_output`. After Check 1 (schema completeness) has passed in step c.5, this line is guaranteed to be exactly `VERDICT: PASS`, `VERDICT: REVISE`, or `VERDICT: FAIL`.
      - Defensive fallback (should be unreachable if c.5 ran correctly): if somehow the first line is malformed despite c.5 passing, log "malformed verdict despite c.5 — orchestrator bug" and treat as REVISE.

   e. **Extract critic feedback for worker, and worker rebuttals for next critic**:

      **From `critic_output`** (build `critic_feedback` for the NEXT Worker turn):
      - On Turn 2+: include the full `# Worker Rebuttal Adjudication` section (Check 1 enforces presence; missing means Critic was redone — by this point in step e the section exists)
      - Include the full `# Coverage Verification` section — Worker sees which Matrix items are still MISSING or PARTIAL and must address them
      - Include the full `# Deepening Questions` section — Worker must address these proactively in the next turn
      - Include the full `# Issues` section
      - Include the full `# Research Directions` section (including Critic's substantive contributions for each RD)
      - Include the full `# Meta-concerns` section (genuinely optional — only present if Critic identified cross-cutting patterns; skip if absent)
      - Append a **dead link list**: scan `# URL Verification Report` for rows where HTTP Status is `✗ 404`, `✗ 500`, `✗ timeout`, or `✓ 200 but content mismatch`. For each dead URL, add: `Dead link: {URL} — find alternative source.`
      - Do NOT include the `# URL Verification Report` table in full, nor `# What's actually solid`, nor `# Reasoning Audit`. Store the result as `critic_feedback`.

      **From `critic_output`** (build state for the NEXT Critic turn):
      - `prev_url_verified_critic_only`: extract the `# URL Verification Report` table verbatim (byte-for-byte from `critic_output`), then keep only rows whose `Provenance` column literally starts with `Critic-verified`. Drop any row whose Provenance is `Worker-claimed (NOT yet Critic-verified)` or any other non-Critic-verified label. The next Critic turn will only skip re-fetch on URLs in this filtered table.
      - `prev_dq`: the full `# Deepening Questions` section, extracted verbatim (so next Critic can verify DQ coverage independently of Worker's Revision Log).
      - `prev_depth_rds`: from `critic_depth_output` (NOT from merged `critic_output`), extract the `# Research Directions` section — specifically the `**RD1/RD2/RD3:** [title]` lines (titles only, not the full body). Store as a compact list of RD titles (3-6 lines). Passed to the next turn's `critic_depth` prompt as `## Prior Research Directions (do not repeat)` to prevent the depth critic from proposing the same directions as prior turns.

      - `dialectic_issues_summary`: from `critic_dialectic_output`, extract `## Issue D-N:` sub-headings and their one-line `- **Problem**:` text. Format as a compact 3-5 line summary. Passed as optional context to next turn's `critic_depth` prompt.
      - On turn 1 only: extract the `## Final Coverage Matrix` sub-section (the 5-8 row table inside `# Coverage Matrix`, not the Stage A/B/Retention Map audit trail) verbatim and save as `coverage_matrix` (used in all subsequent Worker and Critic prompts). **Verbatim means byte-for-byte from the `## Final Coverage Matrix` sub-heading through the last table row — no paraphrasing, no condensing, no whitespace normalization, no orchestrator-side rewriting. The next Critic turn's prompt will include this exact text under `## Coverage Matrix (do not regenerate — use this for Coverage Verification)`. Any orchestrator-side editing here breaks the cross-turn invariant chain — empirically observed in the 1880-1930 electrification test where the orchestrator condensed the Critic's Coverage Matrix into a different summary version, causing untrackable drift. The Stage A brainstorm + Stage B critique + Retention Map remain in Critic Turn 1's `critic_output` for the audit trail (and are visible in the final loop report) but are NOT propagated into the cross-turn `coverage_matrix` state — they served their purpose at Turn 1 and downstream turns only need the committed Final Matrix.**

      **Note on `worker_rebuttals`**: this is extracted in step b (when the Worker draft is produced), not here in step e. By the time you reach step e, `worker_rebuttals` for the next iteration is already set; your job in step e is only the Critic-output-derived state.

      **Reasoning Audit log**: every turn, extract the `Reasoning Audit result:` line from `critic_output`. Save this as `reasoning_audit_result` for this turn.

   f. **Record**: append verdict to `verdict_path`; append a 1-line summary from the critic's `# Summary` section to `critic_summaries`; append `reasoning_audit_result` to `reasoning_audit_results`. Also count Issues by severity in this turn's `# Issues` section: append `{turn: N, critical: X, major: Y, minor: Z}` to `severity_history`.

   g. **Cycle check** (skip on turn 1): extract the `## Issue` titles from the current `critic_output`. Compare with `prev_issue_titles` (the titles saved from the **previous** turn — not yet overwritten this turn). If ≥ 70% of titles are identical (same problems recurring after a revision), override to FAIL with reason: "Loop stuck: same issues recurring after revision — worker is not making progress." Then update: `prev_issue_titles` = current turn's issue titles.

   g2. **Early-exit on diminishing returns** (skip on turn 1 and turn 2; only applies turn ≥ 3): if `verdict` is REVISE but the last 2 turns (current and previous) both have `critical: 0` AND `major: 0` in `severity_history`, override to PASS with reason: "Two consecutive turns produced only minor issues — the loop has converged on the achievable depth. Remaining minors are listed in `# What I Don't Know`." Append all current minor Issues into the final draft's `# What I Don't Know` section before producing Final output.

   h. **Branch**:
      - `PASS` → break the loop
      - `FAIL` → break the loop (including cycle-detected FAIL from step g)
      - `REVISE` → `critic_feedback` already set in step e; continue to next turn

   **PASS 权限检查（每轮强制）**：在执行 Branch 之前，确认 `critic_output` 的第一个非空行确实是 `VERDICT: PASS`。如果你发现自己准备写 Loop Summary 但无法找到这行文字——说明你跳过了 Critic 调用。立即回到步骤 c，补调 Critic，再继续。

3.5. **Draft Acceptance Criteria (DAC) — fallback only when Critic was never invoked**:

DAC exists as a single-purpose safety net: if `verdict_path` is empty (orchestrator skipped step c entirely), check whether the draft is publishable on its own. **If `verdict_path` contains any Critic verdict, DAC does not run** — the Critic's verdict is authoritative.

DAC is a mechanical check, not a judgment. Each criterion is either ✓ or ✗ — there is no partial credit, no "honest disclosure" override. If you can't fill in the table with concrete evidence per criterion, return to step c and call the Critic.

| # | Criterion | Pass test |
|---|-----------|-----------|
| C1 | Every [事实·强]/[FACT] claim has a fetchable `https://` URL with page path (not bare domain, not blacklisted source — see Critic's source blacklist) | Scan Evidence Table |
| C2 | Search Log has ≥ 8 rows whose `Top result URL` is a real `https://` URL (no blacklisted sources) | Count rows |
| C3 | No source-string blacklist hits anywhere (no grounding redirects, no "search summary" placeholders, no SERP URLs, no search-track labels, no vendor home pages anchoring vendor-specific claims) | Scan Evidence Table + Search Log |
| C4 | At least one section explicitly discusses failure cases, counterarguments, or limitations (more than a one-line disclaimer) | Read Answer section |
| C5 | Evidence quality ratio: count Evidence Table rows by label. **([事实·强] count) / (total rows)** must be ≥ 25%. Counter to "downgrade-everything-to-pass" gaming: a draft cannot achieve DAC PASS by relabeling all FACT claims to [事实·弱]/[推断]. Hard data must remain. | Count rows by label |

**Branch**:
- All five ✓ → write `VERDICT: PASS (DAC)` in Loop Summary, document each criterion's evidence in the DAC Result table.
- Any ✗ → return to step c and invoke Critic. The Agent tool is always available in the main session.

The only legal verdict strings in this skill are: `PASS (Critic)`, `PASS (DAC)`, `REVISE at MAX_TURNS`, `FAIL`. Anything else is a fabrication.

4. **After loop ends** (whether by break or by hitting MAX_TURNS), produce the Final output described below. This output is mandatory — do not skip it.

## Final output to user

After the loop ends, produce **this exact structure**. Loop Summary is mandatory; the DAC Result table appears only on the PASS (DAC) path.

```
# Final Answer

[The final draft from the worker, verbatim — do not paraphrase, do not reformat]

<!-- LOOP_METADATA_START -->

---

# Loop Summary

- Turns used: N/MAX_TURNS   (e.g. "3/10")
- Final verdict: PASS (Critic) | PASS (DAC) | PASS (Early-exit) | REVISE at MAX_TURNS | FAIL
- Verdict path: REVISE → REVISE → PASS   (arrow-joined list; if DAC direct pass, write "DAC-PASS")
- Severity history: Turn 1 [crit:X maj:Y min:Z] → Turn 2 [...] → ...

## DAC Result (only present when Final verdict is `PASS (DAC)`)

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| C1 | All [事实·强] have fetchable URLs | ✓ / ✗ | [specific count + sample URLs] |
| C2 | Search Log ≥ 8 rows with real URLs | ✓ / ✗ | [row count] |
| C3 | No blacklisted sources | ✓ / ✗ | [scan result] |
| C4 | Failure-case / counterargument / limitations section | ✓ / ✗ | [section heading] |
| C5 | [事实·强] / total ≥ 25% | ✓ / ✗ | [N/M = X%] |

## Verdict explanation

- **PASS (Critic)**: Draft approved on turn N. Critic verdict is the authority; DAC is not invoked.
- **PASS (DAC)**: Critic was never invoked (orchestrator-skipped path); DAC mechanical check passed all five criteria. Evidence in DAC Result table above.
- **PASS (Early-exit)**: Turn N produced REVISE but step g2 detected two consecutive turns with zero critical/major issues. Remaining minor issues were appended to `# What I Don't Know`.
- **REVISE at MAX_TURNS**: Hit MAX_TURNS without converging. Unresolved issues from final critic output: [paste unresolved Issues].
- **FAIL**: Fundamental flaw. Reason: [paste critic's summary of the fundamental problem].

---

# Turn-by-turn log

[One bullet per turn, format: "Turn N (verdict | reasoning_audit | crit:X maj:Y min:Z): 1-line summary from critic's # Summary"]

- Turn 1 (REVISE | CLEAN | crit:0 maj:5 min:2): ...
- Turn 2 (REVISE | ISSUES FOUND | crit:1 maj:3 min:0): ...
- Turn 3 (PASS | CLEAN | crit:0 maj:0 min:1): ...
```

**Enforcement**: If you find yourself writing "Final Answer" without a "Loop Summary" below it, you have failed your routing job. The Loop Summary is how the user verifies the loop actually ran.

## Discipline

- **No research yourself.** This skill's job is routing. If you catch yourself producing analysis or running WebSearch, stop — that's the worker's job.
- **No editing worker output.** Pass it through verbatim. Do not paraphrase, do not reformat.
- **No overriding the critic.** If critic says REVISE, loop. The only legal early termination is step g2 (early-exit on diminishing returns), which has explicit numeric criteria.
- **DAC is fallback only.** Run DAC only when `verdict_path` is empty (Critic was never called). If Critic was called, the Critic's verdict is authoritative.
- **PASS has three valid paths**: (a) Critic issues `VERDICT: PASS` as first line of `critic_output`; (b) DAC five-criteria check passes when Critic was never invoked; (c) Step g2 early-exit when 2 consecutive turns produced zero critical/major issues. Any other path is a fabrication.
- **Respect MAX_TURNS.** Never loop past MAX_TURNS. If not passing by then, the task needs human attention, not more iteration.
- **Fail fast on FAIL verdict.** Don't try to rescue a fundamentally broken draft by looping — report and stop.
