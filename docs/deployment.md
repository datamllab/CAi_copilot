# CAi Web UI 部署与访问指南

## 快速启动

```bash
# 启动服务（推荐用 nohup 或 tmux 保持后台运行）
python CAi/main.py --port 9966

# 后台运行（防止 SSH 断开后服务停止）
nohup python CAi/main.py --port 9966 > cai.log 2>&1 &
```

启动后终端会显示访问地址和局域网 IP。

---

## 访问方式

### 本机访问

```
http://localhost:9966
```

### 局域网访问（同一校园网/实验室内网）

同事在浏览器中打开：

```
http://<服务器内网IP>:9966
```

服务器内网 IP 可在启动时的终端 banner 中看到，或手动查看：

```bash
hostname -I
```

### 外网访问（校外/家里）

服务器在校内网，外部无法直连。需要用内网穿透工具暴露服务。

#### 方式一：Cloudflare Tunnel（推荐，免费稳定）

```bash
# 下载安装
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared

# 启动隧道（替换 9966 为你的实际端口）
./cloudflared tunnel --url http://localhost:9966
```

终端会输出一个 `https://xxx-xxx.trycloudflare.com` 的公网地址，发给别人即可访问。

#### 方式二：ngrok（一行命令）

```bash
# 安装
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok-v3-stable-linux-amd64.tgz | tar xz

# 启动
./ngrok http 9966
```

会生成类似 `https://xxxx.ngrok-free.app` 的地址。免费版地址每次重启会变。

---

## 配置

主要配置在 `CAi/config.py`，可通过 `CAi/.env` 或环境变量覆盖：

```bash
# LLM 配置
LLM_MODEL=claude-sonnet-4-5-20250929
LLM_API_KEY=your_key

# 服务端口
WEB_UI_PORT=9966
TOOL_SERVER_PORT=8001
```

CLI 参数优先级更高：

```bash
python CAi/main.py --port 9966 --model gpt-4o --temperature 0.7
```

---

## 常见问题

**Q: 别人打开页面但聊天没反应？**
检查浏览器控制台（F12）是否有 CORS 错误。当前配置已放开所有来源（`allow_origins=["*"]`），正常不会有此问题。

**Q: SSH 断开后服务就挂了？**
用 `nohup` 或 `tmux`：
```bash
# tmux 方式（推荐，可随时回来查看）
tmux new -s cai
python CAi/main.py --port 9966
# 按 Ctrl+B 然后按 D 离开，回来看：tmux attach -t cai
```

**Q: 端口被占了怎么办？**
```bash
# 查看谁占了端口
lsof -i :9966

# 换一个端口
python CAi/main.py --port 8888
```

**Q: 服务正在运行但访问很慢？**
- 检查网络带宽（内网穿透会受限于穿透工具的带宽）
- LLM API 响应时间取决于模型和网络（Claude/GPT 可能需要几秒到几十秒）

---

## 当前限制

- 无用户认证，任何人有链接就能使用
- 每个对话会启动一个独立的 Jupyter kernel 进程，并发过多会占用服务器资源
- 对话数据存储在 `agent_workspace/_conversations/` 下的 JSON 文件中
