# SciForge Zulip Deployment Notes

This repository is a SciForge working fork of Zulip Server.

Upstream reference:

- Zulip Server: https://github.com/zulip/zulip
- Initial analysis baseline in this workspace:
  `d2f48ffafdceb62d07933484dad5daba89810888`
- AGI4Sci publication baseline:
  `693c3347e477fc47863b616e38102c3cf3f59d22`
- The workspace was initially created from a shallow clone; local history has
  since been expanded. Re-record the final upstream baseline before release
  provenance, license evidence, or long-lived rebases.

SciForge-specific entry points:

- `PROJECT.md` tracks the SciForge Mobile on Zulip task board.
- `docs/sciforge-mobile-zulip-design.zh-CN.md` is the product/architecture
  design.
- `docs/sciforge-zulip-bridge-plan.zh-CN.md` explains the Bridge integration
  plan.
- `docs/sciforge-zulip-release-boundary.zh-CN.md` records license, NOTICE,
  branding, mobile push, and release evidence boundaries.
- `tools/sciforge_zulip_bridge/` contains the reference Bridge implementation.
- `tools/tests/test_sciforge_zulip_bridge.py` contains offline tests for the
  Bridge protocol.

Deployment starting points:

- Follow Zulip's production install documentation for the server:
  https://zulip.readthedocs.io/en/latest/production/install.html
- Create a Zulip bot for `SciForge Agent`.
- Configure a SciForge Bridge JSON file with realm URL, bot email, secret
  environment variable names, stream mapping, workspace root, and runtime URL.
- Keep Zulip core as the collaboration layer. SciForge Runtime, Model Router,
  workers, Evidence DAG, and model provider calls stay outside Zulip core.

Commercial release checklist:

- Keep Apache-2.0 `LICENSE`, `NOTICE`, and third-party license evidence.
- Rebrand server/web/mobile assets before distributing a SciForge-branded app.
- Treat mobile push as a separate service boundary; do not assume Zulip's
  hosted push service is a SciForge resale entitlement.
