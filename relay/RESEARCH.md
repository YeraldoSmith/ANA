# ANA Relay 市场调研：中转站现状与 ANA 切入点

**日期**: 2026-08-07

---

## 一、中转站市场规模

- **OpenRouter**：ARR 从 ~$5M 增至 ~$50M（不到一年，约 10x），每月路由数万亿 token
- **LiteLLM**：开源网关，零请求费，P50 延迟 ~320ms
- **Portkey**：托管网关，~$100/月（每 1 亿 token）
- **Helicone**：可观测性网关，零请求费，~250ms 开销

中转站是真实且快速增长的市场。统一的跨模型 API 接入是刚需。

---

## 二、中转站核心运转模式

```
用户/Agent
    │
    │  API Key (中转站发放)
    ▼
┌──────────────────────────────────────────────┐
│              中转站                           │
│                                              │
│  1. 接收请求（OpenAI-compatible 格式）         │
│  2. 认证 & 计费                              │
│  3. 模型路由（选最便宜/最快的后端）            │
│  4. 格式翻译（OpenAI ↔ Anthropic ↔ Google）   │
│  5. 转发到上游 LLM API                       │
│  6. 翻译响应格式（统一返回 OpenAI 格式）       │
│  7. 记录 token 用量 & 计费                   │
│                                              │
│  收入来源：                                  │
│    - 上游批发价 vs 下游零售价的差价            │
│    - 加价 10-30%（如 OpenRouter +10%）        │
│    - 月费（如 Portkey $100/月）              │
└──────────────────────────────────────────────┘
    │
    ▼
上游 LLM API (OpenAI / Anthropic / Google / Azure)
```

---

## 三、中转站最大的技术痛点：Function Calling 格式翻译

### 3.1 三种互不兼容的格式

| | OpenAI | Anthropic | Google |
|---|---|---|---|
| **工具定义** | `tools: [{type:"function", function:{name,parameters}}]` | `tools: [{name, input_schema}]` | `function_declarations` |
| **调用输出** | `tool_calls: [{id, function:{name, arguments: JSON string}}]` | `tool_use` content blocks, `input: JSON object` | `functionCall` |
| **结果回传** | `role: "tool"` + `tool_call_id` | `tool_result` content block in user message | `functionResponse` |
| **流式** | SSE `delta.tool_calls` 逐步拼接 | `input_json_delta` 事件 | 谷歌格式 |
| **Schema 差异** | `strict`, `additionalProperties` | 不支持 `strict`，`anyOf` 不稳定 | 自己的格式 |
| **参数字段名** | `parameters` | `input_schema` | `parameters` |

### 3.2 翻译的复杂性

中转站要写的适配器代码：
- OpenAI → Anthropic：重命名字段、转换 `role:tool` → `tool_result`、JSON string → object
- Anthropic → OpenAI：`stop_reason` 映射、`tool_use` → `tool_calls` 数组、`input_json` → `arguments` JSON string
- 流式翻译最复杂：需要**有状态的逐事件翻译 + 参数缓冲**，维护每个 tool call 的 index lane
- **静默丢失**：`frequency_penalty`、`logprobs`、`seed`、`thinking`、`search_result` 等参数在某些方向上被直接丢弃

### 3.3 翻译的性能代价

- 纯 JSON 重构，不增加上游 token 消耗
- 但**中间层 CPU 开销显著**（流式解析 + 格式重构 + Schema 兼容检查）
- Schema 兼容性是常见的 4xx 错误来源（直接用 OpenAI schema 调 Anthropic 会报错）

---

## 四、Token 成本控制现状

### 4.1 现有优化手段

| 手段 | 效果 | ANA 能做什么 |
|------|------|------------|
| **语义缓存** | 省 60%（重复查询） | 互补 — 缓存命中时 ANA 也受益 |
| **智能路由** | 简单任务→便宜模型 | 互补 — 码本告诉路由层"这个调用有多复杂" |
| **Token 限流** | 按预算拒绝 | 互补 — ANA 降低每调用 token 消耗后，同预算可承受更多调用 |
| **Function call 格式优化** | **无人做** ← ANA 的空白 | **省 90% token（112→9/次）** |

### 4.2 成本精确到小数点

- WSO2 网关：token 成本计算到 **10 位小数**（USD）
- Envoy AI Gateway：按 `llm_total_token` 实施 **每小时/每天预算封顶**
- 成本分级路由：预算 >50%→GPT-4o，20-50%→GPT-4o-mini，<20%→拒绝

**中转站对 token 成本极度敏感。** 90% 的 function call token 节省会直接引起注意。

---

## 五、ANA 在中转站里的位置

### 5.1 不是替代中转站，是加一层编码

```
当前中转站（以 OpenAI 格式为例）:

  用户 Agent → JSON tool_call (112 tokens) → 中转站 → 上游 LLM
                            ↑
                    中转站要翻译成 OpenAI/Anthropic/Google 各自格式


ANA 改造后:

  用户 Agent → @s.o.t codon (9 tokens) → 中转站 → 码本查表 → 上游 LLM
                            ↑                              ↑
                    格式统一了                  不需要 parser，整数查表
```

### 5.2 具体节省

| 指标 | 当前（JSON tool_call） | ANA（@s.o.t codon） | 节省 |
|------|----------------------|---------------------|------|
| Function call token（LLM 输出）| 62 | 6 | **91%** |
| Response token（LLM 读）| 50 | 3 | **94%** |
| 往返总 token | 112 | 9 | **92%** |
| 中转站解析 | `json.loads()` + dict 遍历 | regex + 整数查表 | **3-4x CPU** |
| 格式翻译 | 需要（每个模型方向一套） | **不需要** | **零翻译代码** |

### 5.3 为什么中转站会愿意试

1. **直接省钱**：token 节省 = 上游成本节省 = 利润。不需要说服终端用户。
2. **格式统一**：不用再写 OpenAI↔Anthropic↔Google 的翻译适配器。一个 codebook 通吃。
3. **零模型改动**：`@1.1.0 Beijing 7` 就是纯文本。任何模型都能输出。
4. **渐进部署**：可以先在 1-2 个 function 试点，验证省钱效果后再铺开。

---

## 六、真实门槛（诚实评估）

| 门槛 | 细节 |
|------|------|
| **码本维护** | 下游 API 每增/改一个端点，码本要同步更新。和 API 文档是同一份信息，格式不同。 |
| **system prompt 调优** | 要让 LLM 稳定输出 @s.o.t 格式，需要一个好的 system prompt。实测 Claude 95%+ 遵守率。 |
| **容错** | LLM 偶尔输出格式错误 → 重试或 fallback JSON。需要中转站侧做错误处理。 |
| **码本分发** | 终端用户怎么知道 @1.1.0 是 get_forecast？需要 GET /v1/codebook 端点发布码本。已有。 |
| **安全** | 中转站作为码本权威，需要在码本端点加认证。防止未授权访问。 |

---

## 七、下一步（按优先级）

| 优先级 | 行动 | 工作量 |
|--------|------|--------|
| P0 | 找一个真实中转站对接，试点 1-2 个 function | 1-2 天 |
| P1 | 优化 system prompt（提高遵守率到 99%+） | 1 天 |
| P1 | 加容错处理（格式错误→重试/fallback） | 半天 |
| P2 | 码本端点加 API key 认证 | 1 天 |
| P2 | 生产加固（gunicorn + Prometheus） | 2-3 天 |
