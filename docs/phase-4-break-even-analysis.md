# Phase 4：Break-even & Failure Analysis

> 状态：完成。仅分析现有 ANA v0.1 Core 的输入表示；未新增协议字段、Codon、复杂 Chain、多 Agent、跨设备同步或 Memory 功能。
> 原始结果：[phase4-break-even-run-003.json](../benchmarks/results/phase4-break-even-run-003.json)

## 1. 方法与边界

本分析直接读取 Phase 3 的 12 个固定向量，没有修改它们。每个 packet 使用相同的 task 和必要事实；baseline 使用相关自然语言历史，ANA 使用现有的 `memory`、`project_state` 和 `state_deltas` JSON 结构。

分解方法：

- **固定开销**：空 packet 的 canonical JSON 字节数。baseline wrapper 为 24 B，ANA packet wrapper 为 60 B。
- **task / memory / preference / project state / state delta**：相应用户或领域值的 UTF-8 字节数，不含 JSON 键与语法。
- **重复上下文**：baseline 历史文本的原始值字节数。
- **metadata**：总 packet 减去固定开销和上述逻辑值；包括 JSON 键、数组/对象标记、引号、逗号、`kind`/`content` 等结构标签。

这里的“固定开销”是 Phase 3 benchmark packet 的表示成本，不包含 Transport、TLS 或 ANA Chain wire frame。

## 2. 现有 12 个案例逐项分解

表中 `B` 为 baseline，`A` 为 ANA；所有数值均为 UTF-8 字节。

| 案例 | B 总计 | B 固定/任务/重复/元数据 | A 总计 | A 固定/任务/Memory/Preference/Project State/Delta/元数据 |
| --- | ---: | --- | ---: | --- |
| simple-001 | 130 | 24 / 33 / 68 / 5 | 148 | 60 / 33 / 12 / 0 / 0 / 0 / 43 |
| simple-002 | 120 | 24 / 30 / 61 / 5 | 143 | 60 / 30 / 0 / 8 / 0 / 0 / 45 |
| code-001 | 232 | 24 / 54 / 143 / 11 | 253 | 60 / 54 / 14 / 4 / 10 / 0 / 111 |
| code-002 | 218 | 24 / 45 / 138 / 11 | 264 | 60 / 45 / 24 / 6 / 9 / 0 / 120 |
| continuation-001 | 499 | 24 / 59 / 387 / 29 | 437 | 60 / 59 / 59 / 0 / 39 / 0 / 220 |
| continuation-002 | 423 | 24 / 63 / 307 / 29 | 449 | 60 / 63 / 39 / 0 / 68 / 0 / 219 |
| preference-001 | 212 | 24 / 39 / 138 / 11 | 217 | 60 / 39 / 0 / 29 / 0 / 0 / 89 |
| preference-002 | 202 | 24 / 38 / 129 / 11 | 208 | 60 / 38 / 0 / 21 / 0 / 0 / 89 |
| project-001 | 191 | 24 / 29 / 124 / 14 | 221 | 60 / 29 / 3 / 0 / 33 / 0 / 96 |
| project-002 | 195 | 24 / 26 / 131 / 14 | 220 | 60 / 26 / 3 / 0 / 39 / 0 / 92 |
| delta-001 | 217 | 24 / 31 / 145 / 17 | 200 | 60 / 31 / 0 / 0 / 0 / 40 / 69 |
| delta-002 | 240 | 24 / 32 / 167 / 17 | 224 | 60 / 32 / 0 / 0 / 0 / 63 / 69 |

## 3. 为什么 ANA 在多数固定案例未占优

Phase 3 的 9/12 bytes 未占优、10/12 token 估算未占优并非异常，而是当前表示的直接结果：

1. **固定 wrapper 成本更高。** ANA 的空 packet 已比 baseline 多 36 B（60 B 对 24 B）。
2. **结构 metadata 很重。** `memory`、`kind`、`content`、`project_state` 和数组嵌套使 ANA metadata 在代码、continuation 和项目状态案例中达到 89–220 B；baseline 的相关 metadata 只有 5–29 B。
3. **短文本本身已很紧凑。** 简单任务、Preference 和 Project State 的 baseline 用短句表达同一事实，结构化 JSON 没有足够重复可以消除。
4. **结构化 State 不必然等于 token 更少。** 两个 State Delta 案例虽各减少 17 B 与 16 B，但仅 `delta-002` 的 `cl100k_base` 估算更少；`delta-001` 仍多 1 个 token。
5. **当前 ANA 未实现压缩。** v0.1 Core 使用的是可审计的 JSON 结构，不是紧凑二进制格式或 Codon。因此它的收益不能归因于“协议编码压缩”。

`continuation-001` 是唯一固定长上下文正例：baseline 的 387 B 重复历史超过 ANA 的 220 B metadata 加 98 B 的 Memory/State 值。`continuation-002` 虽然也较长，但 ANA 多携带了 68 B Project State，因此仍未反超。

## 4. 参数化规模实验

新参数集固定使用规模 `1, 5, 10, 25, 50, 100`，同时做 1–100 的逐整数搜索。所有测量点都验证两侧拥有相同必要事实；token 是 `cl100k_base` 本地估算，不是 Provider 计费 token。

| 维度 | 规模 1：bytes B/A | 规模 100：bytes B/A | bytes 首次反超 | token 首次反超（1–100） |
| --- | ---: | ---: | ---: | ---: |
| Conversation history | 174 / 241 | 7,792 / 243 | 2 | 2 |
| Project State 项 | 94 / 133 | 2,159 / 2,495 | 无 | 无 |
| User Preference 项 | 99 / 170 | 2,659 / 6,195 | 无 | 无 |
| Repeated context 次数 | 138 / 209 | 6,375 / 209 | 3 | 3 |
| Continuation turns | 208 / 341 | 13,559 / 345 | 3 | 2 |

“首次反超”只在这个生成器、这个 packet 格式、这个 token 估算器和 1–100 搜索范围内成立；它不是通用产品阈值。

### 长期 continuation 曲线

| 轮数 | Baseline / ANA bytes | Baseline / ANA token estimate |
| ---: | ---: | ---: |
| 1 | 208 / 341 | 46 / 74 |
| 5 | 740 / 341 | 162 / 74 |
| 10 | 1,407 / 343 | 307 / 74 |
| 25 | 3,432 / 343 | 742 / 74 |
| 50 | 6,807 / 343 | 1,467 / 74 |
| 100 | 13,559 / 345 | 2,917 / 74 |

逐整数检查显示：第 2 轮时 token 已从 75（baseline）对 74（ANA）开始更小；第 3 轮 bytes 从 474（baseline）对 341（ANA）开始严格更小。第 2 轮 bytes 相等（341 / 341），故不算 bytes break-even。

## 5. ANA 的价值来自什么

| 候选来源 | 当前证据判断 |
| --- | --- |
| Compact serialization | **未证实。** 当前 JSON 结构在多数短场景更大。 |
| 去除重复上下文 | **主要已证实来源。** history、repeated context 与长期 continuation 的反超都由 baseline 随重复线性增长、ANA 保持近似固定而产生。 |
| Structured Memory | **间接有价值。** 它让 Runtime 能选择稳定事实而非重传原始历史；但其 JSON 自身有显著 metadata 成本。 |
| State Delta | **有限证据。** 两个固定案例的 bytes 都较小，但 token 仅一例较小；需要更多真实事件流测试。 |
| Provider-independent representation | **不是大小优势。** Phase 3 的双 Adapter contract 已验证同一 Envelope/Memory 可进入不同 Provider，但这不减少字节。 |

## 6. 最终判断

### 哪些任务不应该使用 ANA？

- 无历史、一次性、极短的简单任务；
- 只有少量简单 Preference 或 Project State，且自然语言上下文已经简短；
- 需要发送完整原始细节而没有可复用、可验证的摘要/状态时。

在这些场景中，当前 ANA JSON wrapper 和 metadata 的成本大于它能避免的重复。

### 哪些任务最适合 ANA？

- 多轮 continuation，且每轮反复携带相同项目约束、偏好和安全边界；
- 多次重传同一稳定上下文的任务；
- 可由小量、可审计的 Project State 或 State Delta 取代较长历史说明的工作流。

### ANA 是否存在明确的 break-even point？

存在**条件化的** break-even，而不存在一个通用数字。当前生成器中：conversation history 为 2 个历史单元，repeated context 为 3 次，continuation 为 2 个 token 单元或 3 个 bytes 单元；单纯 Project State 和 Preference 扩展到 100 项仍没有反超。

### 优势来自协议编码还是避免重复上下文？

现有证据指向**避免重复上下文**，而不是协议编码。ANA 当前未压缩 JSON；反而在短输入中增加固定和 metadata 成本。Structured Memory/State 的作用是让重复内容可以不再发送，而不是让相同内容变得神奇地更短。

### 是否有足够证据继续研究 ANA Chain / Codon compact profile？

没有足够证据把它们作为下一步功能开发。Phase 4 没有发现“只要换一种编码就普遍节省 token”的证据；当前正例都由上下文去重解释。未来可以做一个独立、受控的研究假设测试：在**相同事实、相同任务、相同去重策略**下比较 canonical JSON 与候选 compact profile。此前不应实现或宣传 Codon。

## 7. 限制

- 参数模型是固定、合成的，不能代表所有真实对话；
- 模型正确率和真实 Provider latency 不在此分析中；
- `cl100k_base` 仅为本地估算；
- Memory 是否能始终安全、正确地替代原始历史仍需在真实任务上验证。
