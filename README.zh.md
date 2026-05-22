![CC Research Report](assets/banner.png)

### 实验性：专为 Claude Code 构建的多轮对抗验证研究

[![License: MIT](https://img.shields.io/github/license/npxcnency-ux/CC-Reseach-Report)](LICENSE) [![GitHub stars](https://img.shields.io/github/stars/npxcnency-ux/CC-Reseach-Report?style=social)](https://github.com/npxcnency-ux/CC-Reseach-Report)

---

**cc-research-report 为 Claude Code 研究引入了结构性对抗验证。**
搜索开始前，Worker 必须先提交自我覆盖计划——5-8 个各带具体可验证标准的子问题（须含数字、命名实体、比较要求、失败案例或时间锚之一）——在任何证据收集前就锁定覆盖目标。随后四轨制搜索驱动起草：主流共识、反驳论据、失败案例、非常规视角，从源头抵抗确认偏差。四个 Critic 作为独立 subagent 并行审计各自轴线，上下文完全隔离，无法被 Worker 的叙事框架先入为主地锚定。

Worker 持有反驳权：对每条批评意见明确表态（接受 / 挑战 / 部分接受），Critic 必须认真回应每一项挑战，不得自动驳回。第 1 轮锁定的覆盖矩阵只能修补、不能重新生成，防止多轮迭代中移动研究目标。Orchestrator 向下一轮传递的 URL 记录仅含 Critic 亲自验证的条目，过滤 Worker 自报来源，阻止未验证 URL 在后续轮次中被当作已确认引用。严重程度历史、轮内重做不变量、研究方向均由 orchestrator 统一管理——任何 agent 都无法将未经验证的状态洗入记录。每条输出结论携带认知标签：`[事实·强]` / `[推断]` / `[领域共识]`。

| 普通多 Agent 方式 | cc-research-report |
|---|---|
| 先搜索，事后编覆盖理由 | 搜索前先锁定覆盖计划 |
| 单 agent 单轮，一次出结果 | Worker↔4 Critic，最多 10 轮迭代 |
| 各 agent 共享上下文 | 独立 subagent，Critic 无法被 Worker 叙事锚定 |
| Critic 裁决不可质疑 | Worker 持有反驳权（接受 / 挑战 / 部分接受） |
| 研究目标可在中途改变 | 覆盖矩阵第 1 轮锁定，只能修补，不能重新生成 |
| Agent 自报状态 | Orchestrator 统一管理 URL 来源、重做不变量、严重程度历史 |

> English docs: [README.md](./README.md)

---

## 安装

```bash
git clone https://github.com/npxcnency-ux/CC-Reseach-Report.git
cd CC-Reseach-Report
./install-local.sh     # 在 ~/.claude/ 中创建符号链接
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
/research-report 向量数据库市场竞争格局
/research-report 智能体 AI 系统的主要风险 max_turns: 6
```

**输出文件：**

| 文件 | 说明 |
|------|------|
| `./{标题}-report.html` | 设计驱动的 HTML 报告，生成在当前目录 |
| `~/.claude/cache/research-loop/{slug}-{时间戳}.md` | 经验证的 Markdown + 循环摘要（审计记录） |
| `~/.claude/cache/research-loop/{slug}-{时间戳}-query.md` | 原始问题文本 |

**免重新研究的重新渲染** — 直接将 `research-html-formatter` 指向缓存的 `.md` 文件。研究成本只付一次，改变视觉样式不需要重新搜索。

**缓存行为** — 7 天内再次提问相似问题时，skill 会询问是否复用缓存研究，直接跳到 HTML 渲染步骤。

---

## 流水线

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
       dialectic    →  推理审计（特异性、幸存者偏差、推断链、一致性）
       depth        →  深度缺口 + 新研究方向
       width        →  搜索日志审计（未覆盖的搜索轨道）
        ↓
  重复直至 VERDICT: PASS 或达到最大轮次
        ↓
[第 1.5 步] 经验证的 Markdown 写入 ~/.claude/cache/research-loop/
        ↓
[第 2 步] research-html-formatter → 调用 frontend-design skill → HTML 写入磁盘
        ↓
[第 2.5 步] 设计强制门（拒绝通用输出）
```

### 两个核心原则

1. **对抗验证，而非自我审查。** Worker 从不评判自己的工作。4 个 Critic 各自负责一个独立审计维度，没有任何单一 agent 试图包揽一切。

2. **机械门控，而非提示嘱咐。** LLM 在被"友善地要求"时，会可靠地跳过结构性要求。每一个关键不变量都有编排层级的门控，失败时强制重做。[CHANGELOG](CHANGELOG.md) 记录了 20+ 个补丁，全部遵循同一模式：*提示失败 → 添加门控*。

### Critic 分工

| Agent | 模型 | 职责 |
|-------|------|------|
| `research-worker` | Sonnet | 起草、搜索、自审、反驳 Critic 意见 |
| `research-critic-instruction` | Opus | 覆盖矩阵、URL 验证（WebFetch + Playwright）、Worker 反驳裁定。**发出 VERDICT。** |
| `research-critic-dialectic` | Opus | 推理审计：特异性、幸存者偏差、推断链、内部一致性 |
| `research-critic-depth` | Opus | 深度缺口分析，每轮生成新的研究方向 |
| `research-critic-width` | Opus | 搜索日志审计——标记 Worker 计划了但未执行的搜索轨道 |
| `research-html-formatter` | Opus | 将经验证的 Markdown 渲染为设计驱动的 HTML |

如需更改某个 agent 使用的模型，编辑其 frontmatter 中的 `model:` 字段（`agents/*.md`），重启 Claude Code 生效：

```yaml
---
name: research-worker
model: sonnet   # 可选：opus / haiku / sonnet
---
```

Worker 默认使用 **Sonnet**（URL 抓取纪律更好，成本约为 Opus 的一半）。Critic 默认使用 **Opus**（对抗推理更深入）。将 Critic 切换为 Sonnet 可降低成本，但可能削弱覆盖矩阵深度和推理审计质量。

---

## 结构性强制项

- **自我覆盖计划优先** — Worker 在执行任何搜索前必须确定 5–8 个可验证子问题；跳过此步骤的输出会被门控拒绝
- **来源 URL 门控** — 标注为 `[FACT]` 的证据表行必须有可访问的 `https://` URL；裸域名、搜索重定向、SERP URL 一律拒绝
- **反驳立场** — Worker 必须对每条批评意见明确表态（接受 / 挑战 / 部分接受）；被动接受被拒绝
- **研究方向参与** — Worker 每轮必须响应 ≥ 2 个研究方向
- **设计强制** — HTML 格式化器必须声明具体美学方向；通用 `system-ui` 输出被拒绝

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

- 无法访问专有、付费墙或内部知识库
- 仅获取已发布内容，不是实时数据流
- 网络搜索在结构上偏向英文；非英文研究主题对当地文献的覆盖可能较浅
- 4 轨道搜索策略在实际执行中系统性地少执行第 3–4 轨道；这是结构性偏斜，无法通过提示修复
- 每次 `/research-report` 调用都是独立的，不会在先前会话的基础上构建
- 第 1 轮自我覆盖计划重做几乎必然发生，这是已知的结构性限制

---

## 依赖

- [Claude Code](https://claude.com/claude-code)
- [`frontend-design` 插件](https://github.com/anthropics/claude-plugins-official)
- 网络访问（用于 Web 搜索）

---

## 文件结构

```
cc-research-report/
├── assets/
│   └── banner.png
├── skills/
│   ├── research-report/
│   │   └── SKILL.md              # 流水线编排器（第 0→1→2 步）
│   └── research-loop/
│       └── SKILL.md              # worker↔critic 循环及所有机械门控
├── agents/
│   ├── research-worker.md
│   ├── research-critic-instruction.md
│   ├── research-critic-dialectic.md
│   ├── research-critic-depth.md
│   ├── research-critic-width.md
│   └── research-html-formatter.md
├── CHANGELOG.md                  # 每个补丁及其设计决策理由
├── install-local.sh
├── uninstall-local.sh
└── README.md
```

---

## 许可证

[MIT](LICENSE)

---

[![Star History Chart](https://api.star-history.com/svg?repos=npxcnency-ux/CC-Reseach-Report&type=Date)](https://star-history.com/#npxcnency-ux/CC-Reseach-Report&Date)
