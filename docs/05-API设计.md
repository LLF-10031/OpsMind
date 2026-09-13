# OpsMind · API 设计

> 版本：v0.2（与决策日志 D1–D50 对齐，待定项已清理）
> 接口按业务模块分组，后端执行时确定 report_type，前端仅按 report_type 映射渲染模板（D36/D47）。
> 实现状态：**全量已落地**（含 tracking-metrics toggle/preview、scripts run/preview-llm/trend/trend-summary、templates apply、settings GET/PUT 持久化+密钥掩码、chat 会话 CRUD+消息游标分页+每轮落库+save-memory、eval results 列表/详情、documents preview、memory PUT、hosts 任务），见 `tests/test_api_gaps.py`；全量 30 例 + 缺口 11 例测试全绿。

---

## 一、通用约定

| 项 | 约定 |
|---|---|
| 基础路径 | `/api/v1` |
| 响应格式 | `{success: bool, data: any, error?: {code, message}}` |
| 鉴权 | **admin 密码登录 + JWT 会话校验（O5a 落地）** |
| 分页 | `?page=1&page_size=20`，响应含 `{total, items}` |
| SSE 端点 | `text/event-stream`，`Cache-Control: no-cache` |

---

## 二、主机管理

### `GET /hosts` — 主机列表
### `POST /hosts` — 添加主机（含连通性探测）
Body: `{name, mcp_endpoint, auth_key?, description?}`
响应: `{host_id, status: "connected"|"failed"}`

### `GET /hosts/{id}` — 主机详情
### `PUT /hosts/{id}` — 修改主机
### `DELETE /hosts/{id}` — 软删主机
### `POST /hosts/{id}/ping` — 探测连通性

---

## 三、鉴权

### `POST /auth/login` — 管理员登录
Body: `{password}`
响应: `{token, expires_in}`

### `POST /auth/logout` — 登出
Header: `Authorization: Bearer {token}`

### `GET /auth/verify` — 校验会话有效性

---

## 四、脚本库

### `GET /scripts` — 脚本列表
Query: `?is_builtin=true&is_enabled=true`

### `POST /scripts` — 创建脚本
Body: `{name, content, shell?, timeout?, params_json?, llm_rule_text?, description?, tracking_metrics?: [{name, extraction_mode, regex_pattern?, unit}]}`

### `GET /scripts/{id}` — 脚本详情
### `PUT /scripts/{id}` — 修改脚本（版本递增）
### `DELETE /scripts/{id}` — 软删脚本
### `POST /scripts/{id}/run` — 单脚本测试执行（立即执行，不触发 AI 分析）
Query: `?host_id=xxx`
响应: 按 report_type 渲染

### `POST /scripts/{id}/preview-llm` — LLM 判定试判预览（不落库）
Body: `{llm_rule_text, sample_output?}`

### `GET /scripts/{id}/tracking-metrics` — 跟踪指标列表
响应: 指标数组（name/extraction_mode/regex_pattern/unit/is_enabled）

### `POST /scripts/{id}/tracking-metrics` — 添加跟踪指标
Body: `{name, extraction_mode, regex_pattern?, unit}`
响应含"用最近一次结果试提取"预览

### `PUT /tracking-metrics/{id}/toggle` — 启用/停用跟踪指标
### `DELETE /tracking-metrics/{id}` — 移除（停用，历史保留）
### `POST /tracking-metrics/{id}/preview` — 试提取预览（用最近一次 run 结果验证提取效果）

---

## 五、模板/通用任务方案库

### `GET /templates` — 模板列表
### `POST /templates` — 创建模板
Body: `{name, description?, schedule_json, script_ids: []}`

### `GET /templates/{id}` — 模板详情
### `PUT /templates/{id}` — 修改模板
### `DELETE /templates/{id}` — 软删模板
### `POST /templates/{id}/apply` — 套用模板到指定主机生成任务
Body: `{host_id, task_name?, task_description?}`

---

## 六、巡检任务

### `GET /hosts/{host_id}/tasks` — 主机下的任务列表
### `POST /hosts/{host_id}/tasks` — 创建任务
Body: `{name, description?, schedule_json?, script_ids: []}`
- `schedule_json`（D17）：`null`=仅手动；`{"type":"interval","value":<分钟>}` 或 `{"type":"cron","value":"分 时 日 月 周"}`（非法结构返回 BAD_REQUEST）
- 创建/修改/启停/删除任务时，后端同步注册/移除 APScheduler 定时作业（D17 接线）

### `POST /tasks` — 创建任务（同 `/hosts/{id}/tasks`）
### `GET /tasks/{id}` — 任务详情
### `PUT /tasks/{id}` — 修改任务
### `DELETE /tasks/{id}` — 软删任务
### `POST /tasks/{id}/run` — 立即执行任务
响应: `{task_run_id}`

### `PUT /tasks/{id}/toggle` — 启用/禁用任务
Body: `{is_enabled: bool}`

### `GET /tasks/{id}/runs` — 任务执行历史列表
Query: `?page=1&page_size=20`

---

## 七、任务执行历史与报告

### `GET /task-runs/{id}` — 执行历史详情（含批次汇总视图）
响应: `{task_run_id, status, started_at, finished_at, summary_json, run_count}`

### `GET /task-runs/{id}/stream` — SSE 实时通道
推流事件（按 D47 R-3 收紧）：
```
event: run_result      → {run_id, report_type, level, summary}
event: batch_ready     → {summary_json}
event: ai_done         → {run_id}
event: diag_started    → {run_ids[]}
event: diagnostic_done → {run_ids[], conclusions}
event: diag_failed     → {run_ids[], reason}
event: done            → {task_run_id}
event: error           → {message}
```

### `GET /task-runs/{id}/runs` — 本次执行各脚本运行列表
Query: `?level=warn&report_type=error&page=1`

### `GET /runs/{run_id}` — 单脚本运行详情
### `GET /runs/{run_id}/report` — 单脚本报告（按 report_type 渲染）
响应: `{report_type, meta, raw_output, ai_content, ai_source, annotations, banner}`
- `report_type`: `success` / `error` / `timeout` / `empty` / `host_unreachable`（后端执行时确定，前端只按此映射模板）
- `ai_source`: `ai_analysis`（分析正文） / `ai_diagnosis`（失败诊断） / `template`（固定文案） / `none`

### `GET /runs/{run_id}/output` — 读取 run 原始输出（R-1 磁盘存档）
Query: `?start=<line>&end=<line>&keyword=&limit=100`（行区间/关键词/行数上限，后端解析路径，防穿越）

### `POST /runs/{run_id}/reanalyze` — 重新分析（可切换模型，D21/D48）
Body: `{model?}`

### `GET /scripts/{id}/trend` — 脚本趋势页
Query: `?tracking_metric=cpu&window=30`
响应: `{history: [{task_run_started_at, level}], series: {cpu: [{ts, value, source}]}}`

### `POST /scripts/{id}/trend-summary` — 生成 AI 趋势小结（按需）
Body: `{tracking_metric?}`（空=综合判定级别趋势）

---

## 八、知识库

### `GET /documents` — 文档列表
### `POST /documents` — 上传文档（multipart/form-data）
支持格式：md / txt / pdf
同名文档先删旧数据再入库

### `GET /documents/{id}` — 文档详情（含元信息 + 规范化全文）
### `GET /documents/{id}/content` — 在线浏览完整原文（G3）
响应: `{id, name, file_type, raw_content(原文全文), normalized_md(规范化全文)}`（均不截断）
### `GET /documents/{id}/preview` — 预览该文档的知识单元（保位顺序）
### `DELETE /documents/{id}` — 硬删文档及关联向量
### `POST /documents/search` — 知识库检索
Body: `{query, document_ids?: [] (空=默认文档集), k: 5}`

---

## 九、AI 助手

### `POST /chat` — 对话请求
Body: `{session_id?, message, model?, knowledge_ids?: [], skill_id?, tool_ids?: []}`
响应: SSE 流式回答

### `GET /chat/sessions` — 会话列表

### `POST /chat/sessions` — 创建会话
Body: `{title?, model_snapshot?}`

### `PUT /chat/sessions/{id}` — 修改会话名称
Body: `{title}`

### `DELETE /chat/sessions/{id}` — 软删会话
### `GET /chat/sessions/{id}/messages` — 会话消息历史（游标分页）
Query: `?limit=1..200&before_id=<消息id>`（`before_id` 为游标，不含自身；响应 `{total, items}` 升序）
### `POST /chat/sessions/{id}/save-memory` — 手动保存当前片段为 Episodic 记忆
无 session_id 的 `/chat` 首轮自动建会话（title=首句前 40 字+"…"），user/assistant 每轮双落 Message + last_active_at。

---

## 十、记忆管理

### `GET /memory` — 记忆列表
Query: `?type=episodic|semantic&page=1`

### `DELETE /memory/{type}/{id}` — 删除单条记忆
### `PUT /memory/{type}/{id}` — 编辑单条记忆
Body: `{summary?, topic?, pattern?, ...}`

### `POST /memory/query` — 手动查记忆（query_memory 工具等效）
Body: `{query, type: episodic|semantic|all, k: 3}`

---

## 十一、评估

### `POST /eval/run` — 触发评估运行
Body: `{case_ids?: []}`（空=跑全部案例）

### `GET /eval/results` — 评估结果列表

### `GET /eval/results/{id}` — 评估详情（含雷达图/命中率/误报率数据）

### `GET /eval/cases` — 故障案例集列表

---

## 十二、设置

### `GET /settings` — 获取所有设置
### `PUT /settings` — 批量更新设置

**三组 AI 能力独立配置**（D21/D40；空项自动回落到对话组）：
```
对话/分析：  llm_model, llm_base_url, llm_api_key, llm_temperature
文档处理/轻任务：light_model, docproc_model, docproc_base_url, docproc_api_key
向量 embedding：embedding_model, embedding_base_url, embedding_api_key
其他：       default_document_ids, pipeline_config, injection_detection_enabled ...
```
- 所有 `*_api_key` 加密存 PG、GET 时掩码不回传明文、掩码占位（******xxxx）不覆盖原值；
- PUT 后运行时即时生效（无需重启）。

---

## 十三、健康检查

### `GET /health` — 系统健康检查
响应: `{status, version, pg_ok, redis_ok?, llm_ok?}`

---

> 本文档基于决策日志 D13–D48 编写，与需求/概要/数据库/详细设计对齐；接口随设计演进在本文件内直接补齐。