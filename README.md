# Shadow Tracing

逐影 Shadow Tracing：一个由人工 PI、推理规划层、实验执行层与数据分析层共同构成的闭环科学推理系统。系统以真实太阳风数据为对象，使用 Elastic Net 执行对照实验，并调用 Qwen 系列模型生成科学假设、质询、不确定性与候选实验设计。

## 项目结构

- `core/`：中央控制、假设生成与质询、不确定性识别、候选实验生成、实验执行、评价与状态更新。
- `models/`：Elastic Net 数据读取、特征构造、训练、预测与可视化。
- `scripts/`：实时工作流服务与修复脚本。
- `frontend/`：React + TypeScript + Vite 前端。
- `runtime/live_session/current/`：会话状态、上传数据、实验结果与审计记录。

## 本地开发

### 后端

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
python scripts/live_workflow_server.py
```

后端默认监听 `http://127.0.0.1:8765`，健康检查为 `GET /api/health`。

### 前端

```bash
cd frontend
pnpm install
pnpm dev
```

前端默认监听 `http://127.0.0.1:5173`。生产环境请先执行 `pnpm build`，再将 `frontend/dist` 交给 nginx。

## 环境变量

复制 `.env.example` 到项目根目录 `.env`（`.env` 已在 `.gitignore` 中），至少配置 `DASHSCOPE_API_KEY` 或 `BAILIAN_API_KEY`。当前默认使用 `qwen3.8-flash`，模型价格与计费说明见 `core/runtime_config.py`。

## 部署

阿里云 Ubuntu 服务器完整部署步骤见 [DEPLOY.md](DEPLOY.md)。
