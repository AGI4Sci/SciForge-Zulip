# SciForge-on-Zulip 发布边界

更新时间：2026-07-01

本文记录 SciForge-on-Zulip 第一阶段的许可证、商标、移动端、推送和发布证据
边界。本文不是法律意见，只作为工程实施和后续法务尽调入口。

## 上游基线

- Zulip server 仓库：`https://github.com/zulip/zulip.git`
- 初始调研 commit: `d2f48ffafdceb62d07933484dad5daba89810888`
- AGI4Sci 发布 fork 基线:
  `693c3347e477fc47863b616e38102c3cf3f59d22`
- 当前工作区最初来自 shallow clone，后续已补全本地 Git 历史。
- 第一阶段只做 Bridge 参考实现、设计文档和针对性测试，不改 Zulip core。
- 正式 fork、商业发布、源码归档、完整 SBOM/license scan、移动端改包名、
  或需要严谨修改追踪前，必须重新记录最终 upstream provenance。

## 分发形态

| 形态 | 第一阶段结论 |
| --- | --- |
| Zulip server | 使用官方 server + 外部 SciForge Bridge，暂不改 core。 |
| Zulip Web | 用于验证科研协作流，不做商业去品牌化分发。 |
| Zulip Mobile | 第一阶段使用官方客户端验证；商业发布前单独 fork 和去品牌化。 |
| SciForge Bridge | 属于 SciForge 集成层，长期应在 SciForge 主仓 worker/package。 |
| SciForge Runtime | 继续通过 AgentRuntimeHost、Model Router、workers 和 Evidence DAG。 |
| 帮助中心/文档 | 商业分发前替换默认 Zulip 支持、下载、品牌和政策链接。 |

## 许可证义务

Zulip server 本仓主许可证是 Apache-2.0：

- `LICENSE`
- `NOTICE`
- `docs/contributing/licensing.md`
- `docs/THIRDPARTY`

分发义务：

- 随分发物提供 Apache-2.0 许可证副本。
- 保留上游 copyright、patent、trademark 和 attribution notices。
- 保留并展示上游 `NOTICE` 中要求的声明。
- 修改过的文件需要有显著修改说明。
- Apache-2.0 不授予 Zulip 商标、logo 或官方服务转售权。
- `docs/THIRDPARTY` 中列出的第三方材料和复制代码必须随发布证据保留。
- Python/JS 依赖锁在 `pyproject.toml`、`uv.lock`、`package.json`、
  `pnpm-lock.yaml` 中，但锁文件不等于完整 license matrix；商业发布前
  需要生成 SBOM 和第三方许可证报告。

移动端源码不在本仓。官方 Flutter 客户端 `zulip-flutter` 也是 Apache-2.0，
但移动分发还必须单独处理 Flutter/Dart packages、字体、emoji、KaTeX、
Pygments、Source Code Pro、Source Sans 3 等资产许可证，以及 App Store /
Play Store 元数据。

## 去品牌化清单

商业分发包不能保留 Zulip 名称、logo、App bundle id、默认品牌图形或容易
造成混淆的商标使用。

Server/Web 侧重点：

- 名称和页面文案：`templates/zerver/**`、`templates/zerver/emails/**`、
  `web/templates/about_zulip.hbs`、
  `web/templates/popovers/navbar/navbar_help_menu_popover.hbs`、
  `starlight_help/src/content/docs/**`。
- Logo、favicon、邮件图形和默认图像：`static/images/logo/*`、
  `static/images/favicon.*`、`web/images/zulip-logo.svg`、
  `web/images/logo/*`、`web/images/emails/logo.svg`、
  `static/images/emails/email_logo.png`、`web/templates/favicon.svg.hbs`、
  `web/images/zulip-emoji/zulip.png`。
- 默认通知音：`static/audio/notification_sounds/zulip.*`。
- 邮件模板：`templates/zerver/emails/account_registered.*`、
  `invitation.*`、`invitation_reminder.*`、`confirm_registration.*`、
  `missed_message.*`、`digest.*`、`notify_*`。
- 默认设置和服务链接：`zproject/default_settings.py`、
  `zproject/prod_settings_template.py`、`zproject/computed_settings.py`。
- 帮助、下载、支持链接：`starlight_help/src/components/Footer.astro`、
  `starlight_help/src/content/docs/mobile-app-install-guide.mdx`、
  `starlight_help/src/content/docs/mobile-notifications.mdx`、
  `web/templates/help_link_widget.hbs`、`zproject/urls.py` 中的 `/apps/`
  redirect。
- Corporate/marketing/policy：`templates/corporate/**`、`corporate/**`、
  `templates/corporate/policies/**`。如果 SciForge 分发物不包含 corporate
  站点，可在 release evidence 中记录排除。

移动端去品牌化在 `zulip-flutter` 仓单独完成：

- `pubspec.yaml` 的 name/description。
- Android `applicationId`、namespace、label、icon、URL scheme。
- iOS display name、bundle name、bundle id、URL scheme。
- Android `mipmap-*`、iOS `AppIcon.appiconset` 和启动图。
- App Store / Play Store 名称、截图、隐私政策、支持链接。

## 移动推送边界

Zulip 自托管移动推送通过 Zulip Mobile Push Notification Service 把服务器
生成的 E2EE push 转发到官方 iOS/Android App，再由 APNs/FCM 投递。该服务
受 Zulip Cloud ToS、Privacy、Rules、plan 和 usage metadata 约束。

SciForge 商业发布不能默认把 Zulip 官方 push service 当作可转售能力。

第一阶段：

- 内部验证可使用 Zulip 官方 self-hosted mobile push 配置。
- 高风险审批和专家问题可以验证 push 体验。
- release evidence 必须记录是否上传 usage statistics 和 basic metadata。

商业发布前：

- 确认 Zulip 官方条款允许目标分发方式，或
- 自建 SciForge APNs/FCM relay，并更新移动端 app bundle、证书和服务端配置。

## 发布证据清单

每个 SciForge-on-Zulip release 必须保存：

- Zulip server upstream commit、remote URL、是否 shallow/full history。
- Zulip mobile upstream repo/commit。
- SciForge Bridge commit/package version。
- 修改文件清单和修改说明。
- `LICENSE`、`NOTICE`、`docs/THIRDPARTY` 副本。
- Python、JS、Dart、移动资产的 SBOM/license scan。
- 去品牌化 checklist 结果和截图。
- 移动 push 服务选择、条款依据、APNs/FCM 证书边界。
- Bridge 配置模板，且只包含 secret env var 名，不包含 token 原文。
- Research Ledger schema 和 migration 记录。
- 针对性测试结果。

## 未决问题

- 第一版商业试点是否需要 fork `zulip-flutter`，还是继续使用官方客户端。
- Push service 是走 Zulip 官方 self-hosted service、SciForge 自建 relay，
  还是先限制为 Web/desktop 通知。
- Bridge 长期包位置：SciForge 主仓 worker、独立 package，还是部署模板仓。
- 完整 Git 历史拉取后是否需要重跑 license scan 并生成 SPDX/SBOM。
