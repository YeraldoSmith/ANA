# Phase 7：Independent Implementation & Conformance Validation

> 状态：完成。未增加 ANA 功能、Codon、compact encoding、多 Agent 或新的 Memory 能力。
> 独立实现：[AnaV01Node.java](../conformance/independent-java/AnaV01Node.java)
> 规范歧义记录：[phase-7-spec-ambiguities.md](phase-7-spec-ambiguities.md)

## 1. 结论

ANA v0.1 的 **minimal Core profile** 已证明不是一套只能由 Python 代码实现的约定：一个全新的 Java 节点仅根据 RFC-0001 至 RFC-0005、Schema 和固定 test vectors，重新实现了 canonical Envelope/frame、version 校验、State Delta、sequence/causality、Memory/Project State/Policy import 与拒绝行为，并与 Python 节点双向互通。

这项结论有严格边界：它证明最小 Core 的第三方实现基础，不证明 Codon、TRANSFORM、模型质量、工具执行或完整 Memory 冲突处理已经标准化。

## 2. 独立性边界

Java 节点：

- 只使用 Java 标准库；
- 不导入 `ana/` Python Runtime、`node_a.py`、`node_b.py` 或它们的 codec/reducer/Memory Store；
- 不读取 Python 节点产生的预先保存输出；
- 按 RFC 的 UTF-8、无空白、Unicode code point key 排序规则自行实现 JSON parser 与 canonical serializer；
- 从测试向量的输入构造/验证协议对象，而非硬编码某个 expected wire 输出。

开发时曾出现 Java key comparator 将 `payload_type` 排在 `payload` 前的真实 serializer defect；Python 的 canonical-frame 检查立即拒绝了它。修正 comparator 后双向测试通过。这是独立实现测试能发现实现错误、而不是只“回放已知答案”的直接证据。

## 3. 已实现的 v0.1 最小 Core

| 能力 | Java 独立节点行为 |
| --- | --- |
| Canonical Envelope parsing | 解析、canonical 比较、必需字段与类型验证、版本拒绝 |
| Frame parsing | 验证 `ana-core-chain` v0.1 canonical fallback、无 Codon/transform |
| State Delta | 处理 `project_state.upsert`，验证 stream、task、sequence 与 causal parent |
| Memory / Project State import | 验证 RFC-0004 最小 MemoryRecord 结构，保留 Provider-neutral Project State 与 policy JSON |
| Safety-related state preservation | 保留 `sandbox_first`、secret-disclosure 等 policy 状态；不把 Provider 文本转换为动作 |
| Provider independence | 实现中没有 Provider SDK、会话格式或厂商专属 Memory schema |

## 4. 双向互操作

### Python Reference Node → Java Independent Node → Python Reference Node

1. Python Node A 按固定向量产生 task Envelope wire；
2. Java 节点独立验证 canonical frame 与 Envelope；
3. Java 节点从该 task 产生确定性的 `project_state.upsert` State Delta；
4. Python Node A 验证 Java wire，得到与向量完全相同的 State Delta payload。

### Java Independent Node → Python Reference Node → Java Independent Node

1. Java 节点独立产生相同 task wire；
2. Python Node B 解析并产生确定性 State Delta；
3. Java 节点验证 Python wire，得到与向量完全相同的 canonical payload。

两条路径都精确匹配：

- `expected_envelope_payload`；
- `expected_state_delta_payload`；
- task stream、sequence 和 causal parent；
- `project_state.upsert` 的最小语义。

## 5. 负向 conformance 与错误行为

固定负向向量覆盖以下输入：

| 输入 | Python 节点 | Java 节点 |
| --- | --- | --- |
| Unknown protocol version | 拒绝 | 拒绝：`unsupported_profile` |
| Malformed Envelope (`input` 非 object) | 拒绝 | 拒绝：`invalid_envelope` |
| Invalid State Delta sequence | 拒绝 | 拒绝：`invalid_sequence` |
| Frame/inner State Delta sequence 不一致 | 拒绝 | 拒绝：`invalid_sequence` |
| Broken causality parent | 拒绝 | 拒绝：`broken_causality` |
| Unknown required payload semantics | 拒绝 | 拒绝：`unknown_required_semantics` |
| Invalid State Delta kind | 拒绝 | 拒绝：`invalid_state_delta` |

两端的拒绝结果一致。Java 的 error category 更细；Python 旧节点使用异常类型，尚未有共享的 Chain error-code 字符串规范，因此 suite 比较的是同一输入的“拒绝结果”和 Java 对向量声明的分类，而非虚假的逐字错误文本一致。

## 6. Conformance Suite

固定向量位于 [`docs/test-vectors/`](test-vectors/README.md)：

- 正向 Envelope / State Delta：`ana-v0.1-minimal.json`；
- 负向输入：`ana-v0.1-negative.json`；
- Memory/Project State/Policy import：`ana-v0.1-memory-state.json`；
- Unicode canonical key ordering：`ana-v0.1-canonical.json`。

运行：

```bash
python3 -m conformance.run_phase7_suite
```

具有独立实现的第三方节点通过全部该 suite 后，可以声明：

```text
ANA v0.1 Core Conformant (minimal profile)
```

该声明必须附带 minimal-profile 限定，且不得扩展为对未测试功能的声明。

## 7. 规范歧义与限制

共发现 6 项边界：3 项已作 clarification，3 项仍处于当前最小 Core 范围外。完整记录见 [Phase 7 spec ambiguities](phase-7-spec-ambiguities.md)。

特别限制：

- 现有向量足以验证 frozen minimal profile 的 canonical task/state handoff 与基本拒绝行为；
- 它们不足以验证所有 JSON 小数/指数 canonicalization、复杂 Memory content、冲突合并、Provider 模型质量和真实网络 transport；
- `message_id` 的发送方全局唯一性需要有状态会话测试，不能仅由单帧解析测试证明。

## 8. 最终回答

### 独立实现是否可以只凭规范完成？

可以完成 v0.1 **minimal Core**。Java 节点没有调用 Python ANA 源码，且双向互通通过。

### 有多少规范歧义？

发现 6 项：3 项已在 RFC 中澄清；其余 3 项涉及泛用数值 canonicalization、完整 Memory schema 和统一错误代码，尚不阻塞 minimal Core，但需要未来 profile/RFC。

### Python 与独立实现是否双向互通？

是。两个方向均通过 canonical Envelope 与 `project_state.upsert` handoff，payload 与固定向量精确匹配。

### 错误处理是否一致？

对 7 类固定坏输入，两个实现均拒绝。分类/异常文本尚未跨语言标准化，不能声称 error-code 字符串完全一致。

### Test vectors 是否足以验证实现？

足以验证最小 Core 的基础 conformance；不足以覆盖整个 ANA 愿景或所有 JSON/Memory 语义。

### ANA v0.1 是否已经具备第三方实现基础？

具备，但仅限 `ana-core-chain` v0.1 minimal profile。下一步应扩展规范性向量和错误/数值/Memory profile 的澄清，而不是新增协议功能。
