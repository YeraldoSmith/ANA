# RFC-0003：ANA Envelope Layer

- 状态：v0.1 最小核心已冻结（Draft）
- 版本：0.1
- 更新日期：2026-08-11
- 依赖：[RFC-0001](RFC-0001-Architecture.md)、[RFC-0002](RFC-0002-ANA-Chain.md)、[RFC-0004](RFC-0004-Memory-System.md)

## 摘要

ANAEnvelope 是 Provider 中立的任务描述对象。它让 Local Runtime 可以用统一格式表达任务意图、所需能力、可用上下文、Memory 引用和执行期望，再由 Router 和 Adapter 选择/调用具体计算能力。

Envelope 不是完整通信协议，不是身份凭据，也不是秘密容器。Envelope 在 ANA Chain 中作为 canonical task event 传输或同步。

## 1. 数据模型

v0.1 的最小 Envelope 为：

```json
{
  "version": "0.1",
  "task_id": "uuid",
  "intent": "generate",
  "capabilities": ["code_generation"],
  "input": {"text": "生成 Java Hello World"},
  "context": {"language": "java"},
  "memory_refs": ["mem_xxx"],
  "policy": {"execution_mode": "sandbox_first"}
}
```

| 字段 | 必需 | 类型 | 说明 |
| --- | --- | --- | --- |
| `version` | 是 | string | Envelope schema 版本；v0.1 为 `"0.1"` |
| `task_id` | 是 | string | 全局唯一的任务标识符，建议 UUID |
| `intent` | 是 | string | 结果导向短动词，如 `generate`、`analyze`、`plan` |
| `capabilities` | 是 | string array | 所需 Provider 能力的有序集合，如 `code_generation` |
| `input` | 是 | object | 此任务必须处理的结构化输入 |
| `context` | 否 | object | 非秘密、可序列化的辅助上下文 |
| `memory_refs` | 否 | string array | Local Runtime 管理的 Memory 标识符 |
| `policy` | 否 | object | 调用方期望的执行模式；不能削弱本地硬性策略 |

未识别的可选字段可以被接收方保留或忽略；它们不得改变 v0.1 必需字段的语义。

## 2. 创建与路由

1. Observer 或 Application 接收用户请求。
2. Planner 创建 Envelope，并声明完成该任务所需的能力。
3. Memory 组件只将被策略允许的记录以 `memory_refs` 关联。
4. Router 根据 `capabilities` 选择可用 Provider。
5. Adapter 将 Envelope 转换为 Provider 的原生请求。

`capabilities` 表达需求而非首选厂商。若无 Provider 支持所有必需能力，Router 必须返回可解释的不可路由错误，不得私自降级任务语义。

## 3. Context 与 Memory 边界

`context` 与 `memory_refs` 有不同角色：

- `context` 是本次任务即时、非秘密的提示信息，例如语言、格式、项目范围。
- `memory_refs` 是本地记录的引用，不等同于将整个 Memory 内容发送给 Provider。

Local Runtime 必须在策略允许的范围内解析、摘要或筛选 Memory；不得因一个引用存在就自动发送原始聊天记录。密码、访问令牌、私钥和其他秘密不得作为普通 `context`、`input` 或 portable Memory 内容传输。

## 4. Policy 语义

`policy` 是任务请求者表达的期望，例如：

```json
{"execution_mode": "sandbox_first"}
```

它不是对 Local Safety Policy 的授权升级。Local Runtime 必须能够施加更严格的限制；例如调用方请求自动执行时，本地策略仍可要求确认或拒绝。

## 5. Provider 结果与动作建议

Adapter 应将 Provider 响应转换为 `ProviderResult`：

```json
{
  "provider_id": "example-code-provider",
  "output": {"text": "...", "artifacts": []},
  "proposed_actions": [
    {"kind": "write_file", "target": "generated/Hello.java", "content": "..."}
  ]
}
```

`output` 是结果内容；`proposed_actions` 是明确、结构化的副作用建议。Provider 或 Adapter 不得直接执行 `proposed_actions`。所有动作必须通过 RFC-0005 定义的 Safety Policy 和 Executor。

## 6. 序列化与版本

Envelope 在进入 ANA Chain 前必须被编码为 canonical JSON：UTF-8、对象键按 Unicode 代码点升序排列、数组顺序保持原样、无多余空白、明确的 `version`。在 Python 中，符合该规则的参考写法是 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`。Envelope 版本仅描述任务对象 schema；它不同于 Chain 版本和 Codon 词典版本。

接收方不支持 `version` 时，必须明确报告不兼容；不得把未知必需字段猜测映射到现有字段。

### 6.1 v0.1 最小验证 profile

固定向量中使用的 Envelope 必须只包含第 1 节列出的字段，且 `version` 必须为 `"0.1"`。`task_id` 必须是非空字符串，`intent` 必须是非空字符串，`capabilities` 必须是至少包含一个非空字符串的数组，`input` 必须为对象。`context`、`memory_refs` 和 `policy` 如存在，必须分别为对象、字符串数组和对象。

该 profile 不对 `intent`、`capabilities` 或 `policy` 建立超出测试向量的全局词表；需要跨实现依赖新含义时，必须先通过 RFC 定义。

**Phase 7 clarification：**本 profile 的必需 Envelope 字段仅为本节已列出的字段；v0.1 不定义“未知字段但对所有接收方仍为必需”的标记。未知成员因此只能作为可忽略或可保留的扩展，不能改变 v0.1 Core 语义。若需要某个新字段为必需，必须定义新的 version 或 profile；接收方则必须明确报告不兼容，而不得猜测其含义。

## 7. 错误边界

至少应区分以下失败情形：

- `invalid_envelope`：缺失或类型错误的必需字段；
- `unsupported_envelope_version`：无法处理 `version`；
- `no_capable_provider`：没有 Provider 满足 `capabilities`；
- `memory_access_denied`：策略禁止解析或披露某项 Memory；
- `policy_restricted`：任务期望与本地强制策略冲突；
- `provider_failure`：Adapter 或 Provider 未能产生有效结果。

错误内容不得泄露被拒绝 Memory 的秘密内容或本地安全策略的敏感细节。
