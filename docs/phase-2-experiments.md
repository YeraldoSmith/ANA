# Phase 2 最小实验记录

## 范围

Phase 2 只验证三个问题：

1. ANA 能否通过 Adapter 使用真实的外部计算 Provider，同时不把执行权交给 Provider？
2. 同一份本地 Memory 能否在不同 Provider 间保持连续，而不绑定某一模型？
3. 在固定 continuation 案例中，选择性结构化 Memory 是否比重发相关完整历史更小，同时保留规定事实？

不在本阶段实现 Codon 映射、复杂 Chain、跨设备冲突、自动 Memory 演化、多 Agent 或工具自治。

## 真实 Provider Adapter

[`adapters/openai_responses.py`](../adapters/openai_responses.py) 将 `ANAEnvelope` 映射到 OpenAI Responses API 的 `model` 和 `input`。它要求调用方明确传入模型 ID，并仅从 `OPENAI_API_KEY` 或构造参数取得密钥；没有密钥时明确失败，不会回退到模拟模型。

Adapter 设置 `store: false`，且不会从模型文本创建 `ProposedAction`。因此外部模型仅返回计算结果；本地 Runtime 继续拥有 Memory、策略和执行权。调用外部 API 是可选的，会产生用户账户侧的网络请求与可能的费用，自动化测试使用注入的假传输，不会发送网络请求。

## 模型可替换的 Memory continuation

[`ana/continuation.py`](../ana/continuation.py) 只从明确给定的 `memory_refs` 选择记录，并将结构化结果置入 Provider 中立的 Envelope context。Demo 用两个独立的 deterministic Provider 接收相同的：

- `preference.language = java`
- `semantic.priority = security_first`

两者得到相同的 Memory context。这验证的是接口边界，不是对不同基础模型质量的比较。

## ANA vs baseline benchmark

基准实现位于 [`benchmarks/`](../benchmarks/)，使用一个固定 continuation 案例：

| 指标 | Baseline（相关完整历史） | ANA（选择的结构化 Memory） |
| --- | ---: | ---: |
| canonical JSON UTF-8 字节数 | 615 | 259 |
| 节省字节数 | — | 356 |
| 必要事实完整性 | 3/3 | 3/3 |

该结果仅说明在这个已公开的固定案例中，ANA 输入比 baseline 少约 57.9% 的 UTF-8 字节，同时包含相同的预定义事实。它**不**证明 Token 成本、延迟、模型输出质量或生产场景中的普遍优势。后续若增加指标或案例，必须同时记录输入、模型、提示、运行次数和统计方式。
