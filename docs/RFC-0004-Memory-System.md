# RFC-0004：ANA Memory System

- 状态：v0.1 最小核心已冻结（Draft）
- 版本：0.1
- 更新日期：2026-08-11
- 依赖：[RFC-0001](RFC-0001-Architecture.md)、[RFC-0003](RFC-0003-Envelope.md)

## 摘要

ANA Memory System 定义用户和项目状态如何独立于模型参数保存、演化、迁移与按需披露。它的目的不是保存无限的聊天全文，而是让 Local Agent 能在用户授权下形成可追溯、可纠正、可迁移的长期上下文。

Memory 属于用户控制的 Local Runtime。Cloud Model 只能在当前任务的策略范围内接收经筛选的内容，不能天然拥有或定义用户身份。

## 1. 基本原则

- Memory 必须与模型权重、Provider 私有缓存和设备硬件状态分离。
- 原始来源与派生结论必须可区分。
- 派生的摘要、语义或偏好模型不得伪称可以无损恢复原始记录。
- 用户应能查看、纠正、导出和删除属于自己的 portable Memory。
- Runtime 必须遵循最小披露原则，而不是向 Provider 发送全部历史。

## 2. MemoryRecord

v0.1 的最小记录形状如下：

```json
{
  "id": "mem_xxx",
  "kind": "preference",
  "content": {"security_priority": "high"},
  "portability": "portable",
  "created_at": "2026-08-11T00:00:00+00:00"
}
```

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `id` | 是 | Runtime 内可引用的稳定记录标识符 |
| `kind` | 是 | 本 RFC 第 3 节定义的 Memory 类别 |
| `content` | 是 | 与 `kind` 匹配的结构化内容 |
| `portability` | 是 | `portable`、`device_local` 或 `ephemeral` |
| `created_at` | 是 | 带时区的创建时间 |

后续实现应增加来源、生成者/模型版本、置信度、适用范围、失效条件与撤销关系；这些字段是 Memory Evolution 的必要审计元数据，但当前参考代码尚未实现持久化 schema。

## 3. Memory 类型

### 3.1 Raw Memory

Raw Memory 是原始对话、文件片段、工具输出或事件记录。它适合追溯和纠错，不应默认全量重新发送给模型。Raw Memory 通常包含较多隐私和上下文，应由本地策略严格控制。

### 3.2 Structured Memory

Structured Memory 是从原始材料提取出的显式字段、实体、关系或任务事实。例如项目名称、语言、待办事项、时间范围或来源链接。它便于稳定检索和跨实现处理。

### 3.3 Semantic Memory

Semantic Memory 是经过验证或持续复用的高层结论，例如“该项目优先考虑安全”“用户主要使用 Java”。它必须保留足以追溯其来源或更新理由的信息，且允许被用户纠正。

### 3.4 User Preference

User Preference 记录用户明示或经确认的工作偏好，例如解释详细程度、语言选择、风险偏好。它不是不可见画像；用户应能检查、编辑、导出和删除。

### 3.5 Project State

Project State 表示与一个明确项目或任务相关的状态，例如当前目标、已验证结论、待办事项、任务阶段和产物引用。它必须与一般用户偏好分开，以避免一个项目的临时状态错误地影响其他项目。

## 4. Memory Evolution

为避免无限重读全部上下文，ANA 使用以下演化关系：

```text
Raw Memory
  → Structured Memory / Summary Memory
  → Semantic Memory
  → User Preference 或 Project State 的可复用结论
```

每次演化都是有意抽象，而非 ANA Chain 的可逆变换。实现应保留其输入来源、产生时间、产生者、适用范围和可撤销关系。若来源发生变化或用户纠正结论，Runtime 应使相关派生记录失效或重新生成。

## 5. 可移植性与迁移

`portability` 的值和规则：

- `portable`：用户明确可跨设备带走的偏好、语义结论、技能标签或兼容项目状态；
- `device_local`：本地路径、硬件探测、模型缓存、设备权限和其他不可直接迁移状态；
- `ephemeral`：当前会话或短任务的临时上下文。

迁移以 `MigrationProfile` 形式进行，而不是复制完整 Agent 进程或模型状态。接收设备必须重新发现自身模型、工具、权限和硬件能力。受资源或隐私限制的目标设备可以只接收最小 `portable` 集合。

## 6. 访问与披露

1. Envelope 只保存 `memory_refs`，不自动包含完整记录内容。
2. Local Runtime 必须在任务需要和用户策略允许时才解析/筛选记录。
3. 向 Provider 披露前，Runtime 应优先使用必要的结构化或摘要形式，而不是原始资料。
4. 秘密、令牌和凭据不得通过一般 Memory 导出或普通 Envelope 传递。
5. Provider 输出形成的新 Memory 必须作为候选记录，经 Local Runtime 和适当策略处理后才可写入。

## 7. 与 ANA Chain 的关系

ANA Chain 可以同步 Memory 的引用、事件和经授权的 portable 增量；它不改变 Memory 所有权。Memory 的摘要/语义演化并不因使用 Chain 而自动可逆。跨设备同步使用状态事件，接收方必须按版本、策略与冲突处理规则处理。

## 8. 当前 v0.1 边界

当前参考实现只提供内存中的 `MemoryRecord` 存储和 `portable` Migration Profile 导出。持久化存储、检索排序、加密静态存储、冲突合并、自动摘要和用户管理界面均不在已实现范围内。
