# ANA Chain Layer（核心协议草案）

> 状态：核心设计方向；v0.1 仅实现了其中的可逆流变换参考 codec。
> 本文不将尚未验证的语义压缩效果表述为既有能力。

## 1. 为什么 ANA Chain 是 ANA 的核心

`ANAEnvelope` 规定的是“一个任务如何描述”；它本身不足以构成 AI-to-AI 通信协议。若 ANA 只停留在 Envelope、Adapter 与 Runtime，它更接近一个 Agent Framework 的统一接口。

**ANA Chain Layer** 定义的是在多个 Agent、设备与模型之间，怎样把任务、语义状态与记忆增量组织成可传输、可同步、可还原、可演进的流。它把 ANA 从“调用模型的框架”推进为“AI 节点之间的通信与状态协作标准”。

ANA Chain 的灵感来自神经信号与 DNA：信息不必总以完整自然语言反复传递，也可以以有结构、可组合、版本明确的最小单元在网络中流动。这个类比是设计灵感，不是关于生物学或智能机制的科学主张。

## 2. ANA 协议栈

```text
┌──────────────────────────────────────────────────────────────┐
│ Application Layer: 用户任务、工具结果、模型 Adapter           │
├──────────────────────────────────────────────────────────────┤
│ ANAEnvelope Layer: intent、capabilities、context、policy      │
├──────────────────────────────────────────────────────────────┤
│ ANA Chain Layer: 流变换、语义 codon、状态同步、可逆恢复       │
├──────────────────────────────────────────────────────────────┤
│ Transport Layer: HTTPS / WebSocket / local IPC / future P2P   │
└──────────────────────────────────────────────────────────────┘
```

底层传输由既有成熟技术承担。ANA Chain 不重新发明网络，也不替代端到端加密；它定义 Agent 侧的信息表示与同步语义。

## 3. 固定 ANA Chain 的概念

一条 ANA Chain 是一个版本化的、有顺序的处理链。发送端和接收端根据同一 `chain_id`、版本和描述符，对一个流作相同解释。

```text
Canonical ANA event stream
  → canonicalize（字段顺序、字符集、schema version）
  → transform（固定、可逆的流操作序列）
  → semantic codon mapping（可选的版本化映射）
  → state delta framing（同步边界、因果信息、完整性信息）
  → transport
```

### “固定”意味着什么

- Chain 的操作集、顺序和版本由协议定义或通过受控协商确定，不能由任意模型在每个请求中临时发明。
- 每个消息都携带或可解析到明确的 `chain_id`、`chain_version` 和字典版本。
- 任何接收方不能识别的 Chain 或字典，必须回退到规范定义的 canonical 表示，或显式拒绝；绝不能猜测语义。
- Chain 变换必须是确定性的；若声明可逆，则编码后必须可以无损恢复其 canonical 输入。

这避免“混合排序/变换”退化为不可调试的黑箱，同时保留以固定组合优化传输或状态表达的空间。

## 4. Chain Layer 的四项职责

### 4.1 Stream transformation（流变换）

将 canonical 数据流按固定规则分帧、排序、分块或执行字节级变换，使收发双方以相同方式读取它。v0.1 参考 codec 仅用于验证可逆性：UTF-8 字节可经 `reverse`、`rotate_left`、`xor_a5` 等操作后还原。

它不等于加密或压缩：

- **保密性**应由经过审查的加密层提供；简单可逆变换不能保护数据。
- **传输效率**必须以字节数、Token 数、延迟和成功率实验衡量，不能由“变换”一词自动获得。

### 4.2 Semantic codon mapping（语义 codon 映射）

Codon 是一个短小、版本化、可查表的语义标识符。例如某个标准词表可将 `code_generation`、`write_file`、`preference.security_priority` 映射到稳定 ID。它的目的不是让模型“神秘地理解编码”，而是减少重复描述、消除歧义、让结构化状态可由机器稳定处理。

一个可行的初始形式：

```json
{
  "dictionary_id": "ana-core",
  "dictionary_version": "0.1",
  "codons": [
    {"id": "C:001", "meaning": "capability.code_generation"},
    {"id": "A:010", "meaning": "action.write_file"},
    {"id": "M:020", "meaning": "memory.preference"}
  ]
}
```

在正式互操作前，`meaning` 应以规范词表为准；不同语言的显示文本只是展示层。自由文本、未知概念和长内容仍使用 canonical payload，不能被强行压缩成不透明 codon。

### 4.3 State synchronization（状态同步）

ANA Chain 不只传递一次性 prompt，也应传递可增量同步的 Agent 状态：任务进展、可移植记忆变化、策略决定、工具结果和委派关系。

每个状态帧应至少可表达：

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

未来版本需要定义：快照、增量、重复消息去重、离线重连、冲突解决、删除传播和事件完整性。v0.1 暂不声称已解决多设备冲突。

### 4.4 Reversible transformation（可逆恢复）

当 Chain 声明为可逆时，接收方应能按公开的元数据将传输数据恢复成相同的 canonical 表示。这使调试、审计、跨实现测试和 Provider 切换成为可能。

可逆性必须针对明确的输入和版本测试，而不意味着“所有语义变换都无损”：摘要与用户模型等有意抽象的层，必须带有来源和抽象级别，不能伪称可逆。

## 5. 消息和协商的最小建议

在每个传输会话开始时，节点交换：

```json
{
  "protocol_versions": ["0.1"],
  "supported_chains": [{"id": "ana-core-chain", "versions": ["0.1"]}],
  "dictionaries": [{"id": "ana-core", "versions": ["0.1"]}],
  "max_frame_bytes": 65536
}
```

双方选择最高共同版本；没有共同 Chain 或字典时，退回 canonical JSON event stream。协商内容本身也必须受认证、传输加密和本地策略保护。

## 6. 验证路线与成功标准

ANA Chain 不应以美学或类比取胜，而应在以下指标中展示价值：

| 假设 | 验证方式 |
| --- | --- |
| 可逆流变换可互操作 | 两个独立实现对相同测试向量得到相同编码并能恢复 canonical 输入 |
| Codon 可减少结构化重复 | 在固定任务集对比 canonical JSON 的字节数/Token 数和解析正确率 |
| 状态增量优于重复上下文 | 比较长任务多轮协作中的传输量、恢复时间与遗漏率 |
| 语义仍可审计 | 任意 codon 和状态帧都可展开为版本确定的人类可读含义 |

若某项机制没有相对 canonical 表示的可测量收益，应保持为可选实验，或从核心协议中移除。
