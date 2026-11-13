#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EazyTunnel v1.2.0 —— 单隧道多服务调度器 + TCP/UDP 双协议
                         + 旁路监控 + FRP 创建指引 + 内置 frpc 启动器
                         + frpc 输出自动识别公网地址（IP特征+频次投票）
"""

import asyncio
import ipaddress
import json
import os
import queue
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

APP_NAME = "EazyTunnel"
APP_VERSION = "1.2.0"
APP_ID = "EazyTunnel.App.1.2"

# ============================ 路径（兼容 PyInstaller） ============================
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

CONFIG_FILE = APP_DIR / "config.json"
SERVICES_FILE = APP_DIR / "services.json"

DEFAULT_LISTEN_PORT = 25565

DEFAULT_ADVANCED = {
    "idle_timeout": 3600.0,
    "connect_timeout": 10.0,
    "drain_timeout": 30.0,
    "max_connections": 256,
    "privileged_port_max": 1023,
    "read_size": 65536,
    "udp_session_timeout": 120.0,
}

PRESET_SERVICES = [
    ("Minecraft Java 版", 25565, "联机游戏", "tcp"),
    ("Minecraft 局域网（随机端口）", 40000, "联机游戏", "tcp"),
    ("Minecraft 基岩版", 19132, "联机游戏", "udp"),
    ("泰拉瑞亚 Terraria", 7777, "联机游戏", "tcp"),
    ("英灵神殿 Valheim", 2456, "联机游戏", "udp"),
    ("异星工厂 Factorio", 34197, "联机游戏", "tcp"),
    ("幻兽帕鲁 Palworld", 8211, "联机游戏", "udp"),
    ("七日杀 7 Days to Die", 26900, "联机游戏", "udp"),
    ("Rust", 28015, "联机游戏", "udp"),
    ("饥荒联机版 DST", 10999, "联机游戏", "udp"),
    ("星露谷物语", 24642, "联机游戏", "tcp"),
    ("僵尸毁灭工程", 16261, "联机游戏", "tcp"),
    ("卫戍协议：盟约", 3000, "联机游戏", "tcp"),
    ("Node.js 开发服务器", 3000, "Web / 开发", "tcp"),
    ("Vite 开发服务器", 5173, "Web / 开发", "tcp"),
    ("Python Flask", 5000, "Web / 开发", "tcp"),
    ("Python Django", 8000, "Web / 开发", "tcp"),
    ("Spring Boot", 8080, "Web / 开发", "tcp"),
    ("Nginx / HTTP（特权）", 80, "Web / 开发", "tcp"),
    ("HTTPS（特权）", 443, "Web / 开发", "tcp"),
    ("Windows RDP", 3389, "远程访问", "tcp"),
    ("VNC", 5900, "远程访问", "tcp"),
    ("SSH（特权）", 22, "远程访问", "tcp"),
    ("MySQL", 3306, "数据库", "tcp"),
    ("PostgreSQL", 5432, "数据库", "tcp"),
    ("Redis", 6379, "数据库", "tcp"),
    ("MongoDB", 27017, "数据库", "tcp"),
    ("自定义", 0, "其他", "tcp"),
]

DEFAULT_SERVICES = [
    {"name": "Minecraft Java 版", "port": 25565, "protocol": "tcp"},
    {"name": "Stronghold Protocol", "port": 3000, "protocol": "tcp"},
    {"name": "Minecraft 基岩版", "port": 19132, "protocol": "udp"},
]

ALLOWED_TARGET_HOSTS = {"127.0.0.1", "localhost", "::1"}
LISTEN_HOSTS = {
    "127.0.0.1（仅本机，推荐）": "127.0.0.1",
    "0.0.0.0（局域网可访问，谨慎）": "0.0.0.0",
}

ACCENT = "#2fa572"
ACCENT_HOVER = "#3dbb84"
DANGER = "#c0392b"
DANGER_HOVER = "#d64536"
MONITOR = "#3498db"
UDP_COLOR = "#9b59b6"

SEM_ACQUIRE_TIMEOUT = 5.0
LOG_MAX_LINES = 1000
MONITOR_INTERVAL = 2.0


# ============================ 工具 ============================
def validate_port(port, name="端口", privileged_max=1023):
    if not isinstance(port, int):
        raise ValueError(f"{name} 必须是整数")
    if privileged_max > 0 and port <= privileged_max:
        raise ValueError(
            f"{name} 不能使用 1-{privileged_max} 系统保留端口（可在高级设置中调整）")
    if port > 65535:
        raise ValueError(f"{name} 超出 65535")
    return port


def normalize_target_host(host):
    h = host.strip().lower()
    if h in ALLOWED_TARGET_HOSTS:
        return h
    try:
        ip = ipaddress.ip_address(h)
        if ip.is_loopback:
            return str(ip)
    except ValueError:
        pass
    raise ValueError(f"目标必须是本机回环，拒绝 {host!r}")


def normalize_protocol(p):
    p = (p or "tcp").strip().lower()
    return p if p in ("tcp", "udp") else "tcp"


def make_icon(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1],
                        radius=max(8, size // 4), fill=ACCENT)
    cx, cy = size / 2, size / 2
    arrow_len = size * 0.28
    head = size * 0.10
    line_w = max(3, size // 14)
    gap = size * 0.13
    y1 = cy - gap
    d.line([cx - arrow_len, y1, cx + arrow_len, y1], fill="white", width=line_w)
    d.polygon([(cx + arrow_len + head, y1),
               (cx + arrow_len - head * 0.3, y1 - head),
               (cx + arrow_len - head * 0.3, y1 + head)], fill="white")
    y2 = cy + gap
    d.line([cx - arrow_len, y2, cx + arrow_len, y2], fill="white", width=line_w)
    d.polygon([(cx - arrow_len - head, y2),
               (cx - arrow_len + head * 0.3, y2 - head),
               (cx - arrow_len + head * 0.3, y2 + head)], fill="white")
    return img


# ============================ 公网地址识别 ============================
_NON_TLD = {
    "exe", "log", "txt", "json", "toml", "ini", "yaml", "yml", "go", "js",
    "mjs", "cjs", "ts", "tsx", "jsx", "py", "md", "zip", "tar", "gz", "cfg",
    "conf", "bak", "tmp", "pid", "lock", "db", "sqlite", "bin", "dat", "xml",
    "html", "htm", "css", "png", "jpg", "jpeg", "gif", "svg", "ico", "mp3",
    "mp4", "wav", "ogg", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "vue", "svelte", "wasm", "map",
}

_LOCAL_SUFFIXES = (
    ".localhost", ".local", ".lan", ".internal", ".intranet",
    ".corp", ".home", ".test", ".invalid", ".example", ".arpa",
)

_RE_SCHEME_URL = re.compile(
    r'\b(?:https?|tcp|udp)://([A-Za-z0-9][A-Za-z0-9.\-]*)(?::(\d{1,5}))?',
    re.I)

_RE_BRACKET_IPV6 = re.compile(r'\[([0-9a-fA-F:]+)\](?::(\d{1,5}))?')

_RE_HOST_PORT = re.compile(
    r'(?<![\w.\-/])([A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]|\d+)(?::(\d{1,5}))'
    r'(?![\d])')

_RE_BARE_DOMAIN = re.compile(
    r'(?<![\w.\-/])([A-Za-z0-9][A-Za-z0-9\-]*'
    r'(?:\.[A-Za-z0-9][A-Za-z0-9\-]*)*'
    r'\.[A-Za-z]{2,24})'
    r'(?![\w.\-])')


def _is_public_ip(ip):
    if ip.version == 4:
        return not (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        )
    return ip.is_global and not (ip.is_multicast or ip.is_loopback)


def _is_public_host(host):
    if not host:
        return False
    h = host.strip().strip(".").lower()
    if not h:
        return False
    if h == "localhost" or h.endswith(_LOCAL_SUFFIXES):
        return False
    try:
        ip = ipaddress.ip_address(h.strip("[]"))
        return _is_public_ip(ip)
    except ValueError:
        pass
    if "." not in h:
        return False
    tld = h.rsplit(".", 1)[1]
    if not tld.isalpha() or not (2 <= len(tld) <= 24):
        return False
    if tld in _NON_TLD:
        return False
    return True


def _normalize(host, port, bracket=False):
    host = (host or "").strip().strip(".")
    if not _is_public_host(host.strip("[]")):
        return None
    host = host.lower()
    if bracket and not host.startswith("["):
        host = f"[{host}]"
    if port is None:
        return host
    try:
        p = int(port)
    except (TypeError, ValueError):
        return None
    if not (1 <= p <= 65535):
        return None
    return f"{host}:{p}"


def extract_candidates(line):
    if not line:
        return []
    results = []
    for m in _RE_SCHEME_URL.finditer(line):
        n = _normalize(m.group(1), m.group(2))
        if n:
            results.append(n)
    stripped = _RE_SCHEME_URL.sub(" ", line)

    for m in _RE_BRACKET_IPV6.finditer(stripped):
        n = _normalize(m.group(1), m.group(2), bracket=True)
        if n:
            results.append(n)

    for m in _RE_HOST_PORT.finditer(stripped):
        n = _normalize(m.group(1), m.group(2))
        if n:
            results.append(n)

    stripped2 = _RE_HOST_PORT.sub(" ", stripped)
    for m in _RE_BARE_DOMAIN.finditer(stripped2):
        n = _normalize(m.group(1), None)
        if n:
            results.append(n)

    seen = set()
    out = []
    for r in results:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


class AddressVoter:
    def __init__(self, preferred_port=None):
        self.counter = Counter()
        self.first_seen = {}
        self.lock = threading.Lock()
        self.preferred_port = str(preferred_port) if preferred_port else None

    def set_preferred_port(self, port):
        with self.lock:
            self.preferred_port = str(port) if port else None

    def feed(self, line):
        cands = extract_candidates(line)
        if not cands:
            return
        now = time.time()
        with self.lock:
            for c in cands:
                self.counter[c] += 1
                if c not in self.first_seen:
                    self.first_seen[c] = now

    def best(self):
        with self.lock:
            if not self.counter:
                return None
            if self.preferred_port:
                hit = [a for a in self.counter
                       if a.endswith(f":{self.preferred_port}")]
                if len(hit) == 1:
                    return hit[0]
                if len(hit) > 1:
                    hit.sort(key=lambda a: (-self.counter[a],
                                            self.first_seen.get(a, 0)))
                    if self.counter[hit[0]] > self.counter[hit[1]]:
                        return hit[0]
            ranked = sorted(
                self.counter.items(),
                key=lambda kv: (-kv[1], self.first_seen.get(kv[0], 0)))
            top_addr, top_n = ranked[0]
            if len(ranked) == 1:
                return top_addr
            return top_addr if top_n > ranked[1][1] else None


def try_parse_frpc_config_full(cmd, cwd):
    """返回 (addr_or_None, remote_port_or_None)。"""
    try:
        args = shlex.split(cmd, posix=False) if os.name == "nt" else shlex.split(cmd)
    except Exception:
        return (None, None)
    args = [a.strip('"') for a in args]

    cfg_path = None
    for i, a in enumerate(args):
        if a in ("-c", "--config") and i + 1 < len(args):
            cfg_path = args[i + 1]; break
        if a.startswith("-c=") or a.startswith("--config="):
            cfg_path = a.split("=", 1)[1]; break
    if not cfg_path:
        return (None, None)

    p = Path(cfg_path)
    if not p.is_absolute():
        p = Path(cwd) / p
    if not p.exists():
        return (None, None)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return (None, None)

    server_addr = None
    remote_port = None

    m = re.search(r'^\s*serverAddr\s*=\s*"([^"]+)"', text, re.M)
    if m:
        server_addr = m.group(1)
    else:
        m = re.search(r'^\s*server_addr\s*=\s*(\S+)', text, re.M)
        if m:
            server_addr = m.group(1)

    m = re.search(r'^\s*remotePort\s*=\s*(\d+)', text, re.M)
    if m:
        remote_port = m.group(1)
    else:
        m = re.search(r'^\s*remote_port\s*=\s*(\d+)', text, re.M)
        if m:
            remote_port = m.group(1)

    addr = None
    if server_addr and remote_port and _is_public_host(server_addr):
        addr = f"{server_addr}:{remote_port}"
    return (addr, remote_port)


# ============================ FRP 创建指引 ============================
FRP_GUIDE_TEMPLATE = {
"自建 frps（官方 frp）": """\
前置：一台有公网 IP 的服务器运行 frps。

① VPS 上准备 frps.toml：
   bindPort = 7000
   auth.method = "token"
   auth.token = "你的token"

② 启动 frps：./frps -c frps.toml

③ 本机创建 frpc.toml：
   serverAddr = "VPS 公网 IP"
   serverPort = 7000
   auth.method = "token"
   auth.token = "你的token"

   [[proxies]]
   name = "eazytunnel"
   type = "tcp"                  # 转 UDP 服务时改 "udp"
   localIP = "127.0.0.1"
   localPort = {listen_port}
   remotePort = 想要的公网端口

④ 本机启动：frpc -c frpc.toml
   填进 EazyTunnel「FRP 客户端」页的启动命令，
   程序会读配置文件里的 serverAddr + remotePort 自动填入地址。

⑤ 玩家连接：VPS 公网 IP:remotePort
""",

"SakuraFrp（樱花内网穿透）": """\
创建隧道 > 选择节点 > 选择类型 > 填写端口 > 保存

① 注册并登录 sakurafrp.com
② 创建隧道 > 选择节点
③ 隧道类型：TCP 或 UDP（必须与游戏协议一致）
④ 本地 IP 填 127.0.0.1
⑤ 本地端口填 {listen_port}
⑥ 远程端口：自动分配或手动填
⑦ 保存后下载 SakuraFrp 启动器
⑧ 启动器会打印「隧道 xxx 已启动，映射地址为: xxx」
   EazyTunnel 会自动识别并填入「玩家连接」页

注意：使用自家启动器，不能通过 EazyTunnel 的启动命令直接跑。
""",

"cpolar": """\
创建隧道 > 选择类型 > 填写本地地址 > 创建

① 注册并登录 cpolar.com
② 创建隧道 > 选择「TCP」或「UDP」
③ 本地地址填 127.0.0.1:{listen_port}
④ 创建后得到 x.tcp.cpolar.top:端口
⑤ 客户端会打印「Forwarding tcp://... -> 127.0.0.1:...」，
   EazyTunnel 会从含 -> 的那一行提取箭头左侧地址

注意：使用自家客户端，不能通过 EazyTunnel 启动命令直接跑。
""",

"通用要点（任何 frp 服务）": """\
不管用哪家 frp，核心步骤：

    创建隧道 > 选择 TCP / UDP 类型
              > 本地地址填 127.0.0.1:{listen_port}
              > 拿到公网地址
              > 分享给玩家

协议选择：

  MC Java / Terraria / HTTP / SSH    → TCP
  MC 基岩版 / Valheim / Palworld     → UDP

公网地址自动识别：

  EazyTunnel 从 frpc 每行输出里提取所有「像地址」的串，
  用 IP 特征过滤掉本机、私网、保留地址和假域名，
  剩下的按出现次数投票，反复出现的那个就是真地址。

  官方 frpc 不打印公网 IP，程序会读 frpc.toml / frpc.ini
  里的 serverAddr + remotePort，并用 remotePort 作为投票优先项，
  从而在 serverAddr:serverPort 和 serverAddr:remotePort 中
  正确选出后者。

  你手动改过地址后，自动识别不再覆盖；点「重新启用自动识别」可恢复。
""",
}


# ============================ TCP 转发核心 ============================
class TcpForwarder:
    def __init__(self, listen_host, listen_port, initial_target_port, log_fn, cfg):
        if listen_host not in ("127.0.0.1", "0.0.0.0", "localhost", "::1"):
            raise ValueError(f"不支持的监听地址: {listen_host!r}")
        self.cfg = dict(cfg)
        pm = self.cfg["privileged_port_max"]
        self.listen_host = listen_host
        self.listen_port = validate_port(listen_port, "监听端口", pm)
        self.target_host = "127.0.0.1"
        self.target_port = validate_port(initial_target_port, "目标端口", pm)
        if self.listen_port == self.target_port:
            raise ValueError("监听端口与目标端口相同（应进入监控模式）")
        self.log = log_fn
        self._stop_event = None
        self._server = None
        self._sem = None
        self._active = set()

    @property
    def active_count(self):
        return len(self._active)

    def switch_target(self, port):
        port = validate_port(port, "目标端口", self.cfg["privileged_port_max"])
        if port == self.target_port:
            return 0
        old = self.target_port
        closed = 0
        for w in list(self._active):
            self._safe_close(w); closed += 1
        self._active.clear()
        self.target_port = port
        self.log(f"↻ 目标 {old} → {port}，断开 {closed} 个旧连接")
        return closed

    async def _handle(self, c_reader, c_writer):
        peer = c_writer.get_extra_info("peername")
        peer_ip = peer[0] if peer else "unknown"
        target_port = self.target_port
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=SEM_ACQUIRE_TIMEOUT)
        except asyncio.TimeoutError:
            self.log(f"! 拒绝 {peer_ip}：并发已满（{self.cfg['max_connections']}）")
            self._safe_close(c_writer); return
        try:
            await self._forward(c_reader, c_writer, peer_ip, target_port)
        finally:
            self._sem.release()

    async def _forward(self, c_reader, c_writer, peer_ip, target_port):
        self.log(f"+ 连接 {peer_ip} → 127.0.0.1:{target_port}")
        self._active.add(c_writer)
        try:
            r_reader, r_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.target_host, target_port, limit=self.cfg["read_size"]),
                timeout=self.cfg["connect_timeout"])
        except asyncio.TimeoutError:
            self.log(f"! 连接 127.0.0.1:{target_port} 超时")
            self._safe_close(c_writer); self._active.discard(c_writer); return
        except Exception as e:
            self.log(f"! 连接 127.0.0.1:{target_port} 失败: {e}")
            self._safe_close(c_writer); self._active.discard(c_writer); return

        self._active.add(r_writer)
        for w in (c_writer, r_writer):
            sock = w.get_extra_info("socket")
            if sock:
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass

        tasks = [
            asyncio.create_task(self._pipe(c_reader, r_writer)),
            asyncio.create_task(self._pipe(r_reader, c_writer)),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for w in (c_writer, r_writer):
            self._active.discard(w)
            self._safe_close(w)
        self.log(f"- 断开 {peer_ip}")

    async def _pipe(self, reader, writer):
        try:
            while True:
                data = await asyncio.wait_for(
                    reader.read(self.cfg["read_size"]),
                    timeout=self.cfg["idle_timeout"])
                if not data:
                    break
                writer.write(data)
                await asyncio.wait_for(writer.drain(),
                                       timeout=self.cfg["drain_timeout"])
        except asyncio.TimeoutError:
            self.log("! 空闲或写阻塞超时，断开")
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        except Exception as e:
            self.log(f"! 管道异常: {e}")
        finally:
            try:
                if writer.can_write_eof():
                    writer.write_eof()
            except Exception:
                pass

    @staticmethod
    def _safe_close(writer):
        try:
            writer.close()
        except Exception:
            pass

    async def serve(self):
        self._stop_event = asyncio.Event()
        self._sem = asyncio.Semaphore(self.cfg["max_connections"])
        try:
            self._server = await asyncio.start_server(
                self._handle, self.listen_host, self.listen_port,
                reuse_address=True, limit=self.cfg["read_size"])
        except OSError as e:
            self.log(f"! 无法监听 TCP {self.listen_host}:{self.listen_port}: {e}")
            return
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        self.log(f"✔ TCP 监听 {addrs} → 127.0.0.1:{self.target_port}")
        try:
            async with self._server:
                await self._stop_event.wait()
        finally:
            for w in list(self._active):
                self._safe_close(w)
            self._active.clear()
            self.log("TCP 转发已停止")

    def stop(self):
        if self._stop_event:
            self._stop_event.set()


# ============================ UDP 转发核心 ============================
class _UdpSession(asyncio.DatagramProtocol):
    def __init__(self, forwarder, source_addr):
        self.forwarder = forwarder
        self.source_addr = source_addr

    def datagram_received(self, data, addr):
        self.forwarder._reply_to_source(self.source_addr, data)

    def error_received(self, exc):
        pass


class _UdpMain(asyncio.DatagramProtocol):
    def __init__(self, forwarder):
        self.forwarder = forwarder

    def connection_made(self, transport):
        self.forwarder._transport = transport

    def datagram_received(self, data, addr):
        self.forwarder._on_datagram(data, addr)

    def error_received(self, exc):
        pass


class UdpForwarder:
    def __init__(self, listen_host, listen_port, initial_target_port, log_fn, cfg):
        if listen_host not in ("127.0.0.1", "0.0.0.0", "localhost", "::1"):
            raise ValueError(f"不支持的监听地址: {listen_host!r}")
        self.cfg = dict(cfg)
        pm = self.cfg["privileged_port_max"]
        self.listen_host = listen_host
        self.listen_port = validate_port(listen_port, "监听端口", pm)
        self.target_host = "127.0.0.1"
        self.target_port = validate_port(initial_target_port, "目标端口", pm)
        if self.listen_port == self.target_port:
            raise ValueError("UDP 模式下监听端口不能与目标端口相同")
        self.log = log_fn
        self.session_timeout = float(self.cfg.get("udp_session_timeout", 120.0))

        self._transport = None
        self.sessions = {}
        self._pending = set()
        self._loop = None
        self._stop_event = None
        self._cleanup_task = None

    @property
    def active_count(self):
        return len(self.sessions)

    def switch_target(self, port):
        port = validate_port(port, "目标端口", self.cfg["privileged_port_max"])
        if port == self.target_port:
            return 0
        old = self.target_port
        closed = len(self.sessions)
        for addr in list(self.sessions.keys()):
            self._close_session(addr)
        self.target_port = port
        self.log(f"↻ UDP 目标 {old} → {port}，断开 {closed} 个会话")
        return closed

    async def serve(self):
        self._stop_event = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        try:
            self._transport, _ = await self._loop.create_datagram_endpoint(
                lambda: _UdpMain(self),
                local_addr=(self.listen_host, self.listen_port))
        except OSError as e:
            self.log(f"! 无法监听 UDP {self.listen_host}:{self.listen_port}: {e}")
            return
        self.log(f"✔ UDP 监听 {self.listen_host}:{self.listen_port} → "
                 f"127.0.0.1:{self.target_port}")
        self.log(f"  会话空闲超时 {int(self.session_timeout)}s")
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        try:
            await self._stop_event.wait()
        finally:
            if self._cleanup_task:
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
            for addr in list(self.sessions.keys()):
                self._close_session(addr)
            try:
                if self._transport is not None:
                    self._transport.close()
            except Exception:
                pass
            self.log("UDP 转发已停止")

    def _on_datagram(self, data, addr):
        now = time.time()
        if addr in self.sessions:
            transport, _ = self.sessions[addr]
            try:
                transport.sendto(data)
                self.sessions[addr] = (transport, now)
            except Exception:
                self._close_session(addr)
            return
        if addr in self._pending:
            return
        self._pending.add(addr)
        asyncio.create_task(self._create_session(addr, data))

    async def _create_session(self, addr, first_data):
        try:
            transport, _ = await self._loop.create_datagram_endpoint(
                lambda: _UdpSession(self, addr),
                remote_addr=(self.target_host, self.target_port))
            self.sessions[addr] = (transport, time.time())
            transport.sendto(first_data)
            self.log(f"+ 连接 {addr[0]}:{addr[1]}")
        except Exception as e:
            self.log(f"! 创建 UDP 会话失败 {addr}: {e}")
        finally:
            self._pending.discard(addr)

    def _reply_to_source(self, source_addr, data):
        if self._transport is None or self._transport.is_closing():
            return
        try:
            self._transport.sendto(data, source_addr)
        except Exception:
            pass

    def _close_session(self, addr):
        if addr in self.sessions:
            transport, _ = self.sessions.pop(addr)
            try:
                transport.close()
            except Exception:
                pass
            self.log(f"- 断开 {addr[0]}:{addr[1]}")

    async def _cleanup_loop(self):
        interval = min(10.0, max(2.0, self.session_timeout / 6.0))
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass
            now = time.time()
            expired = [a for a, (_, t) in list(self.sessions.items())
                       if now - t > self.session_timeout]
            for a in expired:
                self._close_session(a)

    def stop(self):
        if self._stop_event:
            self._stop_event.set()


# ============================ 旁路监控 ============================
class PortMonitor:
    def __init__(self, port, log_fn):
        self.port = port
        self.log = log_fn
        self._stop_event = None
        self._prev_peers = set()
        self._psutil = None
        self.latest_count = 0
        self.latest_available = False

    async def run(self):
        self._stop_event = asyncio.Event()
        try:
            import psutil
            self._psutil = psutil
        except ImportError:
            self._psutil = None

        self.log(f"⚠ 监控模式：监听端口 {self.port} = 目标端口")
        self.log(f"  端口已被本地服务占用，EazyTunnel 不绑定、不转发")
        self.log(f"  frpc 的 localPort 直接填 {self.port}，数据不经过本程序")
        if self._psutil is None:
            self.log(f"  psutil 未安装，看不到连接事件（pip install psutil）")

        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self._scan)
            except Exception as e:
                self.log(f"! 扫描异常: {e}")
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=MONITOR_INTERVAL)
            except asyncio.TimeoutError:
                pass
        self.log("监控已停止")

    def _scan(self):
        if self._psutil is None:
            self.latest_available = False
            return
        psutil = self._psutil
        try:
            conns = psutil.net_connections(kind="tcp")
        except Exception:
            self.latest_available = False
            return
        peers = set()
        for c in conns:
            if c.laddr and c.laddr.port == self.port \
                    and c.status == psutil.CONN_ESTABLISHED and c.raddr:
                peers.add(f"{c.raddr.ip}:{c.raddr.port}")
        for p in sorted(peers - self._prev_peers):
            self.log(f"+ 连接 {p}")
        for p in sorted(self._prev_peers - peers):
            self.log(f"- 断开 {p}")
        self._prev_peers = peers
        self.latest_available = True
        self.latest_count = len(peers)

    def stop(self):
        if self._stop_event:
            self._stop_event.set()


# ============================ frpc 启动器 ============================
class FrpcRunner:
    def __init__(self, log_fn, on_stop, on_addr_found=None):
        self.log = log_fn
        self.on_stop = on_stop
        self.on_addr_found = on_addr_found
        self.proc = None
        self._reader_thread = None
        self._lock = threading.Lock()
        self._voter = AddressVoter()
        self._last_emitted = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def prepare_for_start(self, preferred_port=None):
        self._voter = AddressVoter(preferred_port=preferred_port)
        self._last_emitted = None

    def start(self, cmd, cwd):
        with self._lock:
            if self.running:
                self.log("! frpc 已在运行"); return False
            try:
                if os.name == "nt":
                    args = [a.strip('"') for a in shlex.split(cmd, posix=False)]
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP
                    if hasattr(subprocess, "CREATE_NO_WINDOW"):
                        flags |= subprocess.CREATE_NO_WINDOW
                    self.proc = subprocess.Popen(
                        args, cwd=str(cwd),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                        bufsize=1, creationflags=flags)
                else:
                    args = shlex.split(cmd)
                    self.proc = subprocess.Popen(
                        args, cwd=str(cwd),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                        bufsize=1, start_new_session=True)
            except FileNotFoundError:
                self.log(f"! 找不到可执行文件：{cmd}"); return False
            except Exception as e:
                self.log(f"! frpc 启动失败：{e}"); return False

            self._reader_thread = threading.Thread(
                target=self._read_output, args=(self.proc,), daemon=True)
            self._reader_thread.start()
            self.log(f"✔ frpc 已启动（PID {self.proc.pid}）")
            return True

    def _read_output(self, proc):
        try:
            if proc.stdout:
                for line in proc.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    self.log(f"[frpc] {line}")
                    self._voter.feed(line)
                    best = self._voter.best()
                    if best and best != self._last_emitted:
                        self._last_emitted = best
                        if self.on_addr_found:
                            self.on_addr_found(best)
        except Exception as e:
            self.log(f"! 读取 frpc 输出异常：{e}")
        finally:
            try:
                code = proc.wait()
            except Exception:
                code = "?"
            self.log(f"[frpc] 进程已退出（code {code}）")
            with self._lock:
                self.proc = None
            self.on_stop()

    def stop(self, timeout=3.0):
        with self._lock:
            proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True, timeout=timeout)
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception as e:
            self.log(f"! 停止 frpc 异常：{e}")


# ============================ 服务编辑对话框 ============================
class ServiceDialog(ctk.CTkToplevel):
    def __init__(self, parent, title, name="", port="", protocol="tcp"):
        super().__init__(parent)
        self.title(title)
        self.geometry("440x560")
        self.resizable(False, False)
        self.result = None
        self.transient(parent)
        self.after(80, self.grab_set)

        ctk.CTkLabel(self, text=title, font=("", 16, "bold")).pack(pady=(18, 12))
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="x", padx=24)

        ctk.CTkLabel(body, text="从预设快速填入（可输入筛选）", anchor="w",
                     text_color=("#666", "#aaa")).pack(fill="x")
        labels = [f"[{cat}] {n} · {p} · {proto.upper()}"
                  for n, p, cat, proto in PRESET_SERVICES]
        self.preset_var = tk.StringVar(value="")
        self._preset_combo = ctk.CTkComboBox(
            body, values=labels, variable=self.preset_var,
            height=34, command=self._apply_preset)
        self._preset_combo.pack(fill="x", pady=(4, 12))
        self._preset_combo.set("")

        ctk.CTkLabel(body, text="服务名称", anchor="w").pack(fill="x")
        self.name_var = tk.StringVar(value=name)
        ctk.CTkEntry(body, textvariable=self.name_var, height=34).pack(
            fill="x", pady=(4, 12))

        ctk.CTkLabel(body, text="目标端口（1-65535）", anchor="w").pack(fill="x")
        self.port_var = tk.StringVar(value=str(port) if port else "")
        ctk.CTkEntry(body, textvariable=self.port_var, height=34).pack(
            fill="x", pady=(4, 12))

        ctk.CTkLabel(body, text="协议", anchor="w").pack(fill="x")
        self.protocol_var = tk.StringVar(value=normalize_protocol(protocol).upper())
        ctk.CTkSegmentedButton(
            body, values=["TCP", "UDP"], variable=self.protocol_var,
            height=32, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER).pack(fill="x", pady=(4, 4))

        ctk.CTkLabel(
            body,
            text="TCP：MC Java、Terraria、Web 服务。\n"
                 "UDP：MC 基岩版、Valheim、Palworld、Rust 等。\n"
                 "切换协议后记得同步修改 frpc 的 type 字段。",
            font=("", 10), text_color=("#888", "#777"), anchor="w",
            wraplength=380, justify="left").pack(fill="x", pady=(0, 8))

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.pack(fill="x", padx=24, pady=12)
        ctk.CTkButton(btn, text="取消", width=100, height=34,
                      fg_color="transparent", border_width=1,
                      command=self.destroy).pack(side="right")
        ctk.CTkButton(btn, text="确定", width=100, height=34,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._submit).pack(side="right", padx=(0, 8))

        self.bind("<Return>", lambda e: self._submit())
        self.bind("<Escape>", lambda e: self.destroy())

    def _apply_preset(self, choice):
        for n, p, cat, proto in PRESET_SERVICES:
            if f"[{cat}] {n} · {p} · {proto.upper()}" == choice:
                if n == "自定义":
                    self.name_var.set(""); self.port_var.set("")
                    self.protocol_var.set("TCP")
                else:
                    self.name_var.set(n); self.port_var.set(str(p))
                    self.protocol_var.set(proto.upper())
                return

    def _submit(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("错误", "名称不能为空", parent=self); return
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("错误", "端口必须是整数", parent=self); return
        if not (1 <= port <= 65535):
            messagebox.showerror("错误", "端口范围 1-65535", parent=self); return
        self.result = {
            "name": name,
            "port": port,
            "protocol": self.protocol_var.get().lower(),
        }
        self.destroy()

    def wait(self):
        self.wait_window()
        return self.result


# ============================ 高级参数对话框 ============================
class AdvancedDialog(ctk.CTkToplevel):
    FIELDS = [
        ("idle_timeout", "空闲超时（秒，TCP）", "TCP 单向多少秒无数据断开"),
        ("connect_timeout", "连接超时（秒）", "TCP 连接目标端口多久放弃"),
        ("drain_timeout", "写阻塞超时（秒）", "对端不读数据时最多等多久"),
        ("max_connections", "TCP 并发上限", "同时处理的 TCP 连接总数"),
        ("udp_session_timeout", "UDP 会话超时（秒）",
         "UDP 来源多久没包就回收其会话"),
        ("privileged_port_max", "保留端口上限", "低于此值禁止；0 = 全放开"),
        ("read_size", "读块大小（字节）", "单次读取最大字节数，≥1024"),
    ]

    def __init__(self, parent, config):
        super().__init__(parent)
        self.title("高级设置")
        self.geometry("500x680")
        self.resizable(False, False)
        self.result = None
        self.transient(parent)
        self.after(80, self.grab_set)

        ctk.CTkLabel(self, text="高级参数", font=("", 16, "bold")).pack(pady=(18, 4))
        ctk.CTkLabel(self, text="修改后需重新启动生效",
                     font=("", 11), text_color=("#888", "#777")).pack(pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        self.vars = {}
        for key, label, hint in self.FIELDS:
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=6)
            ctk.CTkLabel(row, text=label, anchor="w",
                         font=("", 12, "bold")).pack(fill="x")
            ctk.CTkLabel(row, text=hint, anchor="w", font=("", 10),
                         text_color=("#777", "#888"),
                         wraplength=420, justify="left").pack(fill="x")
            v = tk.StringVar(value=str(config.get(key, DEFAULT_ADVANCED[key])))
            self.vars[key] = v
            ctk.CTkEntry(row, textvariable=v, height=32).pack(fill="x", pady=(4, 0))

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.pack(fill="x", padx=20, pady=(8, 16))
        ctk.CTkButton(btn, text="恢复默认", width=110, height=36,
                      fg_color="transparent", border_width=1,
                      command=self._reset).pack(side="left")
        ctk.CTkButton(btn, text="取消", width=80, height=36,
                      fg_color="transparent", border_width=1,
                      command=self.destroy).pack(side="right")
        ctk.CTkButton(btn, text="保存", width=80, height=36,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._submit).pack(side="right", padx=(0, 8))

    def _reset(self):
        for key, v in self.vars.items():
            v.set(str(DEFAULT_ADVANCED[key]))

    def _submit(self):
        result = {}
        for key, v in self.vars.items():
            raw = v.get().strip()
            default = DEFAULT_ADVANCED[key]
            try:
                val = int(raw) if isinstance(default, int) else float(raw)
            except ValueError:
                messagebox.showerror("错误", f"{key} 格式错误", parent=self); return
            if val < 0:
                messagebox.showerror("错误", f"{key} 不能为负数", parent=self); return
            result[key] = val
        if result["max_connections"] < 1:
            messagebox.showerror("错误", "并发上限至少为 1", parent=self); return
        if result["read_size"] < 1024:
            messagebox.showerror("错误", "读块大小至少为 1024", parent=self); return
        if not (0 <= result["privileged_port_max"] <= 65535):
            messagebox.showerror("错误", "保留端口上限范围 0-65535", parent=self); return
        if result["idle_timeout"] < 1 or result["connect_timeout"] < 0.1 \
                or result["drain_timeout"] < 0.1 or result["udp_session_timeout"] < 1:
            messagebox.showerror("错误", "超时参数过小", parent=self); return
        self.result = result
        self.destroy()

    def wait(self):
        self.wait_window()
        return self.result


# ============================ FRP 创建指引对话框 ============================
class FrpGuideDialog(ctk.CTkToplevel):
    def __init__(self, parent, listen_port):
        super().__init__(parent)
        self.title("FRP 隧道创建指引")
        self.geometry("780x720")
        self.minsize(680, 560)
        self.transient(parent)
        self._listen_port = listen_port
        self.after(80, self.grab_set)

        ctk.CTkLabel(self, text="FRP 隧道创建指引",
                     font=("", 18, "bold")).pack(pady=(16, 4))
        ctk.CTkLabel(
            self,
            text=f"以下所有「本地端口」都填 {listen_port}（= EazyTunnel 监听端口）",
            font=("", 12), text_color=("#555", "#aaa")).pack(pady=(0, 10))

        tabs = ctk.CTkTabview(
            self, segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_HOVER)
        tabs.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        self._tabs = tabs

        for name, text in FRP_GUIDE_TEMPLATE.items():
            tab = tabs.add(name)
            box = ctk.CTkTextbox(tab, font=("Consolas", 12), wrap="word",
                                 fg_color=("#f5f5f5", "#141414"), corner_radius=8)
            box.pack(fill="both", expand=True, padx=6, pady=6)
            box.insert("1.0", text.format(listen_port=listen_port))
            box.configure(state="disabled")

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(btn, text="复制当前页", width=120, height=36,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._copy_current).pack(side="left")
        ctk.CTkButton(btn, text="关闭", width=80, height=36,
                      fg_color="transparent", border_width=1,
                      command=self.destroy).pack(side="right")

    def _copy_current(self):
        name = self._tabs.get()
        self.clipboard_clear()
        self.clipboard_append(FRP_GUIDE_TEMPLATE[name].format(
            listen_port=self._listen_port))
        messagebox.showinfo("已复制", "当前页内容已复制到剪贴板", parent=self)


# ============================ 服务卡片 ============================
class ServiceCard(ctk.CTkFrame):
    def __init__(self, master, service, index, selected, on_click):
        super().__init__(
            master, corner_radius=10, height=64,
            fg_color=("#1e3a2c", "#1e2d24") if selected else ("#f0f0f0", "#262626"),
            border_width=2 if selected else 0, border_color=ACCENT)
        self.pack_propagate(False)
        self.index = index
        self._on_click = on_click
        proto = normalize_protocol(service.get("protocol"))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=14, pady=10)
        ctk.CTkLabel(row, text="●", width=18, font=("", 14),
                     text_color=ACCENT if selected else "#5a5a5a").pack(side="left")
        ctk.CTkLabel(row, text=service["name"],
                     font=("", 13, "bold"), anchor="w").pack(
            side="left", fill="x", expand=True, padx=(6, 0))
        ctk.CTkLabel(row, text=proto.upper(),
                     font=("Consolas", 10, "bold"),
                     text_color=UDP_COLOR if proto == "udp" else "#888"
                     ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(row, text=f":{service['port']}", font=("Consolas", 13),
                     text_color="#8a8a8a").pack(side="right")

        self._bind_click(self)

    def _bind_click(self, w):
        w.bind("<Button-1>", lambda e: self._on_click(self.index, False))
        w.bind("<Double-Button-1>", lambda e: self._on_click(self.index, True))
        for c in w.winfo_children():
            self._bind_click(c)


# ============================ 主窗口 ============================
class App:
    def __init__(self, root):
        self.root = root
        self.log_queue = queue.Queue()
        self.thread = None
        self.loop = None
        self.forwarder = None
        self.monitor = None
        self.monitor_mode = False
        self.current_protocol = "tcp"
        self.running = False
        self.services = self._load_services()
        self._saved_window = None
        self._saved_frpc_cmd = ""
        self._saved_public_addr = ""
        self.advanced = self._load_config()
        self.selected_index = 0
        self.cards = []
        self._last_monitor_key = None

        self._public_addr_source = "empty"
        self._programmatic_set = False

        self.frpc_runner = FrpcRunner(
            log_fn=self.log_queue.put,
            on_stop=lambda: self.log_queue.put("__FRPC_STOPPED__"),
            on_addr_found=lambda a: self.log_queue.put(("__ADDR_FOUND__", a)),
        )

        self._apply_geometry()
        self._build_ui()

        # 首次启动确保配置文件落盘（此时 UI 控件已就绪）
        if not CONFIG_FILE.exists():
            self._save_config()
        if not SERVICES_FILE.exists():
            self._save_services()

        self._pump_logs()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _apply_geometry(self):
        if self._saved_window:
            try:
                m = re.match(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)",
                             self._saved_window)
                if m:
                    w, h = int(m.group(1)), int(m.group(2))
                    x, y = int(m.group(3)), int(m.group(4))
                    sw = self.root.winfo_screenwidth()
                    sh = self.root.winfo_screenheight()
                    if w <= sw and h <= sh and -w + 100 < x < sw - 100 \
                            and -h + 100 < y < sh - 100:
                        self.root.geometry(self._saved_window); return
            except Exception:
                pass
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(1060, sw - 80)
        h = min(760, sh - 100)
        x = max(0, (sw - w) // 2)
        y = max(20, (sh - h) // 2 - 20)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ---------- 持久化 ----------
    def _load_services(self):
        try:
            if SERVICES_FILE.exists():
                data = json.loads(SERVICES_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    for s in data:
                        s["protocol"] = normalize_protocol(s.get("protocol"))
                    return data
        except Exception:
            pass
        return [dict(s) for s in DEFAULT_SERVICES]

    def _save_services(self):
        try:
            SERVICES_FILE.write_text(
                json.dumps(self.services, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            self.log_queue.put(f"! 保存服务列表失败: {e}")

    def _load_config(self):
        self._saved_window = None
        self._saved_frpc_cmd = ""
        self._saved_public_addr = ""
        try:
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(data.get("_window_geometry"), str):
                    self._saved_window = data["_window_geometry"]
                if isinstance(data.get("_frpc_command"), str):
                    self._saved_frpc_cmd = data["_frpc_command"]
                if isinstance(data.get("_public_address"), str):
                    self._saved_public_addr = data["_public_address"]
                cfg = dict(DEFAULT_ADVANCED)
                for k in DEFAULT_ADVANCED:
                    if k in data:
                        default = DEFAULT_ADVANCED[k]
                        cfg[k] = int(data[k]) if isinstance(default, int) \
                            else float(data[k])
                return cfg
        except Exception:
            pass
        return dict(DEFAULT_ADVANCED)

    def _save_config(self):
        try:
            data = dict(self.advanced)
            try:
                data["_window_geometry"] = self.root.geometry()
            except Exception:
                pass
            if hasattr(self, "frpc_cmd_var"):
                data["_frpc_command"] = self.frpc_cmd_var.get()
            if hasattr(self, "public_addr_var"):
                data["_public_address"] = self.public_addr_var.get()
            CONFIG_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            self.log_queue.put(f"! 保存配置失败: {e}")

    # ---------- 构建界面 ----------
    def _build_ui(self):
        self.root.grid_columnconfigure(0, weight=0, minsize=420)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self.root, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=14)
        left.grid_rowconfigure(1, weight=1); left.grid_columnconfigure(0, weight=1)

        right = ctk.CTkFrame(self.root, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=14)
        right.grid_rowconfigure(0, weight=1); right.grid_columnconfigure(0, weight=1)

        self._build_entry_section(left)
        self._build_service_section(left)
        self._build_status_card(left)
        self._build_control_bar(left)

        self.right_tabs = ctk.CTkTabview(
            right, segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_HOVER)
        self.right_tabs.grid(row=0, column=0, sticky="nsew")
        self.right_tabs.add("运行日志")
        self.right_tabs.add("FRP 客户端")
        self.right_tabs.add("玩家连接")

        self._build_log_tab(self.right_tabs.tab("运行日志"))
        self._build_frp_tab(self.right_tabs.tab("FRP 客户端"))
        self._build_connect_tab(self.right_tabs.tab("玩家连接"))

        self.listen_var.trace_add("write", lambda *_: self._refresh_frp_text())

    def _section(self, parent, title, actions=None):
        frame = ctk.CTkFrame(parent, corner_radius=12,
                             fg_color=("#ffffff", "#1c1c1c"))
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(header, text=title, font=("", 13, "bold"),
                     anchor="w", text_color=("#555", "#a0a0a0")).pack(side="left")
        if actions:
            for label, cmd, primary in actions:
                ctk.CTkButton(
                    header, text=label, width=72, height=24,
                    fg_color=ACCENT if primary else "transparent",
                    hover_color=ACCENT_HOVER if primary else ("#ddd", "#333"),
                    border_width=0 if primary else 1,
                    command=cmd).pack(side="right", padx=(4, 0))
        return frame

    def _build_entry_section(self, parent):
        sec = self._section(parent, "隧道入口（frpc 指向这里）",
                            actions=[("高级", self.open_advanced, False)])
        sec.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        body = ctk.CTkFrame(sec, fg_color="transparent")
        body.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkLabel(body, text="监听地址", anchor="w",
                     text_color=("#666", "#b0b0b0")).pack(fill="x")
        self.listen_host_var = tk.StringVar(value=list(LISTEN_HOSTS.keys())[0])
        self._host_menu = ctk.CTkOptionMenu(
            body, values=list(LISTEN_HOSTS.keys()),
            variable=self.listen_host_var, height=34,
            fg_color=("#e8e8e8", "#2d2d2d"),
            button_color=("#d0d0d0", "#383838"),
            text_color=("#222", "#eaeaea"))
        self._host_menu.pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(body, text="监听端口（= frpc localPort）",
                     anchor="w", text_color=("#666", "#b0b0b0")).pack(fill="x")
        self.listen_var = tk.StringVar(value=str(DEFAULT_LISTEN_PORT))
        self._listen_entry = ctk.CTkEntry(body, textvariable=self.listen_var, height=34)
        self._listen_entry.pack(fill="x", pady=(4, 2))

        ctk.CTkLabel(
            body,
            text="协议由所选服务决定；TCP 同端口时进入监控模式",
            font=("", 10), text_color=("#888", "#777"),
            anchor="w", wraplength=380, justify="left").pack(fill="x")

    def _build_service_section(self, parent):
        sec = self._section(parent, "服务列表（同一时刻转发一个）")
        sec.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        self.service_scroll = ctk.CTkScrollableFrame(
            sec, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=("#c0c0c0", "#3a3a3a"))
        self.service_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._refresh_service_list()

        btns = ctk.CTkFrame(sec, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(btns, text="+ 添加", width=80, height=32,
                      fg_color="transparent", border_width=1,
                      command=self.add_service).pack(side="left")
        ctk.CTkButton(btns, text="编辑", width=70, height=32,
                      fg_color="transparent", border_width=1,
                      command=self.edit_service).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="删除", width=70, height=32,
                      fg_color="transparent", border_width=1,
                      command=self.delete_service).pack(side="left")

    def _build_status_card(self, parent):
        self.status_card = ctk.CTkFrame(
            parent, corner_radius=12, fg_color=("#ffffff", "#1c1c1c"))
        self.status_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        inner = ctk.CTkFrame(self.status_card, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=14)
        self._status_dot = ctk.CTkLabel(
            inner, text="●", font=("", 22), width=24, text_color="#5a5a5a")
        self._status_dot.pack(side="left")
        text_box = ctk.CTkFrame(inner, fg_color="transparent")
        text_box.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self._status_title = ctk.CTkLabel(
            text_box, text="未启动", anchor="w", font=("", 16, "bold"))
        self._status_title.pack(fill="x")
        self._status_detail = ctk.CTkLabel(
            text_box, text="选择服务后点击启动", anchor="w",
            font=("", 11), text_color=("#777", "#888"))
        self._status_detail.pack(fill="x")

    def _build_control_bar(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew")
        self.start_btn = ctk.CTkButton(
            bar, text="▶ 启动", height=40, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, font=("", 13, "bold"), command=self.start)
        self.start_btn.pack(side="left", fill="x", expand=True)
        self.stop_btn = ctk.CTkButton(
            bar, text="■ 停止", height=40, width=100,
            fg_color=DANGER, hover_color=DANGER_HOVER,
            state="disabled", command=self.stop)
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.switch_btn = ctk.CTkButton(
            bar, text="切换", height=40, width=80,
            state="disabled", command=self.switch_to_selected)
        self.switch_btn.pack(side="left", padx=(8, 0))

    def _build_log_tab(self, parent):
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", pady=(4, 4))
        ctk.CTkButton(toolbar, text="清空", width=60, height=26,
                      fg_color="transparent", border_width=1,
                      command=self._clear_log).pack(side="right")
        self.text = ctk.CTkTextbox(
            parent, font=("Consolas", 11), wrap="none",
            fg_color=("#f5f5f5", "#141414"), corner_radius=8)
        self.text.pack(fill="both", expand=True, pady=(0, 6))
        self.text.configure(state="disabled")

    def _build_frp_tab(self, parent):
        ctk.CTkLabel(parent, text="frpc 配置文件",
                     anchor="w", font=("", 12, "bold")).pack(fill="x", pady=(4, 4))
        self.frp_text = ctk.CTkTextbox(
            parent, font=("Consolas", 11), wrap="word", height=180,
            fg_color=("#f5f5f5", "#141414"), corner_radius=8)
        self.frp_text.pack(fill="both", expand=True)
        self._refresh_frp_text()

        cfg_btns = ctk.CTkFrame(parent, fg_color="transparent")
        cfg_btns.pack(fill="x", pady=(6, 8))
        ctk.CTkButton(cfg_btns, text="复制", width=70, height=28,
                      fg_color="transparent", border_width=1,
                      command=self._copy_frp).pack(side="left")
        ctk.CTkButton(cfg_btns, text="创建指引", width=90, height=28,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self.open_frp_guide).pack(side="left", padx=6)

        ctk.CTkFrame(parent, height=1,
                     fg_color=("#ddd", "#2d2d2d")).pack(fill="x", pady=(4, 8))

        ctk.CTkLabel(parent, text="frpc 启动器（仅命令行 frpc 可用）",
                     anchor="w", font=("", 12, "bold")).pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(
            parent,
            text="适用于自建 frp / 官方 frpc / cloudflared。\n"
                 "SakuraFrp、cpolar、ngrok 桌面版使用自家启动器，不适用。",
            anchor="w", font=("", 10), text_color=("#888", "#777"),
            wraplength=560, justify="left").pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(parent, text="启动命令（如 frpc -c frpc.toml）",
                     anchor="w", text_color=("#666", "#b0b0b0")).pack(fill="x")
        default_cmd = self._saved_frpc_cmd or "frpc -c frpc.toml"
        self.frpc_cmd_var = tk.StringVar(value=default_cmd)
        ctk.CTkEntry(parent, textvariable=self.frpc_cmd_var, height=34,
                     font=("Consolas", 11)).pack(fill="x", pady=(4, 8))

        launcher_row = ctk.CTkFrame(parent, fg_color="transparent")
        launcher_row.pack(fill="x", pady=(0, 4))
        self.frpc_start_btn = ctk.CTkButton(
            launcher_row, text="启动 frpc", width=100, height=34,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self.start_frpc)
        self.frpc_start_btn.pack(side="left")
        self.frpc_stop_btn = ctk.CTkButton(
            launcher_row, text="停止 frpc", width=100, height=34,
            fg_color=DANGER, hover_color=DANGER_HOVER, state="disabled",
            command=self.stop_frpc)
        self.frpc_stop_btn.pack(side="left", padx=6)
        self.frpc_status_var = tk.StringVar(value="未启动")
        ctk.CTkLabel(launcher_row, textvariable=self.frpc_status_var,
                     anchor="w", font=("", 11),
                     text_color=("#777", "#888")).pack(side="left", padx=8)

    def _build_connect_tab(self, parent):
        ctk.CTkLabel(parent, text="玩家连接地址",
                     anchor="w", font=("", 12, "bold")).pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(
            parent,
            text="从 frpc 输出自动识别公网地址并填入下方输入框；也可手动填写。",
            anchor="w", font=("", 10), text_color=("#888", "#777"),
            wraplength=560, justify="left").pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(parent, text="公网地址",
                     anchor="w", text_color=("#666", "#b0b0b0")).pack(fill="x")

        addr_row = ctk.CTkFrame(parent, fg_color="transparent")
        addr_row.pack(fill="x", pady=(4, 2))
        self.public_addr_var = tk.StringVar()
        self._public_entry = ctk.CTkEntry(
            addr_row, textvariable=self.public_addr_var,
            height=34, font=("Consolas", 11))
        self._public_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            addr_row, text="重新启用自动识别", width=140, height=34,
            fg_color="transparent", border_width=1,
            command=self._reset_addr_to_auto).pack(side="left", padx=(6, 0))

        self.addr_status_var = tk.StringVar(value="")
        ctk.CTkLabel(
            parent, textvariable=self.addr_status_var, anchor="w",
            font=("", 10), text_color=("#888", "#777"),
            wraplength=560, justify="left").pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(parent, text="游戏 / TCP 客户端",
                     anchor="w", font=("", 12, "bold"),
                     text_color=("#444", "#ccc")).pack(fill="x")
        self.mc_addr_var = tk.StringVar(value="—")
        self._build_addr_row(parent, self.mc_addr_var).pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(parent, text="浏览器 / HTTP",
                     anchor="w", font=("", 12, "bold"),
                     text_color=("#444", "#ccc")).pack(fill="x")
        self.http_addr_var = tk.StringVar(value="—")
        self._build_addr_row(parent, self.http_addr_var).pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(
            parent,
            text="提示：浏览器游戏经 frp TCP 隧道访问时地址是 http:// 开头；\n"
                 "需要 HTTPS（如「导入素材包」）请用 cloudflared 或 VPS + 反代。\n"
                 "UDP 服务不适用「浏览器 / HTTP」这一行。",
            anchor="w", font=("", 10), text_color=("#888", "#777"),
            wraplength=560, justify="left").pack(fill="x", pady=(10, 0))

        initial = self._saved_public_addr
        self._public_addr_source = "manual" if initial else "empty"
        self._programmatic_set = True
        try:
            self.public_addr_var.set(initial)
        finally:
            self._programmatic_set = False
        self._update_addr_hint()
        self._render_connect_info()
        self.public_addr_var.trace_add("write", self._on_public_addr_write)

    def _build_addr_row(self, parent, var):
        frame = ctk.CTkFrame(parent, corner_radius=8,
                             fg_color=("#f5f5f5", "#141414"))
        ctk.CTkLabel(frame, textvariable=var, anchor="w",
                     font=("Consolas", 13)).pack(
            side="left", fill="x", expand=True, padx=12, pady=10)
        ctk.CTkButton(frame, text="复制", width=60, height=26,
                      fg_color="transparent", border_width=1,
                      command=lambda: self._copy_text(var.get())).pack(
            side="right", padx=8)
        return frame

    # ---------- 公网地址逻辑 ----------
    def _on_public_addr_write(self, *args):
        self._render_connect_info()
        if self._programmatic_set:
            return
        self._public_addr_source = "manual"
        self._update_addr_hint()

    def _render_connect_info(self):
        addr = self.public_addr_var.get().strip()
        if not addr:
            self.mc_addr_var.set("—"); self.http_addr_var.set("—"); return
        for prefix in ("http://", "https://", "tcp://", "udp://"):
            if addr.lower().startswith(prefix):
                addr = addr[len(prefix):]; break
        addr = addr.rstrip("/")
        self.mc_addr_var.set(addr)
        self.http_addr_var.set(f"http://{addr}")

    def _update_addr_hint(self):
        if self._public_addr_source == "auto":
            addr = self.public_addr_var.get().strip()
            self.addr_status_var.set(f"自动识别（来自 frpc 输出）：{addr}")
        elif self._public_addr_source == "manual":
            self.addr_status_var.set("手动输入")
        else:
            self.addr_status_var.set("等待 frpc 输出自动识别；也可手动填写")

    def _handle_addr_found(self, addr):
        if not addr:
            return
        if self._public_addr_source == "manual":
            self.log_queue.put(
                f"  （识别到 frpc 公网地址 {addr}，但你手动编辑过，保持原值）")
            return
        current = self.public_addr_var.get().strip()
        if current == addr:
            return
        self._programmatic_set = True
        try:
            self.public_addr_var.set(addr)
        finally:
            self._programmatic_set = False
        self._public_addr_source = "auto"
        self._update_addr_hint()
        self.log_queue.put(f"  ✔ 自动识别 frpc 公网地址：{addr}")

    def _reset_addr_to_auto(self):
        self._public_addr_source = "empty"
        self._programmatic_set = True
        try:
            self.public_addr_var.set("")
        finally:
            self._programmatic_set = False
        self._update_addr_hint()
        self.log_queue.put("  （已清空，等待 frpc 输出重新自动识别）")

    def _copy_text(self, text):
        if not text or text == "—":
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    # ---------- frp ----------
    def _current_protocol(self):
        if 0 <= self.selected_index < len(self.services):
            return normalize_protocol(self.services[self.selected_index].get("protocol"))
        return "tcp"

    def _refresh_frp_text(self):
        if not hasattr(self, "frp_text"):
            return
        lp = self.listen_var.get().strip() or str(DEFAULT_LISTEN_PORT)
        proto = self._current_protocol()
        self.frp_text.configure(state="normal")
        self.frp_text.delete("1.0", "end")
        self.frp_text.insert(
            "1.0",
            f"# frpc 与 EazyTunnel 同机运行\n"
            f"# 协议跟随当前选中的服务：{proto.upper()}\n"
            f"# 切换服务后若协议不同，需要同步修改 type 并重启 frpc\n\n"
            f"serverAddr = \"你的frp服务器地址\"\n"
            f"serverPort = 7000\n"
            f"auth.method = \"token\"\n"
            f"auth.token = \"你的token\"\n\n"
            f"[[proxies]]\n"
            f"name = \"eazytunnel\"\n"
            f"type = \"{proto}\"\n"
            f"localIP = \"127.0.0.1\"\n"
            f"localPort = {lp}          # = EazyTunnel 监听端口\n"
            f"remotePort = 你要的公网端口\n")
        self.frp_text.configure(state="disabled")

    def _copy_frp(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.frp_text.get("1.0", "end-1c"))

    def open_frp_guide(self):
        FrpGuideDialog(self.root, self.listen_var.get().strip() or
                       str(DEFAULT_LISTEN_PORT))

    def start_frpc(self):
        cmd = self.frpc_cmd_var.get().strip()
        if not cmd:
            messagebox.showinfo("提示", "请输入 frpc 启动命令", parent=self.root)
            return
        addr, port = try_parse_frpc_config_full(cmd, APP_DIR)
        self.frpc_runner.prepare_for_start(preferred_port=port)
        if not self.frpc_runner.start(cmd, APP_DIR):
            return
        self.frpc_start_btn.configure(state="disabled")
        self.frpc_stop_btn.configure(state="normal")
        self.frpc_status_var.set("运行中")
        self.right_tabs.set("运行日志")
        if addr:
            self._handle_addr_found(addr)

    def stop_frpc(self):
        if not self.frpc_runner.running:
            return
        self.frpc_status_var.set("正在停止…")
        threading.Thread(target=self.frpc_runner.stop, daemon=True).start()

    def _on_frpc_stopped(self):
        if hasattr(self, "frpc_start_btn"):
            self.frpc_start_btn.configure(state="normal")
        if hasattr(self, "frpc_stop_btn"):
            self.frpc_stop_btn.configure(state="disabled")
        if hasattr(self, "frpc_status_var"):
            self.frpc_status_var.set("未启动")

    def _clear_log(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    # ---------- 服务列表 ----------
    def _refresh_service_list(self):
        for c in self.cards:
            c.destroy()
        self.cards.clear()
        for i, s in enumerate(self.services):
            card = ServiceCard(
                self.service_scroll, s, i,
                selected=(i == self.selected_index),
                on_click=self._on_card_click)
            card.pack(fill="x", pady=4, padx=2)
            self.cards.append(card)

    def _on_card_click(self, index, double):
        self.selected_index = index
        self._refresh_service_list()
        self._refresh_frp_text()
        if double and self.running and not self.monitor_mode:
            self.switch_to_selected()

    def add_service(self):
        r = ServiceDialog(self.root, "添加服务").wait()
        if not r:
            return
        self.services.append(r)
        self.selected_index = len(self.services) - 1
        self._save_services()
        self._refresh_service_list()
        self._refresh_frp_text()

    def edit_service(self):
        i = self.selected_index
        if not (0 <= i < len(self.services)):
            return
        cur = self.services[i]
        r = ServiceDialog(self.root, "编辑服务", cur.get("name", ""),
                          cur.get("port", ""),
                          cur.get("protocol", "tcp")).wait()
        if not r:
            return
        self.services[i] = r
        self._save_services()
        self._refresh_service_list()
        self._refresh_frp_text()

    def delete_service(self):
        i = self.selected_index
        if not (0 <= i < len(self.services)):
            return
        if len(self.services) <= 1:
            messagebox.showerror("错误", "至少保留一个服务"); return
        if not messagebox.askyesno("确认", f"删除「{self.services[i]['name']}」？"):
            return
        del self.services[i]
        self.selected_index = max(0, i - 1)
        self._save_services()
        self._refresh_service_list()
        self._refresh_frp_text()

    def open_advanced(self):
        if self.running:
            messagebox.showinfo("提示", "请先停止，再修改高级参数", parent=self.root)
            return
        r = AdvancedDialog(self.root, self.advanced).wait()
        if not r:
            return
        self.advanced = r
        self._save_config()
        messagebox.showinfo("已保存", "高级参数已保存，下次启动生效。",
                            parent=self.root)

    # ---------- 启动 / 停止 / 切换 ----------
    def start(self):
        if self.running:
            return
        i = self.selected_index
        if not (0 <= i < len(self.services)):
            messagebox.showinfo("提示", "请先选中一个服务"); return
        target = self.services[i]
        proto = normalize_protocol(target.get("protocol"))
        pm = self.advanced["privileged_port_max"]
        try:
            lp = validate_port(int(self.listen_var.get().strip()), "监听端口", pm)
            tp = validate_port(int(target["port"]), "目标端口", pm)
        except ValueError as e:
            messagebox.showerror("参数错误", str(e)); return

        if proto == "udp" and lp == tp:
            messagebox.showerror(
                "参数错误",
                f"UDP 模式下监听端口不能与目标端口相同（都是 {lp}）。")
            return

        self.running = True
        self.current_protocol = proto
        self._lock_inputs(True)
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        if proto == "tcp" and lp == tp:
            self._start_monitor(lp, target)
        elif proto == "udp":
            self._start_udp(lp, tp, target)
        else:
            self._start_tcp(lp, tp, target)

    def _start_monitor(self, port, target):
        self.monitor_mode = True
        self.switch_btn.configure(state="disabled")
        self._set_status("monitor", f"监控中 :{port}", target["name"])
        self.log_queue.put(
            f"[{APP_NAME}] TCP 端口相同（{port}），进入监控模式")
        self.log_queue.put(
            f"  frpc 的 localPort 设为 {port}，直连本地服务；本程序只观察不转发")
        self._last_monitor_key = None
        self.thread = threading.Thread(
            target=self._run_monitor, args=(port,), daemon=True)
        self.thread.start()

    def _start_tcp(self, lp, tp, target):
        self.monitor_mode = False
        self.switch_btn.configure(state="normal")
        listen_host = LISTEN_HOSTS.get(self.listen_host_var.get(), "127.0.0.1")
        if listen_host == "0.0.0.0":
            if not messagebox.askyesno(
                    "安全确认",
                    "0.0.0.0 会让同一局域网的任何设备直连监听端口。\n"
                    "只给 frpc 用的话请改回 127.0.0.1。\n\n确认继续？"):
                self.running = False
                self._lock_inputs(False)
                self.start_btn.configure(state="normal")
                self.stop_btn.configure(state="disabled")
                self._set_status("stopped", "未启动", "选择服务后点击启动")
                return
        self._set_status("running", f"TCP {listen_host}:{lp} → {tp}", target["name"])
        self.log_queue.put(
            f"[{APP_NAME}] 启动 TCP {listen_host}:{lp} → 127.0.0.1:{tp}"
            f"（{target['name']}）")
        self.thread = threading.Thread(
            target=self._run_forwarder,
            args=(listen_host, lp, tp, dict(self.advanced), "tcp"), daemon=True)
        self.thread.start()

    def _start_udp(self, lp, tp, target):
        self.monitor_mode = False
        self.switch_btn.configure(state="normal")
        listen_host = LISTEN_HOSTS.get(self.listen_host_var.get(), "127.0.0.1")
        if listen_host == "0.0.0.0":
            if not messagebox.askyesno(
                    "安全确认",
                    "0.0.0.0 会让同一局域网的任何设备直连监听端口。\n\n确认继续？"):
                self.running = False
                self._lock_inputs(False)
                self.start_btn.configure(state="normal")
                self.stop_btn.configure(state="disabled")
                self._set_status("stopped", "未启动", "选择服务后点击启动")
                return
        self._set_status("running", f"UDP {listen_host}:{lp} → {tp}", target["name"])
        self.log_queue.put(
            f"[{APP_NAME}] 启动 UDP {listen_host}:{lp} → 127.0.0.1:{tp}"
            f"（{target['name']}）")
        self.thread = threading.Thread(
            target=self._run_forwarder,
            args=(listen_host, lp, tp, dict(self.advanced), "udp"), daemon=True)
        self.thread.start()

    def stop(self):
        if not self.running:
            return
        self._set_status("stopping", "正在停止…", "")
        if self.loop:
            if self.monitor:
                self.loop.call_soon_threadsafe(self.monitor.stop)
            elif self.forwarder:
                self.loop.call_soon_threadsafe(self.forwarder.stop)

    def switch_to_selected(self):
        if not self.running or self.monitor_mode:
            return
        i = self.selected_index
        if not (0 <= i < len(self.services)):
            return
        target = self.services[i]
        new_proto = normalize_protocol(target.get("protocol"))
        if new_proto != self.current_protocol:
            messagebox.showinfo(
                "协议不同",
                f"当前正在转发 {self.current_protocol.upper()} 服务，\n"
                f"所选服务是 {new_proto.upper()}，无法直接切换。\n\n"
                f"请先停止，再重新启动。",
                parent=self.root)
            return
        tp = target["port"]
        if self.forwarder and tp == self.forwarder.target_port:
            return
        active = self.forwarder.active_count if self.forwarder else 0
        if active and not messagebox.askyesno(
                "确认切换",
                f"当前有 {active} 个活动连接，切换会全部断开。\n\n"
                f"切换到「{target['name']}」(:{tp})？"):
            return
        if self.loop and self.forwarder:
            self.loop.call_soon_threadsafe(self.forwarder.switch_target, tp)
            lp = self.listen_var.get().strip()
            self._set_status("running", f"{self.current_protocol.upper()} {lp} → {tp}",
                             target["name"])
            self._refresh_frp_text()

    def _run_forwarder(self, listen_host, lp, tp, cfg, proto):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        try:
            if proto == "udp":
                fwd = UdpForwarder(listen_host, lp, tp, self.log_queue.put, cfg)
            else:
                fwd = TcpForwarder(listen_host, lp, tp, self.log_queue.put, cfg)
        except ValueError as e:
            self.log_queue.put(f"! 启动失败：{e}")
            self.log_queue.put("__STOPPED__")
            loop.close(); self.loop = None; return
        self.forwarder = fwd
        try:
            loop.run_until_complete(fwd.serve())
        except Exception as e:
            self.log_queue.put(f"! 未捕获异常: {e}")
        finally:
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            self.loop = None
            self.forwarder = None
            self.log_queue.put("__STOPPED__")

    def _run_monitor(self, port):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        mon = PortMonitor(port, self.log_queue.put)
        self.monitor = mon
        try:
            loop.run_until_complete(mon.run())
        except Exception as e:
            self.log_queue.put(f"! 监控异常: {e}")
        finally:
            loop.close()
            self.loop = None
            self.monitor = None
            self.log_queue.put("__STOPPED__")

    def _on_stopped(self):
        self.running = False
        self.monitor_mode = False
        self.current_protocol = "tcp"
        self._last_monitor_key = None
        self._lock_inputs(False)
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.switch_btn.configure(state="disabled")
        self._set_status("stopped", "未启动", "选择服务后点击启动")

    def _lock_inputs(self, locked):
        self._listen_entry.configure(state="disabled" if locked else "normal")
        self._host_menu.configure(state="disabled" if locked else "normal")

    def _set_status(self, kind, title, detail):
        if kind == "running":
            self._status_dot.configure(
                text_color=UDP_COLOR if self.current_protocol == "udp" else ACCENT)
        elif kind == "monitor":
            self._status_dot.configure(text_color=MONITOR)
        elif kind == "stopping":
            self._status_dot.configure(text_color="#e67e22")
        else:
            self._status_dot.configure(text_color="#5a5a5a")
        self._status_title.configure(text=title)
        self._status_detail.configure(text=detail)

    def _render_monitor_stats(self):
        if not self.monitor:
            return
        port = self.monitor.port
        if not self.monitor.latest_available:
            key = ("unavailable",)
            if key != self._last_monitor_key:
                self._last_monitor_key = key
                self._status_detail.configure(
                    text=f"监控 :{port} · 连接统计不可用（psutil 未安装或权限不足）")
            return
        count = self.monitor.latest_count
        key = ("count", count)
        if key != self._last_monitor_key:
            self._last_monitor_key = key
            self._status_detail.configure(text=f"监控 :{port} · {count} 个连接")

    def _pump_logs(self):
        msgs = []
        stopped = False
        frpc_stopped = False
        addr_found = []
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(msg, tuple) and len(msg) == 2 \
                    and msg[0] == "__ADDR_FOUND__":
                addr_found.append(msg[1])
                continue
            if msg == "__STOPPED__":
                stopped = True; continue
            if msg == "__FRPC_STOPPED__":
                frpc_stopped = True; continue
            msgs.append(msg)
        if msgs:
            self.text.configure(state="normal")
            for m in msgs:
                self.text.insert("end", f"{time.strftime('%H:%M:%S')}  {m}\n")
            lines = int(self.text.index("end-1c").split(".")[0])
            if lines > LOG_MAX_LINES:
                self.text.delete("1.0", f"{lines - LOG_MAX_LINES + 1}.0")
            self.text.configure(state="disabled")
            self.text.see("end")
        for addr in addr_found:
            self._handle_addr_found(addr)
        if self.monitor:
            self._render_monitor_stats()
        if frpc_stopped:
            self._on_frpc_stopped()
        if stopped:
            self._on_stopped()
        self.root.after(100, self._pump_logs)

    # ---------- 关闭 ----------
    def on_close(self):
        # 1) 先确认，此时不动任何运行中的进程
        if self.running or self.frpc_runner.running:
            if not messagebox.askyesno(APP_NAME, "仍在运行，确定退出吗？"):
                return

        # 2) 停 frpc（同步，最多等 3 秒）
        if self.frpc_runner.running:
            self.frpc_runner.stop()

        # 3) 停转发（异步）
        if self.running:
            self.stop()

        # 4) 给事件循环一点时间清理，再统一保存 + 关窗
        def _finalize():
            self._save_config()
            self.root.destroy()

        if self.running:
            self.root.after(400, _finalize)
        else:
            _finalize()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    root.title(f"{APP_NAME} v{APP_VERSION} — 单隧道多服务调度器")
    root.minsize(900, 680)

    try:
        icon_img = make_icon(64)
        root._eazy_icon = ImageTk.PhotoImage(icon_img)
        root.iconphoto(True, root._eazy_icon)
    except Exception:
        pass

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()