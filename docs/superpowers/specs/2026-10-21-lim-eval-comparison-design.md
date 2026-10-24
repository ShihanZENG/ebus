# LIM Evaluation Lab 固定版本对比设计

## 意图

补齐 LIM-FR-017 中当前缺少的 Compare Versions / Regression Report。本地实现复用已经持久化的 Golden Dataset Eval 结果，允许评测人员对比同一数据集上的两个固定 Agent 版本，查看逐例差异，并生成可审计的门槛报告。

## 范围

- 仅比较已有且已完成的 Eval Run，不在对比请求中重新执行 Agent 或 Tool。
- 两个 Eval Run 必须使用相同 Dataset ID/版本、相同 DEV/STAGING 环境、相同 Agent ID，并且 Agent 版本不同。当前 EvalRun 没有 model、prompt、index 版本字段，因此报告不假称这些维度固定或比较。
- 只用现有可验证本地结果：PASS/FAIL/NOT_EVALUATED、固定验收断言、用例 risk tier、failure codes、记录的 elapsed_ms、已脱敏 actual_output。
- 逐例结果标注 REGRESSION（baseline PASS → candidate FAIL）、IMPROVED（FAIL → PASS）、UNCHANGED 或 UNCOMPARABLE（涉及 NOT_EVALUATED）。actual_output 差异递归展开为字段路径和值；从值比较中排除结果里仅用于定位运行的 run_id/trace_id。仍返回两侧 Run/Trace ID 作为安全导航引用。
- 总报告展示基线/候选 pass rate（分母只含已评分 PASS/FAIL）、增减、失败与未评测数、逐例退化/改善数、critical 用例失败增量和平均 elapsed_ms（仅描述性指标）。
- 使用报告内显式门槛，默认要求 pass rate 不下降、用例回归数不增加、critical 用例回归数不增加。允许调用者提交较宽或更严格的门槛值；它们只决定该离线报告的 PASS/FAIL，不阻止发布、不修改 Agent/数据集、不触发通知。
- 将比较输入、指标、门槛、每例分类和脱敏输出差异保存为不可变比较记录，附规范化 JSON SHA-256，读取时校验哈希。无更新/删除 API。
- Hash 输入为完整不可变报告 payload（不含 `report_hash`）；`created_at` 仅为数据库元数据，不纳入 payload/hash。JSON 使用 UTF-8、键排序和紧凑分隔符规范化。
- 任一侧结果为 `NOT_EVALUATED` 时，该用例标为 `UNCOMPARABLE`，不计入退化/改善或可评分差异；报告分别统计两侧未评测数。
- Console 增加基线与候选 Eval Run 选择、比较操作、门槛结果和逐例差异/Trace 入口；审计和只读权限复用现有 Eval 权限。

## 门槛

请求门槛：`max_pass_rate_drop`（0..1，默认 0）、`max_case_regressions`（0..200，默认 0）、`max_critical_case_regressions`（0..200，默认 0）。候选相对基线的 pass_rate 降幅不得超过设置值；逐例退化数和 critical 退化数不得超过各自设置值。没有可评分用例时报告为 NOT_EVALUATED，不得标为通过。pass_rate 未定义时 pass-rate 门槛不通过。

这些门槛是可解释的本地回归比较值，不是生产发布策略或已确认的业务质量目标。PRD 建议的 Recall@5、事实忠实度、语义质量、成本、协作质量和人工采纳效果，目前没有本地权威数据，明确不纳入报告。

## 安全与边界

- 创建比较及查看细节遵守现有 `lim:manage` / `assistant:read` 和评测 Run actor 可见性。非管理员只能比较自己可见的两条 Eval Run。
- 报告不复制 Dataset 输入、scope、ground truth 或敏感原始数据；仅引用 Dataset 版本和 case ID，差异取自已脱敏实际输出。
- 版本结果只反映确定性本地 handler 与现有断言。页面明确标注“本地确定性回归报告，不代表真实模型效果或生产发布门禁”。
- 新增 migration `0037`；验证使用隔离 SQLite，禁止升级共享开发库。

## 接口草案

- `GET /api/v1/lim/evals/runs`：分页读取调用者可见的已保存 Eval Run，支持数据集/Agent 筛选。
- `POST /api/v1/lim/evals/comparisons`：固定两条 Eval Run 与门槛，生成并持久化比较报告。
- `GET /api/v1/lim/evals/comparisons`：分页读取调用者可见的历史报告。
- `GET /api/v1/lim/evals/comparisons/{comparison_id}`：读取单份报告并返回完整性校验结果。

## 验收

- 两侧数据集版本或环境不同、Agent ID 不同、版本相同、Run 未完成或任一用例结果不完整时拒绝比较。
- 同一冻结 Dataset 下相同用例进行固定版本比较；PASS→FAIL 计退化，FAIL→PASS 计改善，NOT_EVALUATED 不混入 pass-rate 分母。
- 临界用例退化数、pass-rate 降幅和总回归数按显式门槛计算；空可评分集不能通过。
- JSON 差异排除 run_id/trace_id，展示的数据来自脱敏结果；保存报告后再次读取完全一致且 hash 校验有效。
- 用户不能读取其他调用者报告/运行；只读角色不能创建比较；API 没有修改已保存报告的入口。
- Console 展示版本/数据集、门槛判定、指标、逐例差异和 Trace 跳转，并明确离线本地范围。
- LIM 聚焦回归、隔离 `0037` 往返迁移、Alembic 检查和前端构建通过。
