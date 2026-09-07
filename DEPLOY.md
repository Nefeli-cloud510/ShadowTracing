# 阿里云 Ubuntu 部署指南

## 1. 环境要求

- Ubuntu 22.04 或 24.04
- Python 3.12+
- Node.js 22 LTS（仅构建前端使用）
- pnpm
- nginx

生产环境采用 nginx 托管前端静态文件并反向代理 `/api` 到本机 Python 后端，不需要把后端端口直接暴露到公网。

## 2. 安装系统依赖

```bash
sudo apt update
sudo apt install -y git curl build-essential python3.12 python3.12-venv python3-pip nginx
```

Node.js 22 与 pnpm：

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pnpm
```

## 3. 上传代码并安装后端依赖

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone <your-repo-url> ShadowTracing
sudo chown -R "$USER":"$USER" ShadowTracing
cd ShadowTracing
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，至少填写：

```dotenv
DASHSCOPE_API_KEY=你的百炼APIKey
DASHSCOPE_BASE_URL=https://llm-jz60biyiqkkwzssm.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
BAILIAN_MODEL=qwen3.8-flash
```

项目代码在启动时会以 `.env` 文件中的值为准。若服务器系统环境变量、`/root/.bashrc` 或 systemd 环境里残留了旧 Key，应先删除同名变量或直接让 `.env` 覆盖，避免旧 Key 继续生效。

同源部署（前端静态文件与 `/api` 都由同一个 nginx 提供服务）不需要设置任何前端环境变量，前端构建后会默认使用相对路径 `/api`。只有后端部署在独立域名或跨域端口时，才需要在构建前端时设置 `VITE_WORKFLOW_API_BASE`；例如：

```bash
cd /opt/ShadowTracing/frontend
VITE_WORKFLOW_API_BASE=https://api.example.com/api pnpm build
```

跨域场景下，还需要同时设置 `VITE_STATE_API_BASE` 与 `VITE_STATE_API_IMAGE_BASE`，分别指向状态 JSON 和可视化图片的 API 前缀。

## 4. 构建前端

```bash
cd /opt/ShadowTracing/frontend
pnpm install
pnpm build
```

构建产物位于 `/opt/ShadowTracing/frontend/dist`。

## 5. 启动后端

先手工验证：

```bash
cd /opt/ShadowTracing
.venv/bin/python scripts/live_workflow_server.py
curl http://127.0.0.1:8765/api/health
```

后端默认绑定 `127.0.0.1:8765`，由 nginx 反向代理访问。使用 systemd 托管常驻进程，新建 `/etc/systemd/system/shadowtracing.service`：

```ini
[Unit]
Description=Shadow Tracing Live Workflow Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/ShadowTracing
ExecStart=/opt/ShadowTracing/.venv/bin/python scripts/live_workflow_server.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/ShadowTracing/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now shadowtracing
```

## 6. 配置 nginx

新建 `/etc/nginx/sites-available/shadowtracing`：

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 200m;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;

    root /opt/ShadowTracing/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_request_buffering off;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/shadowtracing /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

完成后通过服务器公网 IP 或域名访问前端页面。HTTPS 可参考 `certbot --nginx` 配置。

## 7. 数据目录与备份

`runtime/live_session/current` 包含会话状态、上传数据、预测结果、图表和审计链，部署后必须持久化保存，不要放入 `/tmp`。建议挂载数据盘并做每日备份：

```bash
tar -czf /backup/shadowtracing-$(date +%F).tar.gz \
  /opt/ShadowTracing/runtime/live_session/current
```

## 8. 安全注意事项

- `.env` 已加入 `.gitignore`，不要提交 API key。
- 阿里云安全组只放行 80/443（或仅 443），不要放行 8765。
- 后端仅监听 `127.0.0.1`，公网访问一律经过 nginx。
