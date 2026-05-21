# cc-research-report

一个 Claude Code skill，通过 worker↔critic 对抗验证循环完成研究，并将经过验证的输出渲染为设计驱动的 HTML 报告。

> English docs: [README.md](./README.md)

---

## 安装

```bash
git clone <仓库地址>
cd cc-research-report
./install-local.sh     # 在 ~/.claude/ 中创建 skills/ 和 agents/ 的符号链接
# 重启 Claude Code 生效
./uninstall-local.sh   # 卸载
```

**前置依赖：** [`frontend-design` 插件](https://github.com/anthropics/claude-plugins-official)——HTML 渲染步骤必需：

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install frontend-design
```

---

## 使用方式

在任意 Claude Code 会话中触发：

```
/research-report AI对教育的影响
/research-report "impact of AI on education"
/research-report 智能体 AI 系统的主要风险有哪些？max_turns: 6
```

**输出文件：**

| 文件 | 说明 |
|------|------|
| `./{标题}-report.html` | 设计驱动的 HTML 报告，生成在当前目录 |
| `~/.claude/cache/research-loop/{slug}-{时间戳}.md` | 经验证的 Markdown + 循环摘要（审计记录） |
| `~/.claude/cache/research-loop/{slug}-{时间戳}-query.md` | 原始问题文本 |

**免重新研究的重新渲染** — 直接将 `research-html-formatter` 指向缓存的 `.md` 文件即可。研究成本只付一次，改变视觉样式不需要重新搜索。

**缓存行为** — 7 天内再次提问相似问题时，skill 会询问是否复用缓存研究，直接跳到 HTML 渲染步骤。

---

## 工作原理

```
/research-report "你的问题"
        ↓
[第 0 步] 缓存检查 — 7 天内有缓存则提示复用
        ↓
[第 1 步] research-loop（最多 10 轮）
  ┌─ Worker：制定计划 → 搜索 → 起草 → 自审
  │    第 1 轮：搜索前先确定自我覆盖计划（5–8 个子问题）
  │    第 2 轮起：对每条批评意见明确表态（接受 / 挑战 / 部分接受）
  │
  └─ 4 个 Critic 并行运行（每轮）：
       instruction  →  覆盖矩阵 + URL 验证 + 裁决（VERDICT）
       dialectic    →  推理审计（特异性、幸存者偏差、推断链、内部一致性）
       depth        →  深度缺口 + 新研究方向
       width        →  搜索日志审计（未覆盖的搜索轨道）
        ↓
  重复直至 VERDICT: PASS 或达到最大轮次
        ↓
[第 1.5 步] 经验证的 Markdown 写入 ~/.claude/cache/research-loop/
        ↓
[第 2 步] research-html-formatter
  → 必须先调用 frontend-design skill
  → 明确声明美学方向
  → 将 HTML 写入磁盘
        ↓
[第 2.5 步] 设计强制门
  → 验证 "Design direction:" 行中包含具体美学描述符
  → 不通过则重试（最多 2 次）
```

---

## 设计理念

**1. 对抗验证，而非自我审查。**
Worker 从不评判自己的工作。4 个 Critic 各自负责一个独立审计维度——没有任何单一 agent 试图包揽一切。这与严谨的人类评审机制相同：不同的审查者负责不同的关注点。

**2. 机械门控，而非提示嘱咐。**
LLM 在被"友善地要求"时，会可靠地跳过结构性要求。每一个关键不变量——自我覆盖计划标题、反驳立场、来源 URL 格式——都有编排层级的门控，失败时强制重做。CHANGELOG 记录了 20+ 个补丁，全部遵循同一模式：*提示失败 → 添加门控*。

**3. 轮内重做不变量。**
当门控触发重做时，未改变的部分会被缓存、逐字注入并验证漂移。这防止了模型在"修复"一行的同时悄悄将其他九行正确内容重新生成为不同版本。

**4. 声明标注是一等输出。**
最终答案中的每一个声明都带有明确的认知标签：`[事实·强]`、`[推断]`、`[领域共识]`、`[理论假设]`。读者清楚地知道哪些是经过核实的，哪些是综合推断的——不存在虚假的确定性。

**5. 研究与渲染解耦。**
经验证的 Markdown 在 HTML 渲染之前写入磁盘。更换视觉风格无需重新研究。

---

## 核心特色

- **每轮 4 个 Critic 并行审查**：覆盖度、推理、深度、搜索宽度
- **自我覆盖计划**：Worker 在执行任何搜索之前，先承诺 5–8 个可验证的子问题
- **反驳系统**：对每条批评意见明确表态（接受 / 挑战 / 部分接受），不存在被动接受
- **来源 URL 门控**：标注为 `[FACT]` 的证据表行必须有可访问的 `https://` URL；裸域名、搜索重定向、SERP URL 一律拒绝
- **7 天研究缓存**，附带原始查询伴随文件，保证可追溯性
- **设计强制的 HTML 输出**：格式化器必须声明具体美学方向（如 `"editorial / Noto Serif + JetBrains Mono / deep navy + amber"`），通用输出会被拒绝
- **循环摘要**随每份 Markdown 输出附加：裁决路径、使用轮次、开放研究方向

---

## 适用场景

**适合：**
- 需要信任输出结果的多角度研究（竞争分析、政策比较、文献综述）
- 存在争议证据、简单综合会产生误导的问题
- 需要分享或发布的研究——证据表和声明标注提供可追溯的审计记录
- 可能需要日后用不同视觉呈现方式重新渲染的主题

**不适合：**
- 快速查询或单一事实问题
- 无法通过网络搜索获取的专有或内部数据
- 实时数据（价格、指标、实时数据流）
- 需要在研究过程中与用户反复交互的任务

---

## 局限性

- **仅限网络搜索** — 无法访问专有、付费墙或内部知识库
- **非实时** — 获取已发布内容，不是实时数据流
- **英文来源偏差** — 网络搜索在结构上偏向英文；非英文研究主题对当地文献的覆盖可能较浅
- **搜索轨道偏斜** — 4 轨道搜索策略（主流 / 反驳 / 失败案例 / 非常规）在实际执行中系统性地少执行第 3–4 轨道；深度 Critic 会标记缺口，但偏斜是结构性的，无法通过提示修复
- **跨问题无记忆** — 每次 `/research-report` 调用都是独立的，不会在先前会话的基础上构建
- **第 1 轮 W1 重做几乎必然发生** — 无论使用何种模型，自我覆盖计划标题门控在第一轮几乎总会触发一次重做；这是已知的结构性限制，不是 bug
- **缓存无限增长** — 没有自动清理机制；需手动修剪 `~/.claude/cache/research-loop/`

---

## 文件结构

```
cc-research-report/
├── skills/
│   ├── research-report/
│   │   └── SKILL.md              # 流水线编排器（第 0→1→2 步）
│   └── research-loop/
│       ├── SKILL.md              # worker↔critic 循环及所有机械门控
│       └── CHANGELOG.md          # 每个补丁及其设计决策理由
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

## 许可证

MIT — 详见 [LICENSE](./LICENSE)。
