# Phase 7：Specification Ambiguities

Phase 7 的 Java 节点只依据 RFC、Schema 与固定向量实现。重实现过程发现以下 6 项规范边界；其中 3 项已作 **clarification**，没有新增 ANA 架构能力或字段。

| # | 规范位置 | 两种合理解释 | 当前选择 | 是否修改 RFC |
| ---: | --- | --- | --- | --- |
| 1 | RFC-0002 §8.1 State Delta sequence | frame 与 inner delta 各自独立递增；或两者描述同一事件，必须相等 | 最小 profile 将两者视为同一事件，必须相等 | 是，已澄清并加负向向量 |
| 2 | RFC-0002 §7.1 / RFC-0003 §6.1 未知“必需”语义 | 未知字段一律忽略；或未知字段可能隐含强制语义 | v0.1 无通用 mandatory-extension 标记。未知成员仅可选；未知的已定义必需字段值必须拒绝 | 是，已澄清 |
| 3 | RFC-0002 §2 canonical JSON parser 边界 | 重复 JSON key 采用本地 parser 行为；或拒绝；Unicode surrogate 可由运行时自行解释 | 拒绝重复成员名及无效 Unicode scalar 序列，避免实现相关语义 | 是，已澄清 |
| 4 | RFC-0002 §2 JSON 数值 canonicalization | 跟随某语言 serializer；或为所有 JSON number 定义独立跨语言格式 | 当前固定 Core 向量只使用非负整数 sequence；Java 节点对 sequence 严格验证整数。泛用小数/指数 canonical 还没有跨语言规范 | 否；需要后续、独立的 clarification |
| 5 | RFC-0004 MemoryRecord | `kind.content`、`created_at` 的每种具体 schema/时间格式可由实现任意定义；或应在 RFC 统一定义 | Core 仅验证最小结构并按 Provider-neutral JSON 原样保留。语义检索、冲突合并和严格时间解析不属于 Core | 否；不阻塞最小 profile，但需要 Memory profile 扩展 |
| 6 | RFC-0002 / RFC-0003 error reporting | 跨语言必须返回相同 machine-readable code；或只要求显式拒绝 | 当前 suite 要求两端对同一坏输入拒绝；Java 暴露分类，Python 旧节点暴露异常类型，尚无统一 Chain error-code taxonomy | 否；建议后续 clarification |

## 已采取的澄清

RFC-0002 已补充：

- canonical JSON 不接受重复成员名或无效 Unicode scalar；
- `sequence` 是非负 JSON 整数；
- `project_state.upsert` payload sequence 必须等于承载 frame sequence；
- v0.1 没有隐式 mandatory-extension 机制，未知必需字段值必须拒绝。

RFC-0003 已补充：未知 Envelope 成员不能在 v0.1 中私自成为必需语义；要引入必需成员必须创建新 version 或 profile。

## 结论

这些歧义没有阻止独立节点实现或双向互通，但它们界定了 `ANA v0.1 Core Conformant (minimal profile)` 的准确范围。特别是，任何宣称覆盖泛用 JSON 数值、完整 Memory 语义或统一错误代码的实现，都需要额外 RFC/向量，而不能从当前 v0.1 Core 推断出来。
