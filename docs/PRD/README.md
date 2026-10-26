# PRD 与架构基线（v1.0 文档集）

本目录收存 CommerceOS 需求基线。**PRD 说明"要什么"，架构基线说明"怎么约束"**，两者需一起看。

| 文件 | 作用 | 规模 | 与代码的关系 |
|---|---|---|---|
| [00_总体说明与跨端矩阵.md](./00_总体说明与跨端矩阵.md) | 五系统三端关系、导航方案、跨端责任矩阵、四状态口径 | 78 行 | 定义了 B01–B31 / A01–A12 / P01–P07 / O01–O07 / S01–S06 与代码的对应 |
| [01_企业经营管理端_PRD.docx](./01_企业经营管理端_PRD.docx) | 企业端：页面 IA、BIZ-FR-001–024、关键页面详细设计、三条端到端流程 | 226 行（转 md 后） | §5.4 B-P13 的任务生命周期与 `lim_runtime.TRANSITIONS` 1:1 一致 |
| [02_AI平台管理端_PRD.docx](./02_AI平台管理端_PRD.docx) | AI 管理端：LIM Runtime、Agent/Tool、GraphRAG、Memory、Harness、Trace、评测与发布 | 200 行 | 对应 `backend/app/lim_*.py` 与 `LimConsolePage.tsx` |
| [03_消费者商城端_PRD.docx](./03_消费者商城端_PRD.docx) | 消费者端：品牌商城、SKU、购物袋、演示/真实结账边界、订单与售后 | 207 行 | 对应 `backend/app/storefront/` 与 `storefront/` 前端 |
| [LLM原生跨境电商ERP-需求文档-v0.3-系统与Agent架构更新.md](./LLM原生跨境电商ERP-需求文档-v0.3-系统与Agent架构更新.md) | 架构基线：3+2 系统、9 Agent、BusinessScope、统一 Run 结构、§7.1 状态机、§7.2 八条硬约束；文末附 v0.2/v0.1 归档 | 1629 行 | 核心依据，用于判断 PRD 条款在架构上是否站得住 |

## 已转换的可检索副本

`outputs/20261021-prd/` 下有三份 docx 转出的 markdown，便于全文检索与条款引用（原 docx 保持不动）：

- `01_企业经营管理端_PRD.md`
- `02_AI平台管理端_PRD.md`
- `03_消费者商城端_PRD.md`

重新生成：`python outputs/20261021-prd/extract_docx.py <docx 路径...>`

## 已知差异（2026-10-21 核对）

架构基线 §7.1 状态机与代码 `backend/app/lim_runtime.py::TRANSITIONS` 有 3 处不一致，验收标准需先定口径：

| 转换 | v0.3 §7.1 | 代码 |
|---|---|---|
| `VERIFYING → WAITING_INPUT`（证据不足/口径矛盾） | 有 | 无 |
| `RECONCILING → REVIEW_REQUIRED`（外部结果不明，人工接管） | 有 | 无（代码用 `WAITING_RECONCILIATION`） |
| `WAITING_INPUT → CANCELLED` | 无 | 有 |

企业端 PRD §5.4 的生命周期是代码的子集，故「PRD vs 代码」无冲突，「v0.3 vs 代码」差上述两条边。
