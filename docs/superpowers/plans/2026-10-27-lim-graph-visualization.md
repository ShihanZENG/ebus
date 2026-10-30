# LIM 证据关系图可视化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/api/v1/lim/v2/live/runs/{run_id}/graph` 从 JSON 文本转储变成可读、可交互的证据关系图，节点标签可读、实体间关系来自 ERP 真实外键，并严格守住「这不是 Temporal GraphRAG」的诚实边界。

**Architecture:** 后端在既有 `graph_snapshot()` 上做三件事——标签解析（UUID → `code · name`）、实体归一（`sku_id` 并入 `sku_code`）、实体间关系推导（8 类真实外键）；响应只增字段不删字段，以兼容 `export_graph` 与既有测试。前端把纯转换逻辑抽到 `src/components/graphView.ts`（可 `node --test` 单测），渲染交给 `src/components/GraphCanvas.tsx` 的 SVG，零新增运行时依赖。

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, React 18, TypeScript, Vite 6, Ant Design 5, node:test.

**Spec:** `docs/superpowers/specs/2026-10-27-lim-graph-visualization-design.md`

## Global Constraints

- `LIM-FR-014 Temporal GraphRAG` 在台账中保持 `未实现`。本计划交付的是**证据关系可视化**，不是时态知识图谱。
- 页面与文档禁止把该图表述为「图谱引擎」「知识图谱已实现」「多跳查询」。措辞用「证据关系图」。
- 禁止把 `backend/app/lim_graphrag.py` 的 6 个种子节点（示例数据）接入真实运行视图。
- 禁止为了让标签好看而扩大查询范围。标签与关系解析严格限定在 `authorized_run` 的店铺/仓库/SKU 作用域内。
- 禁止静默截断。超出上限必须返回 `truncated=true` 与 `truncated_kinds`，UI 必须显示。
- v1 不新增任何运行时 npm 依赖。
- `entities` / `claims` / `edges` 的现有字段只增不删，`lim_live_connections.export_graph` 依赖其结构。
- 响应必须继续携带 `backend: 'erp_database'`、`retrieval`、`time_basis` 与 `limitations`，UI 原样展示。
- 观察时间版本 ≠ 业务有效期。任何 UI 文案不得暗示后者。

## Review Focus

- 标签解析是否引入了范围外数据泄露（越权读取他店/他仓实体名称）。
- 关系边两端是否都存在于返回的 `entities` 中，`query` 过滤后是否仍然成立。
- `sku_id` 归并后，claims 的 `ref_id` 与 `content_hash` 是否未被改动（证据可追溯性）。
- `graph_snapshot()` 两次调用是否仍完全相等（既有测试 `test_lim_live.py:143`）。
- 空范围运行是否显示明确空状态而非空白画布或报错。
- 前端布局是否为纯函数且确定性（同输入同坐标），不引入随机力导。

---

### Task 1: 后端标签解析与实体归一

**Files:** `backend/app/lim_live_views.py`, `backend/app/lim_graph_labels.py`（新建）, `backend/tests/test_lim_graph_view.py`（新建）

**Interfaces:** 新模块 `resolve_entities(db, subjects) -> list[dict]`，输出带 `label`/`label_resolved`/`canonical_id`/`aliases` 的实体；`graph_snapshot()` 改用它产出 `entities`。既有 `id`/`type`/`value` 字段语义不变。

- [ ] 写测试：`sku_id` 节点不再出现，其值进入对应 `sku_code` 节点的 `aliases`，entities 数量相应减少。
- [ ] 写测试：各类型实体标签解析为 `code · name`（shop/warehouse/product/supplier/sku）；`purchase_order_id` 解析为 `po_no`；`campaign_id` 保留原值并附 `campaign_name`。
- [ ] 写测试：查不到行的实体 `label_resolved=false`，`label` 回退为截断的原始 ID。
- [ ] 写测试：`graph_snapshot()` 连续两次调用结果相等。
- [ ] 写测试：claims 的 `ref_id`/`content_hash` 在归并前后保持不变。
- [ ] 实现 `resolve_entities()`：先收集 subject 中出现的全部 ID，按类型批量查表，避免逐条查询。
- [ ] 改 `graph_snapshot()`：调用 `resolve_entities()`，合并 `sku_id`→`sku_code`。
- [ ] 运行新测试与 `backend/tests/test_lim_live.py`、`test_lim_five_pillars_integration.py`，确认无回归。

### Task 2: 后端实体间关系推导

**Files:** `backend/app/lim_graph_labels.py`, `backend/app/lim_live_views.py`, `backend/tests/test_lim_graph_view.py`

**Interfaces:** `resolve_relations(db, live, entity_index) -> list[dict]`，每条含 `source`/`target`/`relation`/`relation_label`/`derived_from`/`basis`。响应新增 `relations`、`stats`、`truncated`、`truncated_kinds`。

- [ ] 写测试：8 类关系各至少一条断言，端点值与数据库外键查询结果一致。
- [ ] 写测试：范围外 SKU/仓库不产生关系边，也不进入 entities。
- [ ] 写测试：每条关系边两端都存在于 entities；`query` 过滤后仍成立。
- [ ] 写测试：`purchase_order` 关系只跟随证据中已出现的 `purchase_order_id`，不按 SKU 反查全量采购单。
- [ ] 写测试：超出上限时 `truncated=true` 且 `truncated_kinds` 非空，entities 数量等于上限。
- [ ] 实现 `resolve_relations()`：按 `has_sku` / `supplies` / `ordered_in` / `po_from_supplier` / `po_to_warehouse` / `stocked_at` / `advertised_in` / `campaign_in_shop` 逐类查询，全部限定运行作用域。
- [ ] 在 `graph_snapshot()` 中挂载 `relations` 与 `stats`，实现上限截断与 `truncated` 标记。
- [ ] 运行后端全量测试。

### Task 3: 前端纯逻辑层与单测

**Files:** `frontend/src/components/graphView.ts`（新建）, `frontend/tests/graphView.test.mjs`（新建）

**Interfaces:** `buildGraphView(payload, options) -> { nodes, edges, relations, legend, stats, notices, truncated }`。纯函数，无 React 依赖，无 DOM 依赖。

- [ ] 写测试：按 `canonical_id` 归并节点，`aliases` 合并到同一节点。
- [ ] 写测试：标签缺失时输出「未解析」标记，回退为原始 ID。
- [ ] 写测试：实体类型 → 中文名与颜色映射完整（7 类）。
- [ ] 写测试：claim 按领域分组（product/inventory/procurement/ads/finance）。
- [ ] 写测试：关系边两端不在节点集合中被丢弃。
- [ ] 写测试：布局坐标确定性——同输入两次调用坐标完全相等；`entities` 为空时返回空视图不抛错。
- [ ] 写测试：1 跳邻接表只含实际相连节点。
- [ ] 实现 `buildGraphView()`：归并、标签回退、类型映射、领域分组、关系过滤、布局计算、邻接表。
- [ ] 实现证据视图布局（实体列按类型固定序、claim 列按领域序）与关系视图布局（径向，角度按 `(type,label)` 排序确定性分配）。
- [ ] 在 `frontend/package.json` 增加 `test:graph` 脚本。
- [ ] 运行 `node --test tests/graphView.test.mjs`（**Node ≥ 22.18**：实测 22.12.0 直接导入 `.ts` 会 `ERR_UNKNOWN_FILE_EXTENSION`，22.22.2 / 24.19.0 正常）。

### Task 4: SVG 渲染组件与页面接入

**Files:** `frontend/src/components/GraphCanvas.tsx`（新建）, `frontend/src/pages/LimLiveWorkbenchPage.tsx`, `frontend/src/pages/workspace.css`

**Interfaces:** `<GraphCanvas view={buildGraphView(...)} mode="evidence" | "relation" onSelect={...} />`。不引入任何 npm 依赖。

- [ ] 写组件骨架：SVG 容器 + 两列（证据视图）节点与贝塞尔边。
- [ ] 实现径向布局渲染（关系视图）：中心 SKU、一环、二环。
- [ ] 实现 hover tooltip：label、类型、值/单位、observed_at、content_hash 前 8 位。
- [ ] 实现点击聚焦：1 跳邻接高亮、其余降透明度；点击空白复位。
- [ ] 实现图例：节点类型配色 + 关系类型中文说明。
- [ ] 实现四种状态：加载、空（文案「当前范围没有业务证据」）、错误、截断提示。
- [ ] 实现明细面板：选中节点的 claim 行（claim_key、value、unit、observed_at、source、content_hash 前 8 位）。
- [ ] 页面接入：保留现有 query 输入框，新增视图切换，挂载 `GraphCanvas`，原始 JSON 收进可折叠「原始数据」区（不删除）。
- [ ] 页面顶部固定展示 `backend`、`retrieval`、`time_basis` 与 `limitations` 原文。
- [ ] 文案审查：全页无「知识图谱」「多跳」「引擎」等越界表述，无「业务有效期」。
- [ ] 运行 `tsc --noEmit && vite build` 与全部前端测试。

### Task 5: 端到端验证与台账更新

**Files:** `docs/lim/g0-capability-inventory.md`

**Interfaces:** 台账 LIM-FR-014 状态保持 `未实现`；G4 行追加一条事实性说明。

- [ ] 启动后端 `127.0.0.1:18080` 与前端 `127.0.0.1:15173`。
- [ ] 浏览器验证：运行 DEMO-SHOP + CN-DEMO + [TEACH-SUPPLY-001, BT-EARBUDS-BLK]，切到「图谱与证据」Tab，确认渲染出节点与连线而非 JSON 文本。
- [ ] 验证节点标签为可读名称，页面上无裸 UUID。
- [ ] 验证证据视图与关系视图均可用，聚焦交互正常，明细面板数字与 API 一致。
- [ ] 验证空范围运行（如 SKU-UK-DRESS-001）显示明确空状态。
- [ ] 验证 `limitations` 与 `backend: erp_database` 在页面可见。
- [ ] 验证无 console 报错、后端日志无 5xx。
- [ ] 更新台账 G4 行：注明可视化已实现且明确列出未实现项（无 valid-time、无多跳查询服务、Neo4j 未验证）；LIM-FR-014 状态保持 `未实现`。
- [ ] 提交前检查 `git diff` 与全量测试结果。
