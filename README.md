![CC Research Report](assets/banner.png)

### Research with verified sources, not confident hallucinations.

[![License: MIT](https://img.shields.io/github/license/npxcnency-ux/CC-Reseach-Report)](LICENSE) [![GitHub stars](https://img.shields.io/github/stars/npxcnency-ux/CC-Reseach-Report?style=social)](https://github.com/npxcnency-ux/CC-Reseach-Report)

---

**cc-research-report turns Claude Code into a research agent that checks its own work.** A worker draft gets torn apart by 4 parallel critics — coverage, reasoning, depth, search gaps — before anything ships. Every claim lands with an epistemic label: `[FACT·verified]` / `[INFERENCE]` / `[Domain Consensus]`. No silent hallucinations.

> 中文文档见 [README.zh.md](./README.zh.md)

---

## Install

```bash
git clone https://github.com/npxcnency-ux/CC-Reseach-Report.git
cd CC-Reseach-Report
./install-local.sh     # symlinks skills/ and agents/ into ~/.claude/
# Restart Claude Code to load.
./uninstall-local.sh   # to remove
```

**Requires:** [`frontend-design` plugin](https://github.com/anthropics/claude-plugins-official) — the HTML rendering step calls it on every run:

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install frontend-design
```

---

## Usage

Invoke from any Claude Code session:

```
/research-report impact of AI on education
/research-report "key risks of agentic AI systems"
/research-report competitive landscape of vector databases max_turns: 6
```

**Outputs:**

| File | Description |
|------|-------------|
| `./{title}-report.html` | Design-driven HTML report in current directory |
| `~/.claude/cache/research-loop/{slug}-{timestamp}.md` | Verified markdown + loop summary (audit trail) |
| `~/.claude/cache/research-loop/{slug}-{timestamp}-query.md` | Original question |

**Re-render without re-researching** — point `research-html-formatter` at the cached `.md` directly. Research is paid once; visual redesigns are free.

**Cache behavior** — if you ask a similar question within 7 days, the skill offers to reuse cached research and skip straight to HTML rendering.

---

## The pipeline

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
[Step 2] research-html-formatter → calls frontend-design skill → HTML on disk
        ↓
[Step 2.5] Design enforcement gate (rejects generic outputs)
```

### The two load-bearing principles

1. **Adversarial validation, not self-review.** The worker never critiques its own work. Four critics each own a narrow audit axis — coverage, reasoning, depth, search-width. No single agent tries to do everything.

2. **Mechanical gates over prompt instructions.** LLMs reliably skip structural requirements when asked nicely. Every critical invariant — Self Coverage Plan heading, Rebuttal stances, source URL format — has an orchestrator-level gate that forces a redo on failure. The [CHANGELOG](CHANGELOG.md) documents 20+ patches all following the same pattern: *prompt failed → add a gate*.

### Critic roster

| Agent | Role |
|-------|------|
| `research-critic-instruction` | Coverage Matrix, URL verification (WebFetch + Playwright), Worker Rebuttal Adjudication. **Issues the VERDICT.** |
| `research-critic-dialectic` | Reasoning Audit: specificity, survivorship bias, inference chain, internal consistency |
| `research-critic-depth` | Depth gap analysis, generates new Research Directions each turn |
| `research-critic-width` | Search Log audit — flags topical tracks the worker planned but didn't execute |

---

## What's structurally enforced

- **Self Coverage Plan first** — worker commits to 5–8 verifiable sub-questions *before* running a single search; orchestrator gate rejects output that skips this
- **Source URL blacklist** — Evidence Table rows labeled `[FACT]` must have fetchable `https://` URLs; bare domains, grounding redirects, and SERP URLs are gate-rejected
- **Rebuttal stances** — worker must take explicit `ACCEPT / CHALLENGE / PARTIAL` position on every critic issue; silent compliance is rejected
- **Track B engagement** — worker must engage ≥ 2 Research Directions per turn
- **Design enforcement** — HTML formatter must declare a named aesthetic direction; generic `system-ui` outputs are rejected

---

## When to use this

**Good fit:**
- Multi-angle research where you need to trust the output — competitor analysis, policy comparison, literature overview
- Questions with contested evidence where naive synthesis misleads
- Research you'll share or publish — evidence table and claim labels provide a traceable audit trail
- Topics you may want to re-render with a different visual presentation later

**Not a good fit:**
- Quick lookups or single-fact questions
- Proprietary or internal data not accessible via web search
- Real-time data (prices, metrics, live feeds)
- Tasks requiring iterative back-and-forth with the user mid-research

---

## What it doesn't do

- It can't access proprietary, paywalled, or internal knowledge bases
- It doesn't retrieve real-time data — published content only
- English-language sources structurally dominate web search; non-English research topics may show shallower coverage of local literature
- The 4-track search strategy (mainstream / counterargument / failure / unconventional) systematically underexecutes tracks 3–4 in practice; depth critic flags gaps but the skew is structural
- No cross-session memory — each `/research-report` invocation is independent
- Turn 1 Self Coverage Plan redo is near-universal regardless of model — budget an extra sub-turn; this is a known structural limitation

---

## Requirements

- [Claude Code](https://claude.com/claude-code)
- [`frontend-design` plugin](https://github.com/anthropics/claude-plugins-official)
- Internet access for web search

---

## File structure

```
cc-research-report/
├── assets/
│   └── banner.png
├── skills/
│   ├── research-report/
│   │   └── SKILL.md              # pipeline orchestrator (Step 0→1→2)
│   └── research-loop/
│       └── SKILL.md              # worker↔critic loop, all mechanical gates
├── agents/
│   ├── research-worker.md
│   ├── research-critic-instruction.md
│   ├── research-critic-dialectic.md
│   ├── research-critic-depth.md
│   ├── research-critic-width.md
│   └── research-html-formatter.md
├── CHANGELOG.md                  # every patch + design decision rationale
├── install-local.sh
├── uninstall-local.sh
└── README.md
```

---

## License

[MIT](LICENSE)

---

[![Star History Chart](https://api.star-history.com/svg?repos=npxcnency-ux/CC-Reseach-Report&type=Date)](https://star-history.com/#npxcnency-ux/CC-Reseach-Report&Date)
