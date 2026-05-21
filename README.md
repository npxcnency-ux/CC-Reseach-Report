# cc-research-report

A Claude Code skill that runs a worker↔critic adversarial research loop and renders the verified output as a design-driven HTML report.

> 中文文档见 [README.zh.md](./README.zh.md)

---

## Install

```bash
git clone <this-repo-url>
cd cc-research-report
./install-local.sh     # symlinks skills/ and agents/ into ~/.claude/
# Restart Claude Code to load.
./uninstall-local.sh   # to remove
```

**Requires:** [`frontend-design` plugin](https://github.com/anthropics/claude-plugins-official) — install it before using this skill:

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install frontend-design
```

---

## Usage

Invoke from any Claude Code session:

```
/research-report AI对教育的影响
/research-report "impact of AI on education"
/research-report What are the key risks of agentic AI systems? max_turns: 6
```

**Outputs:**

| File | Description |
|------|-------------|
| `./{title}-report.html` | Design-driven HTML report in current directory |
| `~/.claude/cache/research-loop/{slug}-{timestamp}.md` | Verified markdown + loop summary (audit trail) |
| `~/.claude/cache/research-loop/{slug}-{timestamp}-query.md` | Original question |

**Re-render without re-researching** — point `research-html-formatter` at the cached `.md` file directly. Research cost is paid once; visual redesigns are free.

**Cache behavior** — if you ask a similar question within 7 days, the skill offers to reuse the cached research and skip straight to HTML rendering.

---

## How It Works

```
/research-report "your question"
        ↓
[Step 0] Cache check — reuse if ≤7 days old
        ↓
[Step 1] research-loop (up to 10 turns)
  ┌─ Worker: plan → search → draft → self-audit
  │    Turn 1: commits to Self Coverage Plan (5–8 sub-questions) before searching
  │    Turn 2+: rebuts every critic issue (ACCEPT / CHALLENGE / PARTIAL)
  │
  └─ 4 Critics in parallel (every turn):
       instruction  →  coverage matrix + URL verification + VERDICT
       dialectic    →  reasoning audit (specificity, bias, inference chain, consistency)
       depth        →  depth gaps + new research directions
       width        →  search log audit (uncovered tracks)
        ↓
  Repeat until VERDICT: PASS or max_turns reached
        ↓
[Step 1.5] Verified markdown written to ~/.claude/cache/research-loop/
        ↓
[Step 2] research-html-formatter
  → calls frontend-design skill first (mandatory)
  → commits to a named aesthetic direction
  → writes HTML to disk
        ↓
[Step 2.5] Design enforcement gate
  → verifies "Design direction:" line with specific aesthetic descriptor
  → re-runs formatter on failure (max 2 retries)
```

---

## Design Philosophy

**1. Adversarial validation, not self-review.**
The worker never critiques its own work. Four critics each own a narrow audit axis — no single agent tries to do everything. This mirrors how rigorous human review works: separate reviewers for separate concerns.

**2. Mechanical gates over prompt instructions.**
LLMs reliably skip structural requirements when asked nicely. Every critical invariant — Self Coverage Plan heading, Rebuttal stances, source URL format — has an orchestrator-level gate that forces a redo on failure. The CHANGELOG documents ~20+ patches all following the same pattern: *prompt failed → add a gate*.

**3. Turn-internal redo invariants.**
When a gate triggers a redo, unchanged sections are cached, injected verbatim, and validated for drift. This prevents the model from "fixing" one row while silently regenerating nine correct ones differently.

**4. Claim labeling as first-class output.**
Every claim in the final answer carries an explicit epistemic label: `[FACT·Strong]`, `[INFERENCE]`, `[Domain Consensus]`, `[Theoretical]`. Readers see exactly what's verified versus synthesized — no false confidence.

**5. Research and rendering are decoupled.**
Verified markdown is written to disk before HTML rendering. Change the visual style without paying for another research run.

---

## Features

- **4-critic parallel review** every turn: coverage, reasoning, depth, search-width
- **Self Coverage Plan**: worker commits to 5–8 verifiable sub-questions *before* running a single search
- **Rebuttal system**: explicit `ACCEPT / CHALLENGE / PARTIAL` stance on every critic issue — no passive acceptance
- **Source URL gate**: Evidence Table rows labeled `[FACT]` must have fetchable `https://` URLs; bare domains, grounding redirects, and SERP URLs are rejected
- **7-day research cache** with companion query file for traceability
- **Design-enforced HTML**: formatter must name a specific aesthetic (e.g. `"editorial / Noto Serif + JetBrains Mono / deep navy + amber"`); generic outputs are rejected
- **Loop Summary** appended to every markdown output: verdict path, turns used, open research directions

---

## When to Use This

**Good fit:**
- Multi-angle research questions where you need to trust the output (competitor analysis, policy comparison, literature overview)
- Questions with contested evidence where naive synthesis misleads
- Research you'll share or publish — the evidence table and claim labels provide a traceable audit trail
- Topics you may want to revisit with a different visual presentation later

**Not a good fit:**
- Quick lookups or single-fact questions
- Proprietary or internal data not accessible via web search
- Real-time data (prices, metrics, live feeds)
- Tasks requiring iterative back-and-forth with the user mid-research

---

## Limitations

- **Web search only** — cannot access proprietary, paywalled, or internal knowledge bases
- **Not real-time** — retrieves published content, not live data feeds
- **English-source bias** — web search is structurally skewed toward English; non-English research topics may show shallower coverage of local literature
- **Search track skew** — the 4-track search strategy (mainstream / counterargument / failure / unconventional) systematically underexecutes tracks 3–4; depth critic flags gaps but the skew is structural, not fixable by prompting
- **No cross-question memory** — each `/research-report` invocation is independent; the tool doesn't build on earlier sessions
- **Turn 1 W1 redo is near-universal** — the Self Coverage Plan heading gate almost always triggers one redo on the first turn regardless of model; this is a known structural limitation, not a bug
- **Cache grows unbounded** — no automatic cleanup; prune `~/.claude/cache/research-loop/` manually

---

## File Structure

```
cc-research-report/
├── skills/
│   ├── research-report/
│   │   └── SKILL.md              # pipeline orchestrator (Step 0→1→2)
│   └── research-loop/
│       ├── SKILL.md              # worker↔critic loop, all mechanical gates
│       └── CHANGELOG.md          # every patch + design decision rationale
├── agents/
│   ├── research-worker.md
│   ├── research-critic-instruction.md
│   ├── research-critic-dialectic.md
│   ├── research-critic-depth.md
│   ├── research-critic-width.md
│   └── research-html-formatter.md
├── install-local.sh
├── uninstall-local.sh
└── README.md
```

---

## License

MIT — see [LICENSE](./LICENSE).
