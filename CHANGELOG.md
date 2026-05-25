# research-loop CHANGELOG

This skill spans three files that are designed to evolve together:
- `skills/research-loop/SKILL.md` (orchestrator)
- `agents/research-worker.md` (subagent)
- `agents/research-critic-{instruction,cm,url,dialectic,depth,width}.md` (subagents)

Changes here document semantic / behavioral changes — not formatting tweaks. Reverse chronological (latest first).

---

## 2026-05-22 — VERDICT 计算四层防御 — 消除 Turn 1 虚假 FAIL

### Why this change

Turn 1 critics 将"内容缺口"标注为 `critical` 严重程度，导致 orchestrator `critical > 0 → FAIL` 公式在 Turn 1 直接触发 FAIL。这是虚假 FAIL：内容缺口（"Copilot Agent Mode 未提及"、"跨服务调试场景缺失"等）是 Worker 需要在下一轮补充的改进点，而非阻断流水线的结构性错误。

根因：各 Critic 对 `critical` 的使用缺乏约束。depth/dialectic/width critic 将内容质量问题与 URL 失效、内部矛盾等结构性错误同等标注为 critical，导致原本应 REVISE 的轮次直接 FAIL。

### What changed

**四层防御机制**（d.1–d.4，在 `skills/research-loop/SKILL.md` 步骤 d 中实现）：

- **d.1 Type B 自动降级**：orchestrator 检测 critical Issues 文本，若包含 `missing/absent/缺失/未提及` 等内容缺口关键词，且无 WebFetch 失败 / URL 失效 / 内部矛盾的 Type A 信号，自动降级为 major。
- **d.2 Turn-gated severity**：Turn 1 的 `effective_critical_count` 固定为 0，不允许 Turn 1 触发 FAIL。Turn 1 是首次尝试，深度不足属于预期内；FAIL 只应在 Turn 2+ Worker 已知问题后仍未修复时发生。
- **d.3 Issue 去重**：同一文本段落被多个 critics 同时标注时（`Where:` 字段 ≥40 字符重叠），只计数一次（优先保留 I- 前缀）。防止同一问题因被三个 critic 标注而将 major 计数 ×3。
- **d.4 最终 VERDICT**：基于 d.1+d.2+d.3 处理后的 effective counts 计算：`effective_critical > 0 → FAIL; effective_major == 0 AND cm_missing == 0 → PASS; else REVISE`。

**`agents/research-critic-{depth,dialectic,width,instruction}.md`（修改）**：

各 critic 新增 Mechanical Severity Taxonomy，明确限定 `critical` 的合法使用范围：
- instruction-critic：仅 3 种合法 critical 用途（`[事实·强]` URL 验证失败、Critic-RD 内容洗白、Turn 2+ 缺少 Rebuttals）
- dialectic-critic：Tier 1 排除规定——内容缺口（missing sections/data/counterarguments）永远不是 critical
- depth-critic：critical 仅限于 `[事实·强]` 声明被 WebFetch 内容矛盾或内部段落明确相悖
- width-critic：Width gaps 永远不是 critical（搜索覆盖缺口 ≤ major）

### Design notes

四层防御的层次设计：Critic-level taxonomy 是上游预防（防止 Type B criticals 产生）；d.1 是下游兜底（即使 taxonomy 未生效也能捕获）；d.2 是硬保障（Turn 1 永不 FAIL）；d.3 减少计数噪音。Advisory VERDICT（instruction-critic 末尾）与 orchestrator 计算 VERDICT 的分歧在这种设计下有诊断价值：分歧 = d.1/d.2/d.3 介入了 Type B criticals，可监测 critic 是否仍在过度产生 critical Issues。

### Validation results (2026-05-22, topic: "Claude Code vs GitHub Copilot 核心设计差异", max_turns=1)

| 验证项 | 结果 |
|--------|------|
| raw critical Issues（四 critic 合计） | 4（D-1 内部矛盾、I-2/I-3 URL 失效、E-5 内容缺口） |
| d.1 Type B 降级 | E-5 降级（"Copilot Agent Mode 完全未提及" = 纯内容缺口，无 Type A 信号） |
| d.2 Turn 1 gate | effective_critical_count = 0（Turn 1 自动归零） |
| d.3 去重 | 无跨 critic 重叠需去重 |
| Orchestrator VERDICT | `REVISE（effective_critical=0 [d.1/d.2/d.3后]，major=13，cm_missing=0；raw_critical=4）` |
| Advisory VERDICT（instruction-critic）| `PASS`（分歧：advisory 对 URL 失效问题估计偏低） |

Turn 1 正确输出 REVISE 而非 FAIL，四层防御均按预期工作。

---

## 2026-05-22 — Instruction-critic split + orchestrator-computed VERDICT

### Why this change

Turn 1 instruction-critic 首次通过率约 0%，失败原因有三层叠加：
1. **排序约束**：VERDICT 必须作为输出第一行（结论先于分析），但推理需要先看完整个 draft 才能给出结论，模型无法在看到输入的瞬间就给出 VERDICT。
2. **CM 生成压力**：Turn 1 必须执行 Stage A→B→Retention Map→Final CM 四阶段 Opus 工作，同时还要做 URL 验证、Coverage Verification、Issues、RDs、VERDICT。
3. **I/O 压力**：必须 WebFetch 所有 Evidence Table URL，这是网络 I/O 密集任务。

这三项同时压在一个 Opus agent 上，~100% 失败，c.5 Check 1 redo 无法修复结构性原因（重做同样失败），Coverage Matrix 缺失破坏所有后续轮次的验证基准。

### What changed

**`agents/research-critic-cm.md`（新建，Opus）**：Turn 1 only。专职生成 Coverage Matrix（Stage A→B→Retention Map→Final CM），完全不做 VERDICT/Issues/URL 验证。移除了指令-验证交织的认知压力。

**`agents/research-critic-url.md`（新建，Sonnet）**：每轮。专职 URL 验证（WebFetch/Playwright + URL Verification Report），完全不做 VERDICT/CM/Issues。URL 验证是 I/O 密集但推理轻量任务，Sonnet 成本约为 Opus 一半。

**`agents/research-critic-instruction.md`（修改）**：
- 移除：VERDICT 首行输出约束（Orders constraint 根本消除）
- 移除：Coverage Matrix 生成（移至 critic-cm）
- 移除：URL WebFetch + URL Verification Report（移至 critic-url）
- 新增：输入说明段（接收 pre-CM + pre-URL-report）
- 新增：Advisory VERDICT 在末尾（非 binding，仅供调试对比）
- 保留：Coverage Verification（使用 pre-provided CM）、Issues（I-prefix）、DQs、RDs、Worker Rebuttal Adjudication

**`skills/research-loop/SKILL.md`（修改）**：
- 步骤 c 重组为 Phase A（并行）+ Phase B（串行）：
  - Turn 1 Phase A：5 个并行 agents（critic-cm + critic-url + dialectic + depth + width）
  - Turn 2+ Phase A：4 个并行 agents（critic-url + dialectic + depth + width）
  - Phase B：instruction-critic（串行，接收 cm_output + url_output）
- 步骤 c.5 新增 CM gate（Turn 1，Phase B 前）和 URL gate（每轮，Phase B 前）；Checks 2/3/4 从 Phase B gate 移入 URL gate
- 步骤 d：orchestrator 机械计算 VERDICT（`critical>0 → FAIL; major==0 AND cm_missing==0 → PASS; else REVISE`），不再依赖 LLM 输出首行
- 步骤 e：`coverage_matrix` 从 `cm_output`（不再从 instruction_output）提取；`prev_url_verified_critic_only` 从 `url_output` 提取

### Design notes

Opus 用于 critic-cm（Coverage Matrix 质量问题会传染所有后续轮次，必须保质）；Sonnet 用于 critic-url（URL 验证是 I/O 密集但推理轻量任务）。Advisory VERDICT 保留在 instruction-critic 末尾供调试对比——可以用来监测 orchestrator 计算 vs LLM 直觉的分歧。orchestrator-computed VERDICT 的核心逻辑：Issues severity + Coverage Verification MISSING 行数，不需要任何 LLM 的"裁决直觉"。

### Validation results (2026-05-22, topic: "AI对知识工作者的影响", max_turns=1)

| 验证项 | 结果 |
|--------|------|
| research-critic-cm 首次产出有效 CM | ✅ Stage A=12 ≥10 / Stage B=12 匹配 / Retention=7 / Final CM=8行 |
| CM gate（Phase B 前）| ✅ PASS，无 redo |
| research-critic-url 首次产出有效 URL 报告 | ✅ 7个URLs WebFetched，6全匹配，1 partial（Goldman Sachs 数字在落地页缺失）|
| URL gate（Phase B 前）| ✅ PASS，无 redo |
| instruction-critic 首次通过 | ✅ **无 redo**（Turn 1 ~100% 失败率降为 0%）|
| Phase B Check 1 | ✅ PASS，无 redo |
| Orchestrator VERDICT 计算 | `FAIL (critical=6, major=10, cm_missing=1)` |
| Advisory VERDICT（instruction-critic）| `REVISE` |
| VERDICT 分歧（orchestrator vs Advisory）| orchestrator=FAIL / advisory=REVISE：差异来自 critical Issues（D-1/D-2/E-1/E-2/W-1/I-1），advisory 低估了 critical 严重性 |

instruction-critic 输出首次通过的三个机制各自独立生效：
1. **排序约束消除**：instruction-critic 不再被要求在推理前写 VERDICT，输出顺序自然（Coverage Verification → Issues → RDs → Advisory VERDICT at end）
2. **CM 生成压力移除**：CM 已由 critic-cm 在 Phase A 完成，instruction-critic 直接使用 pre-generated CM 做 Coverage Verification
3. **URL I/O 压力移除**：URL 验证已由 critic-url 在 Phase A 完成，instruction-critic 直接使用 pre-verified URL report 做 Issues 标注

VERDICT=FAIL 为内容质量问题（经验层级与绩效层级混淆、Goldman Sachs 数字未降级等），非架构问题。Loop 因 max_turns=1 正常结束。



### Why this change

W1 gate 在 Turn 1 首次通过率约 0%：Worker 被要求同时完成"规划 SCP + 搜索 + 写答案"，模型在认知负载峰值时刻完全跳过 SCP，直接进入答案模式。每次 Turn 1 必然产生 ~10k token 的 redo 浪费。根本原因不是格式纪律，而是单次调用中并发认知需求排挤了格式要求。

### What changed

**`skills/research-loop/SKILL.md`**：Turn 1 Worker 调用从单次改为两阶段：

- **Phase 1（SCP-only）**：Worker 只输出 `## Self Coverage Plan` 表格，不搜索，不写答案。W1/W6 gate 在 Phase 1 输出上运行。认知负载接近零，首次通过率预期 ~95%+。
- **Phase 2（Full research）**：Worker 收到 Phase 1 验证过的 `pre_scp` 作为预填 SCP，输出开头直接包含 SCP 表格，然后执行搜索和完整答案。

Phase 1 redo 比当前 Turn 1 redo 便宜约 20x（无搜索，输出只有表格）。主 gates 段落中 W1/W6 在 Turn 1 时 trivially PASS（已在 Phase 1 验证）并加注说明。Turn 2+ 流程完全不变。

### Design notes

不引入新 agent 类型——Phase 1 使用同一个 research-worker（Sonnet），避免 Haiku 规划质量低、Coverage Matrix 降级的风险。两阶段分离了"规划"和"研究"的认知负载，是当前架构下消除 W1 redo 循环的最小侵入性方案。

---

## 2026-05-22 — gates.py: Python gate execution + 5a/5b/5c drift simplification + INTEGRATE search discipline

### Why this change

Three unrelated but structurally related failure modes accumulated:

1. **W1–W6 gates were LLM-simulated regex.** The orchestrator described each gate as natural-language regex for Claude to evaluate at runtime. LLMs do not reliably simulate regex — subtle output format variations (case, whitespace, extra preamble) caused gates to misfire or be bypassed. One character of prefix before `## Self Coverage Plan` would pass a lenient Claude regex while failing the spec.

2. **5a/5b/5c drift detection produced false-positive redos.** The three within-turn Critic invariant checks compared field-level content (Reasoning Audit claim quotes, URL row HTTP Status/Action fields, Issue body text). Any Critic revision that legitimately updated a field (e.g., re-fetched URL with updated status) triggered drift fail even when the research substance was correct. High false-positive rate → excessive redo cost with no quality benefit.

3. **INTEGRATE mode had a "no new search required" escape hatch.** The Revision Log template's `Additional search:` field allowed `"no new search required"` for any mode including INTEGRATE. This directly contradicted Track B's mandate (INTEGRATE must independently fetch and verify Critic's claimed specifics). Workers could integrate Critic training-memory claims as evidence without running a single WebSearch.

### What changed

**`skills/research-loop/gates.py` (new file)**

Python CLI replacing LLM-simulated regex for W1–W6. Deterministic execution via Bash tool:

```bash
python3 ~/.claude/skills/research-loop/gates.py <gate> <draft_file> [turn]
# first line: PASS or FAIL; FAIL followed by violation lines
python3 ~/.claude/skills/research-loop/gates.py coverage-matrix-drift <prior_file> <current_file>
```

| Gate | Logic | Key detail |
|------|-------|------------|
| w1 | `'## Self Coverage Plan' in draft` | Case-sensitive literal |
| w2 | `re.search(r'^# Rebuttals\s*$', draft, re.MULTILINE)` | Single `#`, exact string |
| w3 | Parse Evidence Table; check non-exempt rows against 4 blacklist types | Exempt: `[领域共识]` `[DOMAIN]` `[INFERENCE]` `[推断]` |
| w4 | Parse `# Rebuttals` sub-headings; require `Stance:` with valid value per type | Issue: ACCEPT/CHALLENGE/PARTIAL; RD: ACCEPT/REJECT |
| w5 | Count ACCEPT RDs in Rebuttals + Revision Log; need ≥ 2 | Deduplicates across sections |
| w6 | Count SCP table data rows; need [5, 8] | Skip header + separator rows |
| coverage-matrix-drift | Cell-value comparison of Coverage Matrix between two files | Adding rows = PASS; changing cell value = FAIL |

W3 blacklist patterns (source of truth in `gates.py` — not in SKILL.md prose):
- Bare domain: `^https?://[^/\s]+/?$`
- Grounding redirects: `vertexaisearch.cloud.google.com/grounding-api-redirect/`, `google.com/url?`, `duckduckgo.com/l/?`, `bing.com/ck/a?`
- SERP: `google.com/search?q=`, `bing.com/search?q=`, `duckduckgo.com/?q=`
- Placeholders: `search summary`, `search 综合`, `多源汇总`, `Gemini synthesized`, `no specific URL`

`check_coverage_matrix_drift` uses `_parse_table_cells()` which strips all `|` formatting and returns raw cell values — immune to column alignment, trailing spaces, or markdown padding changes that previously caused false positives on the "normalized string comparison" check.

**`skills/research-loop/SKILL.md` — W1–W6 invocation changed to Bash**

Gates now invoked via `python3 ~/.claude/skills/research-loop/gates.py` instead of LLM evaluation. Each gate: write current_draft to `/tmp/rl-draft-t{turn}.md` (one Write per turn, reused across W1–W6), call gates.py, parse first-line PASS/FAIL. Redo prompt text preserved verbatim.

Coverage Matrix drift check changed from "normalized string comparison" to:
```bash
python3 ~/.claude/skills/research-loop/gates.py coverage-matrix-drift /tmp/prior.md /tmp/current.md
```

**`skills/research-loop/SKILL.md` — 5a/5b/5c drift detection simplified**

| Check | Before | After |
|-------|--------|-------|
| 5a Reasoning Audit | Compare 4 sub-check content verbatim (claim quotes, Y/N text) | Only verify 4 sub-check headings present; no content comparison |
| 5b URL Verification | Per-row HTTP Status / Provenance / Action match | URL set membership only (prior URLs still present) |
| 5c Issues | Issue body fields match (problem text, fix direction) | Issue heading presence only (`## Issue N:` title still appears or `Withdrawn:`) |

**`agents/research-worker.md` — Revision Log INTEGRATE/EXPAND mandatory search**

`Additional search:` field in Revision Log template changed from:

> `[query if new search was needed, or "no new search required"]`

To:

> `(INTEGRATE/EXPAND) actual query string — required; (CHALLENGE only) "used existing evidence" allowed if no new search needed`

`Finding:` field updated to match: `(CHALLENGE only) cite the existing evidence used`.

### Design notes

**Why Python and not a shell one-liner**: W3 requires parsing a markdown table, checking multiple regex patterns per cell, and exempting rows by label. Shell scripts for this level of logic are fragile and hard to maintain. Python gives clean testability: `python3 gates.py w3 test_draft.md` can be run standalone against any fixture.

**Why 5a/5b/5c loosening does not weaken invariant protection**: The invariants that matter for cross-turn state consistency are structural (Coverage Matrix sub-question text, Issue titles, RD identifiers) — not field-level content (which a Critic may legitimately update after new evidence). The previous content-match checks were catching legitimate Critic updates as drift. Simplifying to structural presence catches the actual failure mode (Critic regenerates different sub-questions or different Issue titles) without penalizing legitimate field updates.

**Why INTEGRATE requires a search but CHALLENGE does not**: INTEGRATE means adopting Critic's claimed specifics (typically training-memory numbers like "GPM 41% in 2024"). These need independent verification before entering evidence. CHALLENGE means disputing a Critic claim using Worker's own search results — the search was already done. Requiring a search for CHALLENGE would force Workers to re-search what they already searched, burning tokens.

### How to verify

```bash
# W1 gate: should FAIL on missing SCP
echo "# Answer\nsome text" | python3 skills/research-loop/gates.py w1 /dev/stdin
# FAIL / Missing `## Self Coverage Plan` heading

# W3 gate: should FAIL on bare domain
python3 skills/research-loop/gates.py w3 <file-with-bare-domain-url>
# FAIL / Row N: bare domain root — https://example.com/

# coverage-matrix-drift: should FAIL on changed sub-question text
python3 skills/research-loop/gates.py coverage-matrix-drift prior.md current.md
# FAIL / Row C2 / 子问题: prior="what X" → current="what Y"
```

---

## 2026-05-21 — First-line discipline gates + 4-critic split regression baselines

### Why this change

Two failure modes recurred across multiple research-loop runs (2026-05-20 patch 9 fixture + a fresh AI-org-structure topic + a fresh AI-in-education topic):

1. **Worker** consistently skipped the `## Self Coverage Plan` first-heading discipline. Output started with prose preamble ("Acknowledged...", "Excellent — I now have...", "The DOJ URL redirected...") and jumped to `# Answer` or `# Search Log`. SCP first-heading was missing or, worse, confabulated as compliant in a closing self-audit line ("S1: SCP is the very first heading. ✓") while the heading was physically absent.

2. **research-critic-instruction** consistently produced no first-line `VERDICT:` and no Coverage Matrix three-stage structure on Turn 1 cold start. Output buried the verdict in a closing summary, replaced Stage A/B/Retention/Final with an unstructured `# URL Verification Report` table, and skipped `# Coverage Verification`.

Both are the same pattern as 2026-05-20 patch 9's design-direction failure: **agent reads "MUST" instructions as advisory unless the model's first-token incentive is forced into compliance by either (a) atomic single-line constraint or (b) literal fill-in template**.

### What changed

**`research-critic-instruction.md` — top-of-file hard-stop block (✅ effective)**

Added a `🛑 OUTPUT START DISCIPLINE` block immediately after frontmatter, before the role definition:
- "Your FIRST NON-WHITESPACE LINE must be exactly `VERDICT: PASS|REVISE|FAIL`"
- Explicit forbidden preamble examples ("Acknowledged...", "Here is my review", "URL fetch successful...")
- Mention orchestrator regex `^VERDICT:\s+(PASS|REVISE|FAIL)\s*$` so model knows the gate is mechanical
- Turn 1 follow-on requirement: `# Coverage Matrix` with all four sub-headings (Stage A / Stage B / Retention Map / Final Coverage Matrix)
- Turn 2+ follow-on: `# Reasoning Audit` next, do NOT regenerate Coverage Matrix
- Self-check line ("scan your draft's first three lines") to nudge model to verify before submitting

Result: on regression test (AI-in-education topic, fresh prompt), critic-instruction first-attempt compliance moved from 0/2 to 2/2 — VERDICT first-line ✓, Coverage Matrix three-stage ✓, all required sections ✓.

**`research-worker.md` — top-of-file hard-stop block (❌ ineffective on its own)**

Same structural pattern: `🛑 OUTPUT START DISCIPLINE` block before role definition stating "first character must be `#`", "Turn 1 first heading must be `## Self Coverage Plan`", explicit forbidden preamble list, ignore `<system-reminder>` for output formatting.

Empirical: 0/2 first-attempt compliance on regression. Block is read but doesn't override the model's "explain reasoning before output" instinct — the cognitive cost of producing 5-8 thoughtful sub-questions BEFORE search is too high, model defers ("let me search first then write the plan") and the deferral is implicit silent skip.

**`SKILL.md` — Worker Turn 1 prompt strengthened to literal SCP template injection (❌ also ineffective on its own)**

Step 3.b Turn 1 prompt rewritten from a paragraph instruction to an orchestrator-injected fill-in template:
```
Begin your response by completing exactly this template:

## Self Coverage Plan

| # | 子问题 | 充分覆盖标准 |
|---|--------|--------------|
| C1 | [specific sub-question 1] | [adequacy criterion with verifier] |
| ... |
```

Theory was: critic-instruction succeeded because `VERDICT:` is a 13-character atomic pattern; worker fails because SCP requires deliberate planning. Make SCP equally mechanical by giving model a fill-in template.

Empirical: 0/1 first-attempt compliance. Model still produced prose preamble ("DOJ URL redirected...") before the template heading. The literal fill-in form did not override the preamble instinct.

**`research-worker.md` frontmatter — `model: opus` → `model: sonnet` (no compliance change, side benefits)**

Hypothesis: Opus's RLHF "explain reasoning" instinct may be stronger than Sonnet's; switching to Sonnet might fix first-attempt SCP compliance.

Empirical (same AI-in-education topic, same orchestrator prompt): Sonnet failure mode is **identical** to Opus — same prose preamble ("DOJ URL redirected so I cannot anchor it directly..."), same missing SCP heading, same confabulated closing line claiming SCP completion. **First-attempt SCP compliance is model-invariant.**

Side benefits observed in Sonnet output:
- 5 successfully-fetched primary URL anchors (vs 1-4 with Opus)
- Active anti-pattern self-flagging ("主动规避 anti-pattern #11 URL 路径捏造")
- Sonnet retained as worker default (cost ~half, evidence discipline marginally better)

### What was confirmed

- **critic-instruction first-line VERDICT discipline**: solved by atomic single-line hard-stop block (this patch keeps it).
- **Worker SCP first-heading discipline**: NOT solvable at the prompt layer regardless of model, agent file, or template injection. The W1 gate redo cycle in SKILL.md (already present) remains the only working enforcement — first-attempt redo rate stays ~100% on cold start.

### 4-critic split (instruction/dialectic/depth/width) regression validation

The split into 4 parallel critics (created earlier 2026-05-21) was tested end-to-end across two unrelated topics. Architecture validation:

| Item | Status |
|------|--------|
| 4 critics in agent list (`research-critic-{instruction,dialectic,depth,width}`) | ✓ |
| Single-message parallel dispatch | ✓ both turns |
| Per-critic Phase B isolated redo (only failing critic re-runs) | ✓ Turn 1 instruction failed schema, others one-shot pass |
| Per-critic cached invariants in redo prompt | ✓ |
| VERDICT only from instruction-critic first line | ✓ |
| Output scope correctness (instruction = Coverage/URL/Verdict; dialectic = Reasoning Audit + D-issues; depth = RDs + E-issues; width = Width Audit + W-issues) | ✓ |
| Merge step combines outputs without conflict | ✓ both turns |
| Multi-turn state transfer (coverage_matrix / prev_dq / prev_url_verified / worker_rebuttals / prev_depth_rds / dialectic_issues_summary) | ✓ |
| Worker Rebuttal Adjudication (Turn 2+ mandatory) | ✓ |
| W2/W4/W5 Worker gate (Rebuttals + Stance + Track B engagement ≥ 2) | ✓ |

### Search-track distribution baseline (cross-topic stability check)

Worker's four-track search plan execution distribution measured on two unrelated topics:

| Track | AI-org-structure | AI-education | Expected |
|-------|------------------|--------------|----------|
| 1. Mainstream | 7/12 = 58% | 7/12 = 58% | ~25% |
| 2. Counterargument | 3/12 = 25% | 3/12 = 25% | ~25% |
| 3. Failure-case | 1/12 = 8% | 1/12 = 8% | ~25% |
| 4. Unconventional | 1/12 = 8% | 1/12 = 8% | ~25% |

**Identical distribution across two completely different topics** — this is structural, not topical. Worker plans four tracks honestly but executes ~58% of searches in track 1 because mainstream search results pull subsequent searches deeper into mainstream. Tracks 3 and 4 (failure cases + unconventional sources) are each at ~8% — far below the 25% planned share.

Implication: the four-track plan is a planning artifact that produces good distribution-on-paper but fails distribution-in-execution. Width-critic flagged this in both runs (W-issues clustered around "应搜未搜 X" where X spans tracks 3/4). Genuine fix would require parallel fetcher waves (e.g., dispatch one Haiku per track in parallel) — not in scope for this patch.

### Open recommendations (deferred)

- **C path — dedicated SCP-planner sub-agent (Haiku)**: invoke a tiny planner before Worker that outputs only the 5-8 row SCP table; pass it into Worker prompt as context. Single-purpose agents have trivial first-heading compliance. Estimated 0.5 day, eliminates ~100% of W1 gate redos. Deferred pending decision on whether to optimize first-attempt or stay with the W1 redo cycle.
- **Width-sweep PoC**: parallel Haiku fetcher waves keyed to four-track plan, breaking the 58/25/8/8 execution偏置. Estimated 1-2 days. Deferred — first need to decide if the W1 redo cycle is acceptable as the steady-state Worker pattern.

---



### Why this change

Lightweight test on a synthetic Victorian-era telegraph fixture revealed `research-html-formatter` silently skipped the `frontend-design` skill despite spec stating "Mandatory first step: invoke the design skill". Symptoms in the test run:

- Agent reported `tool_uses: 2` (Read + Write only — no Skill call)
- Final return message lacked the mandatory `Design direction:` line
- Generated HTML body used `font-family: system-ui, -apple-system, 'Segoe UI', sans-serif` (the exact stack `frontend-design` skill warns against) with Tailwind-gray + #1d4ed8 blue (generic SaaS dashboard)
- Topic was Victorian industrial — should have triggered editorial / industrial / art-deco aesthetic per spec; got generic modern minimal instead

This is structurally identical to the long-running pattern: **prompt嘱托 in agent text without orchestrator-side mechanical validation = LLM defaults to training inertia (generic aesthetic in this case, just like Worker defaults to skipping Self Coverage Plan)**. The "Design direction line is mandatory" wording in formatter spec was insufficient — agent treated it as advisory and skipped both the skill load AND the return-line declaration.

### What changed

**research-report/SKILL.md — Step 2 prompt strengthened (B from A+B fix)**

Step 2's Agent prompt now embeds three explicit blocks:
- "## Mandatory tool sequence (orchestrator-enforced)" listing the required FIRST/SECOND/THIRD tool calls (Skill → Read → Write)
- "## Mandatory return format (orchestrator-enforced)" stating the final response must begin with `Design direction: ...` and explaining why (orchestrator greps for it)
- Topic-aesthetic alignment hint ("if industrial/historical, DO NOT pick modern minimal")

The prompt explicitly references the orchestrator gate — agent now knows the redo will trigger if it skips, which empirically improves compliance vs. silent rules.

**research-report/SKILL.md — new Step 2.5 mechanical enforcement gate (A from A+B fix)**

After the formatter Agent returns, orchestrator runs two checks on the agent's return message + written HTML:

- **D1 — Design direction line present (auto-redo)**: regex `^Design direction:\s+\S` somewhere in return; content after colon must be ≥ 20 chars AND contain at least one specific aesthetic descriptor (named font, color, era keyword like `editorial`, `art-deco`, `industrial`, `magazine`, `retro-futuristic`, `brutalist`, `pastel`, `monospace`, `serif`, `display`, `ochre`, `ink`). Missing or too-generic → redo with explicit reject reason prepended to original prompt.

- **D2 — Generic-default font-family detection (advisory only)**: read written HTML, check body `font-family:`. If primary font is `system-ui` / `-apple-system` / `Segoe UI` / `Inter` / `Roboto` / `Arial` / `sans-serif` alone with no named display/serif/mono font, surface as `D2 advisory: body font-family uses only generic system stack` in the user-facing summary. Not auto-redo because legitimate minimal designs may legitimately use system stacks.

Max 2 redos. After 2 failures, accept output but flag in user summary: `WARNING: Design enforcement gate failed after 2 redos. Output may be visually generic.`

**research-html-formatter.md — Mandatory first step block strengthened**

Added:
- "VERY FIRST tool call MUST be Skill" with all-caps emphasis
- Self-test ("did I just call Skill?") between tool calls
- Explicit reference to Step 2.5 D1 detection so agent understands the cost of skipping
- "Why this matters" explanation (without skill → Tailwind grays + system-ui = identical output across all reports)

Output section restructured: `Design direction:` line moved to **front** of final response (orchestrator greps for it as the first signal), with concrete examples showing the required level of specificity. Generic phrases like "clean and modern" are explicitly listed as auto-reject.

### Why D1 + D2 instead of just D1

D1 catches the most common failure: agent skips Skill call entirely → no `Design direction:` line → mechanical detect.

D2 catches the harder case: agent calls Skill but ignores its content (loads, doesn't internalize) and produces `Design direction: editorial classical` while the actual HTML still uses `font-family: system-ui` defaults. D2 is signal-only because false positives exist (some skill-driven minimal directions legitimately use `system-ui`), but surfacing the signal lets users notice "agent claimed direction X but the HTML doesn't reflect it."

Combined, D1 + D2 give: D1 = compliance check (did agent declare a direction?), D2 = follow-through check (does the code reflect the declared direction?). D1 is the bar, D2 is the sniff test.

### How to verify

After running `/research-report` (or the skill directly), look for:
- Agent's return message starts with `Design direction: {specific aesthetic}` (≥ 20 chars, names concrete elements)
- HTML's `<style>` block declares non-default fonts (e.g., `font-family: 'Crimson Text', 'Spectral', serif` instead of `font-family: system-ui, sans-serif`)
- If gate redo triggered, final user-facing summary may include redo count or `WARNING: Design enforcement gate failed`
- D2 advisory line surfaces when font stack is generic

### Risk: D1 keyword whitelist too restrictive

The "specific aesthetic descriptor" check uses a hand-curated keyword list (editorial / art-deco / industrial / etc.). A novel direction not on the list (e.g., "vaporwave neon halftone") fails D1 even if substantively specific. Mitigation: the list also accepts named fonts (matching `\b[A-Z][a-zA-Z]+\b` patterns like `Cinzel`, `Crimson`) and named colors (`ochre`, `ink`, `steel`), which catches most cases. If empirically too tight, can broaden to "any 3+ specific nouns" heuristic.

### Risk: redo cost on D1 false negatives

If agent picks a legitimate direction but happens to phrase it without keywords (e.g., "Bauhaus geometric"), D1 redo wastes tokens. Bauhaus IS in the spirit of the check (specific historical movement), but the keyword list might miss it. Calibrate keyword list against observed redo rate; loosen if > 10% of legitimate runs redo spuriously.

### Empirical context

Identified this session via lightweight fixture test (Victorian telegraph synthetic markdown). Implementation immediately follows. Re-test with same fixture pending — expected to show: Skill tool called as first action, `Design direction:` line in return, font-family deviating from system-ui defaults.

### Pattern reinforcement

This is the 9th major patch and the 7th instance of "prompt嘱托 fails → orchestrator-side mechanical validation needed" in this skill family. The pattern is now well-established. Future agent-spec writers in this codebase should default to "prompt嘱托 + mechanical gate" as a unit, not prompt嘱托 alone.

---

## 2026-05-20 (patch 8) — Markdown-to-disk handoff for HTML formatter (token optimization)

### Why this change

Pre-patch flow: research-report SKILL passed the entire research-loop output (typically 10-25 KB markdown) inline as part of the Agent prompt to research-html-formatter. This costs ~1× markdown tokens on the main session's *output* side (the prompt string serialization the orchestrator produces is part of its output budget), in addition to the formatter agent's input budget. For a 25 KB markdown with the formatter run twice (e.g., user asks for a different design), that's wasted tokens with zero new information.

A second issue: if HTML rendering fails (formatter agent error, design didn't fit) or user wants to re-render with different aesthetic, there was no way to re-run Step 2 alone. The verified markdown lived only in the main session's transient state and was lost when the conversation moved on. Re-rendering required re-running the entire research-loop (multi-turn worker↔critic, costly).

### What changed

**research-report/SKILL.md — new Step 1.5 between research and HTML rendering**

Between Step 1 (run research-loop) and Step 2 (format as HTML), orchestrator now writes `research_output` (the full `# Final Answer` + `# Loop Summary` block) to disk before invoking the formatter:

- Directory: `~/.claude/cache/research-loop/` (created with `mkdir -p` if missing)
- Filename: `{slugified-title}-{YYYYMMDD-HHMMSS}.md` — slug strips filesystem-unsafe chars, truncated to 50 chars; timestamp in local time (matches `ls -l`)
- Write byte-for-byte (no normalization) so the formatter sees identical content to what research-loop produced

Step 2's Agent prompt to research-html-formatter changed from inlining `## research_markdown\n\n{research_output}` to passing `input_path: {markdown_path}`. Prompt drops from ~markdown-size to ~50 tokens.

**Fallback path preserved**: if Write fails (directory permission, disk full), Step 2 falls back to the legacy inline-prompt format with `inline_fallback: true` annotation in the prompt. The pipeline does not block on disk-write failure; user gets a warning but the report still renders.

**research-html-formatter.md — Input contract switched from inline to file path**

- Input parameter renamed: `research_markdown` (inline string) → `input_path` (absolute file path)
- New mandatory first action: "use the `Read` tool on `input_path` to load the markdown content into your context. Do not assume the markdown is inline in your prompt."
- Legacy inline path retained behind `inline_fallback: true` flag for the rare orchestrator-write-failure case

The frontend-design skill integration and "Design direction" mandate (added externally during this work) are preserved — only the Input contract section was modified.

### Token impact

| Step | Pre-patch | Post-patch |
|------|-----------|------------|
| Step 2 prompt construction (main session output) | ~markdown size (10-25 KB) | ~50 tokens |
| research-html-formatter input | ~markdown size + agent prompt overhead | ~50 tokens prompt + Read tool result (~markdown size) |
| **Net main-session output savings** | — | **~markdown size × every formatter invocation** |
| Re-render cost (style change) | re-run research-loop | re-run only Step 2 against existing markdown_path |

The formatter still reads the markdown content once via the Read tool, so total tokens consumed by the formatter's context are roughly unchanged. The savings are on the **orchestrator side** (main session's output budget for the Agent prompt) and on the **re-render** axis (Step 1 doesn't repeat).

### Why disk and not in-memory state

Considered alternatives:
- **Pass markdown via Agent's prompt verbatim**: the existing pre-patch behavior — costs the tokens we want to save
- **Keep markdown in main-session conversation state and reference by ID**: Claude Code Agent prompts are strings, not state references; no mechanism to pass "use the markdown from X earlier message"
- **Write to disk**: bonus durability — markdown survives across session restarts, user can grep / inspect / re-render later, audit trail visible in `ls ~/.claude/cache/research-loop/`

Disk is the only option that delivers all three goals (token savings, re-renderability, audit trail).

### How to verify

- After running `/research-report` or invoking the skill, check `ls ~/.claude/cache/research-loop/` — should see `{slug}-{timestamp}.md` for the latest run
- Step 2's Agent invocation prompt should be short (~few hundred tokens) instead of ~25 KB
- research-html-formatter's first tool call should be `Read` on `input_path` (visible in the agent's transcript)
- Final user-facing report includes both `HTML report path` and `Markdown source path` so user knows where the verified research lives

### Risk: cache directory grows unbounded

`~/.claude/cache/research-loop/` accumulates markdown files indefinitely with no cleanup. Each file is small (~10-25 KB) so disk pressure is low even at high run rates. If this becomes a problem, future patches can add: (a) age-based cleanup (delete files > 30 days), (b) disk quota check before write, (c) explicit `--cache-strategy=ephemeral|persistent` arg. Not implemented now because empirical disk usage isn't yet known.

### Risk: filename collision

Two runs in the same second on similar titles produce same filename → second overwrites first. Probability is low (timestamp has second resolution, slugification produces same string only for near-identical titles), but if observed, can extend to `YYYYMMDD-HHMMSS-microseconds` or append run-counter.

### Empirical context

Identified by user observation post-test ("研究输出没存盘，每次都要重新跑很贵"). Implemented in this session. Not separately re-tested as a standalone change — the change is mechanical (Write + path passing) and the failure modes (disk write fail) have explicit fallback paths.

---

## 2026-05-20 (patch 5) — Critic redo discipline (surgical patch vs regenerate)

### Why this change

Patches 4 (Turn-internal redo invariants) and 6 (Check 5 fine-grained drift detection) put the orchestrator-side mechanical detection in place. But the underlying Critic behavior — treating "redo" as "regenerate from scratch" — wasn't directly addressed. The mechanical gates catch drift after it happens; this patch adds an explicit prompt-level instruction inside critic.md to shift Critic's mental model.

End-to-end test v2 made the failure mode crisp: when the orchestrator said "you missed adding the Tool used column", Critic added the column AND regenerated:
- The Reasoning Audit's 3 Claim A/B/C selections (different claims this time)
- The URL Verification Report's 10 URLs (replaced 8 with different URLs)
- The Issues numbering (preserved content but reorganized)

None of these regenerations were necessary to fix the missing column. Critic was conflating "redo" with "do the entire audit again". The previous redo prompt said "preserve verbatim" but didn't explain why — Critic's training inertia toward "be consistent across the whole output" overrode the literal preservation instruction.

### What changed

**research-critic.md — new "Redo discipline" section between Adversarial discipline and Don't**

The section establishes:

1. **Mental model**: redo is **diff-based revision**, not **fresh generation**. The cached invariants block is the anchor (read it, copy non-failing sections character-for-character, surgically fix only what the gate flagged).

2. **Self-test**: "Would I copy this section character-for-character from the cached invariants?" If you're writing fresh, you're regenerating — stop.

3. **Override hatch + quality validation**: `## Cached invariant override` for legitimate revisions. Reason field must contain specific signals (re-fetch / discovered / misread / Worker rebuttal). Weak reasons (`on reflection`, `更合理`) rejected as silent drift.

4. **Why this matters**: explicit list of consequences when Critic regenerates — `severity_history` unreliable, `prev_url_verified_critic_only` carries garbage, Worker can't track Issues across redos, audit trail lost. This is meant to surface the operational cost in Critic's reasoning, not just procedural rule-following.

5. **Quantitative threshold**: "if you find yourself wanting to override 5+ cached items, you're regenerating; stop and start over by copying cached content". This catches the failure mode where Critic reflexively justifies each drift individually but the cumulative effect is wholesale regeneration.

### Why prompt-level after mechanical-level

The orchestrator's Check 5 (5a/5b/5c + override validation) is the safety net — it mechanically catches drift even if the prompt嘱托 fails. But:

- Each redo costs tokens; reducing drift at the source reduces total token spend
- Override hatch validation has linguistic heuristics that aren't perfect; better Critic discipline upstream → fewer false positives downstream
- The mental model shift ("surgical patch not regenerate") is the kind of thing prompt-level guidance can actually shift, because it's a single conceptual reframe rather than a procedural detail

Mechanical gates and prompt嘱托 work in tandem: prompt sets the baseline behavior, mechanical gate catches outliers. Both are needed.

### How to verify

When running the skill with Critic redos, look for:
- Critic redo output's `# Reasoning Audit` Claim A/B/C are byte-identical to prior attempt
- Critic redo output's `# URL Verification Report` has the same URL set as prior (plus possibly added URLs, never replaced)
- Critic redo output's `# Issues` preserve numbering and content
- If Critic does override, the override section appears with specific Reason matching the quality validation patterns

If empirical testing shows Critic still drifts despite this patch, the fallback is Check 5's mechanical detection — but each redo is wasted work, so prompt-level reduction matters.

### Empirical context

Identified post-test v2. Not separately re-tested as a standalone change — the prompt addition is structurally analogous to other "explain the why behind the rule" guidance that has empirically improved compliance (e.g., Worker Anti-pattern #11 about URL fabrication added explicit consequences and reduced fabrication rate in subsequent tests).

### Risk: prompt嘱托 alone won't fully eliminate drift

LLMs reliably resist procedural constraints if they conflict with training inertia (the entire history of this skill is evidence of this — see Worker SCP repeatedly skipped despite multiple HARD GATE warnings). The Redo discipline section explains *why* with concrete consequences, but Critic may still regenerate. That's why Check 5's mechanical detection (patch 4 + 6) remains the load-bearing mechanism. This patch is upstream complement, not replacement.

If future tests show drift rates haven't dropped substantially, consider:
- Adding a pre-redo "self-audit checklist" Critic must fill (similar to Worker's S1-S6) before submitting
- Making the cached invariants block visually distinct in redo prompts (boxed, indented)
- Forcing Critic to literally include `[preserved from prior attempt]` annotations on each non-modified section

---

## 2026-05-20 (patch 4) — Check 5 fine-grained drift detection (5a/5b/5c)

### Why this change

End-to-end test v2 (1880-1930 electrification topic, post patch 3) revealed Check 5 invariant drift detection was too coarse. When Critic Turn 1 redo was triggered to add the missing Coverage Matrix three-phase structure + Tool used column + Provenance column, Critic regenerated more than it should have:

| Section | What should preserve | What actually happened |
|---------|---------------------|------------------------|
| `# Reasoning Audit` | Same 3 Claim A/B/C selections, same Y/N assessments | Critic picked completely different claims (Claim B from Ford 12.5h to "电气化解放工厂布局"), changed Internal consistency from N to Y |
| `# URL Verification Report` | Same 10 URLs analyzed in prior attempt | Critic replaced with completely different 10 URLs (jstor 2120991 → 2120731, history.state.gov → bls.gov, osha → wikipedia, etc.) |
| `# Issues` | Issue 1-8 numbering and content stable | Issues mostly preserved but renumbered/recast (substantively similar but not character-stable) |

The previous Check 5 implementation only listed "specific drift cases that always trigger fail" with examples, but the comparison rule was "minor markdown formatting tolerance" — too permissive. Reasoning Audit content drift and URL row replacement slipped through because they didn't match any explicit specific case.

This is structurally the same issue as Coverage Matrix drift (patch 4 patch 2) but at a finer granularity. The fix splits Check 5 into three explicit sub-checks: 5a Reasoning Audit content, 5b URL Verification row preservation, 5c Issues numbering/content.

### What changed

**SKILL.md Check 5 expanded with three explicit sub-checks**

- **5a — Reasoning Audit content stability**: each of the 4 sub-checks (Specificity / Survivorship / Inference / Consistency) must preserve verbatim across redos:
  - Specificity test: same Claim A/B/C quotes from Worker draft (cannot pick different claims)
  - Survivorship: same Y/N + explanation
  - Inference: same Y/N + specific gap quote
  - Internal consistency: same Y/N + specific contradiction example
  - Final result line must match
  - Exemption: if a sub-check itself was the gate-failure source, it can regenerate; others stay

- **5b — URL Verification Report row preservation**: build cached and current URL sets:
  - Cached URLs MUST appear in current with same HTTP Status / Provenance / Supports claim? / Action
  - Removing/replacing cached URLs (e.g., jstor 2120991 → jstor 2120731) → drift fail
  - Adding new URLs is allowed
  - Provenance may upgrade from "Worker-claimed" to "Critic-verified Turn N" if re-fetched

- **5c — Issues numbering and content stability**: each cached `## Issue N: title` must appear at the same N with same title, severity, body content. Adding new Issues at N+1, N+2 is OK. Removing/relabeling existing Issues forbidden — must use `Withdrawn:` annotation if Critic believes prior was wrong.

**Critic redo prompt — invariant preservation language strengthened**

The "Cached invariants from prior attempt — preserve verbatim" block now explicitly explains "what verbatim means in practice" with concrete examples per section (Reasoning Audit / URL Verification / Issues / Research Directions / Coverage Matrix / WebFetch Audit). Adds a self-test: "ask yourself if you would copy this section character-for-character — if redo reads differently, you're regenerating not preserving".

Also adds an explicit override path: if Critic has substantive reason to revise cached content (e.g., discovered prior analysis was wrong), it must add `## Cached invariant override` section listing what changed and why. The orchestrator's Check 5 accepts overrides with explicit reasoning but rejects silent drift.

**SKILL.md Check 5 implementation note**

For each of 5a/5b/5c, orchestrator builds a structured comparison report:
- Section/URL/Issue identifier
- Cached content excerpt (first 80 chars)
- Current content excerpt (first 80 chars)
- Match status (PASS / DRIFT)

DRIFT entries appear in redo prompt under `## Check 5 drift findings` so Critic sees specifically what to restore.

### Why this is needed beyond patch 4 (the original Turn-internal redo invariants)

Patch 4 introduced the cache → inject → validate framework. But the validation step was too lenient — "minor formatting tolerance" allowed substantive content swaps. Empirically this is the most common drift pattern: Critic redoes the entire analysis to "be consistent" with the new structure, rather than surgically adding just what was missing.

Patch 6 makes the validation specific enough to catch the actual drift behaviors observed in tests (different Claims chosen, different URLs verified, Issues renumbered). The cost is that orchestrator's drift detection logic becomes more complex, but the alternative (Critic silently regenerating analysis work each redo) means cross-turn invariants are unreliable.

### How to verify

When running the skill with Critic redos, look for:

- Critic redo output's `# Reasoning Audit` Claim A/B/C quotes match prior attempt's quotes character-for-character
- URL Verification Report's URL set is a superset of prior attempt's URL set (no removed URLs, no replaced URLs)
- Issues numbered Issue 1, Issue 2, ... preserve their titles and content; new issues only added at the end
- If Check 5 detects drift, redo prompt now contains `## Check 5 drift findings` with specific section/URL/Issue identifiers and cached vs current excerpts

### Empirical context

Identified in end-to-end test v2 (this session). Not separately re-tested — fix is structurally analogous to other patches' enforcement-via-mechanical-comparison pattern. If future tests show 5a/5b/5c thresholds too strict (e.g., legitimate Critic refinement gets rejected), the comparison heuristic can be tuned. The current "exact match modulo whitespace" is the strictest defensible bar; can loosen to "≥ 80% character-level similarity" if false-positive rate is too high.

### Risk: Critic may struggle to preserve Reasoning Audit perfectly

Reasoning Audit picks 3 Claims A/B/C from Worker draft. If Worker draft changes between Turn 1 and Turn 2 (Worker revised), prior Reasoning Audit's Claims may no longer be relevant. **Within-turn redos** (Critic is redone for gate failure within Turn 1) the Worker draft is unchanged so Claims A/B/C should be stable. **Cross-turn** (Turn 1 → Turn 2) is a different scenario — Critic does new Reasoning Audit each turn against the new Worker draft; this is intended and not subject to drift detection.

Check 5 only applies to within-turn redos (where prior cache exists from a prior attempt this turn). Cross-turn comparison is a different mechanism (DQ tracking, prev_url_verified_critic_only, severity_history).

---

## 2026-05-20 (patch 3) — Coverage Matrix quality enhancement (levers 1+2+3)

### Why this change

User architectural review (after end-to-end test on 1880-1930 electrification) flagged that Turn 1 Coverage Matrix quality directly determines report depth, but the current design has three weaknesses:

1. **Worker SCP underutilized**: Critic Turn 1 receives Worker's Self Coverage Plan but training inertia leads Critic to regenerate from scratch. In tests, only 0-2 of Worker's 8 sub-questions survived into the final Critic Coverage Matrix. The whole "Worker plans first, Critic merges" design intent is essentially dead letter.

2. **Critic commits to spec without self-critique**: current flow is "Critic looks at draft → directly produces Final Matrix". No internal brainstorm-critique-commit phase. Specificity failures and survivorship biases in the matrix itself only get caught (or missed) downstream.

3. **Adequacy criteria too vague to verify**: current criteria are often phrases like "深入讨论 X" or "给出关键问题" — these provide no mechanical anchor for downstream Coverage Verification. A row marked COVERED can rest on subjective Critic judgment rather than measurable evidence.

These three issues compound: a Critic who skips Worker SCP, doesn't self-critique their matrix, and writes vague adequacy criteria produces a Turn 1 spec that locks the entire research direction onto wrong rails for all subsequent turns.

### What changed

**research-critic.md — Coverage Matrix Turn 1 section restructured to three-phase format**

Replaced the previous flat "list 5-8 sub-questions" instruction with a structured brainstorm-critique-commit workflow:

- **Stage A — Brainstorm**: Critic must list ≥ 10 candidate sub-questions, each tagged with origin: `[Worker SCP C#]` (verbatim Worker copy) or `[Critic add]` (new). All Worker SCP rows must appear here — no implicit dropping.
- **Stage B — Critique**: For each Stage A candidate, Critic runs two tests in a markdown table:
  - Specificity test: swap subject — does the question still hold? (Y → too generic, REJECT)
  - Survivorship test: would the answer auto-emerge from successful cases? (Y → REFINE to require failure cases / counterexamples)
- **Retention Map**: Mandatory table mapping every Worker SCP row to RETAIN-AS-IS / RETAIN-REFINED / REJECT, with reason for each REJECT. Includes a `Retention count: N retained / M rejected` line.
- **Final Coverage Matrix**: 5-column schema `| # | 子问题 | 充分覆盖标准 | Origin | Verifier tags |`. Origin column tracks `[Worker SCP C#]` / `[Worker SCP C# refined]` / `[Critic add]`. Verifier tags column lists which mechanical verifier types appear in each row's adequacy criteria.

Five **Verifier tag types** defined with explicit examples and counter-examples (vague criteria that get rejected):
- `[数字]` / `[number]` — numeric thresholds with quantifiers (≥, 至少, minimum)
- `[命名]` / `[named]` — explicit entity-naming requirements
- `[比较]` / `[comparison]` — keywords 对比/差异/vs/between
- `[反例]` / `[failure-case]` — keywords 失败案例/反例/反方/counterexample
- `[时间锚]` / `[time-anchor]` — explicit year regex `\d{4}` or "至少 N 个时间节点"

**SKILL.md c.5 Check 1 adds three Turn-1-only mechanical sub-checks**

- **Coverage Matrix three-phase structure**: scan for the four required sub-headings (`Stage A — Brainstorm`, `Stage B — Critique`, `Retention Map`, `Final Coverage Matrix`). Missing any → gate fail.
- **Coverage Matrix Worker SCP retention count**: parse `## Retention Map` table, count rows with Action ∈ {RETAIN-AS-IS, RETAIN-REFINED}. Must be ≥ 3 unless Critic provides ≥ 100-char `Retention rationale` paragraph explaining why fewer retained.
- **Coverage Matrix adequacy verifier tags**: parse Final Coverage Matrix, for each row scan adequacy column for at least one verifier signature (digit + quantifier OR comparison keyword OR failure-case keyword OR year regex OR named-entity pattern); verify `Verifier tags` column lists actual matches. Missing verifier in any row → gate fail.

**SKILL.md redo prompt updated**

The "Action required" block in the gate-fail redo prompt now includes specific guidance for each new sub-check failure (three-phase missing, retention < 3, adequacy lacking verifier).

### How to verify

When running the skill on Turn 1, look for these signals in Critic output:

- Four explicit `## Stage A` / `## Stage B` / `## Retention Map` / `## Final Coverage Matrix` sub-headings under `# Coverage Matrix`
- Stage A lists ≥ 10 candidates with origin tags
- Retention Map shows explicit Worker SCP → Critic disposition mapping
- Final Coverage Matrix has 5 columns including Origin and Verifier tags
- Each adequacy criterion contains at least one of: a number with quantifier, a named-entity requirement, a comparison directive, a failure-case requirement, or an explicit year/period

Mechanical verifier examples that pass:
- ✅ "至少 3 个具体年份事件" `[数字][时间锚]`
- ✅ "命名 ≥ 2 家代表玩家及其商业模式" `[数字][命名]`
- ✅ "对比 X 和 Y 的差异（≥ 3 个维度）" `[比较][数字]`
- ✅ "≥ 1 个具名失败案例并说明死因" `[数字][反例][命名]`

Examples that fail:
- ❌ "深入讨论该领域的关键问题" — no verifier signature
- ❌ "充分覆盖此话题" — circular, no verifier
- ❌ "给出权威数据" — no quantifier or named source

### Why these three levers (and not others)

User analysis identified four levers; this patch implements the first three (highest ROI / smallest architectural change). Lever 4 (topic-template injection — auto-attach Coverage templates for known task families like business-feasibility / technical-comparison / historical-analysis) deferred because it requires task-type classification logic that doesn't exist in the skill yet.

The deferred but architecturally cleaner long-term option (dynamic Coverage Matrix that evolves across turns via adversarial Critic-Worker negotiation) is documented in conversation history but not built — current monotonic-add-only / lock-on-Turn-1 design is preserved. If future tests show "important sub-questions only emerge after Turn 3" as a recurring pattern, the dynamic design becomes worth the implementation cost.

### Empirical context

Not separately tested — failure mode is structurally analogous to the Worker SCP gap (already empirically validated to need mechanical gating). The three new sub-checks share the same enforcement pattern as Check 1's existing column-structure and Severity validations.

### Risk: increased Critic Turn 1 token usage

Three-phase output adds roughly 30-50% more tokens to Critic Turn 1 output (brainstorm of 10+ candidates, critique table, retention map). On Turn 2+ this is one-time work that doesn't repeat. Net loop token cost increase estimated at 5-10% (Turn 1 is one of typically 2-4 turns).

If empirical testing shows Critic struggles to produce 10 quality brainstorm candidates, the threshold can be tuned down (e.g., ≥ 8). The 10-candidate floor is currently uncalibrated — set as a "force divergent thinking" target, may need adjustment.

---

## 2026-05-20 (patch 2) — Turn-internal redo invariants

### Why this change

End-to-end test on 1880-1930 electrification topic exposed a Coverage Matrix drift bug across Critic Turn 1 redos:

| Stage | Coverage Matrix content |
|-------|------------------------|
| Critic original call | none (schema fail) |
| Critic redo #1 | C1-C9 with sub-questions about "电气化扩散节奏 / 群驱动→单元驱动 / 工人技能结构变化" |
| Critic redo #2 | C1-C9 with **completely different** sub-questions about "电力+科管对工人结构的重塑机制 / 工人受益者 vs 受损者 / 工会与集体行动" |

Despite the redo prompt including "Don't lose: ... The 9-row Coverage Matrix" in prose, Critic regenerated a different version. Then orchestrator paraphrased a third version when passing to Turn 2. Three different Coverage Matrices for the same task, with no mechanical detection — downstream Coverage Verification logic cannot reliably anchor against a moving target.

This is structurally the same failure mode as G1-G12 (prompt嘱托 in agent text without orchestrator-side mechanical enforcement) but applied to a different surface area: cross-attempt content stability within a single turn.

The fix generalizes: any content the Worker/Critic produced in a prior redo within the same turn that wasn't itself the source of the gate failure should be preserved verbatim — and the orchestrator must mechanically validate this preservation rather than asking nicely.

### What changed

**SKILL.md — new section "Turn-internal redo invariants"**

Added explanatory section between `## Execution` and step b. Defines:
- The principle (preserve verbatim across redos within a turn)
- Worker invariants list (SCP table, Search Log queries, Answer body, non-failing Evidence rows, valid Rebuttals stances)
- Critic invariants list (Coverage Matrix, Reasoning Audit, Issues, RDs, fetched URL audit rows, URL verification rows, Worker Rebuttal Adjudication rulings)
- Mechanical preservation procedure (extract → inject in redo prompt → validate after redo with normalized comparison)
- Edge case handling (when invariant content IS the failure cause, mark as non-invariant for that redo)

**SKILL.md — step b adds Worker redo invariant injection**

When any W check triggers redo, orchestrator extracts invariants from the prior Worker output and prepends a "Cached invariants from prior attempt — preserve verbatim" block to the redo prompt. After redo, normalized comparison runs on each cached section.

**SKILL.md — step c.5 adds Critic redo invariant injection + new Check 5**

- Critic redo prompt now includes a structured "Cached invariants from prior attempt" block listing each invariant section verbatim from the most recent Critic attempt this turn that produced it.
- Sections marked NON-INVARIANT for the current redo (i.e., the section that caused the gate failure) are excluded from the cache so they can be regenerated.
- New **Check 5 — Invariant drift detection** runs after Checks 1-4. For each cached invariant section, normalize whitespace and compare with current attempt's content. Mismatch → gate fail with reason `Invariant drift: {section name}`. Counts toward max 2 redos.
- Specific drift cases that always trigger fail:
  - Coverage Matrix sub-question text changed (Turn 1)
  - Issue severity changed without explicit Worker rebuttal acceptance
  - RD body's substantive content changed (named entity / number / framework switched)
  - Already-Critic-verified URL status changed
  - Reasoning Audit sub-check assessment switched (Y → N) without revision rationale

**SKILL.md — step e tightens verbatim extraction**

Explicit reminder added: extracted Coverage Matrix / DQ / URL Verification rows must be byte-for-byte from `critic_output`. No paraphrasing, condensing, whitespace normalization, or orchestrator-side rewriting. The empirical citation in the change rationale: "the 1880-1930 electrification test where the orchestrator condensed the Critic's Coverage Matrix into a different summary version, causing untrackable drift."

### How to verify

When running the skill with redos, look for these new signals:

- Critic redo prompts now contain a `## Cached invariants from prior attempt — preserve verbatim` block listing prior content
- Check 5 may appear in gate fail reasons: `Invariant drift detected: # Coverage Matrix. Prior attempt content differs from current attempt content.`
- Coverage Matrix content from Critic Turn 1 is byte-identical when passed to Critic Turn 2 (compare orchestrator state)

### Why this is a structural fix not a patch

Patches 1-3 (P0/P1/P2 gaps) addressed each missing mechanical check individually. Patch 4 establishes a generic invariant-protection pattern that prevents an entire class of "content drift across redos" bugs. Future turn-internal redo logic can plug into this framework without re-inventing per-section preservation rules.

The deeper insight: research-loop's correctness depends on certain content being stable across the redo sub-loop within a turn. Without mechanical preservation, every redo is a fresh generation, which means orchestrator state (cross-turn variables like `coverage_matrix`, `prev_dq`, etc.) cannot reliably depend on any specific prior-turn content. The invariant cache makes "same turn, multiple attempts" semantically meaningful — only the failing thing changes, everything else is by-construction stable.

### Empirical context

Identified post-test by user review of the 1880-1930 electrification run. Not separately re-tested — the failure mode and fix are structurally analogous to the Worker SCP gap (already empirically validated). If future tests show drift slipping past Check 5, the comparison heuristic (currently "normalized whitespace + sub-question text + severity / RD body / URL status") may need tuning.

---

## 2026-05-20 — P2 quality gap closure (the long tail)

### Why this change

Patch 2 (2026-05-19) closed P0 + P1 gaps. P2 gaps were initially deferred as low-impact, but on reconsideration they share the same structural property as P0/P1 — they're all "prompt嘱托 in agent files but no orchestrator-side validation." Leaving them open means: (a) every future test could surface one of them as a fresh surprise; (b) Critic / Worker have no incentive to stop generating skinny placeholder content if the orchestrator doesn't push back; (c) the asymmetry between heavily-gated areas (URL fetch) and lightly-gated areas (DQ count, RD substance) creates inconsistent quality floors.

The 5 gaps closed here:

| ID | Gap | Where it stated the requirement | Why mechanical validation matters |
|----|-----|--------------------------------|-----------------------------------|
| G8 | Worker `## Self Coverage Plan` table has < 5 or > 8 sub-questions | worker.md:150 mandate "5-8 sub-questions" | Fewer than 5 → coarse plan that doesn't function as coverage standard; more than 8 → dilution / list-padding |
| G9 | Critic `# Coverage Verification` rows marked COVERED missing actual quotes | critic.md:140 "You MUST provide a direct quote" | COVERED without quote = unverifiable claim coverage; reduces Coverage Verification to checkbox theater |
| G10 | Critic `# Deepening Questions` count outside [2, 3] | critic.md:145-151 mandates 2-3 DQs | Fewer than 2 → insufficient depth probing; more than 3 → list-padding rather than substantive probes |
| G11 | Critic `# Research Directions` count outside [2, 3] OR each RD body < 300 chars / lacking concrete content | critic.md:182-184 + Role 2 spec demanding "2-3 paragraphs of actual substance" | Skinny RDs are task-list disguised as research content — exactly what Role 2 explicitly forbids ("you are not writing a task list") |
| G12 | Critic `# Reasoning Audit` missing one or more of the 4 sub-checks (Specificity / Survivorship / Inference / Consistency) | critic.md:96-126 specifies all 4 | Result line alone is insufficient — without sub-check evidence, "Reasoning Audit result: CLEAN" can be Critic shortcutting without actually doing the audit |

### What changed

**SKILL.md — step b adds W6**

- **W6 (NEW)**: SCP sub-question count. Parses the `## Self Coverage Plan` markdown table and counts data rows (excluding header + separator). Must be in [5, 8] inclusive. Out of range → redo with explicit count and target range.

Worker output gate now runs W1-W6 (was W1-W5).

**SKILL.md — c.5 Check 1 adds 4 quality validations**

Existing Check 1 (schema + columns + severity) extended with:

- **Coverage Verification quote check**: each row with Status=COVERED must have Evidence column containing ≥10 non-whitespace chars AND quote marks (`"..."` or `"..."`) or specific phrase reference. Empty / `—` / `n/a` / generic descriptions on COVERED rows are gate fail. PARTIAL/MISSING rows exempt.
- **DQ count check**: count of `^- DQ\d+:` items in `# Deepening Questions` must be in [2, 3] inclusive.
- **RD count + body check**: count of `**RD\d+:` or `## RD\d+:` sub-headings in `# Research Directions` must be in [2, 3]. Each RD's "Critic's contribution" body must be ≥ 300 non-whitespace chars AND contain at least one specific concrete reference (number / named entity / technical term / year). Skinny / abstract RDs are gate fail.
- **Reasoning Audit sub-check check**: `# Reasoning Audit` body must contain all 4 literal sub-headings: `Check 1 — Specificity test`, `Check 2 — Survivorship bias`, `Check 3 — Inference chain completeness`, `Check 4 — Internal consistency`. Each must be followed by an assessment line. Missing any → gate fail.

Redo prompt's "Action required" updated with item-by-item fix instructions for each new failure type.

### Why these heuristics work (and where they don't)

**Why character-count threshold for RD body**: 300 chars ≈ 2-3 short paragraphs. Lower would let one-sentence "task assignments" pass; higher would push Critic toward padding. Empirically validated against Test 3 (LLM inference optimization) where Critic-supplied RDs were 500-1200 chars each — well above threshold.

**Why "concrete reference" requirement on RD**: prevents Critic from satisfying char count with vacuous filler ("we should explore the trade-offs and consider various perspectives..."). Mechanical proxy: regex check for digits OR Title Case proper nouns OR known technical terms. Imperfect but catches the worst offenders.

**Why count ranges (5-8 SCP, 2-3 DQ/RD) instead of just minimums**:
- SCP > 8: signals Worker can't synthesize — too many partially-overlapping sub-questions
- DQ > 3: signals Critic is padding the list with surface-level questions
- RD > 3: same — Role 2 expects 2-3 deep contributions, not a brainstorm dump

**Where these heuristics fail**: a determined Worker/Critic could pad to exactly threshold lengths with low-effort filler that passes regex but fails human review. These gates raise the floor, not the ceiling. The actual quality lives in the reasoning chain visible to humans reading the final report.

### How to verify

When running the skill, look for these new redo signals:
- `W6 hits: SCP has [N] sub-questions, target [5-8]`
- Check 1 redo prompts now include `Coverage row [N] missing quote on COVERED`, `DQ count [N], target [2-3]`, `RD [N] body too skinny ([X] chars)`, `Reasoning Audit missing sub-check [Specificity|Survivorship|Inference|Consistency]` as distinct failure modes

### Empirical context

Not separately tested. The failure modes are structurally analogous to G1-G7 (already validated to need mechanical gating in patch 2). Same fix pattern (orchestrator-side count/content/structure check + redo) applies. The 300-char RD threshold and [2,3] DQ/RD range thresholds are calibrated against observed Critic output in prior tests; if future tests show too many spurious gate fails (e.g., legitimate research with only 2 sub-questions), thresholds can be tuned.

### Final gate inventory (after this patch)

```
step b — Worker output gate
├── W1 ## Self Coverage Plan heading exists                  (Turn 1)
├── W2 # Rebuttals heading exists                            (Turn 2+)
├── W3 Source URL not bare-domain / grounding-redirect / etc (every turn)
├── W4 ## Issue / ## RD have Stance: line                    (Turn 2+)
├── W5 Track B engagement count ≥ 2                          (Turn 2+)
└── W6 SCP sub-question count in [5, 8]                      (Turn 1)

step c.5 — Critic output gate
├── Check 1 (schema + quality)
│   ├── Required headings present
│   ├── First-line VERDICT format
│   ├── # Critic WebFetch Audit has Tool used column
│   ├── # URL Verification Report has Provenance column
│   ├── ## Issue Severity ∈ {critical, major, minor}
│   ├── # Coverage Verification COVERED rows have quotes
│   ├── # Deepening Questions count in [2, 3]
│   ├── # Research Directions count in [2, 3] + body ≥ 300 chars + concrete content
│   └── # Reasoning Audit has 4 sub-checks
├── Check 2 first-encounter URL fetch completeness
├── Check 3 prose self-admission scan
└── Check 4 Playwright escalation on suspicious WebFetch
```

10 gates total, organized by mechanical detectability. P3 (still uncovered) — heuristically harder gaps deferred per CHANGELOG patch 1 design notes (Phase 1/2 ordering, failed-fetch retag laundering across turns, Turn 1/2 auto-REVISE composite rules) — left to prompt嘱托.

---

## 2026-05-19 (patch 2) — P0 + P1 schema gap closure

### Why this change

Self-audit of three files (SKILL.md / worker.md / critic.md) for "prompt嘱托 but no mechanical validation" patterns identified 12 remaining gaps. Top tier (P0/P1) addressed in this patch — the rest (P2 quality issues like "Coverage Verification quotes empty", "RD body too short") deferred as low-impact.

The 7 gaps closed here:

| ID | Gap | Where it stated the requirement | What broke without the gate |
|----|-----|--------------------------------|----------------------------|
| G1 | `# URL Verification Report` table missing `Provenance` column | critic.md:254-269 specifies the column | step e's `prev_url_verified_critic_only` filter (matches rows where Provenance starts with `Critic-verified`) silently fails — either passes nothing (forcing wasteful re-fetch) or passes everything (allowing Worker-self-fetch laundering) |
| G2 | `# Critic WebFetch Audit` table missing `Tool used` column | critic.md:211-219 specifies the 6-column schema | Check 4 (Playwright escalation detection) reads this column to detect missed escalations — column absent = Check 4 silently disabled |
| G3 | `## Issue` lacks `Severity:` field or value not in {critical, major, minor} | critic.md:155-163 specifies the format | step f counts severity_history; malformed severity defaults to 0; step g2 (early-exit on diminishing returns) may spuriously trigger or fail to trigger |
| G4 | Worker Source URL is a bare domain root (e.g., `https://www.idc.com/`) | worker.md:162, 248 ban bare domains | empirically observed multiple times — only Critic catches via fetch, costing 1-2 extra turns |
| G5 | Worker Source URL is a grounding-redirect (e.g., `vertexaisearch.cloud.google.com/grounding-api-redirect/...`) | worker.md:250, anti-pattern #11 | grounding redirects expire within days; Critic's blacklist catches but post-hoc |
| G6 | Worker Track B engaged < 2 RDs (requires ≥2) | worker.md:115 mandate | Critic should detect on Turn 2+ but may miss; single-side compliance breaks adversarial integrity |
| G7 | Worker `# Rebuttals` sub-headings missing `Stance:` line or value invalid | worker.md:140-148 format | Critic's Worker Rebuttal Adjudication reads stance to decide ACCEPTED/REJECTED rulings; malformed stance breaks adjudication |

### What changed

**SKILL.md — step b expanded to W1-W5 (Worker output gate)**

Replaced the previous 2-check structure (SCP + Rebuttals heading) with 5 ordered checks:

- **W1**: `## Self Coverage Plan` heading exists (Turn 1) — unchanged from prior patch
- **W2**: `# Rebuttals` heading exists (Turn 2+) — unchanged from prior patch
- **W3 (NEW)**: Source URL blacklist scan on every turn. Regex-flags bare domain roots, grounding-redirect URLs, SERP URLs, and "search summary" placeholders in Evidence Table rows labeled `[事实·强]`/`[FACT]`/`[事实·弱]`. Exempts `[领域共识]`/`[DOMAIN]`/`[INFERENCE]`/`[推断]` rows.
- **W4 (NEW)**: Stance line per `## Issue [N]:` and `## RD [N]:` inside `# Rebuttals` (Turn 2+). Must match allowed stance set per sub-heading type.
- **W5 (NEW)**: Count engaged RDs (Stance contains `ACCEPT (mode)` in Rebuttals OR non-empty `Engagement mode:` in Revision Log). Must be ≥ 2 (Turn 2+).

Each check has its own redo prompt explaining the specific deficiency.

**SKILL.md — Check 1 expanded with column + Severity validation**

Existing Check 1 (schema completeness) extended:

- **Column structure validation**: `# Critic WebFetch Audit` table must have `Tool used` column header; `# URL Verification Report` table must have `Provenance` column header. Missing columns are gate fail.
- **Issue Severity validation**: each `## Issue [N]:` body must contain a `Severity:` line with value in {`critical`, `major`, `minor`}. Other values (`blocker`, `trivial`, `low`, `high`) are gate fail. Exemption: if `# Issues` literally says "No material issues this turn" with no sub-headings, validation is skipped.

Redo prompt updated to differentiate the new sub-failures (heading missing vs column missing vs severity malformed).

### Why these gates and not others

P2 gaps (G8-G12) deferred:
- **SCP sub-question count 5-8**: low impact — Worker may legitimately have fewer if topic is narrow
- **Coverage Verification quote per row**: hard to mechanically validate "quote is non-trivial"
- **DQ/RD count and body length**: similarly hard to mechanically score "substantive" — Critic's prompt嘱托 has been working OK in tests
- **Reasoning Audit 4 sub-checks present**: only the result line is consumed; full sub-structure is for human readability

These remain prompt嘱托 only. If empirical observation shows them failing, can be added in a future patch.

### How to verify

When running the skill, look for these new redo signals:
- `W3 hits: bare domain / grounding redirect / SERP URL / placeholder` in orchestrator state
- `W4 hits: missing Stance` listing offending sub-headings
- `W5 hits: only N RDs engaged (need 2)`
- Check 1 redo prompts now include `Missing Tool used column` / `Missing Provenance column` / `Malformed Severity` as distinct failure modes

### Empirical context

Not separately tested — the failure modes are structurally analogous to already-validated gaps (Self Coverage Plan, Rebuttals heading). Same fix pattern (orchestrator-side mechanical check + redo) applies.

---

## 2026-05-19 (patch) — Critic schema completeness gate

### Why this change

External review (codex) flagged that the URL-verification gates added earlier did not validate Critic output structure itself. If Critic returned malformed output (e.g., missing `# Issues`, missing `# Coverage Verification`, malformed first-line VERDICT), the orchestrator silently degraded:

1. step d's "malformed first line → treat as REVISE" did not redo, just downgraded the verdict
2. step e built `critic_feedback` by extracting required sections; missing sections produced empty content with no error
3. Worker received a degraded feedback bundle and the loop continued with broken state propagating
4. Existing c.5 Checks 1-3 only validated URL fetch behavior, not output schema

Same failure pattern as the Worker `## Self Coverage Plan` gap: prompt嘱托 in critic.md ("mandatory" tags on each section) was insufficient because LLMs do not reliably honor section requirements that aren't mechanically checked.

### What changed

**SKILL.md**

- **step c.5 Check 1 (NEW): Critic output schema completeness**. Validates first-line VERDICT format and presence of all required headings (`# Reasoning Audit` with `Reasoning Audit result:` line, `# Coverage Verification`, `# Issues`, `# Deepening Questions`, `# Research Directions`, `# Summary`, `# Critic WebFetch Audit`, `# URL Verification Report`, plus Turn-1-only `# Coverage Matrix` and Turn-2+-only `# Worker Rebuttal Adjudication`). Missing sections trigger redo with explicit list of what's missing.
- **Existing checks renumbered**: old Check 1 → Check 2 (URL fetch completeness), old Check 2 → Check 3 (prose self-admission), old Check 3 → Check 4 (Playwright escalation).
- **step d simplified**: malformed verdict is now caught by Check 1 in c.5; step d's old "treat as REVISE" became a defensive fallback marked as "should be unreachable if c.5 ran correctly."
- **step e tightened**: `# Worker Rebuttal Adjudication` no longer has "if present" tolerance — it's required by Check 1 on Turn 2+. `# Meta-concerns` remains genuinely optional (no gate fail on absence) since it's only present when cross-cutting patterns exist.

### How to verify

When running the skill, look for these signals:
- Critic redo triggered on missing required heading: search orchestrator state for `Check 1 hits` or `missing required sections`
- Loop Summary verdict path no longer contains untracked "REVISE (malformed)" — malformed Critic output now becomes "REVISE (Critic-gate-failed-after-2-redos)" if redo also fails

### Empirical context

This patch was applied without further test runs — the failure mode is structurally analogous to the Worker SCP gap (already empirically validated to need mechanical gating), and the fix is symmetrical.

---

## 2026-05-19 — Mechanical gates + Playwright fallback

### Why this change

Empirical testing exposed three structural failure modes that prompt-engineering alone could not fix:

1. **Worker silent non-compliance**: Worker reliably skipped new section-level requirements (e.g., `## Self Coverage Plan`) regardless of how prominently the prompt stated them. Worker also routinely "complied" with URL-path requirements by fabricating plausible-looking paths (e.g., `https://techcrunch.com/2024/05/16/julius-ai-data-analysis-startup-seed/` — well-formed, topical, but 9/10 such URLs returned 404 / SEO-rotated content / placeholder pages when actually fetched).
2. **Critic verification laundering**: Critic inherited Worker's "I fetched it" claims into its own audit table without independent verification, then issued PASS while admitting in prose ("本应抓未抓 — Critic 失职") that it didn't actually fetch.
3. **WebFetch blind spots**: WebFetch doesn't execute JavaScript, so SPA-rendered docs sites (vLLM/SGLang/NVIDIA documentation portals) return JS shells that look like soft 404s. Critic could not distinguish "page legitimately empty" from "JS hasn't run yet."

Pure prompt嘱托 was insufficient — these LLMs reliably matched familiar templates rather than executing new rules. Mechanical orchestrator-side gates + redo + a fallback escalation path were needed to close the loop.

### What changed

**SKILL.md — three orchestrator gates, two redo flows**

- **step b (Worker output gate)**: After Worker returns, orchestrator runs literal-string match on `## Self Coverage Plan` (Turn 1) or `# Rebuttals` (Turn 2+). Missing section → reject + redo (max 2). Forces structural compliance via mechanical check rather than嘱托.
- **step c.5 (Critic verification gate)**: Three sub-checks on Critic output:
  - **Check 1**: Every first-encounter URL with valid page path must have a `Yes — Turn N` row in Critic WebFetch Audit. Inheriting from Worker self-reports is rejected.
  - **Check 2**: Grep prose for self-admission phrases (`本应抓未抓`, `Critic 失职`, `Critic-self-failure`). Match → redo.
  - **Check 3** (NEW Playwright escalation): For any row where WebFetch returned 200 but content matched soft-failure patterns (`Page not found`, `Loading...`, `noscript`, content length < 500, SEO-rotated landing), Critic must escalate to Playwright. If `Tool used` column doesn't include `Playwright` for such rows → redo with Playwright instructions.
- **DAC simplified**: removed defensive prose that emerged from anticipating self-rationalization. Added C5 (`[事实·强]` ratio ≥ 25%) to prevent "downgrade-everything-to-pass" gaming. DAC now triggers only when `verdict_path` is empty (Critic was never called) — Critic's verdict is otherwise authoritative.
- **Early-exit rule (g2)**: After turn ≥ 3, if 2 consecutive turns produced zero critical/major issues, override REVISE → PASS (Early-exit). Remaining minors merged into `# What I Don't Know`.
- **Severity history**: orchestrator now tracks `{turn, critical, major, minor}` per turn, surfaced in Loop Summary.
- **Worker rebuttals extraction moved to step b**: extracted from `current_draft` immediately after Worker returns, passed to Critic via prompt — no longer relies on Critic to dig it out.
- **`prev_url_verified_critic_only`**: filtered from prior `# URL Verification Report` to keep only rows whose `Provenance` column starts with `Critic-verified`. Drops `Worker-claimed` rows so the next Critic turn cannot inherit Worker self-reports through the orchestrator.

**research-worker.md — phased mandatory order + 4 new anti-patterns**

- New **Phase 0 → 1 → 2 → 3 mandatory order** at top: PLAN → SEARCH → WRITE → SELF-AUDIT. `## Self Coverage Plan` is now Turn-1 first action, before any WebSearch.
- Output format adds two new sections:
  - `## Self Coverage Plan` (Turn 1 only, very first heading)
  - `# Rebuttals` (Turn 2+ mandatory, with `## Issue [N]` / `## RD [N]` substructure declaring stance ACCEPT / CHALLENGE / PARTIAL)
- New **Track C (Rebut where Critic is wrong)** added to revision tracks alongside Track A (fix issues) and Track B (engage RDs). Silent compliance with a wrong Critic is now explicitly forbidden.
- Search Log adds **WebFetch-only row format** for URLs fetched without prior WebSearch (e.g., verifying a Critic RD's specific number).
- Search Log Rules add **grounding-redirect URL ban** (`vertexaisearch.cloud.google.com/grounding-api-redirect/...` and equivalents).
- Anti-patterns expanded:
  - **#8 Failed-fetch retag laundering**: WebFetch returning unrelated content means the source is falsified, not weakened — drop the data point, don't relabel `[事实·强]` → `[事实·弱]` and keep the number.
  - **#9 Critic-knowledge laundering**: Critic-RD-supplied numbers are training-knowledge claims until Worker independently fetches and verifies. Citing "search summary" or grounding-redirect URL doesn't qualify.
  - **#10 Silent compliance with wrong Critic**: silently rewriting to remove friction trains the loop to converge on whoever talks more — must use `# Rebuttals` instead.
  - **#11 URL path fabrication to satisfy gate checks** (NEW): well-formed-and-topical URL ≠ valid URL. Empirically observed pattern markers documented (date components matching claim, plausible-looking container IDs, multiple URLs from same domain following same conjectured pattern). Rule: cite only what WebSearch/WebFetch returned character-for-character — no path infilling.

**research-critic.md — Provenance column + URL fabrication detection + Playwright fallback guide**

- `# Critic WebFetch Audit` table now has 6 columns: added **Tool used** column (`WebFetch` / `Playwright` / `WebFetch + Playwright (escalated)` / `Skipped — prior Critic-verified`).
- `# URL Verification Report` table now has **Provenance** column (`Critic-verified Turn N` / `Worker-claimed (NOT yet Critic-verified)` / `Critic-verified Turn N-X (skipped this turn, claim unchanged)`). Orchestrator filters by Provenance starting with `Critic-verified` to build `prev_url_verified_critic_only` — removes the Worker-self-fetch laundering chain.
- New **"When to escalate from WebFetch to Playwright"** section with 7-row trigger table (suspicious WebFetch signals → escalation actions). Documents Playwright call sequence: `browser_navigate` → `browser_wait_for` 2-3s → `browser_snapshot`. Cost discipline noted: escalate only on suspicious signals, not by default.
- New **URL fabrication detection** rule in URL Verification: well-formed URLs with topical slugs are NOT evidence of validity. Specific pattern markers documented (date matching claim, plausible container IDs, repeated path conjectures). Suspicious URLs get extra fetch priority. Content-mismatch markers documented (`Article Not Found`, `Bulk Material Handling Device Market`-style SEO rotation, `currently being developed`, homepage redirect).
- New **Critic-RD provenance check** (Turn 2+): for any draft claim traceable back to a prior-turn Critic RD (e.g., "ICONIQ 2024 GPM 41%"), Worker must have either independently fetched a URL whose content Critic can verify, or explicitly downgraded to `[推断]/[领域共识]`. Mere relabel-as-`[事实·弱]`-with-search-summary-source is laundering and now flagged as critical Issue.
- **Source-string blacklist** added in URL Verification rules: grounding redirects, SERP URLs, "search summary" placeholders, vendor home pages anchoring vendor-specific claims, archive.org timestamp-less paths.
- **Orchestrator gate awareness** paragraph added: Critic now informed that orchestrator runs the three c.5 checks after return, including prose-grep for self-admission phrases. Discourages the "admit in prose, hope next turn fixes it" strategy.
- **Worker Rebuttal Adjudication** restructured: now expects Worker's `# Rebuttals` section to use ACCEPT / CHALLENGE / PARTIAL stance per Issue/RD, with explicit ruling format. Missing `# Rebuttals` on Turn 2+ is critical Issue. Critic must steelman challenges (cannot auto-reject without articulating specific gap).
- **Coverage Matrix Turn 1 workflow** rewritten: Critic now reads Worker's `## Self Coverage Plan`, then keeps/replaces/augments items to produce authoritative Coverage Matrix. Worker's plan is input, not output.

### How to verify the changes work

When running this skill, look for these signals in output:

- Worker Turn 1 first heading should be `## Self Coverage Plan` (if not, gate triggered redo)
- Worker Turn 2+ should contain `# Rebuttals` with explicit stance per Critic Issue
- Critic `# Critic WebFetch Audit` should be 6 columns (`Tool used` present)
- Critic `# URL Verification Report` should be 5 columns (`Provenance` present)
- Loop Summary should include `Severity history: Turn 1 [crit:X maj:Y min:Z] → ...`
- Verdict path should be one of: `PASS (Critic)`, `PASS (DAC)`, `PASS (Early-exit)`, `REVISE at MAX_TURNS`, `FAIL`

### Empirical test results (2026-05-19 session)

- **Test 1** (DAaaS topic, full loop): old behavior reproduced — 14/14 bare-domain URLs, Critic 0 fetches, 3-turn convergence with shallow PASS.
- **Test 2** (after first round of changes): Worker still skipped `## Self Coverage Plan` despite prompt嘱托. Mechanical gate + redo successfully forced compliance.
- **Test 3** (LLM inference optimization topic, end-to-end): Worker SCP gate triggered + redo successful; Worker URLs 21/24 with valid paths (genuine arxiv/usenix/github format); Critic fetched 10/10 first-encounter URLs voluntarily; Critic abstained from Playwright escalation correctly (large real content present); Critic identified 2 citation mismatches (`arxiv:2402.02057` is Lookahead Decoding not SD evidence; `arxiv:2407.08454` is KV-Merger not INT4 quantization) — exactly the kind of finding only real fetch + abstract-reading can produce.

### Known limitations

- **Worker URL fabrication still possible**: Anti-pattern #11 documents the issue but no mechanical pre-Critic check exists. Detection happens only when Critic fetches. Fabrication probability dropped substantially in test 3 vs prior tests, but not zero.
- **Critic Check 3 heuristic surface area**: the soft-failure pattern list (`Page not found`, `Loading...`, etc.) is hand-curated. Real-world failure modes may include patterns not on the list. Updates expected as new failure modes are observed.
- **Playwright cost not budget-capped**: orchestrator does not currently enforce a max-Playwright-calls-per-turn limit. If a malicious or buggy run triggers escalation on every URL, token cost could spike. No incident yet, but worth tracking.

---

## Pre-2026-05-19 — Initial design

Design intent at this stage:
- Worker-Critic adversarial loop with up to MAX_TURNS=10 iterations
- Worker uses 4-track search strategy (mainstream / criticism / failure / non-conventional)
- Critic dual role: adversarial auditor + research accelerator (Research Directions with substantive content)
- Coverage Matrix generated by Critic Turn 1, used as authoritative coverage standard from Turn 2+
- DAC (Draft Acceptance Criteria) as fallback when orchestrator skipped Critic invocation
- Cycle detection via Issue title overlap (≥70% repeat → FAIL)

Behavioral failures discovered through testing led to the 2026-05-19 changes above.
