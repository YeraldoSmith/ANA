# Phase 3：Evidence & External Validation

> 状态：已完成离线证据与 Provider contract 验证；当前环境未配置外部 API Key，因此 live-provider 调用被安全跳过。
> 运行日期：2026-08-11

## 1. 实验边界

Phase 3 没有增加 ANA 协议或 Runtime 能力。实验只使用现有的 Envelope、选定的 Memory context、Provider Adapter 和本地 Safety Policy 边界。

- 不实现 Codon、复杂 Chain、多 Agent、跨设备同步或新的 Memory 功能。
- Provider 返回只转换为 `ProviderResult`；模型文本不产生 `ProposedAction`。
- 输入大小基准不调用模型，因此不会把输入保留率误写成模型正确率。

## 2. 已验证事实

### 2.1 OpenAI Adapter 的 live 验证路径

[`examples/live_openai_validation.py`](../examples/live_openai_validation.py) 实现且仅实现一次最小 live 调用：

```text
Local Runtime → selected ANA Memory / Envelope → OpenAI Adapter
  → OpenAI Responses API → ProviderResult → Local Runtime
```

它仅在 `OPENAI_API_KEY` 已配置时运行，默认选择一个明确的模型 ID（可由 `ANA_OPENAI_MODEL` 覆盖），并将 `store` 设为 `false`。本次运行检测到没有配置该密钥，因此发出 **0** 次请求并写入 [`live-openai.json`](../benchmarks/results/live-openai.json)；后续运行会创建新的 `live-openai-run-NNN.json`，不会覆盖该记录：

```json
{"status":"skipped_missing_openai_api_key","request_count":0}
```

因此，“ANA 已成功接入真实 OpenAI 模型”在本环境中**尚未被 live 验证**；已验证的是安全跳过逻辑、Adapter 请求/响应 contract，以及不会生成本地可执行动作的边界。

### 2.2 Provider 可替换性 contract

新增 [`AnthropicMessagesProvider`](../adapters/anthropic_messages.py)，使用 Anthropic Messages API 的独立 HTTP contract。它和 OpenAI Adapter 都调用相同的 [`render_ana_prompt`](../adapters/prompt.py)，后者只读取同一个 `ANAEnvelope.input` 和 `ANAEnvelope.context`。

离线 contract 测试向两个 Adapter 传递同一份 continuation Envelope，其中含有：

- `preference.language = java`
- `semantic.priority = security_first`

测试证明两个 HTTP 请求携带完全相同的 ANA Memory 输入，且两者都返回非可执行的 `ProviderResult`。本机没有 `ANTHROPIC_API_KEY`，因此没有 Anthropic live 调用或费用。

这个结果证明 **ANA 的输入边界不依赖某一 Provider 格式**；它不证明两个真实模型将以相同质量完成任务。

### 2.3 固定 benchmark 数据集

[`phase3_cases.json`](../benchmarks/phase3_cases.json) 包含 12 个固定向量、每个类别两个案例：

| 类别 | 案例数 |
| --- | ---: |
| 简单任务 | 2 |
| 代码生成/修改 | 2 |
| 长上下文 continuation | 2 |
| 用户 Preference | 2 |
| Project State | 2 |
| State Delta | 2 |

每个向量都有相同任务和 `required_facts`。测试在运行前验证 baseline 和 ANA packet 都包含全部必要事实；不满足该规则的运行不具备可比性。

## 3. 当前实验结果

原始、机器可读结果保留在：

- [当前公平运行（run-001）](../benchmarks/results/phase3-offline-run-001.json)
- [初始不公平运行（保留但排除）](../benchmarks/results/phase3-offline.json)

初始运行中 `continuation-001` 的 baseline 只有 8/9 必要事实；因此它已保留以便审计，但不能作为 ANA 效果的证据。修正向量后，当前运行的 baseline 和 ANA 都达到全部必要事实保留。

### 3.1 输入大小与 token 估算

当前公平运行的结果：

- **必要事实保留**：baseline 与 ANA 均为 12/12 案例完整保留。
- **UTF-8 字节更少**：ANA 在 12 个案例中的 3 个更小，9 个更大。
- **token 估算更少**：ANA 在 12 个案例中的 2 个更小，10 个更大。
- token 使用 `tiktoken` 的 `cl100k_base` 本地估算，不是任何 Provider 的账单 token，也不能推导成本。

按类别观察：

| 类别 | UTF-8 字节结果 | Token 估算结果 |
| --- | --- | --- |
| 简单任务 | ANA 2/2 更大 | ANA 2/2 更大 |
| 代码生成/修改 | ANA 2/2 更大 | ANA 2/2 更大 |
| 长上下文 continuation | 1 个更小，1 个更大 | 1 个更小，1 个更大 |
| 用户 Preference | ANA 2/2 更大 | ANA 2/2 更大 |
| Project State | ANA 2/2 更大 | ANA 2/2 更大 |
| State Delta | ANA 2/2 字节更小 | 1 个更小，1 个更大 |

这说明目前的结构化 JSON 表示有固定开销：在短任务和简单状态中，ANA 输入通常更大；在部分长 continuation 或 State Delta 场景中，ANA 可以减少 UTF-8 字节，但这种减少并不稳定地映射为 token 减少。

### 3.2 本地 encode/decode 开销

每个 packet 在同一进程中进行 1,000 次 canonical JSON serialize + parse，取平均值：

- baseline 平均：2.514 µs / 次；
- ANA 平均：3.594 µs / 次；
- ANA 相对平均增加：1.080 µs / 次；
- 单案例增加范围：0.676–1.854 µs / 次。

这些数值仅反映本机 Python 的小 packet 处理开销；它们不是网络延迟、模型延迟，也不是复杂 Chain 的性能数据。

### 3.3 Task correctness 与 latency

当前 offline benchmark 的 `task_correctness` 明确记录为 `not_evaluated_offline`，端到端 latency 为 `null`。原因是 benchmark 不调用模型，因而不能诚实地评估生成内容是否正确。

如果将来有用户配置的 OpenAI Key，live validator 会用一个单请求、精确文本任务记录 `task_correct`、`latency_ms` 和 `proposed_action_count`。在本次运行中它被跳过，故没有 latency 或真实模型正确率结果。

## 4. 尚未验证的假设

- ANA 的 structured Memory 在真实模型上是否能与完整历史达到相同或更高的任务正确率。
- ANA 在更多、更长、更真实的 continuation 上是否能稳定减少 Provider token 或费用。
- 两个真实 Provider 在同一 ANA Memory 下能否产生足够接近的质量和安全行为。
- 真实网络与模型耗时相对于本地 packet 开销的比例。
- Codon、复杂 Chain 或同步扩展是否带来收益；它们不在本阶段范围内。

## 5. 已知限制

- 数据集很小（12 个手工固定案例），不代表生产流量。
- baseline 使用简短相关历史，而非人为冗长的历史；这使许多 ANA 结果不占优，属于预期且应保留的结果。
- `cl100k_base` 是稳定的本地估算方法，但不保证等同于 OpenAI 或 Anthropic 某个实际模型的计费 tokenizer。
- 第二 Provider 仅完成 contract/offline test；没有 API Key 时不能宣称 live provider portability。
- 一次 live 请求只适合验证端到端连通性，不能构成模型质量 benchmark。

## 6. Phase 3 验收问题的当前回答

| 问题 | 当前证据回答 |
| --- | --- |
| ANA 是否真的可以接入真实模型？ | 真实 OpenAI Adapter 已实现并有 contract 测试；本环境无 Key，成功 live 调用尚未验证。 |
| 更换 Provider 时 Memory 是否仍然可用？ | OpenAI/Anthropic contract 测试证明相同 ANA Envelope/Memory 会进入两个 Adapter；真实模型语义效果尚未验证。 |
| 输入缩减能否在不同任务上重复出现？ | 不能据此声称普遍出现：12 例中仅 3 例字节更小、2 例 token 估算更小。 |
| 输入缩减是否牺牲任务正确率？ | 两侧输入事实均完整保留；真实任务正确率未在 offline benchmark 中评估。 |
| ANA 增加多少本地计算开销？ | 在这组小 JSON packet 上，平均约增加 1.080 µs/次 encode+decode；不代表端到端成本。 |

## 7. 外部接口依据

OpenAI Adapter 按官方 [Responses API 文档](https://developers.openai.com/api/docs/guides/migrate-to-responses) 的 `model`/`input` 模式实现；Anthropic Adapter 按官方 [Messages API reference](https://platform.claude.com/docs/en/api/messages) 的 Messages 端点结构实现。两者均以 ANA 的同一 Envelope 作为唯一上游输入。
