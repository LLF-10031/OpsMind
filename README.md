# OpsMind — 智能运维诊断平台

面向单兵运维/中小团队的定时巡检与 AI 智能分析平台。基于 FastAPI + LangGraph + pgvector 构建。

## 快速启动

### 1. 基础设施（PG + pgvector）
```bash
cd backend
docker compose -f ../docker-compose.yml up -d pg
```

### 2. 配置文件
```bash
cp .env.example .env
# 填入你的 API key（阿里百炼等 OpenAI 兼容服务）
```

### 3. 启动后端
```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

### 4. 启动目标机执行服务
方式 A（推荐，已端到端冒烟）：与 PG 同机跑容器
```bash
docker compose -f docker-compose.yml up -d --build executor
curl http://localhost:8003/mcp   # 应返回 405（FastMCP 挂载点存在）
```
方式 B（本地裸启动，默认仅绑 127.0.0.1）：
```bash
python -m app.executor.server
# 暴露到内网：OPSMIND_BIND_HOST=0.0.0.0 python -m app.executor.server
```

### 5. 启动前端（Vue3 + Vite + Element Plus）
```bash
cd frontend
npm install
npm run dev
# http://localhost:5173（hash 路由；默认直连后端 http://localhost:8000，
# 可用环境变量 VITE_API_BASE 覆盖，如 $env:VITE_API_BASE="http://10.0.0.5:8000"）
# 生产部署：npm run build → dist/ 交 nginx 静态托管
```

### 6. 访问
- Web UI：http://localhost:5173
- API：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health
- 执行服务 MCP：http://localhost:8003（控制端经 `app/executor/mcp_client.py` 握手调用）

> **国内拉镜像提示**（宿主直连 Docker Hub 不通时）：基础镜像带国内代理前缀，如 `docker.m.daocloud.io/python:3.13-slim`、`docker.m.daocloud.io/pgvector/pgvector:pg16`（见 docker-compose.yml）；compose 命令须显式携带 `-f` 指定文件。

### 7. 一键容器启动（推荐）

```bash
# 项目根目录 OpsMind/ 下
docker compose -f docker-compose.yml up -d --build
# 前端 http://localhost  后端 http://localhost:8000/docs  执行器 :8003  PG :5432
```

关闭 / 停止（并避免残留容器）：
```bash
docker compose -f docker-compose.yml down        # 停止并删除容器（PG 数据卷保留，数据不丢）
# 再次启动：docker compose -f docker-compose.yml up -d
```

## 常见坑（重要）

1. **容器内后端访问执行器不能用 `localhost:8003`**
   - 后端在 `opsmind-backend` 容器里，`localhost` 指向它自己；必须用 compose 服务名：
     `主机.mcp_endpoint = http://executor:8003`。
   - 本机裸跑后端（未容器化）时才是 `http://localhost:8003`。
2. **AI 功能需先配 API Key**：`.env` 默认留空 → 未配置时第二关判定按设计降级 `level=unknown`、③分析走模板、助手给引导语。
   在前端 **设置** 里配置，保存即时生效、无需重启。
3. **设置页三组 AI 能力独立配置**（可只用一组，其余留空自动复用对话组）：
   - 对话/分析：`llm_model / llm_base_url / llm_api_key / llm_temperature`
   - 文档处理/轻任务：`light_model / docproc_model / docproc_base_url / docproc_api_key`
   - 向量 embedding：`embedding_model / embedding_base_url / embedding_api_key`
   - 所有 `*_api_key` 加密存 PG、接口只回传掩码；掩码占位不会覆盖已存密钥。
4. **开机自启动**：compose 里服务为 `restart: unless-stopped`（Docker 守护进程启动时会拉起"未被手动停止"的容器）。
   - 不需要自启动：用 `docker compose -f docker-compose.yml down` 删除容器即可；
   - 或关闭 Docker Desktop 开机启动：**Docker Desktop → Settings → General → 取消勾选 "Start Docker Desktop when you sign in"**。


## 项目架构

```
backend/
├── app/
│   ├── api/        # 路由（auth/hosts/scripts/tasks/runs/documents/memory/chat/eval）
│   ├── configs/    # 配置中心
│   ├── core/       # DB/LLM/限流器/日志/异常
│   ├── diagnosis/  # 多 Agent 联动诊断（黑板契约 Planner→并行 Executor→Reviewer）
│   ├── executor/   # 目标机 FastMCP 执行服务
│   ├── graph/      # LangGraph 对话编排
│   ├── knowledge/  # 知识库（规范化/检索/索引/keygen）
│   ├── memory/     # 三层记忆（Working/Episodic/Semantic）
│   ├── models/     # ORM 模型（20 表）
│   ├── services/   # 业务逻辑（判定/报告/调度/校验/审计/评估/上下文压缩）
│   └── tools/      # 工具注册
├── tests/          # pytest 单测（38 用例，全绿）
└── docs/           # 设计文档（决策日志/需求/概要/数据库/详细设计/API/面试/术语）

Dockerfile.executor   # 目标机执行服务镜像（python:3.13-slim + bash/python3/netcat）
```

## 关键特性

- **判定两关**：确定性第一关（exit≠0/超时/empty→短路）+ LLM 第二关（level/reason）
- **报告异步**：②元信息行毫秒先出、③LLM 分析并行受限流器、SSE 事件流
- **知识库**：真实 LLM keygen + embedding → RRF（向量+BM25 中文分词）→ 勾选才查
- **助手对话**：检索 + 真实 LLM 回答生成（qwen-turbo）+ 审计
- **评估体系**：故障案例集 → 复用判定链路 → 命中率/误报率/质量评分
- **联动诊断（多 Agent）**：crit/error 批次自动触发 LangGraph `StateGraph`（Planner 拆假设 → 日志/指标/变更三 Executor 并行只读采集 → Reviewer 汇总）；黑板契约"无证据不出结论"，幂等落库 + SSE（`GET /task-runs/{id}/diagnosis`）
- **三层记忆**：Episodic/Semantic PG 化 + 内存兜底降级
- **安全**：admin JWT、输出敏感打码、全局限流器、工具降级透明
- **执行服务**：FastMCP streamable-http（/mcp + initialize 握手），解释器白名单 + 危险命令检测 + 输出截断，可裸启动或容器化

## 技术栈

Python 3.13 · FastAPI · LangChain · LangGraph · pgvector · APScheduler · FastMCP · SQLAlchemy · pytest

## 赞赏支持

如果这个项目对你有帮助，欢迎请作者喝杯咖啡 ☕（微信扫码），感谢投喂！

<p align="center">
  <img src="docs/收款码/thanks.jpg" alt="微信赞赏码" width="240">
</p>
