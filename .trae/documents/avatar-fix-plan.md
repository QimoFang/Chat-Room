# 头像显示修复计划

## 概要

用户反馈注册登录后，用户列表和聊天界面中头像均未显示（用户列表显示彩色圆形+首字母，聊天界面完全无头像）。通过完整追踪头像数据流（注册→存储→登录→广播→加载→渲染），发现数据通路逻辑基本正确，但存在以下问题。

---

## 当前状态分析

### 头像数据流（已追踪）

```
注册：ImageCrop裁剪 → base64编码 → pickle发送给服务器
服务器注册：base64解码 → 存储BLOB到SQLite
服务器登录：读取BLOB → base64编码 → 广播 (name, addr, icon_b64, uid) 给所有客户端
客户端online_users：base64解码 → PIL打开 → PhotoImage → 缓存到 avatar_cache[uid]
用户列表渲染：从 _avatar_cache[uid] 取 PhotoImage → 绘制
聊天消息：从 interface.avatar_cache[uid] 取 PhotoImage → draw_msg
```

### 服务器 `onlines` 结构
- **5元素元组**: `(conn, name, addr, icon_b64, uid)`
- 登录时广播 4元素: `(name, addr, icon_b64, uid)` ✓

### 客户端 `onlines` 结构
- **`[user_info, DialogueInterface]`**
- `user_info = [name, addr, uid]`

### 头像缓存键值
- `UserListCanvas._avatar_cache` 键为 `uid`
- `DialogueInterface.avatar_cache` 键为 `uid`

---

## 发现的问题

### 问题 1：私聊消息头像检测 `sender_idx > 0` 条件歧义

**文件**: [client.py 第 2194 行](file:///f:/Python%20Programs/Chat%20Room/client.py#L2194)

```python
if sender_idx > 0 and isinstance(...):
```

`onlines[0]` 始终是 robot（无头像），所以 `sender_idx > 0` 对第一个真实用户（index 1）成立。但如果 `onlines` 列表结构改变（如 robot 不在 index 0），头像会丢失。虽当前逻辑正确，但脆弱。

**影响**: 低。当前 robot 始终在 index 0。

────────────────────────────────────

### 问题 2：群聊消息中 `sender_uid` 获取不完整

**文件**: [client.py 第 2237-2241 行](file:///f:/Python%20Programs/Chat%20Room/client.py#L2237-L2241)

之前已修复了从 `grp_interface.avatar_cache` 改为 `user[1].avatar_cache`，但需验证 `sender_uid_val` 正确地从 `user[0][2]` 获取。

➡ 已在上次修复中处理。

────────────────────────────────────

### 问题 3：`rebuild_with_groups` 中 `uid` 未传递给 `item`（致命）

**文件**: [client.py 第 349-366 行](file:///f:/Python%20Programs/Chat%20Room/client.py#L349-L366)

`rebuild_with_groups` 接收的 `user_list` 条目格式为 `(name, addr, uid)`，已在代码中正确提取 `uid = entry[2] if ... else None` 并存入 `item['uid']`。

➡ 代码逻辑正确，不是 bug。

────────────────────────────────────

### 问题 4：服务器 `signup` 不设置 uid，依赖 `_init_db` 延迟分配

**文件**: [server.py 第 54-74 行](file:///f:/Python%20Programs/Chat%20Room/server.py#L54-L74)

注册 INSERT 语句未包含 uid 字段，新用户的 uid 为 NULL。uid 在下次 `get_connection()` 时通过 `_init_db` 分配。

**影响**: 理论上无明显影响（登录时 `_init_db` 会在 SELECT 前为 NULL uid 用户分配 uid），但依赖于 `_init_db` 的重复执行（每次获取连接都会调用），设计上不严谨。更关键的是：数据库连接池的 `_init_db` 中 `ALTER TABLE` 每次都要尝试执行，虽然无害但低效。

────────────────────────────────────

### 问题 5：`recv` 函数使用单次 `recv(n)` 接收 pickle 数据可能不完整

**文件**: [client.py 第 2134-2149 行](file:///f:/Python%20Programs/Chat%20Room/client.py#L2134-L2149)

```python
msg = connection.recv(head["size"])  # 可能没读完
msg = pickle.loads(msg)  # 数据不完整会崩溃
```

TCP 流式特性：`recv(n)` 不一定返回 n 字节。如果 pickle 数据较大（含头像 base64），可能分片到达。异常未被捕获会导致 `recv` 线程崩溃。

**影响**: 中高。头像数据可能使消息增大，recv 线程崩溃后所有消息无法接收。

────────────────────────────────────

### 问题 6：缺少运行时诊断，无法定位具体失败环节

无任何 `print` 查看头像数据是否到达、缓存是否命中、PIL 是否解码成功。

────────────────────────────────────

### 问题 7：`signup` 成功弹窗后用户需要手动切换登录页

注册成功后弹出 "注册成功"，但用户仍停留在注册页面，需手动点击 "已有账号？立即登录" 链接。用户体验不够流畅，但非头像问题的直接原因。

---

## 建议的修复方案

### 修复 A：修复 `recv` 函数确保读取完整数据

**文件**: [client.py 第 2142 行](file:///f:/Python%20Programs/Chat%20Room/client.py#L2142)

**目标**: 修复 TCP recv 可能不读取全部数据的问题。

**方案**:
```python
def recv_all(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionResetError
        data += chunk
    return data

# 在 recv 函数中使用
msg = recv_all(connection, head["size"])
```

**同时处理 `recv_msg` 中服务器端的相同问题**（server.py 第 380, 456 行）。

### 修复 B：添加头像数据流诊断打印

**目标**: 在关键路径加 print 以便运行时定位问题。

- [server.py] 登录时打印 `icon_data_b64` 是否非空、长度
- [server.py] `online_users` 广播时打印每个用户的 icon_b64 长度
- [client.py] `online_users` handler 打印 `icon_b64` 非空判断和长度
- [client.py] `load_avatar` 和 `set_message_avatar` 中打印解码结果
- [client.py] `_draw_item` 中打印 uid 值和缓存查找结果
- [client.py] 聊天消息 avatar 查找时打印 `sender_uid` 和 `avatar_cache.get()`

**注意**: 这只是诊断阶段使用，修复后可清理或保留为 debug 日志。

### 修复 C：修复 `recv_msg`（服务器）的 `recv` 调用

**文件**: [server.py 第 380, 456 行](file:///f:/Python%20Programs/Chat%20Room/server.py)

与客户端类似问题，服务器 `msg_len = int(conn.recv(1024).decode())` 和 `data = pickle.loads(conn.recv(msg_len))` 使用 `recv_all` 替代。

---

## 验证步骤

1. 启动服务器
2. 注册新用户（选头像）
3. 登录
4. 观察控制台输出的诊断信息
5. 检查用户列表是否显示真实头像
6. 与其他用户私聊，检查聊天界面是否显示发送者头像
7. 群聊中检查头像
8. 确认消息收发正常（recv 修复未引入回归）
9. 移除诊断 print

---

## 假定与决策

- 假定之前的修复（群聊头像缓存、注册反馈条件、服务器 update 广播结构）已正确应用
- 最可能的根本原因是 **recv 数据不完整** 导致 pickle 加载失败或头像加载失败
- 诊断打印用于确认问题点，确认后需清理