# LIM Skill 治理生命周期设计

## 意图

实现 PRD LIM-FR-015 / G4 中可在当前 ERP 服务内独立交付的 Skill 治理登记基础：让技能内容从候选、审核、验证到激活有版本、来源证据、业务范围、负责人、验证时间和失效策略可查可审计。

## 目标

- 提供版本化 Skill Registry 和只允许显式状态迁移的审核生命周期：`CANDIDATE → UNDER_REVIEW → VERIFIED → ACTIVE`，另支持 `DEGRADED`、`FROZEN`、`REVOKED` 终态/回退治理状态。
- 保存 PRD 要求的来源事件、证据引用、业务范围、`last_verified_at`、信心校准摘要、使用/纠错计数、失效策略、owner 和版本。
- 创建者只能提交候选；`lim:manage` 管理员执行审核和迁移；每次改变写审计日志。
- 版本内容在进入审核后不可编辑；改动必须创建新版本；所有历史版本保留。
- 用现有 LIM Console 管理并查看版本、来源和生命周期状态。

## 非目标与安全边界

- 不自动学习、生成或激活 Skill，不把 Skill 内容拼进 Agent/Workflow 提示词，也不执行其中的指令。
- 不记录对话原文、用户身份敏感信息或业务原始行；Skill 内容只作受权限保护的治理数据。
- 不伪造使用/纠错/置信度指标；当前没有运行时引用链，计数保持 0，校准信息由审核人提供且记录证据。
- 不实现长期对话记忆写入/召回，也不宣称 FR-015 全量完成。
- 当前 SSO、租户隔离、生产密钥、留存期及多实例作业仍沿用 G0 的未核验状态。

## 数据与状态规则

- 候选仅保存受控元数据：definition 限定为已登记模板 ID 与能力标签；来源事件使用稳定引用 ID；证据仅含引用 ID、版本和 SHA-256，不保存正文/摘录；业务范围使用受控业务域与国家代码；校准仅含允许的方法、样本数、分数和可选数据集引用。未知字段、自由文本和任意嵌套参数均拒绝。显示名使用模板 ID。

- `LimSkill` 保存稳定 `skill_id`、显示名、owner 和创建时间。
- `LimSkillVersion` 以 `(skill_id, version)` 唯一；保存定义、memory level、来源事件、evidence refs、business scope、置信校准、verified time、usage/correction counters、expiry policy、状态、创建/审核人和时间。
- 状态迁移：`CANDIDATE → UNDER_REVIEW`; `UNDER_REVIEW → VERIFIED | CANDIDATE | REVOKED`; `VERIFIED → ACTIVE | REVOKED`; `ACTIVE → DEGRADED | FROZEN | REVOKED`; `DEGRADED → UNDER_REVIEW | FROZEN | REVOKED`; `FROZEN → UNDER_REVIEW | REVOKED`。`REVOKED` 不可恢复；内容更新创建新版本。
- 同一 Skill 同时最多一个 `ACTIVE` 版本。激活新版本与旧版本降级在同一事务内完成；不允许并发形成两个 active 版本。
- 进入 `VERIFIED` 必须有非空来源证据、业务范围和校准摘要；`last_verified_at` 由服务端在该迁移时写入，不接受候选提交者自行设置；激活还需通过失效策略校验，且不得已过期。
- 任意有效状态只可被 `lim:manage` 操作；非管理读取要求 `assistant:read` 且拥有 `lim:manage` 或是该 Skill owner。

## 接口与页面

- `GET/POST /api/v1/lim/skills`：分页查看；登记候选 Skill 版本。
- `PUT /api/v1/lim/skills/{skill_id}/versions/{version}`：owner 可在 `CANDIDATE` 阶段补充/修订受控元数据；候选编辑与状态迁移对同一版本加行锁并重读状态，审核开始后不可改写。
- `GET /api/v1/lim/skills/{skill_id}/versions`：查看版本历史和治理元数据。
- `POST /api/v1/lim/skills/{skill_id}/versions/{version}/transition`：提交目标状态和审核理由，服务端校验状态机、材料和权限。
- LIM Console 增加 Skills 治理页签：登记候选、查看详情、按状态迁移、显示 owner、来源、有效期和未满足的校验条件。
- 所有响应均声明 `runtime_enabled=false`；UI 明确技能不会被自动加载或执行。

## 验收

- 越权创建/读取/迁移拒绝；无 `assistant:read` 的读取拒绝。
- 非法迁移、版本修改、缺来源/范围/验证记录、过期激活均拒绝并返回稳定错误码。
- 同 Skill 仅一个 ACTIVE；再次激活新版本后旧版本不再 ACTIVE。
- 操作人、理由、前后状态进入审计；原始敏感值不得写入审计摘要。
- UI 展示治理状态和校验原因；不提供运行/提示注入入口。
- Alembic 升级/降级、模型约束、API 权限与生命周期测试通过；前端生产构建通过。
