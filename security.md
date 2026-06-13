# 聊天室系统安全分析报告

> **分析日期**: 2026-06-07
> **分析对象**: Chat Room 聊天室系统（server.py / server_async.py / server_improved.py / client.py / stress_test.py）

---

## 目录

1. [SQL 注入](#1-sql-注入)
2. [密码存储安全](#2-密码存储安全)
3. [反序列化攻击（Pickle）](#3-反序列化攻击pickle)
4. [拒绝服务攻击（DDoS/DoS）](#4-拒绝服务攻击ddosdos)
5. [路径遍历（文件服务器）](#5-路径遍历文件服务器)
6. [无加密通信](#6-无加密通信)
7. [敏感信息泄露](#7-敏感信息泄露)
8. [身份认证缺陷](#8-身份认证缺陷)
9. [全局变量竞态条件](#9-全局变量竞态条件)
10. [AI 机器人调用风险](#10-ai-机器人调用风险)
11. [总结与修复建议](#11-总结与修复建议)

---

## 1. SQL 注入

### 当前状态
服务器在数据库操作中使用了**参数化查询**（`?` 占位符），有效防止了 SQL 注入。

```python
# 已使用参数化查询（安全）
sql = "SELECT user_name, password FROM user_msg WHERE user_name = ? and password = ?"
cursor.execute(sql, [login_msg[1], login_msg[2]])
```

### 风险评级：✅ 低
所有 SQL 操作均使用参数化查询，不存在直接的 SQL 注入漏洞。

---

## 2. 密码存储安全

### 当前状态
**密码以明文存储在 SQLite 数据库中**，这是本系统最严重的安全问题之一。

```python
# server.py L56 - 创建表时 password 直接存储明文
"CREATE TABLE IF NOT EXISTS user_msg( user_name TEXT NOT NULL UNIQUE, password TEXT NOT NULL, ...)"

# server.py L402 - 注册时直接存储明文密码
sql = "INSERT INTO user_msg (user_name,password) VALUES(?,?)"
cursor.execute(sql, [login_msg[1], login_msg[2]])
```

### 风险评级：🔴 严重
- 数据库被窃取后，所有用户密码直接泄露
- 用户可能在其他平台使用相同密码，导致撞库攻击
- SQLite 数据库文件 `user_message.db` 无加密保护

### 建议
- 使用 `bcrypt` 或 `argon2` 对密码进行哈希存储
- 示例：
  ```python
  import bcrypt
  hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
  cursor.execute("INSERT INTO user_msg (user_name, password) VALUES(?,?)", 
                 [username, hashed])
  ```

---

## 3. 反序列化攻击（Pickle）

### 当前状态
系统中大量使用 `pickle.loads()` 来反序列化从网络接收的数据。

```python
# server.py L355, L421 - 直接从网络接收并反序列化
login_msg = pickle.loads(login_msg)
data = pickle.loads(conn.recv(msg_len))
```

### 风险评级：🔴 严重
`pickle` 反序列化可以执行任意代码。攻击者构造恶意 pickle 数据包即可远程执行代码（RCE），完全控制服务器。

### 漏洞利用示例
```python
# 攻击者可以构造如下 payload 实现 RCE
import pickle
import os

class Exploit:
    def __reduce__(self):
        return (os.system, ('rm -rf /',))

payload = pickle.dumps(Exploit())
```

### 建议
- 使用 `JSON` 替代 `pickle` 进行网络数据传输
- 如必须使用 `pickle`，需在反序列化前验证数据来源（如 HMAC 签名）

---

## 4. 拒绝服务攻击（DDoS/DoS）

### 4.1 连接限制缺失

**server.py** - 无任何连接限制：
```python
# server.py L456-460 - 无限接受连接，每连接一个线程
while True:
    conn, addr = self.socket.accept()
    recv_thread = threading.Thread(target=self.recv_msg, args=(conn, addr))
    recv_thread.start()
```

**server_improved.py** - 仅有线程池限制（100线程）：
```python
# server_improved.py - 100线程限制，但无 IP 级别限制
MAX_THREADS = 100
thread_pool = ThreadPoolExecutor(max_workers=MAX_THREADS)
```

### 风险评级：🔴 严重
- 无连接速率限制
- 无 IP 黑名单/白名单
- 无单 IP 最大连接数限制
- server.py 创建无限线程，系统资源可被快速耗尽
- 固定头部 1024 字节的填充机制加剧带宽消耗

### 4.2 消息大小未限制

```python
# server.py L354 - 客户端声明任意大小，服务器直接分配
msg_len = int(msg_len.decode())
login_msg = conn.recv(msg_len)  # 可导致内存耗尽
```

### 4.3 文件服务器无大小限制

```python
# server.py L520-529 - 无限接收文件数据
with open(fileName, 'wb') as f:
    while True:
        data = conn.recv(1024)
        if data == 'EOF'.encode():
            break
        f.write(data)  # 可写满磁盘
```

### 建议
- 添加连接速率限制（如 `ratelimit` 库）
- 限制单 IP 最大连接数（如 5）
- 限制消息最大长度（如 64KB）
- 限制文件上传大小（如 100MB）
- 使用 `semaphore` 限制并发连接数
- 添加连接超时

---

## 5. 路径遍历（文件服务器）

### 当前状态
文件服务器的 `cd` 和 `get/put` 操作存在路径遍历漏洞。

```python
# server.py L504-505 - 用户提供文件名，直接拼接路径
name = message.split()[1]  # 用户可控
fileName = r'./' + name     # 路径遍历：get ../../../etc/passwd

# server.py L537-541 - cd 命令可切换到任意目录
message = message.split()[1]
f = r'./' + message
os.chdir(f)  # cd ../../
```

### 风险评级：🔴 严重
攻击者可以读取/写入服务器任意文件：
- `get ../../../etc/passwd` — 读取系统密码文件
- `put ../../../Windows/System32/evil.dll` — 写入恶意文件
- `cd ../../` — 切换出 resources 目录

### 建议
- 使用 `os.path.realpath()` 验证路径是否在允许范围内
- 禁止文件名包含 `..` 或 `/` 开头
- 示例：
  ```python
  import os
  safe_path = os.path.realpath(os.path.join(BASE_DIR, name))
  if not safe_path.startswith(BASE_DIR):
      raise PermissionError("Path traversal detected")
  ```

---

## 6. 无加密通信

### 当前状态
所有网络通信均使用**明文 TCP**，无 TLS/SSL 加密。

```python
# server.py L120 - 使用普通 socket
self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
```

### 风险评级：🟡 中
- 密码、消息内容在网络中明文传输
- 局域网内可被嗅探拦截
- 但在本地/局域网环境下风险可控

### 建议
- 使用 `ssl.wrap_socket()` 包装 socket
- 或使用 WebSocket + WSS 作为传输协议
- 至少对密码字段进行加密传输

---

## 7. 敏感信息泄露

### 发现的问题

**7.1 登录/注册错误信息过于详细**
```python
# server.py L364-364 - 返回 "Repeated Login" 暴露用户是否存在
conn.send("Repeated Login".encode())

# server.py L410 - 返回 "Repeated Sign Up"
conn.send("Repeated Sign Up".encode())
```
攻击者可通过枚举用户名判断哪些用户已注册。

**7.2 完整的路径信息泄露**
```python
# server.py L543-548 - 向客户端发送完整工作路径
path = os.getcwd().split('\\')
```
攻击者可了解服务器文件系统结构。

**7.3 日志可能记录敏感信息**
```python
# server.py L376 - 日志记录明文密码验证过程
logger.info(f"用户 {login_msg[1]} 从 {addr} 登录成功")
```

### 风险评级：🟡 中

### 建议
- 错误信息统一为"用户名或密码错误"
- 不要在日志中记录敏感信息
- 路径信息不要直接发送给客户端

---

## 8. 身份认证缺陷

### 当前状态
- 无会话 Token 机制
- 无登录失败次数限制
- 无密码复杂度要求
- 用户名过于简单时也可注册
- 无二次验证

```python
# server.py L399-413 - 注册无任何校验
sql = "INSERT INTO user_msg (user_name,password) VALUES(?,?)"
cursor.execute(sql, [login_msg[1], login_msg[2]])
# 允许空密码、超短密码
```

### 风险评级：🟡 中

### 建议
- 添加密码复杂度策略（最少8位，包含字母+数字）
- 登录失败 5 次后临时锁定（如 15 分钟）
- 添加会话 Token 管理

---

## 9. 全局变量竞态条件

### 当前状态
多个全局变量在多个线程间共享，存在竞态条件。

```python
# server.py L32 - conversation_history 被所有用户共享
conversation_history = []

# server.py L71 - 所有用户与机器人的对话混在一起
conversation_history.append({"role": "user", "content": question})
```

这意味着**所有用户与 AI 机器人的对话历史是共享的**，用户 A 可以看到用户 B 之前的对话上下文。

### 风险评级：🟡 中
- 用户间可能意外泄露对话内容
- 机器人回复可能包含其他用户的信息

### 建议
- 为每个用户维护独立的 `conversation_history`
- 使用字典 `{user_id: history}` 存储

---

## 10. AI 机器人调用风险

### 当前状态
机器人通过本地 Ollama API 调用，请求体未做安全过滤。

```python
# server.py L74-78 - 用户问题直接传递给 AI 模型
payload = {
    "model": "deepseek-r1",
    "messages": conversation_history,
    "stream": True,
}
```

### 风险评级：✅ 低
- Ollama API 在本地运行（localhost），外部不可访问
- 但应注意 prompt 注入攻击：用户可能通过精心构造的 prompt 让 AI 泄露系统信息

---

## 11. 总结与修复建议

### 风险矩阵

| 漏洞类别 | 风险等级 | 影响范围 |
|---------|---------|---------|
| 密码明文存储 | 🔴 严重 | 所有用户 |
| Pickle 反序列化 RCE | 🔴 严重 | 服务器 |
| 路径遍历 | 🔴 严重 | 服务器文件系统 |
| 无连接限制（DDoS） | 🔴 严重 | 服务器可用性 |
| 无加密通信 | 🟡 中 | 用户数据 |
| 信息泄露 | 🟡 中 | 用户隐私 |
| 身份认证缺陷 | 🟡 中 | 账号安全 |
| 全局变量竞态 | 🟡 中 | 对话隐私 |
| SQL 注入 | ✅ 安全 | — |
| AI 调用 | ✅ 安全 | — |

### 优先级修复建议

| 优先级 | 修复项 | 预估难度 |
|-------|--------|---------|
| P0 | 用 JSON 替代 Pickle 序列化 | 简单 |
| P0 | 对密码进行 bcrypt 哈希存储 | 简单 |
| P0 | 文件服务器添加路径验证 | 简单 |
| P1 | 添加连接频率限制和超时 | 中等 |
| P1 | 限制单 IP 连接数 | 简单 |
| P1 | 限制消息/文件大小 | 简单 |
| P2 | 分离用户的对话历史 | 简单 |
| P2 | 统一登录错误提示信息 | 简单 |
| P3 | 添加 TLS/SSL 加密 | 复杂 |
| P3 | 添加会话 Token 管理 | 中等 |

### 核心安全加固示例代码

```python
# 1. 密码哈希（替代明文存储）
import bcrypt

def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())

def verify_password(password: str, hashed: bytes) -> bool:
    return bcrypt.checkpw(password.encode(), hashed)

# 2. JSON 替代 Pickle（防止 RCE）
import json

# 发送
data = json.dumps({"type": "text", "content": msg, "target": user}).encode()
conn.send(str(len(data)).encode())
conn.send(data)

# 接收
msg_len = int(conn.recv(1024).decode())
data = json.loads(conn.recv(msg_len).decode())

# 3. 路径遍历防护
import os

BASE_DIR = os.path.realpath("resources")

def safe_path(filename: str) -> str:
    full_path = os.path.realpath(os.path.join(BASE_DIR, filename))
    if not full_path.startswith(BASE_DIR):
        raise PermissionError("路径访问被拒绝")
    return full_path

# 4. 连接限流
from collections import defaultdict
import time

connection_counter = defaultdict(list)
MAX_CONNECTIONS_PER_IP = 5
WINDOW_SECONDS = 60

def check_rate_limit(ip: str) -> bool:
    now = time.time()
    connection_counter[ip] = [t for t in connection_counter[ip] 
                               if now - t < WINDOW_SECONDS]
    if len(connection_counter[ip]) >= MAX_CONNECTIONS_PER_IP:
        return False
    connection_counter[ip].append(now)
    return True
```

---

*本报告基于对源代码的静态分析，可能无法覆盖所有安全问题。建议定期进行安全审计和渗透测试。*