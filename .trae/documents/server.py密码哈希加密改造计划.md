# server.py 密码哈希加密改造计划

## 概述

仅对 [server.py](file:///f:/Python%20Programs/Chat%20Room/server.py) 进行密码哈希加密改造。server\_improved.py 和 server\_async.py 已完成改造。

## 当前状态分析

* [server.py](file:///f:/Python%20Programs/Chat%20Room/server.py) 中密码以 **明文** 存储在 SQLite 数据库 `user_message.db` 的 `user_msg` 表的 `password` 列中

* 注册时直接 `INSERT INTO user_msg (user_name, password) VALUES(?, ?)` 存入明文

* 登录时 `SELECT ... WHERE user_name = ? and password = ?` 直接比较明文

* 修改密码时 `UPDATE ... WHERE user_name = ? and password = ?` 用明文条件验证旧密码

## 方案

使用 Python 内置 `hashlib` 的 **PBKDF2-HMAC-SHA256**（无需额外依赖），格式：`iterations:salt:hash`。

## 具体变更

### 1. 添加 import（第 13 行附近）

```python
import hashlib
import secrets
```

### 2. 添加工具函数（在 `logger = logging.getLogger(__name__)` 之后，`IP = socket.gethostbyname(...)` 之前）

新增 3 个函数：

* `hash_password(password)` — 生成随机 salt，PBKDF2 迭代 600,000 次，返回 `iterations:salt:hex_hash`

* `verify_password(password, stored_hash)` — 验证密码，兼容旧版明文（非 `:` 格式时回退为明文比较）

* `upgrade_password_if_plain(con, username, password)` — 登录成功时检测旧明文密码并升级为哈希

### 3. 修改注册逻辑（`recv_msg` 中的 "sign up" 分支）

```python
# 改前
cursor.execute(sql, [login_msg[1], login_msg[2], icon_bytes])

# 改后
hashed_pwd = hash_password(login_msg[2])
cursor.execute(sql, [login_msg[1], hashed_pwd, icon_bytes])
```

### 4. 修改登录逻辑（`recv_msg` 中的 "login" 分支）

```python
# 改前
sql = "SELECT ... WHERE user_name = ? and password = ?"
cursor.execute(sql, [login_msg[1], login_msg[2]])
result = cursor.fetchall()
if result:

# 改后
sql = "SELECT ... WHERE user_name = ?"
cursor.execute(sql, (login_msg[1],))
result = cursor.fetchall()
if result and verify_password(login_msg[2], result[0][1]):
    upgrade_password_if_plain(con, login_msg[1], login_msg[2])
```

### 5. 修改更新密码逻辑（`send_msg` 中的 "update" 分支）

整体重写该分支：

* 先用 `verify_password` 验证旧密码

* 再检查新用户名是否已被占用

* 新密码通过 `hash_password` 哈希后存储

## 涉及文件

| 文件                                                              | 改动                                     |
| --------------------------------------------------------------- | -------------------------------------- |
| [server.py](file:///f:/Python%20Programs/Chat%20Room/server.py) | 新增 import + 3 个工具函数 + 修改注册/登录/更新 3 处逻辑 |

## 验证步骤

1. 运行 `python server.py` 启动服务器
2. 通过客户端注册新用户
3. 用 `check_db.py` 查看 password 字段是否为哈希格式
4. 用注册的账号登录验证

