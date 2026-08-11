# Phase 1 双节点互操作验证

`node_a.py` 和 `node_b.py` 是两个刻意分离的 Python ANA v0.1 最小 profile 实现。二者不导入彼此，也不调用 `ana/` 参考 Runtime 的编解码逻辑。

验证路径为：

```text
Node A
  → 将“Generate Java Hello World”封装为 ANA Envelope frame
  → Node B 独立解析并验证该任务
  → Node B 产生 project_state.upsert State Delta
  → Node A 独立解析、验证因果关系并接收该 Delta
```

固定输入和期望 canonical payload 位于 [`../docs/test-vectors/ana-v0.1-minimal.json`](../docs/test-vectors/ana-v0.1-minimal.json)。运行以下命令可执行验证：

```bash
python3 -m unittest discover -s tests -v
```

该验证证明 v0.1 最小 Chain fallback 能让两个独立节点交换实际任务描述与状态增量；它不证明模型调用、工具执行、加密、Codon 映射或跨设备冲突解决。

## Phase 7：独立 Java 实现

[`independent-java/AnaV01Node.java`](independent-java/AnaV01Node.java) 是一个新的 Java 实现。它不导入 `ana/`、`node_a.py` 或 `node_b.py`，也不使用它们的 codec、reducer 或 Memory Store；它仅按 RFC-0001 至 RFC-0005 与 `docs/test-vectors/` 重新实现最小 Core。

它支持：canonical Envelope/frame、v0.1/version 校验、`project_state.upsert`、sequence/causality 校验、RFC-0004 最小 Memory/Project State/Policy bundle import，以及结构化拒绝。

运行跨语言 suite（需要 JDK）：

```bash
python3 -m conformance.run_phase7_suite
```

suite 覆盖两个方向：

```text
Python Reference Node → Java Independent Node → Python Reference Node
Java Independent Node → Python Reference Node → Java Independent Node
```

并使用固定正向、Unicode canonical、Memory/State 和负向向量验证 unknown version、malformed envelope、sequence、causality、unknown required semantics 与 invalid State Delta 的拒绝行为。

一个实现只有在其独立实现通过本仓库 `ana-core-chain` v0.1 最小 profile 的全部正向和负向 suite 后，才能声明：`ANA v0.1 Core Conformant (minimal profile)`。该声明不覆盖 Codon、TRANSFORM、Provider 模型质量、工具执行、跨设备冲突合并或未定义的 Memory 语义。
