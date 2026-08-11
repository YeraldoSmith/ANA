# RFC-0005：ANA Local Agent Runtime

- 状态：v0.1 最小核心已冻结（Draft）
- 版本：0.1
- 更新日期：2026-08-11
- 依赖：[RFC-0001](RFC-0001-Architecture.md)、[RFC-0002](RFC-0002-ANA-Chain.md)、[RFC-0003](RFC-0003-Envelope.md)、[RFC-0004](RFC-0004-Memory-System.md)

## 摘要

ANA Local Agent Runtime 是部署在用户控制环境中的控制平面。它把用户请求转化为 ANA Envelope，选择适当计算能力，在本地维护 Memory 和项目状态，并确保任何真实工具动作都通过 Safety Policy。

Runtime 可以调用云端模型、本地模型或专用 Agent，但这些 Provider 仅提供计算能力。它们不是用户身份、Memory 或本地执行权限的权威。

## 1. 必需组件

一个最小 ANA Local Agent Runtime 必须逻辑上包含以下组件。它们可以以模块、进程或服务实现，但其职责必须可区分。

| 组件 | 职责 |
| --- | --- |
| Observer | 接收用户请求、环境事件和工具结果；形成可处理的输入事实 |
| Memory | 保存、检索、迁移和按策略披露 RFC-0004 所定义的记录 |
| Planner | 将请求组织为任务意图、能力要求、上下文与执行期望，并创建 Envelope |
| Router | 根据能力和本地可用性选择 Provider/Adapter；不把厂商身份写死为任务语义 |
| Executor | 仅执行已获许可的结构化动作，并报告结果 |
| Safety Policy | 评估 Memory 披露和动作请求，作出允许、确认、沙箱或拒绝决定 |

## 2. 运行流程

```text
Observer
  → Planner（创建 ANAEnvelope）
  → Memory（选择最小必要上下文）
  → Router（选择能力提供方）
  → Adapter / Provider（计算）
  → ProviderResult + ProposedActions
  → Safety Policy（逐项评估）
  → Executor（仅执行获许可动作）
  → Observer / Memory（记录结果和状态事件）
```

该流程的关键规则是：Provider 的文本输出和真实副作用必须分离。一个模型可以建议写文件、运行测试或传输数据；只有 Runtime 的 Safety Policy 与 Executor 可以让建议成为实际动作。

## 3. Observer

Observer 负责收集用户输入、环境变化、Provider 结果和 Executor 结果。它应当：

- 标识输入的来源和所属任务；
- 将用户输入与自动观察到的环境事实区分；
- 不自行把环境数据、文件内容或秘密发送给 Provider；
- 为 Planner、Memory 和审计记录提供可追溯事件。

Observer 不负责决定任务计划、Provider 选择或工具授权。

## 4. Memory

Runtime 的 Memory 组件必须遵循 RFC-0004。它负责：

- 用 `memory_refs` 支持任务与本地记录关联；
- 按最小权限原则检索、摘要和披露内容；
- 管理 portable、device-local 与 ephemeral 的生命周期；
- 导出/导入经授权的 Migration Profile；
- 把 Provider 提议的新记录视为候选，而不是未经审查的事实。

## 5. Planner

Planner 将用户目标整理为 `ANAEnvelope`。它必须：

- 选择明确的 `intent`；
- 声明完成任务所需的 `capabilities`；
- 将即时非秘密信息置于 `input` 或 `context`；
- 引用必要的 `memory_refs`，而非默认携带所有历史；
- 提出 `policy` 期望，但不得绕过 Runtime 的硬性策略。

Planner 可以使用模型辅助推理，但最终 Envelope 必须通过 Runtime 的 schema 校验。

## 6. Router 与 Adapter

Router 必须以能力匹配为主：若任务要求 `code_generation`，Router 选择声明支持该能力的 Provider。选择算法可以考虑本地可用性、延迟、成本、用户偏好或信任设置，但不得因此绕过 Safety Policy。

Adapter 的职责是：

```text
ANAEnvelope → Provider 原生请求
Provider 原生响应 → ProviderResult + ProposedActions
```

Adapter 必须保持这条边界，不得直接调用 Executor、静默改变 Local Memory 或以 Provider 结果覆盖本地策略。

## 7. Executor

Executor 只接收已经通过 Safety Policy 的结构化动作。v0.1 的参考动作形式为：

```json
{"kind": "write_file", "target": "generated/Hello.java", "content": "..."}
```

执行器必须：

- 验证动作目标仍处于已授权范围；
- 在执行后返回成功、失败或取消结果；
- 将结果交回 Observer 形成任务/状态事件；
- 不接受未经策略判定的自由文本命令作为授权。

## 8. Safety Policy

Safety Policy 是 Local Runtime 的最终行为门。它至少应能对 Memory 披露和 `ProposedAction` 返回：

- `allow`：在限定范围内允许；
- `confirm`：需要用户明确确认；
- `sandbox`：应在隔离环境验证后再决定；
- `deny`：不得执行或披露。

v0.1 的参考实现允许写入指定工作区中的文件，并拒绝路径越界；其他操作可要求确认。真实部署应根据操作类别、数据敏感性、目标范围和用户偏好定义更严格规则。

无论 Provider 是官方、第三方或本地模型，Safety Policy 都必须保留否决权。

## 9. 运行时状态同步

Runtime 使用 RFC-0002 的 ANA Chain 传递任务事件、Memory 增量、策略决定和工具结果。它应当：

- 为同步事件分配 `event_id`、`stream_id` 和 `sequence`；
- 仅同步可被策略允许的状态；
- 在无法安全合并的跨节点事件上保留冲突，而非静默覆盖；
- 将 Chain 协商失败或版本不兼容显式报告给上层。

v0.1 不规定自治 Agent 之间的复杂谈判或冲突自动合并。若 Runtime 委派子任务，仍应保持任务来源、能力范围和结果来源可追溯。

## 10. 安全与隐私边界

- Runtime 不得把 Provider 当作用户身份中心；
- Runtime 不得因为模型“可信”就自动扩大数据披露或执行权限；
- Runtime 不得用 ANA Chain 变换代替 TLS、认证或秘密管理；
- Runtime 应保留足够的本地审计信息，以解释“为何选择某 Provider、披露何种 Memory、允许何项动作”；
- Runtime 应允许用户管理 portable Memory 和显式高风险授权。

## 11. 当前 v0.1 参考实现边界

当前代码实现了简单的内存记录、能力 Router、Mock Provider、文件写入策略门和 Executor。它尚未实现真实云端 Adapter、持久化审计、全面沙箱、跨设备会话协商或自动冲突合并。这些限制不改变本 RFC 的职责边界，但必须在产品中如实披露。
