# SciForge-on-Zulip Bridge 实施计划

更新时间：2026-07-01

本文把 `PROJECT.md` 和 `docs/sciforge-mobile-zulip-design.zh-CN.md`
中的任务拆成第一阶段可执行的 Bridge 实施方案。结论是：第一阶段先使用
官方 Zulip Web/Mobile 客户端加外部 Bridge 验证科研协作工作流；移动端
fork、去品牌化、bundle id、App icon、APNs/FCM relay 和商标清理在商业
分发前作为单独发布工程完成。

## 上游基线

- 初始调研 Zulip commit: `d2f48ffafdceb62d07933484dad5daba89810888`。
- AGI4Sci 发布 fork 基线:
  `693c3347e477fc47863b616e38102c3cf3f59d22`。
- 当前工作区最初来自 shallow clone，后续已补全本地 Git 历史。
- 当前阶段只做 Bridge 参考实现、文档和针对性单元测试，不改 Zulip core。
- 进入商业发布、源码归档、完整第三方许可证证据、移动端 fork 或大规模
  rebase 前，需要重新记录最终 upstream provenance。

## 第一阶段路线

第一阶段选择 Bridge + 官方 Zulip 客户端验证，不同时 fork 移动端。

理由：

- `SciForge Zulip Bridge` 可以通过 Zulip 官方 REST API 和 event queue
  完成收消息、发消息、reaction、message edit 和 topic 事件处理，不需要
  改 Zulip core。
- Zulip 的 stream/topic/user group 模型已经能承载项目、实验 topic、
  PI/scientist/reviewer 角色、审批组和 reviewer 组。
- SciForge Runtime、Model Router、Evidence DAG、Paper Radar 和 worker
  已经在 SciForge 主仓存在；Bridge 应调用这些边界，不在 Zulip 仓里直连
  LLM provider。
- 去品牌化和移动推送发布风险主要属于商业分发包，不应该阻塞第一阶段的
  科研工作流 smoke test。

## 放置位置

长期建议把 Bridge 放在 SciForge 主仓的 worker/package 层，或拆成独立
package，由 SciForge Runtime 的 release 流程打包。当前 Zulip 工作区中的
`tools/sciforge_zulip_bridge/` 是参考实现和协议测试层，用于固定接口、
幂等、ledger、卡片和 digest 语义。

不建议把 Bridge 放进 Zulip core：

- Bridge 业务语义属于 SciForge，不属于通用 Zulip。
- Zulip core 改动会扩大 rebase、测试、商标和分发风险。
- 外部 Bridge 可直接使用官方 API，与 Zulip Web/Mobile 客户端保持兼容。

## Zulip 入口

最小可行接收路径：

1. 用 bot 用户的 email/API key 创建 Zulip API client。
2. 使用 Python bindings 的 `call_on_each_event` 或
   `call_on_each_message` 做 smoke；生产化后可直接使用 `/register` +
   `/events` 控制 event_types、narrow、queue 生命周期和重试。
3. 只处理 project stream mapping 中的事件。
4. 对每个 Zulip event id 写入 idempotency key：
   `zulip:event:<event_id>`。
5. 对每条 inbound message 先追加 Research Ledger 事件，再路由到
   Runtime 或审批/反馈处理。

Zulip 发消息路径：

- `POST /messages` 发送 question、approval、artifact、weekly digest 和
  safety alert。
- 已有卡片更新使用 message edit，而不是重复发新消息。
- 所有 outbound 必须先追加 ledger，再调用 Zulip API；失败时写 delivery
  状态，由重试队列按 idempotency key 重试。

## 权限映射

| SciForge 角色 | Zulip 映射 |
| --- | --- |
| PI | realm owner/admin 或 `pi` user group |
| Scientist | realm member 或 `scientist` user group |
| Reviewer | `reviewer` user group |
| Student/RA | project stream member |
| External collaborator | guest/restricted user，仅订阅授权 streams/topics |
| SciForge Agent | Zulip bot user |

审批处理必须读取 user group membership 的快照并写入 ledger。无法确认角色、
reaction 来源、卡片 action id 或 runtime approval id 时按 fail closed
处理，只追加 rejected/needs_evidence/redaction/tombstone 等事实事件，不
删除旧事实。

## 配置

Bridge 配置只保存 token 的 env var 名，不保存 secret 原文：

```json
{
  "initial_upstream_zulip_commit": "d2f48ffafdceb62d07933484dad5daba89810888",
  "agi4sci_publication_baseline": "693c3347e477fc47863b616e38102c3cf3f59d22",
  "shallow_clone": false,
  "require_full_history_before_release": true,
  "ledger_path": ".sciforge/zulip-bridge/ledger.sqlite3",
  "bot": {
    "realm_url": "https://zulip.example.com",
    "bot_email": "sciforge-agent-bot@example.com",
    "bot_api_key_env": "SCIFORGE_ZULIP_BOT_API_KEY",
    "bot_user_id": 42
  },
  "runtime": {
    "base_url": "http://127.0.0.1:39100",
    "token_env": "SCIFORGE_RUNTIME_TOKEN",
    "default_governance_profile": "remote_guard"
  },
  "stream_mappings": [
    {
      "zulip_stream_id": 10,
      "zulip_stream_name": "protein-design",
      "project_id": "project-protein-design",
      "workspace_root": "/srv/sciforge/workspaces/protein-design",
      "runtime_id": "sciforge"
    }
  ]
}
```

## 幂等和 delivery 状态

幂等键：

- Zulip event: `zulip:event:<event_id>`
- Zulip message: `zulip:message:<message_id>`
- Card action: `zulip:card-action:<card_id>:<action>:<actor_user_id>`
- Runtime turn: `runtime:turn:<runtime_id>:<thread_id>:<turn_id>`
- Outbound card: `zulip:outbound:<card_type>:<card_id>:<version>`
- Weekly digest: `digest:<project_id>:<period_start>:<period_end>`

Delivery 状态：

- `pending`: ledger 已写，尚未发送或等待重试。
- `delivered`: Zulip API 返回 message id。
- `delivery_failed`: Zulip API 失败，保留错误摘要和下次重试时间。
- `superseded`: 该卡片版本被更高版本编辑替换。

Bridge 重启后只从 idempotency 和 delivery 表恢复状态，不从 Zulip 消息
删除或编辑历史中推断科研事实。

## Research Ledger

第一版选择 SQLite，原因是：

- append-only 表、唯一幂等键和 delivery 状态都能用单文件事务表达。
- 比 JSONL 更容易查询 weekly digest、最近失败和重试队列。
- 不依赖 Zulip 数据库，也不把 SciForge 事实写进 Zulip core。
- 后续可以迁移到 SciForge runtime event store；SQLite schema 是边界契约。

事件种类至少覆盖：

- `zulip_message_received`
- `zulip_message_edited`
- `zulip_reaction_received`
- `agent_turn_started`
- `agent_turn_completed`
- `approval_requested`
- `approval_resolved`
- `feedback_received`
- `artifact_created`
- `evidence_claim_created`
- `decision_recorded`
- `digest_generated`
- `digest_published`
- `redaction_recorded`
- `tombstone_recorded`

Ledger 没有物理删除事实事件的 API。Zulip message deletion/edit 只追加
redaction、edit 或 tombstone 事件。

## Runtime 接入

Bridge 调用 SciForge `AgentRuntimeHost` 边界：

- `startThread`
- `startTurn`
- `readThread`
- `steerTurn`
- `resolveApproval`
- `resolveUserInput`

所有 Zulip 入口 turn 使用 `remote_guard` governance profile，并在 metadata
中写入：

- Zulip realm URL
- stream id/name
- topic name
- message id
- event id
- sender user id
- project id
- idempotency key

显示给 Zulip 的 `display_text` 与给 runtime 的 `hidden_prompt` 分离。
Hidden prompt 只能包含路由、权限、provenance、Evidence DAG 和 ledger 引用，
不得原样回显到 Zulip。

## 卡片协议

所有卡片都包含：

- `card_type`
- `card_id`
- `version`
- `idempotency_key`
- source refs

问题卡字段：

- why
- needed from
- options
- deadline
- evidence refs

审批卡字段：

- action
- risk
- required role
- approve/reject/request_changes/ask_evidence

Artifact 卡字段：

- kind
- summary
- hash/ref
- sensitivity
- review status

Weekly digest 卡字段：

- period
- source refs
- unverified 标记
- review/publish 状态

## 周报

周报生成输入：

- Research Ledger 本周事件
- Evidence DAG claim/status/source
- Paper Radar digest
- Runtime thread summaries

周报 draft 必须先发 reviewer/PI 审阅 topic。未确认前不能发布到
`weekly-report`。每条关键结论必须带 ledger event id、evidence claim id、
paper id 或 runtime thread id；未验证内容必须显式标 `unverified`。

## 运维和管理

第一版提供 CLI/config file，不改 SciForge 桌面 UI。CLI 最小能力：

- 校验配置并输出脱敏配置。
- 初始化或检查 ledger。
- 测试 bot token 是否可用。
- 发送测试消息到指定 stream/topic。
- 查看 Bridge 健康状态。
- 查看队列积压、最近失败和最近 delivery 记录。

后续再把这些能力接入 SciForge 桌面端设置页。

## 预检风险

- 重复 Zulip event 会造成重复任务：用 event id/message id/card action id
  幂等键防止。
- 高风险动作被普通 reaction 误批准：审批必须校验 user group，无法确认时
  fail closed。
- Agent 过程刷屏：Noise Gate 默认只允许问题、审批、artifact、digest、
  safety alert 和决策记录进 Zulip。
- 隐藏上下文泄漏：display text 与 hidden prompt 分离，测试覆盖不回显。
- 商业发布保留 Zulip 品牌：发布边界文档中的去品牌化 checklist 在 fork
  移动端前必须全部完成。
- 移动 push 依赖官方服务：商业发布前确认条款或自建 APNs/FCM relay。
