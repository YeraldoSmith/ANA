# RFC-0002：ANA Chain Layer

- 状态：v0.1 最小核心已冻结（Draft）
- 版本：0.1
- 更新日期：2026-08-11
- 依赖：[RFC-0001](RFC-0001-Architecture.md)、[RFC-0003](RFC-0003-Envelope.md)

## 摘要

ANA Chain Layer 是 ANA 节点之间的信息表达、语义映射和状态同步层。它定义如何将 canonical 任务/状态事件按一个固定、版本化、可验证的处理链组织为流，并在接收方恢复相同的 canonical 表示。

ANA Chain 不提供加密、身份认证或传输安全。这些由 TLS、HTTPS、WebSocket 的安全配置和部署环境的身份认证承担。

## 1. 作用与范围

ANA Envelope 解决“任务如何描述”；ANA Chain 解决“任务、记忆增量和 Agent 状态如何在节点间表达、传递与同步”。它的职责为：

1. **Stream transformation**：规范化、分帧和按固定规则变换数据流；
2. **Semantic Codon mapping**：用版本化词典表达重复出现的结构化概念；
3. **State Synchronization**：传递任务、记忆和协作状态的增量事件；
4. **Reversible transformation**：对于声明为可逆的 Chain，恢复同一 canonical 输入。

ANA Chain 不要求自然语言必须被编码为 Codon，也不声称所有任务都会因此节省 Token 或提高模型智能。

## 2. Canonical stream

在进入 Chain 前，发送方必须将输入转换为 canonical representation：

- 使用协议所定义的 schema；
- 使用 UTF-8；
- 对对象键采用确定性排序；
- 保留协议版本、Chain 标识和词典版本；
- 不隐式依赖本地语言、对象地址或未声明的 Provider 行为。

v0.1 的 canonical payload 使用 JSON 文本：UTF-8、对象键按 Unicode 代码点升序排列、数组顺序保持原样、无多余空白。在 Python 中，符合该规则的参考写法是 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`。接收方在解链后必须能解析为相同的 JSON 值。

**Phase 7 clarification：**canonical JSON 对象不得包含重复成员名；字符串必须由有效 Unicode scalar value 序列组成。接收方必须在 canonical 比较前拒绝不满足任一条件的 JSON，而不得按本地 parser 的“最后一个重复键获胜”等行为继续处理。

## 3. 固定 Chain

一个 Chain 由 `chain_id`、`chain_version` 和按顺序执行的 Chain Instruction Set（CIS）构成。

```json
{
  "chain_id": "ana-core-chain",
  "chain_version": "0.1",
  "instructions": ["CANONICALIZE", "MAP_CODONS", "FRAME", "TRANSFORM", "EMIT"]
}
```

“固定”具有以下规范含义：

- 发送方不得由模型输出临时定义新的操作或改变操作顺序；
- 指令语义由对应 `chain_id` 和版本唯一确定；
- 同一输入、同一 Chain 与同一词典必须得到相同的输出；
- 接收方若不支持该 Chain，必须请求或使用 canonical fallback，或明确拒绝；
- 发送方不得假设未声明支持的接收方能理解私有变换。

## 4. Chain Instruction Set（CIS）

v0.1 定义以下概念性指令。它们定义处理顺序，不强制某个编程语言实现。

| 指令 | 输入 | 输出 | 要求 |
| --- | --- | --- | --- |
| `CANONICALIZE` | 协议对象 | canonical JSON | 必须；按第 2 节规则处理 |
| `MAP_CODONS` | canonical JSON | 词典标识后的结构化表示 | 可选；必须记录词典 ID/版本 |
| `FRAME` | 表示流 | 有边界的帧序列 | 必须；每帧必须可识别所属 stream |
| `TRANSFORM` | 帧 payload | 变换后的 payload | 可选；操作必须由 Chain 固定定义 |
| `EMIT` | 帧 | Transport 可发送数据 | 必须；包含版本元数据 |

接收方向相反执行 `PARSE`、`INVERSE_TRANSFORM`（若适用）、`UNMAP_CODONS`（若适用）和 canonical JSON 解析。

### 4.1 v0.1 参考变换

参考实现提供 `reverse`、`rotate_left` 与 `xor_a5` 三个字节变换，用以测试确定性和可逆性。它们不是安全算法，不是强制生产实现，也不代表 ANA 的最终优化方法。

任何新增的 `TRANSFORM` 必须定义输入输出、确定性、逆操作（如声明可逆）、版本范围和测试向量。

## 5. Codon

Codon 是一个短小、稳定、版本化且可查表的协议语义标识符。它用于重复、结构化、跨语言的概念，而不是取代自由文本或隐藏语义。

v0.1 的 Codon 词典应具有如下结构：

```json
{
  "dictionary_id": "ana-core",
  "dictionary_version": "0.1",
  "entries": [
    {"id": "C:001", "meaning": "capability.code_generation"},
    {"id": "A:010", "meaning": "action.write_file"},
    {"id": "M:020", "meaning": "memory.preference"}
  ]
}
```

Codon 规则：

- `id` 在该词典版本内必须唯一；
- `meaning` 必须指向可公开阅读的规范词条；
- 未知 Codon 必须保留为未知或使用 canonical 文本回退，不得由接收方猜测；
- Codon 只优化/规范结构化字段；用户原文、长文本和未知概念必须保留为 payload；
- 显示语言可本地化，但协议含义以词典条目为准。

## 6. State synchronization

状态同步通过有序事件帧完成，而不是每轮重传全部对话或完整 Agent 内部状态。v0.1 定义如下最小事件形状：

```json
{
  "event_id": "uuid",
  "stream_id": "task-or-device-stream-id",
  "parent_event_id": "optional-causal-parent",
  "sequence": 42,
  "kind": "memory.upsert",
  "payload": {"record_ref": "mem_xxx"},
  "chain_id": "ana-core-chain",
  "chain_version": "0.1"
}
```

- `event_id` 必须在其产生节点内唯一；
- `stream_id` 标识同一任务或同步流；
- `sequence` 必须在一个发送方的同一 stream 内单调递增；
- `parent_event_id` 可表达显式因果关系；
- `kind` 表达事件类别，例如任务进展、Memory 更新、策略决定或工具结果；
- `payload` 必须遵从 `kind` 对应 schema，且不得包含未经授权的秘密。

v0.1 定义事件封装和顺序语义，但不定义离线冲突合并、全局时钟、跨节点删除冲突或分布式共识。实现遇到无法安全排序或合并的事件时，必须保留冲突并交由 Local Runtime/用户处理，而不能静默覆盖。

## 7. 会话协商与版本控制

节点在首次传输前应交换能力声明：

```json
{
  "protocol_versions": ["0.1"],
  "supported_chains": [{"id": "ana-core-chain", "versions": ["0.1"]}],
  "dictionaries": [{"id": "ana-core", "versions": ["0.1"]}],
  "max_frame_bytes": 65536
}
```

协商规则：

1. 选择双方共同支持的最高协议、Chain 和词典版本；
2. 没有共同 Chain 或词典时，使用未映射、未变换的 canonical JSON event stream；
3. 没有共同协议版本时，终止会话并报告不兼容；
4. 每一帧必须标注实际选用的 `chain_id` 和 `chain_version`；
5. 接收方不得根据仅名称相同的私有 Chain 假定兼容。

### 7.1 `ana-core-chain` v0.1 最小互操作 profile

Phase 1 冻结以下最小 profile。它用于验证两个独立节点，不要求实现 Codon 或字节变换。

```json
{
  "protocol_version": "0.1",
  "chain_id": "ana-core-chain",
  "chain_version": "0.1",
  "dictionary_id": null,
  "dictionary_version": null,
  "message_id": "unique-message-id",
  "stream_id": "task-or-device-stream-id",
  "sequence": 0,
  "payload_type": "envelope",
  "payload": "canonical JSON text",
  "transforms": []
}
```

该 profile 的规则如下：

1. Transport 数据是上述 frame 的 canonical JSON 的 UTF-8 字节；
2. `payload` 必须是 RFC-0003 Envelope 或本 RFC State Delta 对象的 canonical JSON 文本，而不是嵌套 JSON 对象；
3. `dictionary_id`、`dictionary_version` 必须为 `null`，`transforms` 必须为空数组；这表示不使用 Codon 和字节变换；
4. `payload_type` 必须为 `envelope` 或 `state_delta`；
5. `message_id` 在发送节点内必须唯一；`sequence` 必须是非负 JSON 整数，且在同一 `stream_id` 的同一发送方内必须单调递增；
6. 接收方必须先验证 frame 元数据，再解析 `payload`；任一步失败都必须拒绝该 frame；
7. 不支持此 profile 的节点必须明确报告不兼容，不得猜测转换方式。
8. 本 profile 的必需 frame 字段和允许值只由本节定义；v0.1 没有“未知 extension 也要求接收方执行”的通用机制。接收方可保留或忽略未知 frame 成员，但必须拒绝未知的必需字段值（例如未知 `payload_type`、协议版本或 Chain 版本）。

该 profile 是 ANA Chain 的 canonical fallback，也是 v0.1 的最低互操作要求。Codon 和 `TRANSFORM` 仍是已定义的 Chain 机制，但不属于本 profile 的必需实现。

## 8. 可逆变换原则

若 Chain 或其中指令宣称“可逆”，则同一版本的接收方必须能从该输出恢复同一 canonical 输入。可逆性适用于表示变换，不适用于有意抽象。

特别地，Summary Memory、Semantic Memory 和 User Preference 的派生结论可能丢失原始细节；它们必须记录来源和抽象关系，不能被标为可逆 Chain 的产物。

### 8.1 v0.1 State Delta

Phase 1 采用 `payload_type: "state_delta"` 表达状态增量。其 canonical payload 必须包含：

```json
{
  "event_id": "unique-event-id",
  "stream_id": "task-or-device-stream-id",
  "parent_event_id": "causal-message-id-or-event-id",
  "sequence": 1,
  "kind": "project_state.upsert",
  "payload": {
    "task_id": "task-id",
    "status": "routed",
    "required_capabilities": ["code_generation"]
  }
}
```

`project_state.upsert` 表示“对一个项目/任务状态的新增或更新建议”。在最小 profile 中，`payload.task_id` 必须等于 `stream_id`，`parent_event_id` 必须指向导致该状态变化的前序 `message_id` 或 `event_id`，且 `sequence` 必须大于该前序帧的序列号。State Delta payload 的 `sequence` 必须等于承载它的 frame `sequence`。该事件不授权任何工具动作，也不自动写入 Memory；其是否落盘仍由 Local Runtime 的策略决定。

## 9. 安全说明

ANA Chain 不加密数据。需要保密、完整性、节点认证或防重放时，部署必须使用 TLS、认证会话、签名或其他经过审查的安全机制。Codon、变换、短 ID 或字节异或均不是安全控制。

## 10. 互操作测试要求

一个 Chain 实现至少应测试：

- 相同 canonical 输入在独立实现间的相同编码结果；
- 可逆 Chain 的往返恢复；
- 未知 Chain/词典的 canonical fallback；
- 未知 Codon 不被错误解释；
- 同一 stream 的事件序列保持顺序；
- 无法安全处理的冲突被显式报告。

固定输入和期望输出位于 [`test-vectors/ana-v0.1-minimal.json`](test-vectors/ana-v0.1-minimal.json)，执行规则位于 [`test-vectors/README.md`](test-vectors/README.md)。
