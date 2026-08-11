# ANA v0.1 最小核心测试向量

本目录中的向量是 `ana-core-chain` v0.1 最小互操作 profile 的规范性示例。它们不测试模型质量、加密、Codon 压缩或工具执行；它们只测试：

1. 独立节点能从同一 Envelope 得到相同 canonical JSON；
2. Node A 能将任务封装为 canonical ANA Chain frame；
3. Node B 能在不复用 Node A 编解码代码的前提下解析该 frame；
4. Node B 能由任务产生规定的 `project_state.upsert` State Delta；
5. Node A 能解析该 State Delta，并验证其因果与序列关系。

## 使用规则

- `ana-v0.1-minimal.json` 的 `expected_*_payload` 是内层 `payload` 的精确 canonical JSON 文本。
- `frame` 是发送时附加到 payload 的固定头部。实现必须按 RFC-0002 §7.1 构造外层 frame。
- 外层 frame 同样必须使用 RFC-0003 §6 的 canonical JSON 规则并编码为 UTF-8。
- `expected_state_delta` 是 Node B 对给定任务产生的确定性最小状态增量；它不代表 Provider 已执行任务或已修改项目文件。
- 修改任一向量、版本或语义必须先修改相应 RFC，并建立新的向量 ID。

## 通过条件

两个节点的实现必须相互独立：它们不得调用对方的编码、解码或验证函数。通过条件是 Node A 产生的 wire bytes 能被 Node B 解析，Node B 产生的 wire bytes 能被 Node A 解析，且两端产生的 payload 均与本向量完全相等。

## Phase 7 独立实现扩展向量

- `ana-v0.1-negative.json` 固定记录未知版本、错误 Envelope、错误 sequence、断裂因果、未知必需语义及无效 State Delta 的拒绝输入。它使用最小正向向量作为确定性基底；测试工具只做文件中声明的 patch，不向实现提供期望输出。
- `ana-v0.1-memory-state.json` 检验 RFC-0004 MemoryRecord、Project State 与 Safety-related policy 在 Provider-neutral 结构中的导入/保留。
- `ana-v0.1-canonical.json` 包含 Unicode code point 键排序向量，避免实现误把运行时字符串的内部排序规则当作 canonical 规则。

这些向量不定义新的协议字段或架构能力。
