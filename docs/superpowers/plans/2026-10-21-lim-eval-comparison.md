# LIM Evaluation Lab 固定版本比较实施计划

> 计划基于 `docs/superpowers/specs/2026-10-21-lim-eval-comparison-design.md`。

**目标：** 对同一数据集上的两个已完成固定 Agent 版本评测运行生成本地回归报告，持久化门槛与逐例脱敏差异，并在 Console 展示。

**架构：** 新增 `0037` 比较记录表和只读/创建 API；比较服务只消费已保存的 `LimEvalRun` 与 `LimEvalCaseResult`，不重新执行 Runtime。报告 JSON 规范化哈希用于读取校验。React Eval 页面提供 Run 选择、门槛输入及回归报告。

## 约束

- 不接入模型服务、不声称语义质量/真实模型效果、不创建生产发布门禁。
- 不修改企业/商城模块；不升级共享开发数据库。
- 报告仅使用脱敏输出及固定的 PASS/FAIL/NOT_EVALUATED 断言。

## 任务

### 1. 比较算法和持久化报告
- [x] 先写对比行为测试：退化/改善分类、未评测用例、门槛、脱敏 JSON 变化及数组内字段路径。
- [x] 新增 `LimEvalComparison` 模型与可回滚 migration `0037`。
- [x] 新增比较服务：校验输入运行相容性、结果完整性，计算本地指标与逐例差异，生成规范化 hash 并持久化。
- [x] 验证隔离 SQLite 报告读取与 hash。

### 2. API 和权限
- [x] 增加可见范围过滤的 Eval Run 分页列表。
- [x] 增加比较创建、列表、详情 API；遵守 actor 可见性，拒绝越权和不可兼容 Run。
- [x] 增加 API 回归：错误门槛、报告哈希篡改、只读写入口关闭及报告不可改写。

### 3. Console 与说明
- [x] Eval 页面加入 baseline/candidate Run 选择及可编辑本地门槛。
- [x] 展示比较摘要、门槛结果、逐例分类、脱敏字段变化和 Trace 入口。
- [x] 清楚标注本地确定性指标，不代表真实模型效果或生产发布门禁。
- [x] 更新 LIM FR-017 最新状态与 README。
- [x] 跑 LIM 聚焦测试、隔离迁移往返/Alembic check、前端构建和 `git diff --check`。
