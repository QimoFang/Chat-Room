# SSL/TLS 加密通信升级计划

## 概述

将聊天室系统中的所有普通 TCP Socket 通信升级为 SSL/TLS 加密通信，防止中间人攻击和数据窃听。

***

## 当前状态分析

### 涉及的 Socket 连接

| 组件                   | 文件                       | 行号                                                  | 当前实现   |
| -------------------- | ------------------------ | --------------------------------------------------- | ------ |
| ChatServer 监听 Socket | `server.py:135`          | `socket.socket(socket.AF_INET, socket.SOCK_STREAM)` | <br /> |
| ChatServer 接受连接      | `server.py:528`          | `self.socket.accept()` → 直接返回普通 `conn`              | <br /> |
| FileServer 监听 Socket | `server.py:546`          | `socket.socket(socket.AF_INET, socket.SOCK_STREAM)` | <br /> |
| FileServer 接受连接      | `server.py:659`          | `self.s.accept()` → 直接返回普通 `conn`                   | <br /> |
| 客户端连接 Socket         | `client.py:1106-1107`    | `socket.socket(...)` + `connection.connect(...)`    | <br /> |
| improved 服务器         | `server_improved.py:148` | 与 server.py 相同模式                                    | <br /> |
| async 服务器            | `server_async.py`        | 使用 asyncio，需单独处理                                    | <br /> |

### 传输协议特征

* 固定长度头部（1024字节 JSON）+ 可变长度消息体（pickle 编码）

* 文件传输使用独立的连接和协议（纯字节流 + EOF 标记）

* 登录/注册消息使用同一连接上的请求-响应模式

***

## 变更计划

### Step 1: 生成 SSL 证书

创建 `generate_cert.py` 脚本，使用 Python 的 `cryptography` 库生成自签名证书。

**输出文件：**

* `cert.pem` — SSL 证书文件

* `key.pem` — SSL 私钥文件

**依赖：** 需要 `cryptography` 库（后续通过 pip 安装）

### Step 2: 修改 `server.py` — ChatServer

在 `__init__` 中创建 SSLContext 并加载证书，在 `run()` 中对接受的连接进行 SSL 包装。

**具体修改：**

1. **新增 import:** `import ssl`
2. **修改** **`__init__`** (line 132-135): 创建 SSLContext 并加载 cert/key
3. **修改** **`run()`** (line 520-539): 在 `self.socket.accept()` 后，对 `conn` 调用 `ssl_context.wrap_socket(conn, server_side=True)`

### Step 3: 修改 `server.py` — FileServer

跳过，用户选择暂不加密文件传输。

### Step 4: 修改 `client.py`

在创建 socket 后，用 SSLContext 包装它。

**具体修改：**

1. **新增 import:** `import ssl`
2. **修改 line 1106-1107:** 创建 socket → 连接 → 用 SSLContext 包装
3. 设置 `check_hostname=False` 和 `verify_mode=ssl.CERT_NONE`（自签名证书）

### Step 6: 处理文件传输的独立连接

用户选择暂不加密文件传输，跳过此步骤。

***

## 详细修改内容

### `server.py` (ChatServer 部分)

```python
# 新增 import
import ssl

# ChatServer.__init__ 修改
def __init__(self, ip, port):
    threading.Thread.__init__(self)
    self.addr = (ip, port)
    self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # SSL 上下文
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain('cert.pem', 'key.pem')
    self.ssl_context = ssl_context

# ChatServer.run 修改
def run(self):
    try:
        self.socket.bind(self.addr)
        self.socket.listen()
        send_thread = threading.Thread(target=self.send_msg)
        send_thread.start()
        while True:
            conn, addr = self.socket.accept()
            conn = self.ssl_context.wrap_socket(conn, server_side=True)
            recv_thread = threading.Thread(target=self.recv_msg, args=(conn, addr))
            recv_thread.start()
    ...
```

### `server_improved.py` (ChatServer 部分)

与 server.py 相同的变更。

### `client.py`

```python
# 新增 import
import ssl

# 创建 SSL 连接的客户端
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
connection.connect((IP, PORT))
connection = ssl_context.wrap_socket(connection)
```

***

## 假设与决策

* **自签名证书**: 使用自签名证书而非 CA 签名证书，因为这是一个本地/局域网聊天室应用

* **证书验证**: 客户端设置 `verify_mode=ssl.CERT_NONE`，因为自签名证书无法通过标准 CA 验证

* **文件传输暂不加密**: 用户选择保持文件传输为明文

* **server\_async.py 跳过**: 用户选择暂不升级异步服务器

* **所有副本文件**: `client - 副本.py`、`server - 副本.py` 等副本文件不修改

***

## 验证步骤

1. 运行服务器 `python server.py`，确认没有 SSL 相关错误
2. 运行客户端 `python client.py`，确认能正常连接、登录、注册
3. 发送消息，确认消息能正常收发
4. 测试文件传输功能
5. 使用 Wireshark 确认流量已加密并告知用户如何操作

