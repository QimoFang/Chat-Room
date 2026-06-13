<div align="center">

# 💬 Chat Room

**一个功能全面的 Python 加密聊天室** · 实时消息 · 文件传输 · AI 聊天机器人

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-0078D4)]()
[![SSL](https://img.shields.io/badge/Communication-SSL%2FTLS%20Encrypted-brightgreen)]()

[**English**](README.md) · [**中文版**](#)

</div>

---

## ✨ 特性

- **🔒 端到端安全** — SSL/TLS 加密通信，PBKDF2-SHA256 密码哈希保护
- **💬 实时聊天** — 基于 TCP Socket 的即时消息收发，毫秒级延时
- **👥 在线用户管理** — 实时显示在线用户列表及状态
- **📁 文件传输** — 内置文件服务器，支持文件上传与下载
- **🤖 AI 聊天机器人** — 集成 Ollama API，支持本地大模型对话
- **📹 音视频通话邀请** — 支持语音/视频通话邀请功能
- **👨‍👩‍👧‍👦 群组聊天** — 支持群组创建与群组消息
- **🎨 丰富的消息展示** — Emoji 表情支持
- **👤 用户系统** — 注册/登录、头像上传、资料修改、账号注销
- **🧪 压力测试工具** — 内置高性能压测脚本，支持并发测试

## 🏗️ 系统架构

```
┌─────────────────┐       SSL/TLS        ┌──────────────────┐
│   client.py     │ ◄──────────────────► │   server.py      │
│  (Tkinter GUI)  │     加密 TCP 连接     │  (聊天服务器)     │
└─────────────────┘                      └────────┬─────────┘
                                                   │
                             ┌─────────────────────┼─────────────────────┐
                             │                     │                     │
                             ▼                     ▼                     ▼
                     ┌──────────────┐    ┌──────────────┐    ┌─────────────────┐
                     │  SQLite 数据库│    │  文件服务器   │    │   Ollama AI     │
                     │  用户数据存储  │    │  文件传输服务  │    │  聊天机器人 API  │
                     └──────────────┘    └──────────────┘    └─────────────────┘
```

### 组件说明

| 组件 | 文件 | 说明 |
|------|------|------|
| **聊天服务器** | `server.py` | 多线程 TCP 聊天服务器，处理消息路由、用户管理和数据库操作 |
| **文件服务器** | `server.py` (内置) | 独立的文件传输服务，支持文件上传/下载和目录浏览 |
| **客户端** | `client.py` | Tkinter GUI 客户端，支持 Markdown 渲染、表情和文件传输 |
| **AI 服务** | `server.py` (集成) | 通过 Ollama API 调用本地大语言模型 |

## 🚀 快速开始

### 前置依赖

- Python **3.11+**
- [Ollama](https://ollama.ai/)（可选，AI 聊天机器人功能需要，需拉取模型如 `llama3.2:1b`）

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/QimoFang/Chat-Room.git
cd Chat-Room

# 2. 安装依赖
pip install -r requirements.txt
```

### 运行

#### 1. 启动服务器

```bash
python server.py
```

服务器默认监听 `50000` 端口，首次运行会自动生成 `user_message.db` 数据库文件。

#### 2. 启动客户端

```bash
python client.py
```

启动后进入登录界面，注册账号即可开始聊天。

> **首次使用**：若 SSL 证书不存在，先运行 `python generate_cert.py` 生成自签名证书。

## 📋 功能详情

### 👤 用户系统

| 功能 | 说明 |
|------|------|
| **注册** | 填写用户名、密码、头像即可注册 |
| **登录** | 凭用户名和密码登录，支持重复登录检测 |
| **资料修改** | 可修改用户名、密码、头像 |
| **注销账号** | 一键注销当前账号 |

### 💬 消息系统

- **私聊** — 选择在线用户发送私密消息
- **群聊** — 创建群组，邀请成员，发送群消息
- **Emoji 表情** — 内置表情选择器

### 🤖 AI 聊天机器人

- 集成 Ollama 本地大模型
- 支持多轮对话上下文
- 可配置模型选择

## 🛠️ 技术栈

| 技术 | 用途 |
|------|------|
| **Python** | 主开发语言 |
| **Tkinter** | GUI 界面 |
| **Socket + SSL** | 加密网络通信 |
| **SQLite3** | 用户数据存储 |
| **Threading** | 并发处理 |
| **Pillow (PIL)** | 图像处理 |
| **Ollama API** | AI 聊天机器人 |
| **MarkdownIt** | Markdown 渲染 |

## 📂 项目结构

```
chat-room/
├── server.py              主服务器（聊天 + 文件服务）
├── client.py              主客户端（Tkinter GUI）
├── client2.py             备选客户端（TinUI）
├── emojo.py               表情功能模块
├── generate_cert.py       SSL 证书生成工具
├── stress_test.py         压力测试工具
├── requirements.txt       依赖清单
├── resources/             文件服务器资源目录
├── font/                  字体文件
├── icon/                  图标资源
└── icons/                 UI 图标
```

## 🧪 压力测试

内置压力测试工具，支持模拟多用户并发场景：

```bash
python stress_test.py
```

可配置并发客户端数量和消息数量，测试结果包含响应时间统计（最小/最大/平均/中位数/P95/P99）和吞吐量分析。

## 📜 开源协议

本项目基于 [MIT License](LICENSE) 开源，欢迎自由使用和贡献。

<div align="center">
  <p>如果这个项目对你有帮助，欢迎 ⭐ Star 支持！</p>
  <p>如有问题或建议，请提交 <a href="https://github.com/QimoFang/Chat-Room/issues">Issue</a></p>
  <p><a href="README.md">English Version</a></p>
</div>