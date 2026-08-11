# RFC-0001：ANA v0.1 总体架构

- 状态：v0.1 最小核心已冻结（Draft）
- 版本：0.1
- 更新日期：2026-08-11
- 相关 RFC：[RFC-0002](RFC-0002-ANA-Chain.md)、[RFC-0003](RFC-0003-Envelope.md)、[RFC-0004](RFC-0004-Memory-System.md)、[RFC-0005](RFC-0005-Agent-Runtime.md)

## 摘要

ANA（Agent Network Architecture）定义一个以本地 Agent 为用户状态中心的架构与协议族。它使不同 Agent、设备和模型提供方能以统一的任务表达、语义映射和状态同步机制协作。

ANA 不训练模型，不持有用户身份，也不替代 HTTPS、WebSocket、TLS 或身份认证。云端或本地模型是可替换的计算能力提供方；用户的记忆、偏好、权限、任务状态和最终执行权属于本地 ANA Runtime。

## 1. 术语与约定

本文中的“必须（MUST）”“不得（MUST NOT）”“应当（SHOULD）”“可以（MAY）”用于描述 ANA v0.1 的实现要求。

- **Local Agent / Local Runtime**：运行在用户控制环境中的 ANA 控制平面。
- **Provider**：提供推理、生成、分析或其他能力的云端模型、本地模型或专用 Agent 服务。
- **Adapter**：在 ANA 表示与 Provider 原生接口之间进行转换的组件。
- **Node**：可发送或接收 ANA Chain 流的 Runtime、Agent 或兼容服务。
- **Canonical representation**：按 ANA schema、UTF-8 和确定性字段顺序编码的标准表示。
- **Memory**：独立于模型参数保存的用户或项目状态；详见 RFC-0004。

## 2. 设计目标

ANA v0.1 的目标如下：

1. **本地状态主权**：Local Agent 是用户状态、授权与策略的最终裁决者。
2. **模型与记忆分离**：模型权重、上下文缓存和用户长期记忆不是同一对象，也不应被强绑定。
3. **能力导向互换**：上层任务请求能力，如 `code_generation`，而不是固定某一厂商。
4. **AI 节点通信与同步**：任务、结构化语义和状态增量可以在兼容节点之间传递与恢复。
5. **最小权限**：只向 Provider 提供完成当前任务所需的最小上下文和权限。
6. **可独立实现**：协议不得依赖某个私有 Runtime、模型或服务才能解释。

## 3. 非目标

ANA v0.1 不定义或承诺以下内容：

- 基础模型训练、模型托管或模型能力评级；
- 通用聊天产品或完整个人助手产品；
- 加密、密钥管理、传输认证或访问令牌格式；
- 将任何可逆变换作为保密机制；
- 已被证明的通用 Token 压缩或“模型通用语言”；
- 自治多 Agent 社会、区块链、代币或经济系统。

## 4. 分层模型

ANA 的实现必须按以下逻辑层理解。相邻层可在同一进程内实现，但其职责不得混淆。

```text
┌─────────────────────────────────────────────────────────────┐
│ Application Layer                                            │
│ 用户任务、工具结果、Provider Adapter、应用呈现               │
├─────────────────────────────────────────────────────────────┤
│ ANA Envelope Layer                                           │
│ intent、capabilities、context、memory_refs、policy           │
├─────────────────────────────────────────────────────────────┤
│ ANA Chain Layer                                              │
│ 固定 Chain、指令、Codon、状态事件、版本与可逆恢复            │
├─────────────────────────────────────────────────────────────┤
│ Transport Layer                                              │
│ HTTPS / WebSocket / local IPC                                │
└─────────────────────────────────────────────────────────────┘
```

### 4.1 Application Layer

Application Layer 创建用户可见任务、消费结果，并通过 Adapter 连接具体 Provider。它可以使用自然语言、GUI、命令行或其他产品形式；这些形式不是 ANA 协议的一部分。

### 4.2 ANA Envelope Layer

Envelope 是一个 Provider 中立的任务描述。它表达“要做什么、需要什么能力、可使用哪些上下文引用、期望怎样执行”，但不规定字节如何传输或状态如何同步。具体格式见 RFC-0003。

### 4.3 ANA Chain Layer

Chain 是 ANA 的通信和状态同步核心。它将 canonical 的任务与状态事件组织为版本化流，并规定固定处理链、语义 Codon、状态增量与可逆恢复。具体格式见 RFC-0002。

### 4.4 Transport Layer

Transport Layer 负责节点间的实际传送。v0.1 可建立于 HTTPS、WebSocket 或 local IPC。TLS、服务端身份认证、用户认证、会话管理和网络访问控制由 Transport 或部署环境负责，不由 ANA Chain 提供。

## 5. 信任与控制边界

```text
用户
  │ 授权、偏好、控制
  ▼
Local Agent / Runtime ──────── ANA Envelope / Chain ───────► Provider
  │ 选择上下文、评估动作、记录状态                         │ 推理/生成
  ▼                                                         ▼
Safety Policy → Executor → 本地工具                  ProviderResult
```

Local Agent 必须保有以下权力：

- 决定哪些 Memory 可用于某一任务；
- 决定选择哪个 Provider；
- 将 Provider 的输出与 `ProposedAction` 分离；
- 允许、要求确认、沙箱执行或拒绝真实动作；
- 维护任务和状态事件的本地记录。

Provider 不得因其“官方”或“高信任”身份绕过这些边界。Cloud Model 是计算能力，不是用户身份、记忆的所有者或本地工具的直接控制者。

## 6. 互操作性原则

兼容实现应当：

1. 支持或显式拒绝特定协议、Chain 和词典版本；
2. 当无共同 Chain/Codon 词典时，使用 canonical 表示回退，而不是推测含义；
3. 保持 Provider Adapter 与 Executor 的分离；
4. 允许 portable Memory 在用户授权范围内导出、导入和审计；
5. 对版本不兼容、策略拒绝和无法解析的状态事件提供明确错误。

## 7. 安全说明

ANA 负责信息表达、状态同步和语义映射，不是加密协议。部署 ANA 时：

- 跨网络传输应使用 TLS 等成熟传输保护；
- 节点和用户身份应使用部署环境提供的认证机制；
- 秘密、密码和访问令牌不得放入普通 Envelope 或 portable Memory；
- Provider 返回的任何副作用请求必须先通过 Local Runtime 的 Safety Policy；
- 可逆 Chain 变换不得被当作混淆、加密或隐私保证。

## 8. 版本策略

ANA 的协议版本、Chain 版本和 Codon 词典版本彼此独立。一个实现只能在双方存在共同支持版本时发送对应表示。未知版本必须回退到共同的 canonical 表示或明确失败。

破坏字段语义、删除必需字段或改变 Chain 指令含义的修改必须发布为新的兼容性边界版本；新增可选字段和新增可选 Codon 可以在兼容规则下发布为次级版本。

### 8.1 v0.1 最小核心冻结范围

为完成 Phase 1 互操作验证，以下内容在 v0.1 内冻结：

- 分层职责以及 Local Runtime 对用户状态、Memory、策略和执行的本地权威；
- `ANAEnvelope` 的必需字段与 `ProviderResult`/`ProposedAction` 的建议-执行分离；
- `ana-core-chain` 版本 `0.1` 的 canonical JSON fallback frame；
- 无 Codon、无字节变换时的 Chain 行为；
- `project_state.upsert` State Delta 的最小语义；
- 此 profile 的固定测试向量和通过条件。

在此冻结范围中没有明确规定的行为，兼容实现不得自行假定为跨实现语义。实现可以在本地使用额外行为，但不得以 v0.1 互操作能力的名义发送给其他节点；需要共享时必须先补充 RFC。

## 9. Implementation Roadmap

### Phase 1：最小协议验证

- 冻结 v0.1 RFC 中的最小术语、Envelope、Chain 与 Memory 数据边界。
- 提供 canonical 表示、固定 Chain fallback 与 State Delta 的测试向量；Codon 词典保留为已定义但非必需的后续验证对象。
- 验证两个最小节点可以交换一个任务事件和一个状态增量，并可恢复 canonical 表示。
- 验证 Provider 只能提出动作，不能绕过本地 Safety Policy。

### Phase 2：Reference Implementation

- 实现可持久化的 Local Runtime、Memory Store、Router、Policy 和 Executor 接口。
- 实现 v0.1 的 Chain 编解码、会话协商、事件日志与 portable Memory 导入/导出。
- 以一个真实 Provider Adapter 和一个 deterministic Mock Adapter 验证边界。
- 为跨设备迁移、路径越界拒绝、版本回退和可逆性建立互操作测试。

### Phase 3：生态 Adapter

- 提供 Adapter 开发指南、能力声明格式、测试套件与兼容性样例。
- 支持模型厂商、本地模型社区和独立团队维护各自的 Adapter。
- 以至少两个独立 Runtime 与至少两个独立 Adapter 的互操作作为生态验证门槛。
- 根据测量结果决定 Codon 与 Chain 机制的哪些部分成为核心，哪些保持可选扩展。
