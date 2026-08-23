# 沉浸对话 · AI 角色聊天 App

一个用 **FastAPI + 原生前端（PWA）** 打造的沉浸式 AI 角色扮演聊天应用，风格参考「猫箱」：简约暗色、氛围感、气泡式对话。

> cd核心特性：自定义大模型（任意 OpenAI 兼容接口 / 本地 Ollama）、角色卡系统、猫箱式记忆机制、上下文长记忆、深度代入防跳出人设、会话管理、回复长度与暗亮主题调节、可直接在手机「添加到主屏幕」安装。
>
> **新增能力**：① 管理员登录鉴权（仅 admin，不支持注册），并新增**单独的用户管理后台页面**，可查看每个用户创建的角色、会话、消息、记忆与操作日志，支持后台修改用户信息/密码/删除用户 ② 每次回复附带「心理活动/动作」旁白、每 50 条消息自动总结前文（超长记忆不丢失）③ 会话级自定义聊天背景 ④ 根据最近聊天生成「人物当前状态」图片（文字描述 + 可选图像生成）⑤ **对话模型与图像模型可分别测试连接**。

---

## 一、目录结构

```
ai-chat-app/
├── backend/                # FastAPI 后端
│   ├── main.py             # 主程序 + 所有接口 + 静态托管
│   ├── config.py           # 全局配置（api_key / 地址 / 模型 等，落盘 config.json）
│   ├── db.py               # SQLite 持久化（角色/记忆/会话/消息）
│   ├── llm.py              # OpenAI 兼容大模型客户端（流式 + 记忆总结）
│   ├── requirements.txt
│   └── config.json         # 自动生成（不要手动写密钥）
└── frontend/               # 原生前端（无构建步骤）
    ├── index.html
    ├── users.html           # 管理员用户管理后台（单独页面）
    ├── style.css
    ├── app.js
    ├── manifest.json        # PWA 配置（手机可安装）
    ├── sw.js                # Service Worker（应用外壳缓存）
    ├── icons/               # 自动生成的图标
    └── generate_icons.py    # 图标生成脚本（纯标准库）
```

---

## 二、环境要求

- Python 3.10+（已在 3.13 验证）
- 一个 OpenAI 兼容的大模型接口，任选其一：
  - **本地 Ollama**（推荐，免联网）：`ollama run llama3` 等
  - 云端：OpenAI / DeepSeek / 硅基流动 / 腾讯云等任意 `/v1` 兼容地址
- 手机安装只需浏览器（无需应用商店）

---

## 三、启动（PC 端）

```bash
# 1. 进入后端目录
cd ai-chat-app/backend

# 2. 安装依赖（建议使用虚拟环境）
pip install -r requirements.txt
# 或：python -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# 3. 启动服务（0.0.0.0 便于手机同局域网访问）
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

启动后浏览器打开 **http://localhost:8000** 即可使用。

> 也提供了 `start.bat`（Windows） / `start.sh`（Linux/Mac）一键启动脚本。

---

## 四、配置大模型（关键，不写死密钥）

项目默认已填入 **阿里云灵积 DashScope** 的 OpenAI 兼容接口地址。打开页面右上角 **⚙️ 设置**，填写你的 API Key 并确认模型名后保存即可。

| 配置项 | 说明 | 默认示例（DashScope 灵积） | 本地 Ollama 示例 |
|--------|------|----------------------------|------------------|
| API 地址 | OpenAI 兼容接口 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `http://localhost:11434/v1` |
| API Key | 填写对应平台密钥 | DashScope API Key | 本地可留空或填 `ollama` |
| 模型名称 | 与平台一致 | `qwen-turbo` / `qwen-plus` / `qwen-max` | `llama3` / `qwen2.5` |
| 温度 | 越高越有创意 | 0.9 |
| 回复长度 | 单次最大 token | 512 |
| 上下文记忆轮数 | AI 记住最近 N 轮 | 30 |
| 全局附加提示 | 可选微调 | 如「语气更温柔」|

填完点 **保存**。设置面板提供两个测试按钮：
- **测试对话模型**：验证当前填写的 API 地址 / Key / 模型名能否正常流式生成。
- **测试图像模型**：验证图像生成接口是否可连通（调用 `/v1/models`，不真正出图、不扣费）。

所有配置保存在后端 `backend/config.json`，任何设备访问同一服务都生效。

### 对接本地 Ollama（GGUF 模型免联网）

```bash
# 安装并拉取模型
ollama pull llama3
ollama run llama3        # 确认能跑通

# Ollama 默认已开启 OpenAI 兼容接口：
#   http://localhost:11434/v1
```

GGUF 量化模型直接 `ollama create` 或 `ollama run <模型名>` 即可，无需联网大模型。

### 对接阿里云灵积 DashScope（默认已配置）

- API 地址：`https://dashscope.aliyuncs.com/compatible-mode/v1`
- API Key：在 [DashScope 控制台](https://dashscope.console.aliyun.com/) 获取
- 模型名：`qwen-turbo`（快/便宜）、`qwen-plus`、`qwen-max`、`qwen2.5-7b-instruct` 等

> 注意：灵积没有 `qwen2.5-flash` 这个模型名，常见报错就是模型不存在。

### 对接其他云端（以 OpenAI 兼容为例）

- API 地址填 `https://api.openai.com/v1`（或对应厂商地址）
- API Key 填你的密钥
- 模型名填 `gpt-4o-mini` / `deepseek-chat` 等

---

## 五、管理员登录鉴权

应用**仅支持管理员登录，不支持注册**（避免被随意注册滥用）。

- 默认账户：**admin** ／ 密码：**nxb03070**
- 账户在后端首次启动时自动写入 SQLite（`backend/app.db` 的 `users` 表，密码使用 PBKDF2-HMAC-SHA256 加盐哈希，不存明文）。
- 登录后发放 **Bearer Token**，所有 `/api/*` 业务接口都需要携带该 Token（前端自动从 `localStorage` 读取并注入请求头）；`/api/health` 与 `/api/login` 无需鉴权。
- **用户管理后台**：管理员点击设置面板里的 **「打开用户管理后台 →」** 可进入单独的 `users.html` 页面，查看每个用户的：
  - 数据概览（角色数、会话数、消息数、记忆数）
  - 创建的角色与会话列表
  - 操作日志（创建角色、新建会话、发送消息、添加记忆、生成状态图等）
  - 可修改用户名、角色、重置密码，或删除普通用户
- **快速添加用户**：设置面板「用户管理」区域也可直接新增/删除普通用户；不支持公开注册。
- **修改密码**：任何登录用户都可在设置面板修改自己的密码；管理员还可在用户管理后台直接重置任意用户密码。
- 退出：设置面板点击「退出登录」即吊销当前 Token；主界面右上角 👤 按钮也可快速退出。

> 首次进入会显示登录屏，输入 admin / nxb03070 即可进入主界面。

---

## 六、功能使用

1. **角色卡**：点「新建对话」→ 选角色；或在「角色库」新建/编辑/导入/导出。
   - 可设置：名字、头像（emoji 或上传图片）、人物背景、性格、说话风格、示例对话、世界观长设定、开场白、标签。
   - **导入/导出**：角色卡为 JSON 文件，头像以 dataURL 内嵌，可随身携带。
2. **对话**：气泡式 UI，Enter 发送、Shift+Enter 换行，AI 流式逐字回复。
3. **💭 心理活动 / 动作旁白（沉浸增强）**：每次角色回复后，系统会另调一次模型生成一句「心理活动 / 动作描写」，以灰色斜体旁白显示在气泡下方（如 `*轻轻别过脸，耳尖发红*`）；同时系统提示词也鼓励角色在对话中自然融入动作神态（用 `*动作*` 标注），让演绎更有画面感。
4. **超长记忆（每 50 条自动总结）**：当某个会话累计消息达到 50 的倍数时，系统自动把最近 50 轮对话交给大模型总结为「记忆要点」写入角色记忆，从而**突破上下文窗口限制，实现超长记忆不丢失**。你也会看到「已自动总结 N 条长期记忆」的提示。
5. **🎨 自定义聊天背景**：聊天页点 **🎨 背景**，可为当前会话选择预设渐变背景或上传图片（图片以 dataURL 随会话保存），让每个角色的聊天氛围各不相同。
6. **🖼 人物当前状态图**：聊天页点 **🖼 状态图**，系统根据角色设定、记忆与最近聊天，生成一段「人物此刻状态」的画面描述；若你在设置中填写了 **图像生成 API 地址**（OpenAI 兼容 `/v1/images/generations`），还会进一步生成图片并直接展示。
7. **记忆模块（猫箱式）**：聊天页点 **🧠 记忆**
   - 手动添加记忆要点（如「用户叫小明，是 TA 青梅竹马」）
   - 可编辑 / 删除
   - **✨ 从最近对话自动总结为记忆**：调用大模型把对话提炼成记忆要点写入，后续对话 AI 会自动读取
   - 系统在生成回复时把记忆注入提示词，AI 因此记住人物关系与剧情细节。
8. **上下文记忆**：默认记住最近 30 轮（可在设置调），AI 不会轻易「失忆」。
9. **会话管理**：新建 / 删除会话 / 清空上下文。
10. **防跳出人设**：系统提示词强制 AI 代入角色、禁止道德说教、禁止反复提醒「这是虚构」，支持日常/恋爱/脑洞剧情沉浸式演绎。
11. **主题**：右上角 🌗 切换暗色/亮色。

---

## 七、手机安装（两种方式）

### 方式 A：PWA「添加到主屏幕」（推荐，零成本）

1. 让手机与运行后端的电脑在**同一局域网**。
2. 电脑启动后端时用 `--host 0.0.0.0`，并确认防火墙放行 8000 端口。
3. 手机浏览器访问 `http://<电脑局域网IP>:8000`（如 `http://192.168.1.20:8000`）。
   - 同局域网用 IP 访问时，部分浏览器要求 **HTTPS** 才会弹出「安装」提示。
     最简方案：用任意内网穿透/反向代理套一层 HTTPS，或直接用 Cloudflare Tunnel / ngrok 等。
4. 浏览器菜单 → **「添加到主屏幕」**（Android Chrome / iOS Safari 均支持），即可像 App 一样全屏使用。

> 说明：本项目已内置 `manifest.json` + `sw.js`，满足 PWA 安装条件。纯局域网 IP 下部分浏览器安装提示受 HTTPS 限制，属浏览器安全策略，非代码问题。

### 方式 B：打包成真正 APK（可选，需 Node 环境）

如需不上浏览器的原生安装包，可用 Capacitor 把 `frontend/` 包成 Android/iOS App：

```bash
npm init -y && npm i @capacitor/core @capacitor/cli @capacitor/android
npx cap init "沉浸对话" "com.example.aichat"
# 把 frontend 内容放进 www/，或修改 capacitor.config.ts 的 webDir 指向 frontend
npx cap add android
npx cap sync
# 用 Android Studio 打开 android/ 项目，连接手机或模拟器，Build → APK
```

前端通过相对路径 `/api` 调用后端，打包时把 `server` 指向你的后端地址（局域网 IP 或公网 HTTPS 域名）即可。

---

## 八、后端接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/login` | 登录（返回 token）|
| POST | `/api/logout` | 退出登录（吊销 token）|
| GET | `/api/me` | 获取当前登录用户名与管理员状态 |
| GET | `/api/users` | 用户列表（仅管理员）|
| GET | `/api/users/:id` | 用户详情 + 数据统计（仅管理员）|
| POST | `/api/users` | 新增用户（仅管理员）|
| PUT | `/api/users/:id` | 修改任意用户信息/密码/角色（仅管理员）|
| DELETE | `/api/users/:id` | 删除用户（仅管理员，不能删 admin）|
| GET | `/api/users/:id/activity` | 用户操作日志（仅管理员）|
| GET | `/api/users/:id/characters` | 某用户创建的角色（仅管理员）|
| GET | `/api/users/:id/conversations` | 某用户的会话（仅管理员）|
| PUT | `/api/users/me/password` | 修改当前用户密码 |
| GET | `/api/health` | 健康检查（无需鉴权）|
| GET/PUT | `/api/config` | 读取/更新全局配置 |
| POST | `/api/test` | 测试对话/图像模型连接（支持分别测试） |
| GET | `/api/characters` | 角色卡列表 |
| POST/GET/PUT/DELETE | `/api/characters[/:id]` | 角色增删改查 |
| POST | `/api/characters/import` | 导入角色卡 |
| GET | `/api/characters/:id/export` | 导出角色卡 |
| GET/POST/PUT/DELETE | `/api/characters/:id/memories[/:mid]` | 记忆管理 |
| GET/POST | `/api/conversations` | 会话列表/新建 |
| GET/DELETE | `/api/conversations/:id` | 会话详情/删除 |
| POST | `/api/conversations/:id/clear` | 清空上下文 |
| PUT | `/api/conversations/:id/background` | 设置会话聊天背景 |
| POST | `/api/conversations/:id/summarize` | 自动总结记忆 |
| POST | `/api/conversations/:id/portrait` | 生成人物当前状态图描述/图片 |
| POST | `/api/chat` | 流式对话（SSE：`delta`/`done`/`inner`/`summary`/`error`）|

---

## 九、常见问题

- **打开页面后对话一直报错？** 多半是模型没配好。先到「设置」填好 API 地址/模型，点「测试连接」。
- **登录不上？** 默认账户 admin / 密码 nxb03070；若改过密码请在 `backend/app.db` 的 `users` 表重置。
- **打开页面没有登录屏、直接看到主界面但接口报 401？** 这是旧版 Service Worker 缓存了旧前端。按 `Ctrl+F5`（或 `Ctrl+Shift+R`）强制刷新；若仍不行，在浏览器开发者工具 → Application → Service Workers → 点击「Unregister」，然后清空缓存再刷新。
- **主界面右上角 👤 按钮有什么用？** 显示当前登录用户，点击可快速退出；未登录时会回到登录屏。
- **本地 Ollama 连不上？** 确认 `ollama run <模型>` 能跑；后端 `api_base` 填 `http://localhost:11434/v1`；若后端与本机 Ollama 同机，`localhost` 即可，跨机用 IP。
- **心理活动 / 状态图不出现？** 这两者都依赖大模型调用（多一次请求），请确保模型接口可用；状态图出图还需在设置中填写「图像生成 API 地址」（OpenAI 兼容），否则只返回文字描述。
- **记忆不生效？** 记忆仅对「该角色」生效，新建对话后会随提示词注入；可用「从对话自动总结」批量写入。每 50 条消息也会自动总结前文。
- **数据存哪？** 全部在 `backend/app.db`（SQLite，含账户/角色/记忆/会话/消息/操作日志）。后端每次启动会自动备份到 `backend/backups/app.bak`，即使误操作也可手动恢复。角色卡导出为 JSON 可备份。
- **重新运行代码后数据丢失？** 正常情况下不会丢失。数据库使用 backend 目录下的 `app.db` 绝对路径，与你在哪个目录执行 uvicorn 无关；且每次启动都会先备份。若你确实发现数据没了，请检查是否手动删除过 `app.db`，或从 `backend/backups/app.bak` 恢复：先停止服务，把 `backups/app.bak` 复制为 `app.db`，再重启。
