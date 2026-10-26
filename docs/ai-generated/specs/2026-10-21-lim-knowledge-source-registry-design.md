# LIM Knowledge Source Registry — G2 文档治理纵切

## 意图

为 LIM 已有的本地 Markdown 词面检索补上受控来源清单、不可变内容版本、审核激活、访问策略与可引用元数据。目标是让后续 AI/业务纵切能指出“依据哪个来源版本的哪段内容”，并让内容更新经过审核后才影响检索。

## 目标

- 只管理现有知识检索白名单：`docs/功能章节` 与 `docs/oms` 中的 Markdown 文件；来源路径由服务端扫描产生，客户端不能提交任意文件路径。
- 稳定 `source_id` 由规范化相对路径确定；版本由文件内容 SHA-256 确定。同一内容重复扫描不创建重复版本。
- 来源记录保存名称、路径、分类、摘要、访问策略和存在状态；来源版本保存内容哈希、有效时间、状态和审计责任人；文本分块在版本创建时持久化，旧版本内容不可变。
- 当前在白名单中的已审核文档首次登记为 active，保持现有助手检索行为。后续发现的新文档或变更文档建立 draft 版本；管理员显式激活后成为该来源唯一 active 版本，旧版本归档。
- `assistant:read` 用户只能检索 active、在有效期内且其角色具备来源所需全部权限的版本；管理员可管理来源并读取全部来源。
- 来源记录的元数据字段为 `display_name`、`category`、`summary`、`required_permissions`；名称从首个 H1 生成，缺少 H1 时取文件名；分类默认为 `general`，摘要默认为空，由管理员通过来源 PATCH 编辑。权限必须来自现有 `PERMISSIONS` 清单，角色授权取持久化 `Role.permissions`。
- 初次导入当前白名单文档时按兼容现状作为 active。之后扫描发现新增/变更内容建立 draft；摘要和分类可编辑，激活前须设置有效期或确认无到期时间。
- 文件从允许目录中消失时仅置来源 `is_present=false` 并在管理页标记；已存的 active 快照仍可检索，扫描不删除版本、不自动归档。管理员可归档整个来源以停止检索；文件重新出现时标记存在但不自动撤销既有归档。
- 词面检索继续使用确定性本地算法。每条结果包含稳定 `ref_id`、`source_id`、`source_version`、`content_hash`、分块 ID、文件路径、章节、行号及片段。
- 管理端可扫描、查看来源/版本、查看草稿差异摘要、激活/归档版本；关键操作记录现有审计日志。
- 将来源元数据暴露为只读 LIM API，后续业务纵切可用返回的稳定来源引用，不在此批增加业务证据模型或业务查询。

## 非目标

- 不接入向量数据库、Embedding、外部知识库、网络抓取或文档上传。
- 不修改补货、订单、商品或财务业务模块，不创建 Finding/Proposal/ExecutionReceipt 业务对象。
- 不宣称来源权限等价于数据库行级业务授权；实时业务事实仍由现有 ERP 工具按用户范围获取。
- 不支持 PDF、Office、图片 OCR、多租户 ACL、自动发布、自动摘要生成或来源生命周期通知。

## 约束与安全

- 扫描根目录固定为 `assistant_knowledge.py` 当前的两个目录；拒绝符号链接、路径穿越、非 `.md` 文件和超出仓库根目录的解析路径。
- 版本快照及分块建立后不可原地编辑；内容变更必须产生新 SHA-256 版本，且默认 draft。
- 对来源配置、扫描、激活、归档均写 `record_audit`。Trace/检索响应只引用分块元数据和已审核正文，不回显来源文件系统绝对路径。
- API 读取要求 `assistant:read`；扫描/激活/归档要求管理员或 `lim:manage`。新版本激活时要求来源的元数据校验通过，且仅有一个 active 版本。
- 有效期采用 UTC 时间。无 `valid_from` 表示立即有效，无 `valid_until` 表示不自动到期；查询时间必须满足左闭右开区间。
- 兼容当前助手 `search_knowledge(query)` 调用；检索仍限 top 5，空查询返回既有明确验证错误。

## API 与数据边界

- `POST /api/v1/lim/knowledge/sync`：扫描白名单；返回新来源、新版本、未变更项、拒绝项计数。不接受路径参数。
- `GET /api/v1/lim/knowledge/sources`：分页读取来源及当前 active 版本概要。
- `GET /api/v1/lim/knowledge/sources/{source_id}/versions`：读取版本及状态、哈希和生效时间，不返回绝对路径。
- `PATCH /api/v1/lim/knowledge/sources/{source_id}`：更新显示名、分类、摘要和所需权限；所有值写审计日志。
- `POST /api/v1/lim/knowledge/sources/{source_id}/versions/{version}/activate`：校验并原子切换 active 版本。
- `POST /api/v1/lim/knowledge/sources/{source_id}/versions/{version}/archive`：归档非 active 草稿或历史版本；active 版本须先激活另一个版本。
- `POST /api/v1/lim/knowledge/sources/{source_id}/archive`：归档来源并停止所有版本检索，保留其版本和分块供审计。
- Search tool 返回 `items[]` 中的稳定引用字段以及 `retrieval='lexical'`；不为业务层改写引用 ID。

## 数据模型

- `LimKnowledgeSource`: stable source ID、规范化相对路径、显示名、分类、摘要、所需权限、是否存在、是否归档、创建人和时间；路径唯一。
- `LimKnowledgeSourceVersion`: `(source_id, version)` 唯一键，SHA-256 内容哈希、有效期、草稿/active/archived 状态、审核/创建人和时间。
- `LimKnowledgeChunk`: `(source_id, version, chunk_id)` 唯一键、章节、起止行、不可变文本、文本哈希；外键指向版本并级联删除只允许在测试/降级时使用。

## 调用流程

1. 管理员触发无参数扫描；服务端遍历两个固定根目录，校验路径，读取 Markdown，计算 SHA-256 并按现有分块规则生成 chunk。
2. 新来源的当前仓库版本作为首次受审导入 active；已有来源内容未变则不写数据库；内容变更或新文件成为 draft，旧 active 继续可搜。
3. 管理员查看草稿来源/哈希/块数及差异摘要，确认后激活；事务内归档旧 active 并激活所选版本。
4. 助手检索仅读取来源未归档、版本 active 且有效、权限匹配的持久化 chunks；排序沿用当前 BM25 式词面分数和路径/行号稳定 tie-break。
5. 引用解析不重写 ID；每个结果返回足以验证仓库文档版本和行范围的 metadata。

## 验收

- 重复扫描不生成重复来源版本；文件内容改变时新增 draft，原 active 搜索结果保持不变直到激活。
- 用户不能通过请求参数注册任意文件、符号链接或白名单外路径；拒绝不泄露服务器路径。
- 缺少 `assistant:read` 的用户不能搜索；用户缺少来源 ACL 中任一权限时结果中不出现该来源。
- 不能归档唯一 active 版本；激活新版本后旧 active 自动归档；并发激活保持一个 active 版本并有审计记录。
- 未生效或过期来源不参与检索；当前版本分块的路径、版本、哈希和行号在 Search API 和助手 Tool 中一致。
- 迁移在当前 Alembic head（可能由并发 Storefront 工作继续演进）上可升级/回滚，不覆盖其他迁移。
- 跨窗口消费者可按 `(source_id, source_version, chunk_id, content_hash)` 存引用，不依赖前端文本或 `K1` 序号。

## 实现调用

- 复用现有 `assistant_knowledge._read_chunks` 的分块语义、`search_knowledge` 的词面打分、LIM `lim:manage`、`assistant:read`、用户角色和 `record_audit`。
- 初次扫描把当前已在允许目录内的文档视为现有审核语料并创建 active snapshot；之后所有新增/内容修改都需显式激活。
- 管理端工作台加“知识源”Tab，提供扫描、来源/版本表、草稿激活和归档操作；不创建本批业务证据视图。
- 如果企业经营管理端需要用这些引用，公开的稳定来源字段由知识检索 API 提供；其业务 Evidence schema 仍归消费端/企业经营模块所有。
