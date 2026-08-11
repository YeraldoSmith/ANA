# Phase 5：Ablation & Fair Baseline Validation

> 状态：完成。未新增 ANA v0.1 协议字段、Codon、压缩格式或 Memory 功能。
> 有效原始结果：[phase5-ablation-run-002.json](../benchmarks/results/phase5-ablation-run-002.json)
> 固定向量：[phase5_parameters.json](../benchmarks/phase5_parameters.json) 与 [phase5_fidelity_cases.json](../benchmarks/phase5_fidelity_cases.json)

## 1. 结论

在本组受控测试中，**ANA 相对同样聪明的普通 JSON 实现没有额外的输入效率优势**。相同选择、去重后的 Smart Baseline 在全部 7 个轮次都比 ANA 小 **124–126 UTF-8 B**、**32 个 `cl100k_base` token 估算**，本地 encode/decode 微基准也低约 **0.7–1.5 µs**。

ANA 相对 Naive Baseline 在长期 continuation 中仍然显著更小，但这项收益已经被 Smart Baseline 以同样的方式获得。因此，当前证据将主要收益归因于 **Memory/State selection 与 context deduplication**，不能归因于 ANA Envelope 或 canonical JSON 表示。

这不否定 ANA 的协议价值：它仍提供可验证的状态、因果关系、标识符和 Provider-independent 表达。然而当前 v0.1 Envelope 的实验定位是**互操作和状态表达**，不是压缩。

## 2. 公平性设计

三组都完成同一个 continuation task，并检验相同的 7 个必要事实：`ANA`、`local_runtime`、`security_first`、`english`、`phase_5`、`continued` 与当前轮次。

| 组别 | 输入内容 |
| --- | --- |
| A — Naive Baseline | 每一轮重传截至当前轮的必要历史。 |
| B — Smart Baseline | 使用与 ANA 完全相同的 selected Memory、Project State 和 State Delta；以简单普通 JSON `message` + `context` 表示。 |
| C — ANA | 使用与 B **同一对象值**的 `context`；只额外使用既有 ANA v0.1 canonical Envelope 字段。 |

B 与 C 的 `context` 通过深度相等测试；它们没有不同的事实筛选权。`task_id`、版本、引用和 policy 等仅被视为协议表示成本，而非给 ANA 的额外语义信息。结果中每一组必要事实保留率均为 **7/7**。

测量为 canonical JSON 的 UTF-8 bytes、`cl100k_base` 本地 token estimate，以及在同一进程中 1,000 次 JSON canonicalize + parse 的平均微秒数。它们不代表 Provider 计费 token、网络延迟或模型正确率。

## 3. Continuation 对比

`B`/`T`/`µs` 分别表示 UTF-8 bytes、token estimate、encode/decode mean microseconds。三组在每个轮次都保留 7/7 必要事实。

| 轮次 | Naive B / T / µs | Smart B / T / µs | ANA B / T / µs |
| ---: | --- | --- | --- |
| 1 | 248 / 60 / 2.409 | 589 / 131 / 7.091 | 713 / 163 / 8.633 |
| 2 | 421 / 103 / 2.941 | 585 / 132 / 7.104 | 709 / 164 / 8.390 |
| 5 | 940 / 232 / 4.637 | 585 / 132 / 7.145 | 709 / 164 / 8.170 |
| 10 | 1,807 / 447 / 7.381 | 589 / 132 / 7.204 | 714 / 164 / 8.110 |
| 25 | 4,432 / 1,092 / 15.061 | 590 / 132 / 7.245 | 715 / 164 / 8.161 |
| 50 | 8,807 / 2,167 / 27.648 | 590 / 132 / 7.202 | 715 / 164 / 7.922 |
| 100 | 17,559 / 4,317 / 51.566 | 594 / 132 / 7.078 | 720 / 164 / 7.910 |

短任务（1–2 轮）应使用 Naive 表示：它还没有足够重复可消除。第 5 轮起，二者都有选择能力的方案都反超 Naive；但 Smart 始终比 ANA 小。

在第 100 轮：

- A → B：减少 **16,965 B（96.6%）** 与 **4,185 token estimate（96.9%）**；
- A → C：减少 **16,839 B（95.9%）** 与 **4,153 token estimate（96.2%）**；
- B → C：ANA 增加 **126 B** 与 **32 token estimate**。

所以在本实验中，A → B 的减少可归因于选择/去重；B → C 是 ANA protocol representation 的净成本，而不是额外节省。

## 4. Envelope 消融

以下是从完整 ANA Envelope 删除既有字段组后减少的 bytes。字段组可能共享 JSON 结构，因此是**边际值，不能相加**。`state_fields` 仅指 `project_state`；`causality` 为 State Delta 内的 `event_id`、`parent_event_id` 和 `sequence`。

| 字段组 | 第 1 轮边际 B | 第 100 轮边际 B | 含义 |
| --- | ---: | ---: | --- |
| 完整 Envelope | 713 | 720 | 总 canonical packet |
| `version` | 16 | 16 | 版本协商成本 |
| metadata（`intent`、`capabilities`、`policy`） | 99 | 99 | 语义路由与安全声明 |
| identifiers（`task_id`、`memory_refs`） | 95 | 97 | 关联和 Memory 引用 |
| state fields（`project_state`） | 60 | 62 | 当前项目状态 |
| causality information | 62 | 63 | Delta 顺序和父事件关联 |

与 Smart Baseline 的完整比较更直接地给出当前 Envelope 的固定表示成本：**124–126 B / 32 token estimate**。该差异包含 ANA 的顶层命名、版本、标识符与 policy 等，同时 B 已有同等任务和 context 内容。它随轮次只因数字/ID 位数而轻微变化。

## 5. Memory fidelity

这些不是模型问答质量测试，而是对 selection 结果的可审计保真测试：当前有效事实必须在选中 Memory 中，过时或冲突事实不得存在。

| 测试向量 | 当前事实 | 被排除的旧/冲突事实 | 结果 |
| --- | --- | --- | --- |
| 很久以前的重要事实 | `local_runtime` | 临时讨论 | 1/1 保留，1/1 排除 |
| 用户偏好变化 | `detailed` | `concise` | 1/1 保留，1/1 排除 |
| Project State 更新 | `phase_5` | `phase_3` | 1/1 保留，1/1 排除 |
| 相互冲突的事实 | `python` | `java` | 1/1 保留，1/1 排除 |
| 时间相关状态 | `2026-08-20` | `2026-08-10` | 1/1 保留，1/1 排除 |

这证明固定选择向量没有把被标记为过时的值混入 payload；它**不**证明真实生产 Memory 系统一定能正确解决所有冲突、摘要或召回问题。

## 6. 实验完整性与限制

- Phase 3 与 Phase 4 的向量和原始结果均未改写。
- 本阶段首次运行的原始文件仍保留为 `phase5-ablation-run-001.json`。它暴露了时间测试向量中“当前记录 timestamp 与旧 deadline 字面值相同”的自冲突，因而不能作为有效保真结果。修正向量的 timestamp 后重新运行，`run-002` 是本报告引用的有效结果；没有删除失败结果。
- JSON 微基准很小且受机器噪声影响；它只说明本地序列化/解析量级，不代表真实端到端延迟。
- token 使用 `cl100k_base` 的本地估算，其他 Provider 的 tokenizer 可能不同。
- 所有 continuation 内容为固定、合成向量；还未覆盖真实模型的答案质量或用户任务成功率。

## 7. 最终回答

### ANA 相对于“同样聪明的普通实现”还有多少额外效率优势？

本实验中没有。Smart Baseline 在全部测量点更小：ANA 额外增加 124–126 B 和 32 token estimate。

### 当前节省中有多少来自 Memory selection，有多少来自 ANA protocol？

在第 100 轮，selection/dedup（A → B）解释了 16,965 B 的减少；ANA 表示（B → C）增加了 126 B。该实验没有观测到可归因于 protocol representation 的输入节省。

### ANA Envelope 的固定成本是多少？

在此具体任务和普通 JSON 对照下，完整 ANA canonical representation 的净成本为 124–126 B / 32 token estimate。按字段的边际成本见第 4 节，且不可相加。

### ANA 最适合解决压缩问题，还是状态/互操作问题？

当前证据支持后者。它适合将 Local Runtime 选择出的 Memory、State 与 Delta 用可验证、Provider-independent 的形式表达；压缩收益来自不再重传历史，而不是 Envelope 本身。

### 是否存在开发 compact ANA Chain 的实验依据？

没有。本实验进一步表明，在 selection 相同的条件下，普通 JSON 比当前 ANA packet 更小。若未来研究 compact profile，应先提出独立假设，并在完全相同的事实、选择策略和任务下与 Smart Baseline 比较；在那之前不应开发 Codon 或声称其会节省 token、成本或延迟。
