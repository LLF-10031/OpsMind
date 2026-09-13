# OpsMind · 开发交接清单（dev-handoff）

> 给开发子会话（如 `opsmind-dev`）的开工指引。
> **决策日志 = 唯一真源**：开发中若发现"本文档/04 详细设计 与 决策日志 D1–D50 冲突"，一律以决策日志为准并回写文档。

---

## 📊 开发进度（开发子会话维护）

| 阶段 | 状态 | 备注 |
|---|---|---|
| LLM/API 就绪 | ✅ | 阿里百炼 qwen-turbo（便宜模型）+ text-embedding-v3 已配 .env；chat/embedding/判定/报告③分析 真实调用通过；KB 检索走真实向量（embedded=True）不再降级 |
| Phase 0 骨架 | ✅ 完成 | 结构/pyproject/settings/限流器/模型16表/FastMCP执行服务/MCP client/认证/health |
| Phase 1 调度与执行 | ✅ 完成 | 执行引擎(execute_task_run)：MCP下发→第一关→第二关LLM→Run/Report落库→批次DONE；后台触发；判定单测+端到端 |
| Phase 2 报告与 SSE | ✅ 完成 | O4五阶段+柔性标注；报告③(真实LLM+限流+敏感打码+校验)；report/run API(read_run_output/reanalyze)；SSE事件流(run_result/batch_ready/done) |
| Phase 3 知识库与助手 | ✅ 完成 | 知识库完整链路(LLM keygen+真实embedding+RRF BM25中文分词)✅ 助手对话图(检索+**真实LLM回答生成**+勾选才查D48+审计)✅ **chat API=SSE 流式**(事件集 start/kb_ready/token/done/error，每块敏感打码，空消息/未勾选/LLM失败均有降级兜底)✅ 记忆PG层✅ 18测试全绿、真实PG e2e通过；另修复 main.py 调度器导入 bug(None.start) |
| Phase 4 记忆/评估/安全 | ✅ 完成(安全更细待做) | 评估案例CRUD+运行评估(**真实判定链路**：第一关短路+第二关复用second_gate_llm受限流+降级unknown)+聚合指标(命中率/误报率/质量)；eval表就绪API挂载；19测试全绿；"待做"雷达图前端(二期)+安全更细 |
| Phase 5 测试+启动 | ✅ 完成 | **executor Docker 起服并 MCP 冒烟全通**（Dockerfile.executor 镜像可构建、容器 opsmind-executor 运行、8003 映射；修复 3 处：容器内绑127.0.0.1外部不通→OPSMIND_BIND_HOST/0.0.0.0、client 拼错 /message→/mcp+initialize握手+SSE解析、解释器 argv 带多余元素→候选路径首个存在者）；hosts 建主机即探活真实 MCP ping 通过 + 真实 PG e2e 通过；19测试全绿；README按需 |
| API 缺口闭环（05-API 全量落地） | ✅ 完成 | **templates/settings/tracking-metrics/scripts(单脚本 run/preview-llm/trend/trend-summary)/chat 会话(CRUD+消息游标分页+每轮落 Message+save-memory)/eval results 列表+详情聚合/内部 memory PUT/hosts 任务/documents 预览 全量落地**。要点：`POST /scripts/{id}/run?host_id=` 走 `trigger=test` 独立 Run（task_id 空、不触发 AI 分析）供 tracking 预览复用；eval 详情按 run_id 实时聚合命中/误报/质量+雷达；settings 持久化 SettingsKV + llm_api_key 掩码。**修复两处**：`app/api/settings.py` 与配置对象 `settings` 撞名→main.py 导入别名 `settings_api`；scripts.py 两处误调 `serialize`→`_to_dict`（真实 bug）。新增缺口测试 `tests/test_api_gaps.py` 11 例；**全量 30 例全绿** |

> 启动方式：`cd backend && .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload`

---

## 一、先读什么（按顺序）

1. `D:\IdeaDocs\myproject\设计讨论决策日志.md` —— 全文 D1–D50（唯一真源，含所有取舍与原因）
2. `D:\IdeaDocs\myproject\OpsMind\docs\02-概要设计.md` —— 架构/模块/部署/数据流/一致性对照表（附录A/B）
3. `D:\IdeaDocs\myproject\OpsMind\docs\03-数据库设计.md` —— 表结构（含 pgvector/session/memory）
4. `D:\IdeaDocs\myproject\OpsMind\docs\04-详细设计.md` —— §0–§7 实现蓝图（判定/报告/执行/校验/调度/知识库/助手/记忆/评估/安全）
5. `D:\IdeaDocs\myproject\OpsMind\docs\05-API设计.md` —— 接口清单（含鉴权/评估/记忆/read_run_output）
6. `D:\IdeaDocs\myproject\OpsMind\docs\01-需求文档.md` —— 功能范围/边界
7. `D:\IdeaDocs\myproject\OpsMind\docs\06-简历亮点与面试题.md` / `08-AI术语与面试攻防.md`——（面试向，可后读）

## 二、技术栈（确认版本后再动码）

- Python 3.11+ · FastAPI + Uvicorn · LangChain + LangGraph · APScheduler
- LLM：通义 DashScope（OpenAI 兼容），设置页可换
- 向量库：**PostgreSQL + pgvector**（业务元数据 + 向量一体；不用 Milvus/Chroma）
- MCP：FastMCP（目标机执行服务）/ langchain-mcp-adapters（控制端 client）
- 缓存：单实例内存 LRU（不用 Redis；Redis 仅可选演进）
- 前端（二期/另会话或轻量）：Vue3 + Vite（本会话优先后端 API）
- 测试：pytest + pytest-asyncio + pytest-cov

## 三、落地顺序（按 04-详细设计 章节）

```
Phase 0  骨架：项目结构 / settings / DB 连接(pgvector) / 依赖版本
Phase 1  §5 调度与执行引擎：Host/Task/Template/TaskRun/Run 模型 + APScheduler + MCP client
          §3 执行通道：FastMCP 执行服务(ping/run_script/get_runtime_info) + run_script 下发/回收
          §1 判定体系：第一关确定性 → 第二关 LLM(level/reason) → report_type×level 落库
Phase 2  §2 报告与 SSE：report 占位/②元信息行/③LLM分析/批次汇总；SSE 事件集 + 前端分派字段
          §4 校验管线：O4 五阶段 + reason 覆盖 + 柔性标注 + 横幅 + 规则可配
          §0 端到端链路打通（判定→报告→crit/error→诊断触发→回填）
Phase 3  §6 知识库与助手：
          6.1 文档规范化(md/txt/pdf→unit→key_index)
          6.2 检索：向量+BM25 RRF + topK + LLM选择 + search_kb 勾选约束
          6.3 助手对话图(LangGraph) + D38 工具闭环 + 上下文压缩(D43) + 记忆(D44)
          6.6/6.7 历史会话持久化 + 存储降级
Phase 4  §7 记忆/评估/安全：
          7.1 三层记忆 + 前端记忆管理
          7.2 评估体系(故障案例集/命中率/误报率/雷达)
          7.3 安全（直接/间接注入、输出打码、限流器、审计、admin JWT 登录）
Phase 5  测试 + 补齐 05-API 主要接口 + 启动文档
```

## 四、需严格遵守的关键决策（防漏，来自 D17–D48）

- **两关模型**：第一关确定性短路永远不走 LLM；第二关 LLM 只读原始结果+规则文本→`{level,reason}`；**阈值比较已废弃**（别做 indicator/字段绑定）。
- **report_type ≠ level**：`report_type{success,error,timeout,empty,host_unreachable}` 管渲染/AI介入；`level{ok,warn,crit}` 管颜色/计数/是否触发诊断。
- **crit/error 只跑联动诊断一次**（不另跑③）；诊断块批次级一次；error run ③=失败诊断。
- **LLM 全局限流器**：所有 LLM 调用（判定/③/诊断/摘要/记忆）信号量+令牌桶统一过。
- **上下文压缩（D43）**：预算=ctx−max_output−reserved(10k或20%)，80%触发；压缩用"轻任务模型"；摘要固定分区+增量。
- **R-1**：run 原始输出落磁盘（`outputs/{task_run}/{run}.out`），DB 存路径；agent 经 `read_run_output` 按需精读。
- **D38 工具闭环**：三图所有工具调用——入参校验失败自纠≤2 / 执行失败重试3退避 / 三档降级 / degradation_notes 透明。
- **search_kb 默认只在"勾选文档集"内检索**；全量=显式开关。
- **记忆（D44）**：Episodic=片段闭合(压缩/闲置10min/手动保存按钮)触发；Semantic=累计≥30 提炼+跨会话证据校验。
- **安全（D39/D48）**：输出敏感打码是所有生成文本出口的横切点；admin JWT 登录；审计是三图工具调用横切点。

## 五、验收清单（每阶段结束自查）

- [ ] 06 接口依据 05-API 可跑通（登录→hosts/scripts→task→run→report SSE）
- [ ] 两关判定+report_type×level 正确落库（含 host_unreachable/empty/timeout/error 分支）
- [ ] 报告异步：②先出、③并行受限流、crit/error 走联动并回填；SSE 事件齐全
- [ ] O4 五阶段作用到 ③+reason；存疑/横幅/可展开生效；规则可配
- [ ] 知识库：上传→规范化→unit→key_index；RRF+勾选集约束可跑
- [ ] 助手对话图：工具循环+D38 降级+上下文压缩+记忆 query_memory
- [ ] 存储降级：PG 挂→内存会话提示；探活恢复
- [ ] 默认 dev 环境：性能期望值（判定<200ms、检索<100ms、脚本执行<2s）可标"设计目标待压测"

## 六、默认值速查

| 参数 | 默认 |
|---|---|
| 脚本类型 | Shell(bash)/Python3，解释器白名单 |
| 脚本并发 | ≤5 |
| 报告生成并发 | 全局 ≤4 |
| LLM 并发 | ≤5~10（限流器，按 API 限额） |
| 上下文 | 预算=ctx−max_output−10000；N=10；80% 触发；summary_cap=clamp(20%,800,4000) |
| 保留/清理 | 会话 30 天归档、软上限 300；run 输出磁盘配额 ≤2GB |
| 技能 | 3 内置按需加载（system-health/log-root-cause/release-analysis） |
| 队列优先级 | 诊断 > ③分析 > 摘要/记忆 |