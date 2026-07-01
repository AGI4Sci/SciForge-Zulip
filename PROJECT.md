# SciForge Mobile on Zulip 任务板

更新时间：2026-07-01

## 当前目标

在 Zulip 工作目录中推进 SciForge 手机端与科研协作层。实现方向以 `docs/sciforge-mobile-zulip-design.zh-CN.md` 为准：基于 Zulip 的 stream/topic、bot、event queue、REST API 和移动端能力，把 SciForge Agent 的自主科研、专家反馈、审批、证据链和周报同步接入科研项目群。

当前仓库最初来自 Zulip 上游 `main` 的浅克隆，主要用作 SciForge Mobile
Zulip 方案的调研、改造和实现工作区。发布到 AGI4Sci 时，使用
`zulip/zulip` 的 GitHub fork 关系保留上游引用，并把 SciForge 增量提交
应用到该 fork 的当前 `main` 基线上。

关键上下文：

- 设计文档：`docs/sciforge-mobile-zulip-design.zh-CN.md`
- SciForge 主仓：`/Applications/workspace/ailab/research/app/DeepSeek-GUI`
- 当前 Zulip 工作目录：`/Applications/workspace/ailab/research/app/zulip`
- 初始调研基线：`d2f48ffafdceb62d07933484dad5daba89810888`
- AGI4Sci 发布 fork 基线：
  `693c3347e477fc47863b616e38102c3cf3f59d22`
- 当前本地工作区已补全 Git 历史，`git rev-parse --is-shallow-repository`
  为 `false`

---

## 不可变原则

- 旧逻辑代码和最终目标冲突时，删除旧逻辑，直接实现新版本，不做兼容，保持代码干净。
- 所有修改必须通用，不能为特色例子写硬编码补丁。
- 相同功能的工作链路需要统一，不要额外生出旁路;删除冗余,代码尽可能精简
- 许可证优先。Zulip Apache-2.0 边界是选择它的核心原因；所有改造必须保留上游 license、copyright、NOTICE 和依赖许可证证据。
- 去品牌化。不能在 SciForge 商业分发中保留 Zulip 名称、logo、App bundle id、默认品牌图形或容易造成混淆的商标使用。
- 不把 Agent 过程刷进群。Zulip 只承载高信号节点：专家问题、审批请求、决策记录、artifact 卡片、Paper Radar 摘要和周报。
- 高风险动作默认 fail closed。删除/覆盖数据、外发成果、访问 restricted 数据、高预算计算、安装依赖、把未验证 claim 升级为结论，都必须审批。
- Research Ledger 必须 append-only。Zulip 消息删除或编辑不能抹掉科研事实，只能追加 redaction、edit 或 tombstone 事件。
- SciForge Runtime 和模型调用必须走 SciForge 现有边界：AgentRuntimeHost、Model Router、workers、Evidence DAG。不要在 Zulip 代码里直连上游 LLM provider。
- 尽量以 Bridge / 集成层实现，不要为了 SciForge 用例大面积 fork Zulip 核心语义。必须改 Zulip core 时，保持小切片、可测试、可回退。
- 遵守 Zulip 上游工程纪律。工作前阅读 `AGENTS.md`，改代码时运行针对性 lint/test，不要把无关格式化或大范围重构混进功能改动。

---

## 产品边界

第一版要证明的是：

- 科学家只用 Zulip Mobile/Web 就能进入项目 stream，与人类成员和 SciForge Agent 协作。
- `@SciForge Agent` 可以从 Zulip 触发 SciForge runtime 任务。
- Agent 在后台执行，必要时向科学家发问题卡或审批卡。
- 专家回复、reaction 或审批能回写 SciForge runtime，解除 Agent 阻塞。
- 周报从 ledger、Evidence DAG、Paper Radar 和 runtime thread summary 生成，先审阅后发布。

第一版不做：

- 通用微信替代品。
- 完整 SciForge 桌面移动化。
- 湿实验仪器、采购、云预算等高风险自动执行。
- Agent token 流、工具调用日志、调试信息的群内直播。

---

## 架构目标

```text
Zulip Mobile / Web
  -> Zulip Server
    -> Zulip Event Queue / REST API / Bot Webhook
      -> SciForge Zulip Bridge
        -> Noise Gate
        -> Policy Governor
        -> Research Ledger
        -> AgentRuntimeHost
          -> SciForge Runtime / Codex / Claude adapter
          -> Model Router
          -> Workers: Schedule, Paper Radar, Workflow, Remote Executor
        -> Evidence DAG
        -> Digest Generator
      -> Zulip REST API
        -> Agent question cards
        -> Approval cards
        -> Artifact cards
        -> Weekly digest
```

Zulip 负责协作、身份、stream/topic、移动端和通知。SciForge 负责科研执行、runtime、模型、证据链、调度和 artifact 管理。Bridge 负责两边的协议、权限、降噪和幂等。

---

## 当前状态

- [x] 克隆 Zulip 到 `/Applications/workspace/ailab/research/app/zulip`。
- [x] 将 SciForge Mobile Zulip 设计文档复制到 `docs/sciforge-mobile-zulip-design.zh-CN.md`。
- [x] 固定并记录初始上游基线、AGI4Sci 发布基线和完整历史状态。
- [x] 建立 SciForge-on-Zulip 的实现计划或 OpenSpec change。
- [x] 选择第一阶段路线：只做 Bridge + 官方 Zulip 客户端验证，商业发布前再 fork/去品牌化移动端。

本轮交付：

- `docs/sciforge-zulip-bridge-plan.zh-CN.md`：第一阶段 Bridge 路线、Zulip
  入口、权限映射、幂等、delivery、ledger、Runtime、卡片、周报和运维计划。
- `docs/sciforge-zulip-release-boundary.zh-CN.md`：上游基线、Apache-2.0 /
  NOTICE / 第三方依赖、去品牌化、移动推送和 release evidence 边界。
- `tools/sciforge_zulip_bridge/`：外部 Bridge 参考实现，覆盖配置脱敏、
  Zulip event/webhook 归一化、append-only SQLite ledger、Runtime HTTP
  协议、角色 fail-closed 策略、卡片协议、周报来源聚合和 CLI 运维入口。
- `tools/tests/test_sciforge_zulip_bridge.py`：离线单元测试，覆盖幂等、
  审批授权、反馈解除阻塞、卡片编辑、周报来源和 secret 脱敏。

## 首批任务拆分

### 1. 许可证和发布边界

- [x] 确认 Zulip server、Zulip mobile、关键依赖许可证和 NOTICE 分发义务。
- [x] 编写或更新 SciForge-on-Zulip release boundary 文档。
- [x] 列过去品牌化清单：名称、logo、bundle id、App icon、默认邮件/页面文案、帮助链接。
- [x] 决定是否需要完整 Git 历史；本地工作区已补全历史，商业发布/完整
  license evidence 前仍需重新记录最终发布基线。

### 2. Zulip 功能调研

- [x] 调研 Zulip event queue、bot、REST API、stream/topic、user group、reaction、message edit 的现有实现点。
- [x] 找到最小可行的 bot 收消息和发消息路径。
- [x] 找到 Zulip 权限模型中适合映射 PI/scientist/reviewer 的位置。
- [x] 找到自托管移动推送的配置和商业发布风险点。

### 3. Bridge 服务设计

- [x] 决定 Bridge 放置位置：第一阶段本仓保留参考实现，长期放到 SciForge 主仓 worker/package 或独立 package。
- [x] 定义配置：Zulip realm URL、bot email/token、stream mapping、workspace root、runtime id。
- [x] 定义幂等键：Zulip event id、message id、card action id、runtime turn id。
- [x] 定义失败重试和 delivery 状态。

### 4. Research Ledger

- [x] 选择第一版存储：SQLite、JSONL，或复用 SciForge runtime event store。
- [x] 实现 append-only event schema。
- [x] 记录 Zulip inbound/outbound、Agent turn、approval、feedback、artifact、digest 事件。
- [x] 增加 redaction/tombstone 事件，不做物理删除事实。

### 5. AgentRuntime 接入

- [x] Bridge 调用 SciForge `AgentRuntimeHost.startThread/startTurn/readThread`。
- [x] 支持 `steerTurn`、`resolveApproval`、`resolveUserInput`。
- [x] 为 Zulip 入口使用 `remote_guard` governance profile。
- [x] 将 Zulip message id、stream id、topic name 写入 runtime metadata。
- [x] 区分 Zulip 可见 display text 和给 runtime 的 hidden prompt。

### 6. Zulip 卡片协议

- [x] 定义问题卡：why、needed from、options、deadline、evidence refs。
- [x] 定义审批卡：action、risk、required role、approve/reject/request_changes/ask_evidence。
- [x] 定义 artifact 卡：kind、summary、hash/ref、sensitivity、review status。
- [x] 定义 weekly digest 卡：source refs、unverified 标记、review/publish 状态。
- [x] 支持编辑已有卡片，而不是重复发新消息。

### 7. 周报和 Evidence DAG

- [x] 从 Research Ledger 查询本周事件。
- [x] 从 Evidence DAG 查询 claim/status/source。
- [x] 从 Paper Radar 查询 digest。
- [x] 从 runtime threads 查询任务摘要。
- [x] 生成 draft，等待 PI 或 reviewer 确认后发布。

### 8. 管理 UI 和运维

- [x] 在 SciForge 桌面端添加 Zulip 配置入口，或先提供 CLI/config file。
- [x] 支持测试 bot 连接、测试发消息、查看 Bridge 健康状态。
- [x] 支持查看队列积压、最近失败、最近投递记录。
- [x] 增加 token/secret 脱敏日志。

---

## 建议第一轮执行顺序

1. 读 `docs/sciforge-mobile-zulip-design.zh-CN.md` 和本文件。
2. 读 Zulip `AGENTS.md`，遵守上游测试和代码风格要求。
3. 只读探索 Zulip event queue / bot / REST API / stream/topic 权限实现。
4. 在不改大面积 Zulip core 的前提下，提出 Bridge 的最小实现位置和接口。
5. 先做一个 smoke：从 Zulip 测试消息触发一个本地 Bridge handler，再把固定回复发回同 topic。
6. 再接 SciForge Runtime，最后接审批和周报。

---

## 验收标准

- 一个外部科学家只使用 Zulip Mobile/Web，就能看到项目 stream、Agent 问题、审批、成果和周报。
- `@SciForge Agent` 可以创建或复用 SciForge runtime thread。
- Agent 后台执行时不会把过程日志刷进群。
- 专家回复或 reaction 能解除 Agent 的 user input / approval 阻塞。
- 高风险动作无审批不能执行。
- 周报每条关键结论都能追溯到 Research Ledger 或 Evidence DAG。
- Bridge 重启、重复事件、网络重试不会重复创建任务或重复审批。
- 商业分发包不包含 Zulip 品牌，并保留 Apache-2.0 与依赖许可证证据。

---

## 测试指引

遵守 Zulip 上游 `AGENTS.md`。优先运行针对性测试，不默认跑完整大套件。

常用命令：

```sh
./tools/lint path/to/changed/files.py
./tools/test-backend zerver.tests.test_relevant_module
./tools/test-js-with-node
```

如果只改 Markdown 文档，说明未跑代码测试即可。涉及 Bridge、bot、REST、权限、审批和 ledger 的代码必须添加或更新测试。

---

## 未决问题

- [x] 第一版是否直接 fork Zulip Mobile，还是先使用官方 Zulip Mobile + SciForge bot/Bridge 验证工作流。
- [x] Bridge 应该放在 Zulip 仓库、SciForge 主仓，还是独立仓库。
- [x] Research Ledger 第一版使用 SQLite、JSONL，还是复用 SciForge runtime event store。
- [x] Zulip user group 到 SciForge 权限的最小映射是什么。
- [x] 自托管移动推送是否能满足商业发布，是否需要 SciForge 自建 APNs/FCM relay。
- [x] 外部合作者使用 Zulip guest/restricted user，还是接 SciForge 自己的 identity federation。

---

## 当前工作树提示

本文件和 `docs/sciforge-mobile-zulip-design.zh-CN.md` 是 SciForge 方案新增文件。当前仓库还可能存在上游以外的未跟踪 agent 辅助文件，例如 `.agents/` 和 `AGENTS.md`；不要在不了解用途时删除或覆盖它们。
