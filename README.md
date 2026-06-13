<div align="center">

# 💬 Chat Room

**A Full-Featured Encrypted Python Chat Room** · Real-time Messaging · File Transfer · AI Chatbot

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-0078D4)]()
[![SSL](https://img.shields.io/badge/Communication-SSL%2FTLS%20Encrypted-brightgreen)]()

[**中文版**](README_CN.md) · [**English**](#)

</div>

---

## ✨ Features

- **🔒 End-to-End Security** — SSL/TLS encrypted communication with PBKDF2-SHA256 password hashing
- **💬 Real-time Chat** — Instant messaging over TCP sockets with millisecond latency
- **👥 Online User Management** — Live user list with real-time status updates
- **📁 File Transfer** — Built-in file server for upload and download
- **🤖 AI Chatbot** — Local LLM integration via Ollama API
- **📹 Voice/Video Call Invitation** — Send voice and video call requests
- **👨‍👩‍👧‍👦 Group Chat** — Create groups and send group messages
- **🎨 Rich Message Display** — Emoji support
- **👤 User System** — Signup/login, avatar upload, profile editing, account deletion
- **🧪 Stress Testing** — Built-in concurrency testing tool

## 🏗️ Architecture

```
┌─────────────────┐       SSL/TLS        ┌──────────────────┐
│   client.py     │ ◄──────────────────► │   server.py      │
│  (Tkinter GUI)  │     Encrypted TCP    │  (Chat Server)   │
└─────────────────┘                      └────────┬─────────┘
                                                   │
                             ┌─────────────────────┼─────────────────────┐
                             │                     │                     │
                             ▼                     ▼                     ▼
                     ┌──────────────┐    ┌──────────────┐    ┌─────────────────┐
                     │  SQLite DB   │    │  File Server │    │   Ollama AI     │
                     │  User Data   │    │  File Xfer   │    │   Chatbot API   │
                     └──────────────┘    └──────────────┘    └─────────────────┘
```

### Components

| Component | File | Description |
|-----------|------|-------------|
| **Chat Server** | `server.py` | Multi-threaded TCP server handling message routing, user management & database operations |
| **File Server** | `server.py` (built-in) | Standalone file transfer service supporting upload, download & directory listing |
| **Client** | `client.py` | Tkinter GUI client with Markdown rendering, emoji & file transfer |
| **AI Service** | `server.py` (integrated) | Local LLM integration via Ollama API |

## 🚀 Quick Start

### Prerequisites

- Python **3.11+**
- [Ollama](https://ollama.ai/) (optional, required for AI chatbot; pull a model like `llama3.2:1b`)

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/QimoFang/Chat-Room.git
cd Chat-Room

# 2. Install dependencies
pip install -r requirements.txt
```

### Running

#### 1. Start the Server

```bash
python server.py
```

The server listens on port `50000` by default and auto-creates `user_message.db` on first run.

#### 2. Start the Client

```bash
python client.py
```

Launch the login screen, sign up, and start chatting.

> **First time**: If SSL certificates are missing, run `python generate_cert.py` first to generate self-signed certificates.

## 📋 Feature Details

### 👤 User System

| Feature | Description |
|---------|-------------|
| **Sign Up** | Register with username, password and avatar |
| **Login** | Login with duplicate session detection |
| **Profile Edit** | Update username, password and avatar |
| **Delete Account** | One-click account deletion |

### 💬 Messaging

- **Private Chat** — Select an online user to send private messages
- **Group Chat** — Create groups, invite members & send group messages
- **Emoji** — Built-in emoji picker

### 🤖 AI Chatbot

- Integrated with local Ollama LLMs
- Multi-turn conversation context support
- Configurable model selection

## 🛠️ Tech Stack

| Technology | Purpose |
|------------|---------|
| **Python** | Primary language |
| **Tkinter** | Graphical user interface |
| **Socket + SSL** | Encrypted network communication |
| **SQLite3** | User data persistence |
| **Threading** | Concurrency handling |
| **Pillow (PIL)** | Image processing |
| **Ollama API** | AI chatbot integration |
| **MarkdownIt** | Markdown rendering |

## 📂 Project Structure

```
chat-room/
├── server.py              Main server (chat + file service)
├── client.py              Main client (Tkinter GUI)
├── client2.py             Alternative client (TinUI)
├── emojo.py               Emoji module
├── generate_cert.py       SSL cert generator
├── stress_test.py         Stress testing tool
├── requirements.txt       Dependencies
├── resources/             File server resource directory
├── font/                  Font files
├── icon/                  Icon resources
└── icons/                 UI icons
```

## 🧪 Stress Testing

Built-in stress testing tool for simulating concurrent multi-user scenarios:

```bash
python stress_test.py
```

Configurable concurrent clients and message counts. Reports include response time statistics (min/max/avg/median/P95/P99) and throughput analysis.

## 📜 License

This project is open-sourced under the [MIT License](LICENSE). Feel free to use and contribute.

<div align="center">
  <p>If you find this project helpful, please ⭐ Star it!</p>
  <p>For questions or suggestions, please open an <a href="https://github.com/QimoFang/Chat-Room/issues">Issue</a></p>
  <p><a href="README_CN.md">中文版</a></p>
</div>