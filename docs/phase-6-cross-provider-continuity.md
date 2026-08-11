# Phase 6：Cross-Provider State Continuity Validation

> 状态：完成（offline contract validation）；真实 API validation 未完成。
> 离线原始结果：[phase6-offline-contract-run-001.json](../benchmarks/results/phase6-offline-contract-run-001.json)
> Live 入口结果：[phase6-live-run-001.json](../benchmarks/results/phase6-live-run-001.json)（缺少所需密钥，0 次请求）

## 1. 结论

在确定性的协议合同实验中，同一个 Local Agent 能够从 OpenAI-contract 切换至 Anthropic-contract，也能反向切换，并保留选中的用户 Memory、`security_first` Preference、Java 项目状态以及本地 Safety Policy。Provider B 没有得到 Provider A 的聊天历史；它只得到新构造的、同一份本地 ANA Memory/State/Policy context。

这验证的是**协议层连续性**，不是对真实模型理解能力的承诺。当前环境没有两个 Provider 的 API Key，因此没有真实 OpenAI ↔ Anthropic API 调用，也不声称已经完成 live-provider continuity。

## 2. 固定接力 Demo

初始 Local State：Java 项目已有 `src/main/java/ana/App.java`，阶段为 `scaffolded`，sequence 为 4，已完成 `create_basic_structure`。选中 Memory 包含：

- `language=java`、`project=ANA`；
- `priority=security_first`；
- `memory_owner=local_runtime`。

旧的冲突状态 `mem-old-phase: phase=discovery` 保留在本地 Memory Store 中，但不在选择结果内。

```mermaid
sequenceDiagram
    participant L as Local Agent
    participant A as Provider A
    participant B as Provider B
    L->>A: ANA Memory + State(seq=4) + Policy
    A-->>L: Candidate: validate scaffold
    L->>L: Validate and commit local State Delta
    Note over L: phase scaffolded → implementation<br/>sequence 4 → 5
    L->>B: Fresh ANA Memory + State(seq=5) + Policy<br/>No Provider A chat history
    B-->>L: Continue project; sees completed validation
```

最终状态 diff：

| 字段 | 切换前 | Provider A 后由 Local Runtime 提交 |
| --- | --- | --- |
| `phase` | `scaffolded` | `implementation` |
| `sequence` | 4 | 5 |
| `completed_tasks` | `create_basic_structure` | 加入 `validate_scaffold` |
| 文件 | `src/main/java/ana/App.java` | 未重复创建 |

两条独立迁移均通过：

1. `openai-contract → anthropic-contract`
2. `anthropic-contract → openai-contract`

## 3. Continuity assertions

两条迁移均通过以下 assertions：

| Assertion | 结果 |
| --- | --- |
| `security_first` Preference 保留 | 通过 |
| Provider B 看见阶段 `implementation` | 通过 |
| Provider B 看见 `validate_scaffold` 已完成，因而不会重复任务 | 通过 |
| 最新 State 覆盖未选中的旧 `discovery` Memory | 通过 |
| Provider B 不接收 Provider A 的完整历史 | 通过 |
| Memory 不含 `openai` / `anthropic` 专属结构 | 通过 |
| `sandbox_first` Safety Policy 在切换后仍在 context 中 | 通过 |

Provider A 的候选 State Delta 不是自动可信输入。Local Runtime 先校验 sequence、parent event、预期 phase 和任务去重条件，再由本地提交新状态；模型文本不能直接产生可执行动作。

## 4. Provider independence

ANA Memory 仅由 provider-neutral 的 `id`、`kind` 与 `content` 表示，没有 OpenAI Responses object、Anthropic Messages object、response ID 或任一厂商的会话状态。

真实 Adapter 类的离线 boundary contract test 使用注入的无网络响应，验证：

- OpenAI Responses Adapter 与 Anthropic Messages Adapter 从**同一个** ANA Envelope 渲染出相同的 provider-neutral prompt；
- Adapter 返回的 `ProviderResult` 不含 `ProposedAction`；
- Adapter 不会修改或迁移 ANA Memory schema；
- Provider 切换无需将 Memory 转换成另一厂商格式。

因此，Provider Adapter 的职责仍然只是 ANA ↔ Provider API 的边界转换；Local Runtime 持有的 Memory/State 不属于任何 Provider。

## 5. Failure cases

以下所有 Provider B 建议均由 Local Runtime 检测或拒绝，且 local State 保持不变：

| Provider B 故障 | Local Runtime 结果 |
| --- | --- |
| 建议将当前项目阶段回退为 `discovery` | 拒绝：`state_conflicts_with_current_project` |
| 忽略 `security_first`，返回 `speed_first` | 拒绝：`preference_not_preserved` |
| 建议写入 workspace 外的文件 | Local Safety Policy 拒绝：`unsafe_action_denied_by_local_policy` |
| 返回回退的 State sequence | 拒绝：`state_sequence_not_monotonic` |
| 引用未选中的过期 `mem-old-phase` | 拒绝：`stale_or_unselected_memory_referenced` |

这说明 Provider 输出只能是候选信息，不能取代 Local Runtime 的状态与安全决策。

## 6. 验证层级与限制

| 层级 | 当前状态 | 说明 |
| --- | --- | --- |
| Protocol-level continuity | 已验证 | 两条确定性接力、State diff、Memory/State/Policy 断言与故障拦截均通过。 |
| Offline contract validation | 已验证 | 21 个全量测试通过；真实 Adapter boundary 使用无网络注入响应测试。 |
| Model-quality continuity | 未验证 | contract provider 按规范回显状态，不代表真实模型总能理解、遵循 Preference 或输出正确任务结果。 |
| Live API validation | 未验证 | 当前缺少 OpenAI 与 Anthropic 所需密钥；live 入口安全跳过，0 次请求。 |

可选 live 入口为：

```bash
python3 -m examples.live_cross_provider_validation
```

它仅在两个密钥都已配置时才会进行 4 次最小 Adapter-path 请求，且不会输出、保存或传输密钥。即使完成，该入口也会把结果标记为 `completed_adapter_path_only`：它验证真实 Adapter 路径，而不把自由文本模型响应升级为本地状态操作或模型质量证明。

## 7. 最终回答

### 换 Provider 是否需要重新读取完整历史？

在已验证的协议路径中不需要。Provider B 接收一个新 ANA Envelope，其中只有选中的 Memory、当前 Project State、State Delta context 和 Safety Policy；它不接收 Provider A 的聊天历史。

### 换 Provider 是否会丢失长期 Memory？

离线合同实验中不会：Java 项目事实、`security_first` 和 `memory_owner=local_runtime` 都保留。对真实模型的长期召回质量仍未验证。

### Project State 是否连续？

是。Local Runtime 将 phase 从 `scaffolded` 提交为 `implementation`，并将 sequence 从 4 增至 5；切换后的 Provider B 看见新状态和已完成任务。

### Safety Policy 是否连续？

是。Policy 在新 Envelope 中仍为 `sandbox_first`，且跨 Provider 的不安全写入建议被本地 policy 拒绝。

### Provider 是否真正可替换？

在协议和 Adapter 合同层面可替换：两个方向均通过，且没有 Memory schema migration。真实 OpenAI ↔ Anthropic 的 live 调用尚未进行，因此不应把本阶段表述为真实 Provider 的模型质量等价或生产可用性证明。
