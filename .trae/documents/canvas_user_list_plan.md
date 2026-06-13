# Canvas 重写用户列表并增加来信提示 - 实施计划

## 概述

将现有的 `tk.Listbox` 用户列表替换为 `tk.Canvas` 自绘列表，实现更美观的视觉效果，并增加未读消息红点提示。

## 当前状态分析

### 现有架构

* [client.py:1888-1897](file:///f:/Python%20Programs/Chat%20Room/client.py#L1888-L1897): `online_list` 是 `tk.Listbox`，放在 `online_frame`（左侧20%宽度）中

* [client.py:1621-1663](file:///f:/Python%20Programs/Chat%20Room/client.py#L1621-L1663): `choose_user()` 处理 `<<ListboxSelect>>` 事件，切换聊天 Canvas

* [client.py:1493-1516](file:///f:/Python%20Programs/Chat%20Room/client.py#L1493-L1516): `online_users` 处理器插入/更新列表项

* [client.py:1517-1533](file:///f:/Python%20Programs/Chat%20Room/client.py#L1517-L1533): `update` 处理器同步更新列表

* [client.py:1694-1698](file:///f:/Python%20Programs/Chat%20Room/client.py#L1694-L1698): `update_echo` 处理器更新列表

* [client.py:1440-1467](file:///f:/Python%20Programs/Chat%20Room/client.py#L1440-L1467): 接收消息时绘制到对应用户的 Canvas

* [client.py:1553-1592](file:///f:/Python%20Programs/Chat%20Room/client.py#L1553-L1592): 发送消息时绘制到当前选中用户的 Canvas

* [client.py:142-178](file:///f:/Python%20Programs/Chat%20Room/client.py#L142-L178): `Theme` 类定义了所有配色

### 数据结构

* `onlines`: `[("robot", None), DialogueInterface], [[name, (ip, port)], DialogueInterface], ...]`

* `users`: `[[("robot", None)], [(name, (ip, port))], ...]`

* `online_list`: 当前是 `tk.Listbox` 控件

### 关键问题

* 当前 `online_list` 索引与 `onlines` 索引一一对应（index 0 = robot, index 1..n = 用户）

* `choose_user` 通过 `online_list.curselection()` 获取选中索引，映射到 `onlines[index]`

* `send_text` 通过 `online_list.curselection()[0]` 获取目标用户索引

* 所有列表操作点：`online_list.insert()`, `online_list.delete()`, `online_list.curselection()` 需要全部替换

***

## 修改计划

### 1. 添加 `UserListCanvas` 类（新建，在 `client.py` 中）

在 `DialogueInterface` 类之后添加一个封装类，管理 Canvas 用户列表的绘制和交互。

```python
class UserListCanvas:
    """Canvas 自绘用户列表，支持未读消息红点提示"""
    
    def __init__(self, parent):
        # 创建 Canvas 和 Scrollbar
        # 存储 items: [{name, addr, unread, canvas_items}, ...]
        # 绑定鼠标事件和滚轮
    
    def rebuild(self, user_list):
        """根据 user_list 重建列表项，保留已有 unread 计数"""
    
    def set_unread(self, addr, increment=True):
        """设置/增加未读计数，触发红点重绘"""
    
    def clear_unread(self, index):
        """清除指定项的未读计数"""
    
    def get_selection(self):
        """返回当前选中项的索引"""
    
    def select(self, index):
        """程序化选中指定项"""
    
    def _draw_item(self, index, name, unread, selected):
        """绘制单个列表项（头像圆、名字、红点）"""
```

**绘制细节：**

* 头像圆：40x40 圆形，背景色取名字首字符 hash 映射到预设颜色，中间显示名字首字

* 用户名：微软雅黑 12px，`Theme.TEXT_PRIMARY`

* 未读红点：红色圆形，数字白字，显示在右侧

* 选中态：背景高亮 `Theme.HOVER_LIGHT`

* 悬停态：背景微变（`<Enter>`/`<Leave>` 绑定）

* 项高度：60px，间距 4px

### 2. 替换 `online_list` 为 `UserListCanvas`

**位置：** [client.py:1887-1897](file:///f:/Python%20Programs/Chat%20Room/client.py#L1887-L1897)

**改动：**

* 删除 `tk.Listbox` 创建代码

* 创建 `UserListCanvas` 实例：`user_list_canvas = UserListCanvas(online_frame)`

* 放置在相同位置 `(x=0, y=55, relwidth=1.0, relheight=1.0, height=-70)`

* 初始插入 "🤖 deepseek助手" 和机器人头像

### 3. 修改 `choose_user` 函数

**位置：** [client.py:1621-1663](file:///f:/Python%20Programs/Chat%20Room/client.py#L1621-L1663)

**改动：**

* `online_list.curselection()` → `user_list_canvas.get_selection()`

* 选中用户后调用 `user_list_canvas.clear_unread(index)` 清除该用户的未读红点

* 添加 `user_list_canvas.select(index)` 高亮选中项

### 4. 修改 `online_users` 处理器

**位置：** [client.py:1513-1516](file:///f:/Python%20Programs/Chat%20Room/client.py#L1513-L1516)

**改动：**

* `online_list.delete()` + `online_list.insert()` 循环 → `user_list_canvas.rebuild(msg)`

* `rebuild` 内部根据 IP 地址匹配已有项，保留 unread 计数

### 5. 修改 `update` 处理器

**位置：** [client.py:1530-1533](file:///f:/Python%20Programs/Chat%20Room/client.py#L1530-L1533)

**改动：**

* `online_list.delete()` + `online_list.insert()` 循环 → `user_list_canvas.rebuild(msg)`

### 6. 修改 `update_echo` 处理器

**位置：** [client.py:1694-1698](file:///f:/Python%20Programs/Chat%20Room/client.py#L1694-L1698)

**改动：**

* `online_list.delete()` + `online_list.insert()` 循环 → `user_list_canvas.rebuild(onlines[1:])`

### 7. 修改消息接收逻辑（添加未读红点）

**位置：** [client.py:1440-1467](file:///f:/Python%20Programs/Chat%20Room/client.py#L1440-L1467)

**改动：**

* 当消息发送者不是当前选中用户时，调用 `user_list_canvas.set_unread(sender_addr)` 增加红点

### 8. 修改 `send_text` 中的列表引用

**位置：** [client.py:1553, 1573, 1582, 1588](file:///f:/Python%20Programs/Chat%20Room/client.py#L1553) 附近

**改动：**

* `online_list.curselection()[0]` → `user_list_canvas.get_selection()`

***

## 假设与决策

* 需虚拟滚动

* 未读计数只在用户**未选中**时累加，选中后清零

* 保持 `online_frame` 的布局不变（20% 宽度）

## 验证步骤

1. 启动客户端，登录后确认用户列表正常显示
2. 切换用户，确认聊天面板正确切换
3. 用另一个客户端发送消息，确认未读红点出现
4. 点击有红点的用户，确认红点消失
5. 用户上线/下线，确认列表更新正确
6. 修改用户名，确认列表更新正确

