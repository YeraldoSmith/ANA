# ANA 链协议规范 v0.3.0（草案）

## 摘要

ANA 链是一种 AI 原生的紧凑调用层，用预共享码本（codebook）支持的二进制"密码子"（codon）表示 API 操作。它能减少 Agent ↔ API 重复调用的格式开销，但不压缩任意响应数据，也不替代传输层安全。

---

## 术语表

| 术语 | 英文 | 定义 |
|------|------|------|
| 密码子 | Codon | 一个二进制标识符（3 字节头 + 动态参数），映射到一个 API 操作 |
| 反密码子 | Anticodon | 接收方的反向查找过程：将密码子字节还原为操作描述 |
| 码本 | Codebook | 定义了密码子到操作映射关系的查找表，从种子确定性生成 |
| 子链 | Sub-chain | 从 master_seed 派生的一段独立映射空间，每 1000 包轮换 |
| 会话随机数 | Session nonce | 每次会话生成的 32 字节随机数，用于派生唯一的会话码本 |
| 噪声密码子 | Noise codon | 值为 `[0x00, 0x00, 0x00]` 的占位密码子，用于混淆流量模式 |
| 主种子 | Master seed | 从码本种子 + 会话随机数经 HKDF 派生的 64 字节会话密钥材料 |

---

## 1. 设计目标

| 目标 | 机制 |
|------|------|
| 消除 JSON 序列化开销 | 二进制密码子直接映射到 API 操作 |
| 降低 LLM Token 消耗 | 紧凑密码子文本可减少重复的工具调用语法 |
| 安全部署 | 通过 TLS/QUIC 提供认证和保密；码本不透明性不是加密 |
| 优雅降级 | 码本不匹配时自动回退到 JSON-RPC 2.0 模式 |
| 与现有协议分层协作 | 工作在 MCP、A2A 下层；与 TLS 互补 |

---

## 2. 码本

### 2.1 层级结构

```
Service（服务，uint8，0~255）
└── Operation（操作，uint8，0~255）
    └── ParameterTemplate（参数模板，uint8，0~255）
        ├── 固定参数（编译期已知）
        └── 通配槽位（运行时值，varint 编码）
```

每个码本支持 256³ = **16,777,216** 种操作签名。

### 2.2 定义格式（YAML）

```yaml
codebook_id: "weather-v1"
version: 1
codebook_seed: "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0"

services:
  - id: 1
    name: "weather"
    operations:
      - id: 1
        name: "get_forecast"
        templates:
          - id: 0
            description: "按城市查询，公制单位"
            params: [city, days]
            types: [string, uint8]
            defaults: {days: 7}
          - id: 1
            description: "按坐标查询，英制单位"
            params: [lat, lon, days]
            types: [float32, float32, uint8]
            defaults: {days: 3}
```

### 2.3 码本生成

码本通过 HKDF + ChaCha20 从种子确定性生成：

```
codebook_seed = random(32 bytes)         # 每个码本版本一个种子
master_seed   = HKDF(salt=codebook_seed, ikm=session_nonce, info="ANA-v1")
subchain[n]   = HKDF(salt=master_seed, ikm=uint32_be(n), info="ANA-v1-sub")
```

关键性质：
- **码本无需存储或传输** — 双方持有种子即可按需生成
- **每个会话派生唯一映射** — 相同基础种子 + 不同会话随机数 = 不同码本
- **子链轮换限制暴露面** — 每 1000 包自动切换子链

### 2.4 关于"位置跳跃"的说明

> **原始设计中**的"位置跳跃"（P_{i+1} = (P_i + H(chain_id||i)) mod L）基于一个物理存在的全局链表（256^256 条链，每条长 64^64 单词）。
>
> **优化版中不再需要位置跳跃**，原因：码本已从"预存的物理总表"变为"种子实时生成"。密码子不再有"在链上的物理位置"——每个密码子 `[S, O, T]` 的映射由 `subchain_seed` 通过 ChaCha20 PRNG 动态生成。子链轮换（每 1000 包切换种子）替代了位置跳跃的安全功能：限制单段密钥的暴露面。
>
> 如果你需要原始的"位置跳跃"语义（用于不可预测的码本映射切换），可以缩短旋转间隔到更小的值（如 100 包），或在子链内对每个密码子应用 `derive_scramble(seed, S, O, T)` 进行单独随机化。参考实现中已包含 `derive_scramble` 函数。

### 2.5 版本管理

```
CodebookVersion:
  codebook_id:  string      # "weather-v1"
  version:      uint16      # 单调递增 0~65535
  seed_hash:    bytes[32]   # codebook_seed 的 SHA-256
  capabilities: uint32      # 能力位掩码
  content_hash: bytes[32]   # 规范化码本定义的 SHA-256
```

`content_hash` 对规范化后的 UTF-8 JSON 计算 SHA-256：对象键按字典序排序、
不包含无意义空白，包含 `codebook_id`、`version`、`seed_hash`、
`capabilities` 与 `services`；服务、操作和模板均按数字 ID 排序；哈希字段本身
不参与计算。声明了 `content_hash` 的码本若校验不匹配，接收方必须拒绝。

---

## 3. 数据包格式

### 3.1 v0.3 调用封包（已实现的草案 profile）

`@service.operation.template` 是给 LLM 使用的文本表示，不是传输格式。
v0.3 的二进制调用契约可装载在 CODON 包、MCP 消息、HTTP body 或 QUIC stream 中：

```
偏移   大小  字段
----   ----  ----
0      4     魔数：ASCII "ANA3"
4      1     封包版本：1
5      1     Flags（bit 0 = fire-and-forget；其余保留且必须为 0）
6      32    码本 content_hash
38     16    request_id（重试时保持不变）
54     4     deadline_ms（uint32；0 表示未设置协议级截止时间）
58     2     codon_length（uint16，大端）
60     N     恰好一个编码后的密码子
```

接收方必须拒绝未知版本、长度错误、尾随字节或码本哈希不一致的封包。协议仅提供
至少一次投递；需要恰好一次业务效果的 API 必须将 `request_id` 作为幂等键。

### 3.2 通用包头（12 字节）

```
（无 AEAD 模式 — v0.2.0 及更早版本）
偏移   大小   字段
----   ----   ----
0      2      魔数: 0xA7A7
2      1      协议版本 (0x02)
3      1      标志位
              bit 0-2: 包类型 (0-7)
              bit 3:   含噪声密码子
              bit 4:   分片标记
              bit 5:   ACK 标记（CODON 确认包）
              bit 6:   加密模式 (0=明文, 1=AEAD)
              bit 7:   保留
4      2      流 ID (uint16, 大端)
6      4      序列号 (uint32, 大端)
10     2      载荷长度 (uint16, 大端)
12     16     AEAD 认证标签 (Poly1305, 仅加密模式)
28     N      载荷（加密模式下为 ChaCha20 密文）
28+N   2      CRC-16 校验和（非加密模式）/ 无（加密模式，Poly1305 替代）
```

**协议版本升至 0x02**（v0.3.0）。

- 明文模式（bit 6 = 0）：同 v0.2.0，CRC-16 + 可选 HMAC
- 加密模式（bit 6 = 1）：Poly1305 认证标签替代 CRC-16 + HMAC

协议头总开销：**12 字节**（非加密）/ **28 字节**（AEAD 加密，含 16 字节 auth tag）。

### 3.3 包类型

| 类型值 | 名称 | 方向 | 说明 |
|--------|------|------|------|
| 0x00 | HELLO | Agent→API | 安全握手：AID + ephemeral key + 码本列表 |
| 0x01 | HELLO_ACK | API→Agent | 握手响应：AID + ephemeral key + 选定码本 |
| 0x02 | CONFIRM | Agent→API | 确认会话建立（含 HMAC 密钥确认） |
| 0x03 | CODON | 双向 | 数据传输：一个或多个密码子（AEAD 加密） |
| 0x04 | ROTATE | 双向 | 触发子链轮换 |
| 0x05 | ROTATE_ACK | 双向 | 确认轮换 |
| 0x06 | ERROR | 双向 | 报告错误 |
| 0x07 | FALLBACK | 双向 | 切换到 JSON/文本模式 |
| 0x08 | RESUME | Agent→API | PSK 会话恢复（0-RTT） |
| 0x09 | RESUME_ACK | API→Agent | PSK 恢复确认 |
| 0x0A | REKEY | 双向 | 主动密钥更新 |

> **v0.3.0 变更**：NEGOTIATE → HELLO，NEGOTIATE_ACK → HELLO_ACK，NEGOTIATE_CONFIRM → CONFIRM。新增 RESUME / RESUME_ACK / REKEY。

### 3.4 密码子编码

载荷格式：

```
[chain_index: uint16]    # 发送方当前子链索引（用于同步校验）
[codon_count: uint8]     # 有效密码子数量
[noise_count:  uint8]    # 噪声密码子数量（紧随有效密码子之后）
[codons:       codon[]]  # 有效密码子，连续排列
[noise:        codon[]]  # 噪声密码子，接收方丢弃
```

每个密码子的内部格式：

```
字节 0:    服务 ID (uint8)
字节 1:    操作 ID (uint8)，bit 7 = 响应标记
字节 2:    模板 ID (uint8)
字节 3+:   动态参数值（无符号 LEB128 varint 编码）
```

**控制密码子**（服务 ID = 0xFF）：

| 编码 | 名称 | 说明 |
|------|------|------|
| `[0xFF, 0x04, 0x00]` | PING | 心跳探测，接收方应回复 PONG |
| `[0xFF, 0x05, 0x00]` | PONG | 心跳响应 |
| `[0xFF, 0x02, 0x00]` | TEARDOWN | 优雅关闭会话 |

**CODON ACK 包**（CODON 类型 + ACK 标志位 = 1）：

```
[chain_index: uint16]    # ACK 发送方的子链索引
[ack_sequence: uint32]   # 被确认的 CODON 包的序列号
```

### 3.4 噪声密码子机制

> 噪声注入用于抵抗流量分析。攻击者无法区分真实密码子和噪声密码子，
> 从而无法通过包大小或频次推断通信模式。

**格式**: 噪声密码子 = `[0x00, 0x00, 0x00]`（NOOP）

**生成规则**:
- 噪声比例默认 **10%**（每 10 个真实密码子插入 1 个噪声）
- 噪声密码子随机散布在真实密码子之间（非固定位置）
- 在 CODON 包载荷中，`noise_count` 字段声明噪声密码子数量
- 真实密码子和噪声密码子在载荷中交替排列，接收方根据 count 分离

**识别与丢弃规则**:
- 接收方检查每个密码子的前 3 字节
- `[0x00, 0x00, 0x00]` → 噪声，立即丢弃
- 任何非零密码子 → 执行反密码子查表
- 查表失败（未知密码子） → 记录错误，丢弃该包

**性能影响**（实测数据）:
- 10% 噪声比增加约 21% 字节开销
- 解码额外耗时约 0.3 µs/次（可忽略）

### 3.5 数据分片

> 当一个操作调用过大，无法放入单个数据包时，使用分片传输。

**分片机制**:
- 标志位 bit 4（IS_FRAGMENTED）置 1 表示还有后续分片
- 同一个 `stream_id` + 连续 `sequence` 号标识同一次调用的分片
- 最后一个分片 IS_FRAGMENTED = 0
- 每个分片独立经 CRC-16 校验

**重组规则**:
- 接收方按 `(stream_id, sequence)` 收集分片
- 当收到 IS_FRAGMENTED = 0 的分片时，该调用完成
- 所有分片接收完毕后，拼接 payload 再统一解码
- 超时未收齐 → 发送 ERROR (TRANSPORT_ERROR)，丢弃该调用的所有分片

### 3.7 HMAC 消息认证（可选，v0.2.0+）

当会话协商了 `CAP_HMAC` 能力时，每个数据包在 CRC-16 之后追加 HMAC-SHA256 标签：

```
（无 HMAC）[header][payload][CRC16][padding]
（有 HMAC）[header][payload][CRC16][HMAC16][padding]
                               ↑ 检错    ↑ 防篡改
```

- HMAC key = `derive_hmac_key(master_seed, chain_index)`，32 字节
- 覆盖范围：header + payload + CRC-16（整包签名）
- 标签截断到 16 字节（128 位）
- 验证使用 `hmac.compare_digest()` 常量时间比较
- HMAC 标签在填充之前写入，不被填充吸收；但在标准尺寸（64/128/256...）下，16 字节 HMAC 通常和 2 字节 CRC 一起被填充吸收

### 3.8 填充

数据包填充到最近的标准尺寸：64、128、256、512 或 1024 字节。填充字节为随机数（同时充当抗流量分析的噪声）。填充在 CRC-16 和 HMAC（如有）**之后**追加，因此不改变 payload_len。

---

## 4. 协议流程

### 4.1 阶段 1：安全握手（ANA-S，未来 profile）

ANA-S 是未来的实验性 profile。在使用经过独立审查的 Noise 实现、完成静态身份密钥绑定前，部署必须使用 TLS 或 QUIC/TLS 提供保密性和对端认证。码本保密、HMAC 与当前原型握手均不能替代 TLS。

**设计原则**：
- 信任根：Agent Identity（AID），32 字节唯一标识 + Ed25519 公钥
- 点对点信任：类似 SSH known_hosts，无 CA 层级
- 每个 Agent 拥有长期 AID，会话间可恢复

**AID 信任建立**（带外）：
1. **预注册**：Agent 开发者在 API 平台注册 AID（提供公钥）
2. **邀请码**：临时链接包含 AID + 公钥，通过任意信道交换
3. **DHT/注册表**：AID 发布到分布式注册表，查询获取公钥（v0.4+ 计划）

**初始握手** — 1-RTT（基于 Noise_IK 模式）：

```
Agent A (发起方)                        Agent B (响应方)
  |                                       |
  |── HELLO ────────────────────────────>|
  |   aid_id_A:     32 bytes            |  （A 的身份）
  |   eph_pk_A:     32 bytes (X25519)   |  （A 的临时公钥）
  |   nonce_A:      16 bytes            |
  |   codebook_ids: ["weather-v1",...]  |  （支持的码本列表）
  |   signature_A:  64 bytes (Ed25519)  |  （A 对上述字段的签名）
  |                                       |
  |                   B 做以下计算：        |
  |                   shared = X25519(sk_B, eph_pk_A)  ← ECDH (静态-临时)
  |                   session_seed = HKDF(shared,       |
  |                     nonce_A || nonce_B)            |
  |                   验证 A 的 Ed25519 签名             |
  |                   选择共同码本                        |
  |                                       |
  |<── HELLO_ACK ───────────────────────|
  |   aid_id_B:     32 bytes            |
  |   eph_pk_B:     32 bytes (X25519)   |  （B 的临时公钥）
  |   nonce_B:      16 bytes            |
  |   codebook_id:  "weather-v1"        |
  |   codebook_ver: uint16 (3)          |
  |   session_conf: 超时/包大小/轮换间隔  |
  |   signature_B:  64 bytes (Ed25519)  |
  |                                       |
  |   A 做以下计算：                        |
  |   shared = X25519(eph_sk_A, eph_pk_B) ← 第二次 ECDH (临时-临时)
  |   shared_total = HKDF(shared_A_B, shared_A_ephemeral)
  |   session_seed = HKDF(shared_total, nonce_A || nonce_B)
  |   验证 B 的 Ed25519 签名                   |
  |                                       |
  |── CONFIRM ──────────────────────────>|
  |   HMAC(session_seed, "ANA-S-confirm") |
  |                                       |
  |══ 安全通道已建立 ═══════════════════|
```

**关键安全属性**：
- **前向保密**：每次握手使用新的 X25519 ephemeral key pair。即使长期 AID 私钥在未来泄露，历史 session_seed 不受影响——因为 session_seed 混合了 ephemeral shared secret
- **身份绑定**：Ed25519 签名证明"发起方确实拥有 aid_id_A 的私钥"
- **密钥确认**：CONFIRM 包证明双方已计算出相同的 session_seed

**会话恢复（PSK 0-RTT）**：

对于频繁通信的 Agent，缓存上次的 session_seed：

```
Agent A                                Agent B
  |── RESUME ─────────────────────────>|
  |   psk_id: hash(session_seed_prev)  |
  |   eph_pk_A:    32 bytes (X25519)   |
  |   nonce_A:     16 bytes            |
  |   0-RTT 加密数据 (AEAD)             |
  |   signature_A: 64 bytes            |
  |                                     |
  |<── RESUME_ACK ─────────────────────|
  |   nonce_B:     16 bytes            |
  |   signature_B: 64 bytes            |
  |                                     |
  |══ 新安全通道已建立 ═══════════════|
```

- A 在第一个包就发送加密数据（0-RTT），使用缓存的 session_seed 派生临时 AEAD key
- B 用 PSK 解密 0-RTT 数据，生成新的 session_seed
- **前向保密保持**：新 session 使用 ephemeral key，旧 session_seed 泄露不影响新会话

**超时与重试**：
- HELLO 发送后 5 秒内未收到 HELLO_ACK → 重发（最多 3 次）
- HELLO_ACK 发送后 5 秒内未收到 CONFIRM → 关闭连接
- 3 次重试全部失败 → 切换到 FALLBACK 模式（JSON-RPC 2.0）

**版本兼容性与会话过期**：同 v0.2.0。

### 4.2 阶段 2：数据传输（AEAD 加密）

```
Agent                                API
  |                                   |
  |── CODON [seq=1] ────────────────>|
  |   密码子: S=1,O=1,T=0,           |
  |     city="Beijing", days=7       |
  |                                   |
  |<── CODON [seq=1] ────────────────|
  |   密码子: S=128,O=1,T=0,         |
  |     (响应: temp=28, humidity=65) |
```

**Agent 端步骤**:
1. 将 tool call 编码为密码子：`[S, O, T] + encode_params(params, types)`
2. 按噪声比例混入噪声密码子
3. 构建 CODON 包（含序列号、流 ID）
4. 序列化为链路字节（含填充）
5. 通过 UDP（或 TCP）发送

**API 端步骤**:
1. 接收数据包 → CRC-16 校验
2. 提取密码子列表 → 过滤噪声（`[0x00,0x00,0x00]`）
3. 对每个真实密码子执行反密码子查表：
   - `service = codebook.services[S]`
   - `operation = service.operations[O & 0x7F]`
   - `template = operation.templates[T]`
   - `params = decode_params(codon[3:], template.types)`
4. 执行操作，将结果编码为响应密码子（操作 ID 高位 = 1）
5. 发送响应 CODON 包（相同 stream_id，相同 sequence）

### 4.3 阶段 3：子链轮换

每 N 包（默认 **1000**）自动触发：

```
Agent                                API
  |── CODON [seq=1000] ─────────────>|
  |                                   |
  |── ROTATE ───────────────────────>|
  |   new_chain_index: 1             |
  |   (后续所有密码子使用            |
  |    subchain[1] 映射)             |
  |                                   |
  |<── ROTATE_ACK ───────────────────|
  |   ack_chain_index: 1             |
  |                                   |
  |══ 现在使用 SUBCHAIN[1] ═════════|
```

**ROTATE_ACK 丢失处理**:
- 发送方发送 ROTATE 后启动 5 秒定时器
- 未收到 ROTATE_ACK → 重发 ROTATE（最多 3 次）
- 3 次后仍未收到 → 发送 ERROR (TRANSPORT_ERROR)，回退到上一个子链
- 接收方收到重复的 ROTATE（chain_index 已切换）→ 再次发送 ROTATE_ACK

**子链索引溢出**:
- chain_index 为 uint32，最大 4,294,967,295
- 如果达到最大值：发送 ROTATE 到 chain_index = 0，开始循环
- 更安全的做法：在达到 UINT32_MAX 前重新协商会话（产生新的 master_seed）

### 4.4 降级流程

```
Agent                                API
  |── CODON [seq=N] ────────────────>|
  |<── ERROR ────────────────────────|
  |   code: CODON_UNKNOWN (0x1001)   |
  |                                   |
  |── FALLBACK ─────────────────────>|
  |   reason: "codebook mismatch"    |
  |                                   |
  |══ 切换到 JSON-RPC 2.0 模式 ═════|
  |══ （后续可重新协商恢复密码子模式）|
```

### 4.5 可靠性层

> ANA 使用 UDP 传输数据，但 UDP 本身不保证送达。可靠性层在上层提供
> ACK 确认、超时重传、心跳检测和子链同步校验。

**CODON ACK 机制**：
- 每个 CODON 包收到后，接收方必须发送 CODON ACK（带 IS_ACK 标志位）
- ACK 包含被确认包的序列号 `ack_sequence`
- 发送方维护待确认队列 `ACKTracker`，默认超时 1.0 秒
- 超时未确认 → 自动重传（默认最多 3 次）
- 3 次重传仍未确认 → 上报 `TimeoutEvent`，应用层决定如何处理

**心跳检测（PING/PONG）**：
- 空闲 30 秒无数据 → 自动发送 PING 控制密码子 (`[0xFF, 0x04, 0x00]`)
- 接收方收到 PING → 回复 PONG (`[0xFF, 0x05, 0x00]`)
- 90 秒内未收到任何包（数据/PING/PONG）→ 判定对端不可达 → `PeerDeadEvent`
- 任何有效包的到达都刷新心跳计时器

**子链同步校验**：
- 每个 CODON 包携带发送方当前 `chain_index`（payload 首 2 字节）
- 接收方收到后比对 `chain_index` 与本地值
- 不匹配 → 上报 `ChainMismatchEvent` → 应用层可触发重新同步
- 这防止了 ROTATE 包丢失导致的"双方各自使用不同子链"静默故障

**重传与 ACK 状态机**：
```
发送方                   接收方
  |                        |
  |── CODON [seq=5] ─────>|  收到，发送 ACK
  |   (加入待确认队列)     |── CODON+ACK [ack=5] ──>|
  |                        |
  |<── CODON+ACK ──────   |  收到 ACK，移出队列 ✓
  |
  |── CODON [seq=6] ─────>|  ⚡ 丢包
  |   (1.0s 后超时)        |
  |── CODON [seq=6] ─────>|  收到，发送 ACK ✓
  |   (重传 #1)
```

---

## 5. 安全模型

### 5.1 威胁模型（完整版）

| 威胁 | 严重性 | 防御 | 残余风险 |
|------|--------|------|---------|
| **被动窃听**（无码本） | 中 | 密码子为不透明随机字节 | 元数据（IP、包时序）仍然可见 |
| **被动窃听**（有旧码本） | 高 | 子链轮换限制窗口为 1000 包 | 攻击者拥有码本时可解码当前子链内的所有包 |
| **已知明文攻击** | 高 | 子链轮换 + 每会话独立随机数 | 攻击者若知道操作名且拥有码本，可反推该位置的映射。单会话内影响有限（最多 1000 包），跨会话无效 |
| **重放攻击** | 中 | 序列号滑动窗口（拒绝 seq < last_seen - 100） | 窗口内重放仍可能成功（最多 100 次机会） |
| **数据包注入** | 高 | CRC-16 + 反密码子校验 | ⚠️ CRC-16 是**检错码**而非 MAC——攻击者可篡改载荷并重新计算 CRC。**ANA 不单独提供完整性保护** |
| **流量分析** | 低 | 固定尺寸填充 + 噪声密码子 | 时序侧信道仍可能泄露信息（v0.2 计划恒定速率模式） |
| **时序侧信道** | 低 | —（当前版本未处理） | 查表操作的耗时差异可能泄露码本索引。缓解：常量时间查表（v0.2 计划） |
| **拒绝服务** | 高 | 速率限制 + 噪声密码子快速过滤 | 攻击者发送大量无效密码子，服务器需做查表。缓解：O(1) 布隆过滤器预筛 |

### 5.2 双重校验：CRC-16 + HMAC-SHA256

> **v0.2.0 起，ANA 提供可选的消息认证码（HMAC-SHA256），与 CRC-16 组成双重校验。**

| 校验层 | 类型 | 大小 | 作用 |
|--------|------|------|------|
| CRC-16 | 检错码 | 2 字节 | 检测随机比特错误（无线噪声、存储损坏） |
| HMAC-SHA256 | 消息认证码 | 16 字节（截断） | 检测主动篡改攻击 |

**CRC-16 保留的理由**：在噪声环境（无线、长距离链路）中，随机比特翻转比主动攻击更常见。CRC-16 以极低成本（2 字节 + 0.05 µs）过滤 99.997% 的随机错误。

**HMAC 的工作原理**：
- 密钥从 `master_seed` 经由 HKDF 派生：`derive_hmac_key(master_seed, chain_index)`
- 覆盖范围：`header + payload + CRC-16`（整包签名）
- 截断到 16 字节（128 位），抵抗 2^128 次伪造尝试
- 每次子链轮换自动切换 HMAC key
- 通过 `CAP_HMAC` 能力标志协商启用

**性能**：HMAC 计算 +0.9 µs，校验 +0.9 µs。16 字节标签被 64B 固定填充吸收。硬件加速 SHA-256 在 Apple Silicon 上 ~0.9 µs/次。

**主动攻击者现在需要**：
1. 拥有码本（否则密码子为随机字节）
2. 拥有 HMAC key（否则无法伪造认证标签）
3. 或破坏 TLS 层（如果部署了 TLS）

### 5.3 DoS 防护 — 布隆过滤器

> **v0.2.0 新增布隆过滤器预筛，在反密码子查表之前 O(1) 淘汰无效密码子。**

**攻击场景**：攻击者发送大量随机 CODON 包，每个包都需要反密码子查表才能判定无效。查表是 O(log N) 操作（字典查找），10K 无效包/秒可耗尽服务端 CPU。

**布隆过滤器预筛**：
- 大小：1 KB（8192 位），7 个哈希函数
- 对于 1000 个有效密码子前缀，误报率 < 1%
- 已知有效的前缀 → 命中 → 进入正常查表（+0.57 µs）
- 未知的前缀 → 99.9% 概率未命中 → 直接拒绝（-1.5 µs 的查表时间）
- 对 DoS 攻击节省 62% CPU

**注意事项**：
- 布隆过滤器有 1% 误报率（将无效密码子误判为有效），会在后续反密码子查表中被准确拒绝
- 控制密码子 (PING/PONG/TEARDOWN) 和噪声密码子 [0x00,0x00,0x00] 不加入过滤器
- 过滤器在加载码本时构建，支持动态增删

### 5.4 ANA-S：自有安全层（v0.3.0）

> **ANA-S 仍是未来的实验性安全 profile。**
> 在完成独立审查与固定身份绑定前，TLS/QUIC-TLS 是生产部署的必需安全层。

#### 5.4.1 设计动机

TLS 的安全模型（X.509 证书 + CA 层级）是为"浏览器-服务器"通信设计的，与 Agent 场景存在结构性矛盾：

| TLS 假设 | Agent 现实 |
|----------|-----------|
| 有域名和 CA 签发的证书 | Agent 用 UUID/AID 标识，无域名 |
| CA 信任链可验证 | Agent 之间只有点对点信任 |
| 证书有效期 1 年 | Agent 会话可能仅持续 5 秒 |
| 人类点击"信任此证书" | Agent 通信完全自动化 |
| 非对称加密（ECDHE）在服务器上运行 | Agent 可能在 IoT/边缘设备上运行 |

#### 5.4.2 密码学原语

| 原语 | 算法 | 用途 |
|------|------|------|
| 密钥交换 | **X25519** (ECDH over Curve25519) | 安全协商 shared secret |
| 身份签名 | **Ed25519** | 签名握手包，绑定身份 |
| 链路加密 | **ChaCha20-Poly1305** (AEAD) | 加密载荷 + 完整性认证标签 |
| 密钥派生 | **HKDF-SHA256** | 从 shared secret 派生 session_seed、AEAD key、子链密钥 |
| 哈希 | **BLAKE2b** | 快速哈希（AID 指纹、PSK ID） |

**为什么 ChaCha20-Poly1305 优先于 AES-GCM？**
- 纯软件实现速度与 AES-GCM 相当
- 不需要 AES-NI 硬件加速（IoT/边缘友好）
- 天然抵抗缓存时序侧信道攻击
- RFC 8439 标准化，WireGuard / TLS 1.3 均已支持

#### 5.4.3 密钥层级

```
AID 长期密钥对 (长期, 离线存储)
  ├── X25519 静态私钥 (sk_A): 用于接收 HELLO 时计算 ECDH
  └── Ed25519 签名私钥: 用于签名握手包

握手后：
  X25519(eph_sk_A, eph_pk_B) → shared_secret_1  ← 临时-临时 ECDH
  X25519(sk_A, eph_pk_B)     → shared_secret_2  ← 静态-临时 ECDH
  session_seed = HKDF(shared_secret_1 || shared_secret_2,
                      nonce_A || nonce_B)
  ↓
  K₀ = HKDF(session_seed, "ANA-v1-K0")        ← 每 1000 包轮换
  ↓
  AEAD_key_j = HKDF(Kᵢ, j, "ANA-v1-AEAD")    ← 每包一个密钥
```

#### 5.4.4 安全保证

| 安全属性 | 机制 | 强度 |
|----------|------|------|
| **载荷机密性** | ChaCha20-Poly1305 AEAD 加密 | 256 位 |
| **消息完整性** | Poly1305 认证标签（16 字节） | 128 位 |
| **身份认证** | Ed25519 签名（A 和 B 双向验证） | 128 位 |
| **前向保密** | X25519 ephemeral key，每次握手新生成 | 每会话 |
| **密钥前向保密** | 链式 HKDF 派生，Kᵢ 泄露不影响 Kᵢ₊₁ | 每 1000 包 |
| **抗重放** | 序列号 + 滑动窗口（±100） | 100 包窗口 |
| **抗 MITM** | Ed25519 绑定身份 + 双向签名 | 计算安全 |
| **抗流量分析** | 固定填充 + 噪声密码子 + AEAD 加密 | 有限 |

#### 5.4.5 量子威胁评估

| 原语 | 量子威胁 | 攻击算法 |
|------|---------|---------|
| X25519 ECDH | ⚠️ **完全破解** | Shor 算法（多项式时间） |
| Ed25519 签名 | ⚠️ **完全破解** | Shor 算法（多项式时间） |
| ChaCha20-Poly1305 | ✅ 安全（2^128） | Grover 算法 |
| HKDF-SHA256 | ✅ 安全（2^128） | Grover 算法 |

> **v0.3.0 不与抗量子密码学（PQC）竞争。** 如果需要抗量子保护，v0.4+ 计划支持 CRYSTALS-Kyber（密钥交换）+ CRYSTALS-Dilithium（签名）作为可选的 PQC 原语。

#### 5.4.6 与 TLS 1.3 对比

| 维度 | TLS 1.3 | ANA-S v0.3.0 |
|------|---------|-------------|
| 信任模型 | CA 层级（X.509） | 点对点（AID + 公钥） |
| 初始握手 | 1-RTT (~1-5ms) | 1-RTT (~0.3ms) |
| PSK 恢复 | 0-RTT | 0-RTT |
| 加密原语 | AES-GCM / ChaCha20-Poly1305 | ChaCha20-Poly1305 |
| 密钥交换 | ECDHE (X25519) | X25519 ephemeral-static + ephemeral-ephemeral |
| 签名 | ECDSA / Ed25519 / RSA | Ed25519 |
| 前向保密 | ✅ (ECDHE ephemeral) | ✅ (ephemeral X25519) |
| 握手包大小 | ~200-400 字节 | ~288 字节 |
| 证书管理 | 需要 CA、域名、证书 | 仅需 AID + 公钥，预共享 |
| 生产验证 | 10 年 | 尚未 |

#### 5.4.7 包格式变更（AEAD 加密模式）

当 ANA-S 激活时，数据包格式更新为：

```
[header: 12B] [auth_tag: 16B] [encrypted_payload: N bytes] [padding]
                  ↑ Poly1305                 ↑ ChaCha20 加密
```

- `payload_len` 指向加密后的载荷长度
- `auth_tag` 覆盖 `header + encrypted_payload`
- 接收方先验证 auth_tag，再解密 payload，再解码密码子
- CRC-16 和 HMAC 在 AEAD 模式下被 Poly1305 认证标签替代（AEAD 同时提供完整性和加密）

#### 5.4.8 降级模式

- 如果一方不支持 ANA-S（旧版 Agent/API），回退到 v0.2.0 的协商模式
- 旧版仍可依赖外部 TLS（如需要）
- 新版 Agent 在发现 API 不支持 ANA-S 时，自动回退到 v0.2.0 协商

---

## 6. 性能特征

### 6.1 编码格式对比

| 对比维度 | JSON | Protobuf | ANA Codon |
|----------|------|----------|-----------|
| 序列化开销 | 高（字段名重复） | 中（field number） | 极低（3 字节头） |
| 人类可读 | ✅ 是 | ❌ 否 | ❌ 否 |
| 需要 Schema | ❌ 否 | ✅ .proto 文件 | ✅ 码本 |
| 解析速度 | 慢（字符串解析） | 中 | 极快（整数查表） |
| Token 友好 | ❌ 每字段名都是 token | ❌ 二进制 | ✅ 语义 token |
| 典型消息尺寸 | 200-500 B | 50-150 B | 8-30 B |

### 6.2 基准测试结果（实测数据）

| 指标 | JSON/HTTP | ANA Chain | 提升 |
|------|-----------|-----------|------|
| **端到端延迟** | 250.6 ms | 38.0 ms | **6.6x** |
| LLM 生成时间 | 243.9 ms | 59.0 ms | **4.1x** |
| 编码吞吐量 | 638K ops/s | 1,653K ops/s | **2.6x** |
| Token 消耗/调用 | 19.5 | 4.7 | **76%** 减少 |
| 链路带宽/调用 | 274 B | 64 B | **77%** 减少 |
| 协议开销 | ~195 B | 14 B | **14x** 更小 |

### 6.3 密码子尺寸 vs JSON

| 操作 | JSON (字节) | 密码子 (字节) | 缩减 |
|------|------------|-------------|------|
| `get_weather(city="Beijing")` | ~200 | 4 | 50x |
| `db_query(sql="SELECT...")` | ~500 | 6 | 83x |
| `read_file(path="/a/b/c")` | ~150 | 5 | 30x |
| `noop_response()` | ~50 | 3 | 17x |

### 6.4 Token 成本估算

LLM 每次 function call 节省 ~50–200 token（输出）+ ~100–250 token（上下文窗口）。以典型定价（~$3/百万输入，~$15/百万输出），1000 次调用/天可节省 ~$3.30/天。

---

## 7. 错误码

| 错误码 | 名称 | 说明 |
|--------|------|------|
| 0x1001 | CODON_UNKNOWN | 密码子在当前码本中未找到 |
| 0x1002 | CODON_INVALID | 密码子格式无效 |
| 0x2001 | CODEBOOK_MISMATCH | 双方无共同码本版本 |
| 0x3001 | SESSION_EXPIRED | 会话超时 |
| 0x3002 | SEQUENCE_INVALID | 序列号超出窗口（可能为重放） |
| 0x3003 | SUBCHAIN_MISMATCH | 子链索引不匹配（ROTATE 可能丢失） |
| 0x3004 | AUTH_FAILED | Ed25519 签名验证失败 |
| 0x3005 | AID_UNKNOWN | 对端 AID 不在信任列表中 |
| 0x4001 | TRANSPORT_ERROR | 传输层错误（分片超时等） |
| 0x4002 | PEER_UNREACHABLE | 对端不可达（心跳超时） |
| 0x4003 | AEAD_ERROR | AEAD 解密/认证失败（密钥不匹配或数据损坏） |

---

## 8. 扩展点

### 8.1 服务 ID 0xFF — 控制信道

保留用于协议级控制操作：
- `[0xFF, 0x01, *]` — 心跳/Ping
- `[0xFF, 0x02, *]` — 会话关闭
- `[0xFF, 0x03, *]` — 能力重新协商

### 8.2 模板 ID 0xFF — 动态参数

指示完全动态参数（无预定义模板）。

**注意**：v0.1 暂不支持动态参数的二进制 schema 描述符。当前版本要求所有参数类型在码本的模板定义中预先声明。如果运行时需要动态参数，建议：
- 回退到 JSON-RPC 模式（使用 FALLBACK 包）
- 或在 v0.2 中实现紧凑二进制 schema 描述符

### 8.3 v0.2.0 已完成 ✅

- ✅ **HMAC-SHA256 消息认证** — 可选能力 (CAP_HMAC)，密钥跟随子链轮换
- ✅ **布隆过滤器预筛** — 1KB / O(1) 淘汰无效密码子，抗 DoS

### 8.4 v0.3+ 计划特性

- **常量时间查表** — 抵抗时序侧信道
- **恒定速率模式** — 以固定间隔发送，彻底掩盖活动模式
- **多跳路由** — 通过中间 Agent 转发密码子
- **流式密码子** — 长运行操作的增量结果传输
- **权限绑定码本** — 只读/限定范围的码本子集
- **码本注册中心** — 分布式的 codebook 版本发现与分发
- **多语言 SDK** — Rust / Go / TypeScript 实现

---

## 9. 与现有协议的关系

```
┌─────────────────────────────────────┐
│         AI Agent（LLM）             │
├─────────────────────────────────────┤
│   MCP / A2A（工具发现 & 编排）       │
├─────────────────────────────────────┤
│   ★ ANA Chain（编码层）             │  ← 本协议
├─────────────────────────────────────┤
│   TLS（传输安全）— 生产环境必须      │
├─────────────────────────────────────┤
│   TCP / UDP                        │
└─────────────────────────────────────┘
```

ANA 不替代 MCP、A2A 或 TLS——它在它们下层，提供 AI 原生的编码格式。现有 Agent 框架只需在工具调用时切换到 ANA 编码器，其余层不变。

---

## 10. 参考实现

- **语言**: Python 3.13+
- **版本**: v0.3.0
- **路径**: `ana-chain/ana/`（核心库）、`ana-chain/examples/`（演示）、`ana-chain/benchmarks/`（基准测试）
- **测试**: 91 项单元测试全部通过（覆盖 HKDF RFC5869 向量、ChaCha20 PRNG、varint 编解码、包序列化、噪声过滤、防重放、子链轮换、会话生命周期、HMAC 防篡改、布隆过滤器误报率）
- **依赖**: PyYAML（码本定义文件解析）

关键模块：
```
ana/
├── codebook.py    # 码本模型 + HKDF + ChaCha20 PRNG + HMAC 密钥派生
├── codon.py       # 密码子编解码 + LEB128 varint + 控制密码子 (PING/PONG)
├── packet.py      # 数据包格式 + CRC-16 + HMAC-SHA256 + 能力标志
├── session.py     # 会话状态机 + 防重放 + HMAC 密钥管理
├── negotiator.py  # TCP 协商握手
├── transport.py   # UDP 传输 + 噪声注入
├── reliability.py # ACK/重传/心跳/子链同步 + 布隆过滤器 DoS 防护
├── security.py    # ANA-S: X25519 + Ed25519 + ChaCha20-Poly1305 AEAD（v0.3.0 新增）
└── fallback.py    # JSON-RPC 2.0 降级通道
```

---

## 变更日志

```
## v0.3.0 (2026-08-04) — ANA-S 自有安全层
- ANA-S 安全层：摆脱 TLS，自带安全握手
- X25519 ECDH 密钥交换 + Ed25519 签名 + ChaCha20-Poly1305 AEAD
- Agent Identity (AID) 信任模型（点对点，无 CA）
- 1-RTT 初始握手（Noise_IK 模式）
- 0-RTT PSK 会话恢复
- 前向保密（ephemeral X25519）
- 链式 HKDF 密钥层级（session_seed → Kᵢ → AEAD_keyⱼ）
- 包格式更新：+AEAD auth tag (16B)，加密模式 bit 6
- 包类型更新：NEGOTIATE→HELLO，+RESUME/RESUME_ACK/REKEY
- 协议版本升至 0x02
- 新增错误码：AUTH_FAILED、AID_UNKNOWN、AEAD_ERROR

## v0.2.0 (2026-08-04)
- HMAC-SHA256 消息认证（可选能力 CAP_HMAC）
- 布隆过滤器 DoS 预筛（1KB, <1% 误报率）
- CRC-16 + HMAC 双重校验架构
- CODON ACK + 超时重传 + PING/PONG 心跳 + 子链同步
- 测试从 62 → 91 项

## v0.1.0 (2026-08-03)
- 初始草案：核心线路格式、协商流程、码本层级结构
- 噪声密码子、数据分片、安全威胁模型
- 术语表、超时重试、参考实现
```

---

*规范版本: v0.3.0 | 日期: 2026-08-04*
