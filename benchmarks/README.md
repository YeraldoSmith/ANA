# Phase 2：ANA continuation benchmark

该基准比较两种对同一 continuation 请求的输入组织方式：

- **baseline**：重发完整的、与该请求相关的对话历史；
- **ANA**：重发请求与已选择的结构化 Memory。

它只报告 canonical JSON 的 UTF-8 字节数，以及两边是否包含预先定义的必要事实。它不宣称 Token、价格、延迟或模型结果质量相同；这些需要在同一模型、同一提示和受控实验中另行测量。

运行：

```bash
python3 -m benchmarks.run_continuation_benchmark
```

通过条件是 ANA 输入包含所有 `required_facts`，且在该固定案例中小于 baseline 输入。案例集可扩展，但任何新指标都必须在此处说明其测量范围。

## Phase 3 evidence benchmark

Phase 3 使用 [`phase3_cases.json`](phase3_cases.json) 中的 12 个固定向量。它比较 baseline 相关历史与 ANA 的 selected Memory / Project State / State Delta packet，并保存每次原始结果：

```bash
python3 -m benchmarks.run_phase3_benchmark
```

每次运行会写入新的 `benchmarks/results/phase3-offline-run-NNN.json`；先前运行不会被脚本删除。Token 是 `cl100k_base` 本地估算，而非任意 Provider 的账单 token。完整方法、结果与限制见 [Phase 3 evidence](../docs/phase-3-evidence.md)。

## Phase 4 break-even analysis

Phase 4 不改写 Phase 3 数据；它逐项分解当前 12 个 packet，并用固定参数集观察历史、Project State、Preference、重复上下文与 continuation 规模增长：

```bash
python3 -m benchmarks.phase4_analysis
```

每次会保留 `benchmarks/results/phase4-break-even-run-NNN.json`。分析和当前结论见 [Phase 4 break-even analysis](../docs/phase-4-break-even-analysis.md)。

## Phase 5 ablation and fair-baseline validation

Phase 5 separates three representations for the same continuation task: Naive history, Smart JSON with the same Memory/State selection as ANA, and ANA canonical Envelope. It also measures existing Envelope field groups and fixed Memory-selection fidelity vectors:

```bash
python3 -m benchmarks.phase5_analysis
```

Each run preserves `benchmarks/results/phase5-ablation-run-NNN.json`; prior runs are never overwritten. Method, raw-result qualification, results, and limitations are in [Phase 5 ablation and fair-baseline validation](../docs/phase-5-ablation-fair-baseline.md).

## Phase 6 cross-provider continuity

Phase 6 validates that two provider boundaries can hand off the same selected ANA Memory, Project State and Local Safety Policy. Its deterministic contract run covers OpenAI → Anthropic and Anthropic → OpenAI, plus rejected-provider-output cases:

```bash
python3 -m benchmarks.run_phase6_continuity
```

Each invocation preserves `benchmarks/results/phase6-offline-contract-run-NNN.json`. The optional real-adapter entry is `python3 -m examples.live_cross_provider_validation`; it performs zero requests unless **both** provider keys are configured, and it records adapter-path evidence separately from model-quality evidence. Details are in [Phase 6 cross-provider continuity](../docs/phase-6-cross-provider-continuity.md).
