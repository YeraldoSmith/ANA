# ANA v0.1 独立 Java Node

`AnaV01Node.java` 是 Phase 7 的独立实现。它只依赖 Java 标准库；不导入 Python ANA Runtime、Python Node 或 Python JSON codec。它实现一个小型 JSON parser/writer，以使 canonical JSON 行为可审计。

从仓库根目录执行：

```bash
build_dir=$(mktemp -d)
javac -d "$build_dir" conformance/independent-java/AnaV01Node.java
python3 -m conformance.run_phase7_suite
```

CLI 操作：

- `emit-envelope`：从固定 Envelope/header 产生 canonical `ana-core-chain` frame；
- `accept-envelope`：验证并输出内层 canonical Envelope；
- `emit-state-delta`：产生确定性 `project_state.upsert`；
- `validate-state-delta`：验证 State Delta sequence、stream、parent 和 task；
- `import-state-bundle`：验证并 canonicalize 最小 Provider-neutral Memory/Project State/Policy bundle；
- `canonicalize`：检验 canonical JSON 行为。

输入/输出均为 stdin/stdout 的 UTF-8 JSON；失败以非零退出和 `ERROR:<category>:` 报告。操作语义与固定输入在 `docs/test-vectors/`，而不是硬编码的测试输出中定义。
