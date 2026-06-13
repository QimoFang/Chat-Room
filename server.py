import socket
import ssl
import threading
import time
import os
import base64
import json
import pickle
import queue
import sqlite3
import requests
import unicodedata
import hashlib
import secrets
import logging
from contextlib import contextmanager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('server.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """使用 PBKDF2-SHA256 对密码进行哈希，返回 format: iterations:salt:hash"""
    salt = secrets.token_hex(32)
    iterations = 600000
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)
    return f"{iterations}:{salt}:{pwd_hash.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """验证密码是否匹配存储的哈希"""
    if not stored_hash or stored_hash.count(':') != 2:
        return False
    try:
        iterations, salt, pwd_hash = stored_hash.split(':', 2)
        new_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(iterations))
        return new_hash.hex() == pwd_hash
    except (ValueError, AttributeError):
        return False


IP = socket.gethostbyname(socket.gethostname())
PORT = 50000
OLLAMA_API_URL = "http://localhost:11434/api/chat"
que = queue.Queue()
onlines = []
lock = threading.Lock()
conversation_history = []


def recv_all(sock, size):
    """确保从 socket 读取完整 size 字节"""
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionResetError("连接已断开")
        data += chunk
    return data


# 数据库连接池
class DatabasePool:
    def __init__(self, db_path, max_connections=10):
        self.db_path = db_path
        self.max_connections = max_connections
        self.connections = []
        self.lock = threading.Lock()

    @contextmanager
    def get_connection(self):
        # 为每个线程创建新的连接，确保线程安全
        conn = sqlite3.connect(self.db_path)
        try:
            self._init_db(conn)
            yield conn
        finally:
            conn.close()

    def _init_db(self, conn):
        cursor = conn.cursor()
        try:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS user_msg( user_name TEXT NOT NULL UNIQUE, password TEXT NOT NULL, icon_data BLOB, uid INTEGER, PRIMARY KEY(user_name))"
            )
            conn.commit()
            # 兼容旧表：尝试添加 uid 列（可能已存在）
            try:
                cursor.execute("ALTER TABLE user_msg ADD COLUMN uid INTEGER")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            # 为旧用户分配 UID
            cursor.execute("SELECT MAX(uid) FROM user_msg")
            row = cursor.fetchone()
            next_uid = (row[0] or 0) + 1
            cursor.execute("SELECT user_name FROM user_msg WHERE uid IS NULL")
            for row in cursor.fetchall():
                cursor.execute("UPDATE user_msg SET uid = ? WHERE user_name = ?", (next_uid, row[0]))
                next_uid += 1
            conn.commit()
        except sqlite3.OperationalError as e:
            logger.error(f"数据库初始化失败: {e}")
        finally:
            cursor.close()


db_pool = DatabasePool("user_message.db")


def call_robot(question):
    answer = ""
    conversation_history.append({"role": "user", "content": question})

    # 构建请求体
    payload = {
        "model": "llama3.2:1b",
        "messages": conversation_history,
        "stream": True,
    }

    try:
        # 使用 stream=True 来接收流式响应
        with requests.post(OLLAMA_API_URL, json=payload, stream=True) as response:
            response.raise_for_status()  # 如果请求失败（如404, 500），则抛出异常

            logger.info("AI: ")

            # 逐行迭代响应内容
            for line in response.iter_lines():
                if line:
                    # 解码每一行（它们是JSON字符串）
                    chunk = json.loads(line.decode('utf-8'))

                    # 提取消息内容
                    content = chunk['message']['content']
                    answer += content

                    # 检查对话是否结束
                    if chunk.get('done', False):
                        # 将完整的助手回答添加到历史记录中
                        conversation_history.append({"role": "assistant", "content": answer})
                        print(answer)
                        return answer

    except requests.exceptions.RequestException as e:
        logger.error(f"无法连接到Ollama API: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"解析JSON响应失败: {e}")
    except Exception as e:
        logger.error(f"调用机器人失败: {e}")


# noinspection PyUnreachableCode
class ChatServer(threading.Thread):
    global que, onlines, lock

    def __init__(self, ip, port):
        threading.Thread.__init__(self)
        self.addr = (ip, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # SSL 上下文
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain('cert.pem', 'key.pem')
        self.ssl_context = ssl_context

    def del_user(self, addr):
        for user, mark in zip(onlines, range(0, len(onlines))):
            if user[2] == addr:
                onlines.pop(mark)
                users = []
                for old_user in onlines:
                    users.append((old_user[1], old_user[2], old_user[3], old_user[4]))
                self.put_queue(users, addr)
                break

    def split_str(self, string: str, max_width):
        parts = []
        current_width = 0
        buffer = []
        text = ""

        for char in string:
            width = unicodedata.east_asian_width(char)
            if width in 'FW':
                char_width = 2
            else:
                char_width = 1
            if current_width + char_width > max_width:
                parts.append(''.join(buffer))
                buffer = [char]
                current_width = char_width
            else:
                buffer.append(char)
                current_width += char_width
        if buffer:
            parts.append(''.join(buffer))
        for i in parts:
            text += i + '\n'
        return text

    def put_queue(self, data, addr):
        lock.acquire()
        try:
            que.put((addr, data))
        finally:
            lock.release()

    def send_msg(self):
        while True:
            if not que.empty():
                message = que.get()
                logger.debug(f"处理消息: {message}")
                data = pickle.dumps(message[1])
                size = len(data)
                if message[1]:
                    if isinstance(message[1][0], str):
                        if message[1][2] == "robot":
                            def callback():
                                for user in onlines:
                                    if user[2] == message[1][3]:
                                        data = pickle.dumps(
                                            ['text', self.split_str(str(call_robot(message[1][1])), 30),
                                             [(user[1], user[2], user[4])],
                                             "robot"])
                                        size = len(data)
                                        head = json.dumps({"type": "text", "size": size}).encode()
                                        logger.debug(f"发送机器人消息: {pickle.loads(data)}")
                                        try:
                                            user[0].send(head + b" " * (1024 - len(head)))
                                            user[0].send(data)
                                            logger.info(f"机器人消息发送成功给 {user[1]}")
                                        except ConnectionResetError:
                                            logger.warning(f"发送机器人消息失败: 用户 {user[1]} 已断开连接")

                            threading.Thread(target=callback, daemon=True).start()
                        elif message[1][0] == "update":
                            try:
                                with db_pool.get_connection() as con:
                                    cursor = con.cursor()

                                    conn = None
                                    for user in onlines:
                                        if user[2] == message[0]:
                                            conn = user[0]
                                            break

                                    # 验证旧密码
                                    cursor.execute("SELECT password FROM user_msg WHERE user_name = ?",
                                                   (message[1][1][0],))
                                    row = cursor.fetchone()
                                    if not row or not verify_password(message[1][1][1], row[0]):
                                        if conn:
                                            head = json.dumps(
                                                {"type": "update_echo",
                                                 "size": len(pickle.dumps("Update Failed"))}).encode()
                                            conn.send(head + b' ' * (1024 - len(head)))
                                            conn.send(pickle.dumps("Update Failed"))
                                        continue

                                    # 检查新用户名是否已被占用
                                    cursor.execute("SELECT user_name FROM user_msg WHERE user_name = ?",
                                                   (message[1][2][0],))
                                    if cursor.fetchone():
                                        if conn:
                                            head = json.dumps(
                                                {"type": "update_echo",
                                                 "size": len(pickle.dumps("Repeated Update"))}).encode()
                                            conn.send(head + b' ' * (1024 - len(head)))
                                            conn.send(pickle.dumps("Repeated Update"))
                                        continue

                                    # 执行更新
                                    new_hashed = hash_password(message[1][2][1])
                                    sql = "UPDATE user_msg SET user_name=?, password=?, icon_data=? WHERE user_name = ?"
                                    cursor.execute(sql,
                                                   [message[1][2][0], new_hashed,
                                                    base64.b64decode(message[1][2][2]),
                                                    message[1][1][0]])
                                    con.commit()
                                    head = json.dumps(
                                        {"type": "update_echo",
                                         "size": len(pickle.dumps("Update Success"))}).encode()
                                    conn.send(head + b' ' * (1024 - len(head)))
                                    conn.send(pickle.dumps("Update Success"))

                                    data = []
                                    for index in range(0, len(onlines)):
                                        if onlines[index][1] == message[1][1][0]:
                                            new_icon_b64 = message[1][2][2].decode() if message[1][2][2] else ""
                                            onlines[index] = (
                                            onlines[index][0], message[1][2][0], onlines[index][2], new_icon_b64, onlines[index][4])
                                        data.append((onlines[index][1], onlines[index][2], onlines[index][3], onlines[index][4]))
                                    logger.info(f"更新后的在线用户: {data}")
                                    data = pickle.dumps(data)
                                    head = json.dumps({"type": "update", "size": len(data)}).encode()
                                    logger.debug(f"发送更新消息: {pickle.loads(data)}")
                                    for user in onlines:
                                        try:
                                            user[0].send(head + b' ' * (1024 - len(head)))
                                            user[0].send(data)
                                        except ConnectionResetError:
                                            pass
                            except sqlite3.Error as e:
                                logger.error(f"数据库更新失败: {e}")
                                if conn:
                                    head = json.dumps(
                                        {"type": "update_echo",
                                         "size": len(pickle.dumps("Update Failed"))}).encode()
                                    conn.send(head + b' ' * (1024 - len(head)))
                                    conn.send(pickle.dumps("Update Failed"))
                            except Exception as e:
                                logger.error(f"处理更新消息失败: {e}")
                        elif message[1][0] == "group_text":
                            # 群聊消息：广播给所有在线用户（除自己外）
                            sender_addr = message[1][3] if len(message[1]) > 3 else None
                            # 查找发送者的 uid 和 name
                            sender_uid = None
                            sender_name = ""
                            for user in onlines:
                                if user[2] == sender_addr:
                                    sender_uid = user[4]
                                    sender_name = user[1]
                                    break
                            targets = [user for user in onlines if user[4] != sender_uid]
                            group_name = message[1][4] if len(message[1]) > 4 else "群聊"
                            # 构建带群组信息的消息体 - [type, txt, sender_name, sender_addr, group_name]
                            out_data = pickle.dumps(["group_text", message[1][1], sender_name, sender_addr, group_name])
                            size = len(out_data)
                            head = json.dumps({"type": "group_text", "size": size}).encode()
                            logger.debug(f"发送群聊消息: {pickle.loads(out_data)}")
                            for user in targets:
                                try:
                                    user[0].send(head + b" " * (1024 - len(head)))
                                    user[0].send(out_data)
                                    logger.info(f"群聊消息发送成功给 {user[1]}")
                                except ConnectionResetError:
                                    logger.warning(f"群聊消息发送失败: 用户 {user[1]} 已断开连接")
                        elif message[1][0] == "group_create":
                            # 群组创建：广播给所有在线用户
                            # message: ["group_create", group_name, members_list]
                            group_name = message[1][1]
                            members = message[1][2]
                            out_data = pickle.dumps(["group_create", group_name, members])
                            size = len(out_data)
                            head = json.dumps({"type": "group_create", "size": size}).encode()
                            logger.debug(f"广播群组创建: {group_name}, 成员: {members}")
                            for user in onlines:
                                try:
                                    user[0].send(head + b" " * (1024 - len(head)))
                                    user[0].send(out_data)
                                    logger.info(f"群组创建通知发送成功给 {user[1]}")
                                except ConnectionResetError:
                                    logger.warning(f"群组创建通知发送失败: 用户 {user[1]} 已断开连接")
                        elif message[1][0] == "vchat":
                            users = []
                            for flag in message[1][2]:
                                for user in onlines:
                                    if user[1] == flag[0] and user[2] == flag[1]:
                                        users.append(user)
                            head = json.dumps({"type": "invite_v", "size": size}).encode()
                            logger.debug(f"发送视频聊天邀请: {pickle.loads(data)}")
                            for user in users:
                                try:
                                    user[0].send(head + b" " * (1024 - len(head)))
                                    user[0].send(data)
                                    logger.info(f"视频聊天邀请发送成功给 {user[1]}")
                                except ConnectionResetError:
                                    logger.warning(f"发送视频聊天邀请失败: 用户 {user[1]} 已断开连接")
                        elif message[1][0] == "achat":
                            users = []
                            for flag in message[1][2]:
                                for user in onlines:
                                    if user[1] == flag[0] and user[2] == flag[1]:
                                        users.append(user)
                            head = json.dumps({"type": "invite_a", "size": size}).encode()
                            logger.debug(f"发送语音聊天邀请: {pickle.loads(data)}")
                            for user in users:
                                try:
                                    user[0].send(head + b" " * (1024 - len(head)))
                                    user[0].send(data)
                                    logger.info(f"语音聊天邀请发送成功给 {user[1]}")
                                except ConnectionResetError:
                                    logger.warning(f"发送语音聊天邀请失败: 用户 {user[1]} 已断开连接")
                        elif message[1][0] == "delete":
                            try:
                                with db_pool.get_connection() as con:
                                    cursor = con.cursor()
                                    sql = "DELETE FROM user_msg WHERE user_name = ?"
                                    cursor.execute(sql, message[1][1])
                                    con.commit()

                                    conn = None
                                    for user in onlines:
                                        if user[2] == message[0]:
                                            conn = user[0]
                                            break

                                    if conn:
                                        head = json.dumps(
                                            {"type": "delete_echo",
                                             "size": len(pickle.dumps("Delete Success"))}).encode()
                                        conn.send(head + b' ' * (1024 - len(head)))
                                        conn.send(pickle.dumps("Delete Success"))
                                        logger.info(f"用户 {message[1][1]} 已注销")
                            except sqlite3.Error as e:
                                logger.error(f"数据库删除失败: {e}")
                                conn = None
                                for user in onlines:
                                    if user[2] == message[0]:
                                        conn = user[0]
                                        break
                                if conn:
                                    head = json.dumps(
                                        {"type": "delete_echo", "size": len(pickle.dumps("Delete Failed"))}).encode()
                                    conn.send(head + b' ' * (1024 - len(head)))
                                    conn.send(pickle.dumps("Delete Failed"))
                            except Exception as e:
                                logger.error(f"处理删除消息失败: {e}")
                        else:
                            users = []
                            for flag in message[1][2]:
                                for user in onlines:
                                    if user[1] == flag[0] and user[2] == flag[1]:
                                        users.append(user)
                            head = json.dumps({"type": "text", "size": size}).encode()
                            logger.debug(f"发送文本消息: {pickle.loads(data)}")
                            for user in users:
                                try:
                                    user[0].send(head + b" " * (1024 - len(head)))
                                    user[0].send(data)
                                    logger.info(f"文本消息发送成功给 {user[1]}")
                                except ConnectionResetError:
                                    logger.warning(f"发送文本消息失败: 用户 {user[1]} 已断开连接")
                    elif isinstance(message[1][0], tuple):
                        head = json.dumps({"type": "online_users", "size": size}).encode()
                        logger.info(f"更新在线用户列表，当前在线用户数: {len(onlines)}")
                        # 诊断：打印广播的 icon_b64 信息
                        for u_entry in message[1]:
                            print(f"[DIAG] 广播 online_users: name={u_entry[0]}, icon_b64非空={bool(u_entry[2])}, 长度={len(u_entry[2])}, uid={u_entry[3] if len(u_entry) > 3 else 'N/A'}")
                        for user in onlines:
                            try:
                                user[0].send(head + b" " * (1024 - len(head)))
                                user[0].send(data)
                                logger.debug(f"在线用户列表发送成功给 {user[1]}")
                            except ConnectionResetError:
                                logger.warning(f"发送在线用户列表失败: 用户 {user[1]} 已断开连接")
                else:
                    pass

    def recv_msg(self, conn, addr):
        try:
            while True:
                msg_len = int(recv_all(conn, 10).decode().strip())
                login_msg = pickle.loads(recv_all(conn, msg_len))
                logger.debug(f"收到来自 {addr} 的消息: {login_msg[0]}")
                if login_msg[0] == "login":
                    try:
                        for user in onlines:
                            if user[1] == login_msg[1]:
                                head = json.dumps({"type": "login_echo", "size": len("Repeated Login")}).encode()
                                conn.send(head + b' ' * (1024 - len(head)))
                                conn.send("Repeated Login".encode())
                                break
                        else:
                            with db_pool.get_connection() as con:
                                cursor = con.cursor()
                                sql = "SELECT user_name, password, icon_data, uid FROM user_msg WHERE user_name = ?"
                                cursor.execute(sql, (login_msg[1],))
                                result = cursor.fetchall()
                                if result and verify_password(login_msg[2], result[0][1]):
                                    head = json.dumps({"type": "login_echo", "size": len("Login Success")}).encode()
                                    conn.send(head + b' ' * (1024 - len(head)))
                                    conn.send("Login Success".encode())
                                    logger.info(f"用户 {login_msg[1]} 从 {addr} 登录成功")
                                    # 提取图标数据
                                    icon_data_b64 = base64.b64encode(result[0][2]).decode() if len(result[0]) > 2 and result[0][2] else ""
                                    uid_val = result[0][3]
                                    print(f"[DIAG] 用户 {login_msg[1]} 登录: icon_b64非空={bool(icon_data_b64)}, 长度={len(icon_data_b64)}, uid={uid_val}")
                                    onlines.append((conn, login_msg[1], addr, icon_data_b64, uid_val))
                                    users = []
                                    for user in onlines:
                                        users.append((user[1], user[2], user[3], user[4]))
                                    logger.info(f"用户 {login_msg[1]} 加入在线列表，当前在线用户数: {len(onlines)}")
                                    self.put_queue(users, addr)
                                    break
                                else:
                                    head = json.dumps({"type": "login_echo", "size": len("Login Failed")}).encode()
                                    conn.send(head + b' ' * (1024 - len(head)))
                                    conn.send("Login Failed".encode())
                                    logger.warning(f"用户 {login_msg[1]} 从 {addr} 登录失败: 用户名或密码错误")
                    except sqlite3.Error as e:
                        logger.error(f"数据库登录验证失败: {e}")
                        head = json.dumps({"type": "login_echo", "size": len("Login Failed")}).encode()
                        conn.send(head + b' ' * (1024 - len(head)))
                        conn.send("Login Failed".encode())
                elif login_msg[0] == "sign up":
                    try:
                        with db_pool.get_connection() as con:
                            cursor = con.cursor()
                            sql = "SELECT user_name, password FROM user_msg WHERE user_name = ?"
                            cursor.execute(sql, (login_msg[1],))
                            result = cursor.fetchall()
                            if not result:
                                # 解码图标数据（base64）
                                icon_bytes = None
                                if len(login_msg) > 3 and login_msg[3]:
                                    try:
                                        icon_bytes = base64.b64decode(login_msg[3])
                                    except Exception:
                                        icon_bytes = None
                                hashed_pwd = hash_password(login_msg[2])
                                sql = "INSERT INTO user_msg (user_name,password,icon_data) VALUES(?,?,?)"
                                cursor.execute(sql, [login_msg[1], hashed_pwd, icon_bytes])
                                con.commit()
                                head = json.dumps({"type": "sign up_echo", "size": len("Sign Up Success")}).encode()
                                conn.send(head + b' ' * (1024 - len(head)))
                                conn.send("Sign Up Success".encode())
                                logger.info(f"用户 {login_msg[1]} 从 {addr} 注册成功")
                            else:
                                head = json.dumps({"type": "sign up_echo", "size": len("Repeated Sign Up")}).encode()
                                conn.send(head + b' ' * (1024 - len(head)))
                                conn.send("Repeated Sign Up".encode())
                                logger.warning(f"用户 {login_msg[1]} 从 {addr} 注册失败: 用户名已存在")
                    except sqlite3.Error as e:
                        logger.error(f"用户 {login_msg[1]} 注册失败: {e}")
                        head = json.dumps({"type": "sign up_echo", "size": len("Sign Up Failed")}).encode()
                        conn.send(head + b' ' * (1024 - len(head)))
                        conn.send("Sign Up Failed".encode())
            logger.debug(f"当前在线用户: {onlines}")
            while True:
                msg_len = int(recv_all(conn, 10).decode().strip())
                data = pickle.loads(recv_all(conn, msg_len))
                logger.debug(f"收到来自 {addr} 的消息: {data[0]}")
                if isinstance(data[0], str):
                    if data[0] == "text":
                        logger.info(f"收到来自 {login_msg[1]} 的文本消息，目标: {data[2]}")
                    elif data[0] == "group_text":
                        logger.info(f"收到来自 {login_msg[1]} 的群聊消息，群组: {data[4] if len(data) > 4 else 'unknown'}")
                    elif data[0] == "group_create":
                        logger.info(f"收到来自 {login_msg[1]} 的群组创建请求: {data[1] if len(data) > 1 else 'unknown'}")
                    elif data[0] == "update":
                        logger.info(f"用户 {login_msg[1]} 更新个人信息")
                    elif data[0] == "delete":
                        logger.info(f"用户 {login_msg[1]} 请求注销账号")
                    elif data[0] == "vchat":
                        logger.info(f"用户 {login_msg[1]} 请求视频聊天，目标: {data[2]}")
                    elif data[0] == "achat":
                        logger.info(f"用户 {login_msg[1]} 请求语音聊天，目标: {data[2]}")
                    elif data[2] == "robot":
                        logger.info(f"用户 {login_msg[1]} 向机器人发送消息")
                self.put_queue(data, addr)
        except ConnectionResetError:
            logger.info(f"用户 {addr} 下线")
            self.del_user(addr)
            conn.close()
        except Exception as e:
            logger.error(f"接收消息失败: {e}")
            try:
                conn.close()
            except Exception:
                pass

    def run(self):
        try:
            self.socket.bind(self.addr)
            self.socket.listen()
            logger.info(f"开始在 {socket.gethostbyname(socket.gethostname())} 处侦听")
            send_thread = threading.Thread(target=self.send_msg)
            send_thread.start()
            while True:
                conn, addr = self.socket.accept()
                conn = self.ssl_context.wrap_socket(conn, server_side=True)
                logger.info(f"新用户连接：{addr}")
                recv_thread = threading.Thread(target=self.recv_msg, args=(conn, addr))
                recv_thread.start()
        except Exception as e:
            logger.error(f"服务器运行失败: {e}")
        finally:
            try:
                self.socket.close()
            except Exception:
                pass
        self.socket.close()


class FileServer(threading.Thread):
    def __init__(self, ip, port):
        threading.Thread.__init__(self)
        self.addr = (ip, port)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.path = r'resources'
        os.chdir(self.path)

    # 文件收发线程函数
    def handle_client(self, conn, addr):
        logger.info(f'文件服务器：客户机地址：{addr}')
        try:
            while True:  # 消息处理主循环
                data = conn.recv(1024)
                if not data:
                    break
                data = data.decode()
                if data == 'quit':
                    logger.info(f'文件服务器：客户机 {addr} 文件服务结束！')
                    break
                order = data.split()[0]  # 获取动作
                self.call_func(order, data, conn)
        except Exception as e:
            logger.error(f"文件服务器处理客户端失败: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # 发送文件
    def sendFile(self, message, conn):
        try:
            name = message.split()[1]  # 获取第二个参数（文件名）
            fileName = r'./' + name
            # 读取并发送文件
            with open(fileName, 'rb') as f:
                while True:
                    a = f.read(1024)
                    if not a:
                        break
                    conn.send(a)
            time.sleep(0.1)
            conn.send('EOF'.encode())  # 发送文件结束符
            logger.info(f"发送文件成功: {name}")
        except Exception as e:
            logger.error(f"发送文件失败: {e}")

    # 接收文件
    def recvFile(self, message, conn):
        try:
            name = message.split()[1]  # 获取文件名
            fileName = r'./' + name
            # 接收并写入文件流
            with open(fileName, 'wb') as f:
                while True:
                    data = conn.recv(1024)
                    if data == 'EOF'.encode():
                        break
                    f.write(data)
            logger.info(f"接收文件成功: {name}")
        except Exception as e:
            logger.error(f"接收文件失败: {e}")

    # 切换工作目录
    def cd(self, message, conn):
        try:
            message = message.split()[1]  # 截取目录名称
            if message != 'same':  # 需要切换
                f = r'./' + message
                os.chdir(f)
            path = os.getcwd().split('\\')  # 当前工作目录
            for i in range(len(path)):
                if path[i] == 'resources':
                    break
            pat = ''
            for j in range(i, len(path)):
                pat = pat + path[j] + ' '
            pat = '\\'.join(pat.split())
            # 如果切换目录超出范围则回退到当前目录
            if 'resources' not in path:
                f = r'./resources'
                os.chdir(f)
                pat = 'resources'
            conn.send(pat.encode())  # 新目录发送给客户机
            logger.info(f"切换目录成功: {pat}")
        except Exception as e:
            logger.error(f"切换目录失败: {e}")

    # 向con连接的客户机传输当前目录列表
    def sendList(self, conn):
        try:
            listdir = os.listdir(os.getcwd())
            listdir = json.dumps(listdir)
            conn.sendall(listdir.encode())
            logger.info(f"发送目录列表成功: {listdir}")
        except Exception as e:
            logger.error(f"发送目录列表失败: {e}")

    # 判断消息类型并执行相应的函数
    def call_func(self, order, message, conn):
        if order == 'get':
            return self.sendFile(message, conn)
        elif order == 'put':
            return self.recvFile(message, conn)
        elif order == 'dir':
            return self.sendList(conn)
        elif order == 'cd':
            return self.cd(message, conn)

    def run(self):  # 主运行函数
        try:
            logger.info('文件服务器运行中...')
            self.s.bind(self.addr)
            logger.info(f'文件服务器工作地址：{self.addr}')
            self.s.listen()
            while True:
                conn, addr = self.s.accept()  # 处理链接
                t = threading.Thread(target=self.handle_client, args=(conn, addr))
                t.start()
        except Exception as e:
            logger.error(f"文件服务器运行失败: {e}")
        finally:
            try:
                self.s.close()
            except Exception:
                pass


if __name__ == "__main__":
    cserver = ChatServer(IP, PORT)
    cserver.run()
    fserver = FileServer(IP, PORT)
    fserver.run()
