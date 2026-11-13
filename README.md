# EazyTunnel 🚇
> 单隧道多服务调度器 —— 让一条 frp 隧道，接管你所有的联机游戏。

**EazyTunnel** 是一个基于 Python 和 CustomTkinter 开发的图形化本地端口转发与调度工具。它专为解决“不同游戏/服务需要开不同 frp 隧道”的痛点而生。

通过 EazyTunnel，你只需要配置**一条**固定的 frp 隧道，即可在《我的世界》、《卫戍协议》、各种 Web 开发服务器之间自由切换，无需频繁修改 frpc 配置或重启隧道。

---

## ✨ 核心特性

- **单隧道多服务**：frpc 始终指向 EazyTunnel 的监听端口，换游戏只需在 UI 里点一下「切换」。
- **TCP / UDP 双协议**：原生支持《Minecraft Java 版》（TCP）和《基岩版 / 幻兽帕鲁 / 英灵神殿》（UDP）。
- **智能同端口监控**：当监听端口与目标端口相同时（例如都在 25565），自动进入**监控模式**，不抢占端口，仅通过 `psutil` 旁路记录连接日志，完美兼容直接开服的场景。
- **frpc 内置托管**：无需打开黑色命令行窗口，直接在软件内输入启动命令，日志统一收集，关闭软件自动清理进程。
- **公网地址智能提取**：自动从 frpc 输出（或配置文件）中，利用 IP 特征与频次投票算法，精准提取服务商分配的公网 IP 和端口，一键生成玩家连接 URL。
- **高颜值深色 UI**：告别丑陋的原生 Tkinter，沉浸式深色主题，支持服务列表持久化与窗口状态记忆。

---

## 🛠️ 环境依赖

- **Python 3.8+**
- 第三方依赖库：
  ```bash
  pip install customtkinter pillow psutil
  ```
  *(注：`psutil` 为可选依赖，仅在“监控模式”下用于统计连接数)*

---

## 🚀 快速开始

### 1. 运行源码
```bash
python eazytunnel_gui.py
```

### 2. 基础使用流程
1. **配置 EazyTunnel**：
   - **监听地址**：保持 `127.0.0.1` 或 `0.0.0.0`。
   - **监听端口**：保持默认 `25565`（或任意空闲端口）。
   - **服务列表**：选择你要转发的游戏（如 `Stronghold Protocol` :3000），点击下方 **▶ 启动**。
2. **配置 frpc**：
   - 切换到右侧 **「FRP 客户端」** 页。
   - 复制生成的 `frpc.toml` / `frpc.ini` 配置，保存到本地。
   - **注意**：配置中的 `localPort` **必须**等于 EazyTunnel 的监听端口（默认 25565）。
3. **启动隧道**：
   - 在「FRP 客户端」页的启动命令框填入 `frpc -c frpc.toml`，点击 **启动 frpc**。
4. **分享地址**：
   - 切换到 **「玩家连接」** 页，程序会自动识别出公网地址，点击「复制」发给朋友即可。

---

## 🧠 两种工作模式说明

| 模式 | 触发条件 | 数据流向 | 适用场景 |
| :--- | :--- | :--- | :--- |
| **转发模式** | 监听端口 **≠** 目标端口 | 玩家 -> frps -> frpc -> **EazyTunnel** -> 本地服务 | 转《卫戍协议》(3000)、MC 局域网随机端口 (40000) 等 |
| **监控模式** | 监听端口 **=** 目标端口 | 玩家 -> frps -> frpc -> **本地服务** (EazyTunnel 不参与转发) | 纯原版 MC 开服（直接用 25565），EazyTunnel 仅提供连接日志旁路监控 |

---

## 📦 打包为 EXE (Windows)

如果你想让没有安装 Python 的朋友也能使用，可以使用 PyInstaller 打包：

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name EazyTunnel eazytunnel_gui.py
```
打包后的 `EazyTunnel.exe` 会在 `dist` 目录下。程序的 `config.json` 和 `services.json` 会自动生成在 exe 同级目录下，方便携带和修改。

---

## ❓ 常见问题排错 (FAQ)

**1. frpc 报错：`dial tcp 127.0.0.1:25565: connectex: No connection could be made because the target machine actively refused it.`**
*   **原因**：frpc 敲错门了。
*   **解决**：检查 `frpc.toml` 里的 `localPort`，确保它和 EazyTunnel 界面左上角的「监听端口」**完全一致**。

**2. 浏览器访问报错：`ERR_EMPTY_RESPONSE`（如《卫戍协议》）**
*   **原因**：隧道通了，但后端服务没返回数据。
*   **解决**：检查本地游戏是否启动；检查 `frpc` 的 `type` 是否写成了 `"tcp"`（必须是小写）；检查云服务器安全组是否放行了 `remotePort`。

**3. 网页能打开，但游戏内点不动 / 频繁掉线**
*   **原因**：WebSocket 被拦截，或 UDP 协议匹配错误。
*   **解决**：确认如果是 UDP 游戏（如基岩版），服务协议需选 UDP，且 frpc 的 `type = "udp"`。如果是网页游戏，确保反向代理支持 WebSocket 升级（EazyTunnel 纯 TCP 转发天然支持，通常问题出在云服务器防火墙或游戏自身配置）。

**4. 为什么我的地址识别没出来？**
*   **原因**：有些官方 frpc 不直接打印公网 IP。
*   **解决**：EazyTunnel 会尝试读取启动命令中 `-c` 指向的 `frpc.toml`，并用 `remotePort` 进行特征投票。如果还是没识别出来，请在「玩家连接」页手动输入 `ip:端口`。

---

## 📝 配置文件说明

程序运行后，会在同级目录自动生成两个文件，请勿在软件运行时手动修改，以免被覆盖：
- `config.json`：存储高级参数（并发限制、超时时间）、窗口位置大小、上次使用的 frpc 命令及公网地址。
- `services.json`：存储你的服务列表（名称、端口、TCP/UDP 协议）。

---

## 📄 免责声明
本项目仅供学习与交流使用。请遵守您所使用的内网穿透服务商的用户协议，切勿用于任何非法用途。
