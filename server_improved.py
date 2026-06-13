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
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('server.log'),
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


# 服务器配置
IP = socket.gethostbyname(socket.gethostname())
PORT = 50000
OLLAMA_API_URL = "http://localhost:11434/api/chat"

# 线程池配置
MAX_THREADS = 100

# 消息队列配置
MAX_QUEUE_SIZE = 1000

# 数据库配置
DB_PATH = "user_message.db"

# 全局变量
que = queue.Queue(maxsize=MAX_QUEUE_SIZE)
onlines = []
lock = threading.Lock()
conversation_history = []
thread_pool = ThreadPoolExecutor(max_workers=MAX_THREADS)

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
                "CREATE TABLE IF NOT EXISTS user_msg( user_name TEXT NOT NULL UNIQUE, password TEXT NOT NULL, icon_data BLOB, PRIMARY KEY(user_name))"
            )
            conn.commit()
        except sqlite3.OperationalError as e:
            logger.error(f"数据库初始化失败: {e}")
        finally:
            cursor.close()

db_pool = DatabasePool(DB_PATH)

# 检查端口是否可用
def is_port_available(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((IP, port))
        sock.close()
        return True
    except OSError:
        return False

# 寻找可用端口
def find_available_port(start_port, max_attempts=10):
    for port in range(start_port, start_port + max_attempts):
        if is_port_available(port):
            return port
    return None

# 调用AI机器人处理问题
def call_robot(question):
    answer = ""
    conversation_history.append({"role": "user", "content": question})

    # 构建请求体
    payload = {
        "model": "deepseek-r1",
        "messages": conversation_history,
        "stream": True
    }

    try:
        # 使用 stream=True 来接收流式响应
        with requests.post(OLLAMA_API_URL, json=payload, stream=True, timeout=30) as response:
            response.raise_for_status()  # 如果请求失败（如404, 500），则抛出异常

            logger.info("deepseek: ")

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
                        logger.info(answer)
                        return answer

    except requests.exceptions.RequestException as e:
        logger.error(f"无法连接到Ollama API: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"解析JSON响应失败: {e}")
    except Exception as e:
        logger.error(f"调用机器人失败: {e}")
    return "抱歉，机器人暂时无法响应，请稍后再试。"

# 聊天服务器类
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
        with lock:
            for user, mark in zip(onlines, range(len(onlines))):
                if user[2] == addr:
                    onlines.pop(mark)
                    users = [(user[1], user[2]) for user in onlines]
                    self.put_queue(users, addr)
                    logger.info(f"用户 {addr} 已从在线列表中移除")
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
        try:
            que.put((addr, data), timeout=1)
        except queue.Full:
            logger.warning("消息队列已满，丢弃消息")
        except Exception as e:
            logger.error(f"放入队列失败: {e}")

    def send_msg(self):
        while True:
            try:
                if not que.empty():
                    message = que.get(timeout=1)
                    logger.debug(f"处理消息: {message}")
                    data = pickle.dumps(message[1])
                    size = len(data)
                    if message[1]:
                        if isinstance(message[1][0], str):
                            if message[1][2] == "robot":
                                def callback():
                                    for user in onlines:
                                        if user[2] == message[1][3]:
                                            try:
                                                robot_response = call_robot(message[1][1])
                                                data = pickle.dumps(
                                                    ['text', self.split_str(str(robot_response), 30),
                                                     [(user[1], user[2])],
                                                     "robot"])
                                                size = len(data)
                                                head = json.dumps({"type": "text", "size": size}).encode()
                                                logger.debug(f"发送机器人消息: {pickle.loads(data)}")
                                                user[0].send(head + b" " * (1024 - len(head)))
                                                user[0].send(data)
                                            except ConnectionResetError:
                                                logger.warning(f"发送失败，用户 {user[2]} 已断开连接")
                                            except Exception as e:
                                                logger.error(f"发送机器人消息失败: {e}")

                                thread_pool.submit(callback)
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
                                                    {"type": "update_echo", "size": len(pickle.dumps("Update Failed"))}).encode()
                                                conn.send(head + b' ' * (1024 - len(head)))
                                                conn.send(pickle.dumps("Update Failed"))
                                            continue

                                        # 检查新用户名是否已被占用
                                        cursor.execute("SELECT user_name FROM user_msg WHERE user_name = ?",
                                                       (message[1][2][0],))
                                        if cursor.fetchone():
                                            if conn:
                                                head = json.dumps(
                                                    {"type": "update_echo", "size": len(pickle.dumps("Repeated Update"))}).encode()
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
                                            {"type": "update_echo", "size": len(pickle.dumps("Update Success"))}).encode()
                                        conn.send(head + b' ' * (1024 - len(head)))
                                        conn.send(pickle.dumps("Update Success"))

                                        # 更新在线用户列表
                                        updated_users = []
                                        with lock:
                                            for index in range(len(onlines)):
                                                if onlines[index][1] == message[1][1][0]:
                                                    onlines[index] = (onlines[index][0], message[1][2][0], onlines[index][2])
                                                updated_users.append((onlines[index][1], onlines[index][2]))

                                        logger.info(f"更新后的在线用户: {updated_users}")
                                        data = pickle.dumps(updated_users)
                                        head = json.dumps({"type": "update", "size": len(data)}).encode()

                                        # 通知所有在线用户
                                        for user in onlines:
                                            try:
                                                user[0].send(head + b' ' * (1024 - len(head)))
                                                user[0].send(data)
                                            except ConnectionResetError:
                                                logger.warning(f"发送失败，用户 {user[2]} 已断开连接")
                                            except Exception as e:
                                                logger.error(f"发送更新消息失败: {e}")
                                except sqlite3.Error as e:
                                    logger.error(f"数据库更新失败: {e}")
                                    if conn:
                                        head = json.dumps(
                                            {"type": "update_echo", "size": len(pickle.dumps("Update Failed"))}).encode()
                                        conn.send(head + b' ' * (1024 - len(head)))
                                        conn.send(pickle.dumps("Update Failed"))
                                except Exception as e:
                                    logger.error(f"处理更新消息失败: {e}")
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
                                    except ConnectionResetError:
                                        logger.warning(f"发送失败，用户 {user[2]} 已断开连接")
                                    except Exception as e:
                                        logger.error(f"发送视频聊天邀请失败: {e}")
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
                                    except ConnectionResetError:
                                        logger.warning(f"发送失败，用户 {user[2]} 已断开连接")
                                    except Exception as e:
                                        logger.error(f"发送语音聊天邀请失败: {e}")
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
                                                {"type": "delete_echo", "size": len(pickle.dumps("Delete Success"))}).encode()
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
                                    except ConnectionResetError:
                                        logger.warning(f"发送失败，用户 {user[2]} 已断开连接")
                                    except Exception as e:
                                        logger.error(f"发送文本消息失败: {e}")
                        elif isinstance(message[1][0], tuple):
                            head = json.dumps({"type": "online_users", "size": size}).encode()
                            for user in onlines:
                                try:
                                    user[0].send(head + b" " * (1024 - len(head)))
                                    user[0].send(data)
                                except ConnectionResetError:
                                    logger.warning(f"发送失败，用户 {user[2]} 已断开连接")
                                except Exception as e:
                                    logger.error(f"发送在线用户列表失败: {e}")
            except queue.Empty:
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                time.sleep(0.1)

    def recv_msg(self, conn, addr):
        try:
            # 接收消息长度（可变长度）
            def receive_message_length():
                msg_len_data = b''
                while True:
                    chunk = conn.recv(1)
                    if not chunk:
                        raise ConnectionResetError
                    if chunk == b'\n':
                        break
                    msg_len_data += chunk
                return int(msg_len_data.decode())
            
            # 接收完整消息
            def receive_full_message(msg_len):
                data = b''
                while len(data) < msg_len:
                    chunk = conn.recv(min(4096, msg_len - len(data)))
                    if not chunk:
                        raise ConnectionResetError
                    data += chunk
                return data
            
            # 处理登录/注册请求
            while True:
                try:
                    msg_len = receive_message_length()
                    login_msg = receive_full_message(msg_len)
                    login_msg = pickle.loads(login_msg)
                    
                    if login_msg[0] == "login":
                        try:
                            # 检查是否重复登录
                            with lock:
                                for user in onlines:
                                    if user[1] == login_msg[1]:
                                        head = json.dumps({"type": "login_echo", "size": len("Repeated Login")}).encode()
                                        conn.send(head + b' ' * (1024 - len(head)))
                                        conn.send("Repeated Login".encode())
                                        logger.warning(f"用户 {login_msg[1]} 尝试重复登录")
                                        return
                            
                            # 验证用户名和密码
                            with db_pool.get_connection() as con:
                                cursor = con.cursor()
                                sql = "SELECT user_name, password FROM user_msg WHERE user_name = ?"
                                cursor.execute(sql, (login_msg[1],))
                                result = cursor.fetchall()
                                if result and verify_password(login_msg[2], result[0][1]):
                                    head = json.dumps({"type": "login_echo", "size": len("Login Success")}).encode()
                                    conn.send(head + b' ' * (1024 - len(head)))
                                    conn.send("Login Success".encode())
                                    logger.info(f"用户 {login_msg[1]} 登录成功")
                                    
                                    # 添加到在线用户列表
                                    with lock:
                                        onlines.append((conn, login_msg[1], addr))
                                        users = [(user[1], user[2]) for user in onlines]
                                    self.put_queue(users, addr)
                                    logger.debug(f"当前在线用户: {users}")
                                else:
                                    head = json.dumps({"type": "login_echo", "size": len("Login Failed")}).encode()
                                    conn.send(head + b' ' * (1024 - len(head)))
                                    conn.send("Login Failed".encode())
                                    logger.warning(f"用户 {login_msg[1]} 登录失败")
                                    return
                        except sqlite3.Error as e:
                            logger.error(f"数据库登录验证失败: {e}")
                            head = json.dumps({"type": "login_echo", "size": len("Login Failed")}).encode()
                            conn.send(head + b' ' * (1024 - len(head)))
                            conn.send("Login Failed".encode())
                            return
                        except Exception as e:
                            logger.error(f"处理登录请求失败: {e}")
                            return
                    elif login_msg[0] == "sign up":
                        try:
                            with db_pool.get_connection() as con:
                                cursor = con.cursor()
                                sql = "SELECT user_name, password FROM user_msg WHERE user_name = ?"
                                cursor.execute(sql, (login_msg[1],))
                                result = cursor.fetchall()
                                
                                if not result:
                                    hashed_pwd = hash_password(login_msg[2])
                                    sql = "INSERT INTO user_msg (user_name,password) VALUES(?,?)"
                                    cursor.execute(sql, [login_msg[1], hashed_pwd])
                                    con.commit()
                                    head = json.dumps({"type": "sign up_echo", "size": len("Sign Up Success")}).encode()
                                    conn.send(head + b' ' * (1024 - len(head)))
                                    conn.send("Sign Up Success".encode())
                                    logger.info(f"用户 {login_msg[1]} 注册成功")
                                else:
                                    head = json.dumps({"type": "sign up_echo", "size": len("Repeated Sign Up")}).encode()
                                    conn.send(head + b' ' * (1024 - len(head)))
                                    conn.send("Repeated Sign Up".encode())
                                    logger.warning(f"用户 {login_msg[1]} 尝试重复注册")
                        except sqlite3.Error as e:
                            logger.error(f"数据库注册失败: {e}")
                            head = json.dumps({"type": "sign up_echo", "size": len("Sign Up Failed")}).encode()
                            conn.send(head + b' ' * (1024 - len(head)))
                            conn.send("Sign Up Failed".encode())
                        except Exception as e:
                            logger.error(f"处理注册请求失败: {e}")
                            head = json.dumps({"type": "sign up_echo", "size": len("Sign Up Failed")}).encode()
                            conn.send(head + b' ' * (1024 - len(head)))
                            conn.send("Sign Up Failed".encode())
                        return
                except ConnectionResetError:
                    raise
                except Exception as e:
                    logger.error(f"处理登录/注册请求失败: {e}")
                    return
            
            # 处理登录后的消息
            while True:
                msg_len = receive_message_length()
                data = receive_full_message(msg_len)
                data = pickle.loads(data)
                self.put_queue(data, addr)
        except ConnectionResetError:
            logger.info(f"用户 {addr} 下线")
            self.del_user(addr)
            try:
                conn.close()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"接收消息失败: {e}")
            try:
                conn.close()
            except Exception:
                pass

    def run(self):
        # 寻找可用端口
        available_port = find_available_port(PORT)
        if available_port is None:
            logger.error("无法找到可用端口，启动失败")
            return
        
        self.addr = (IP, available_port)
        
        try:
            self.socket.bind(self.addr)
            self.socket.listen(50)  # 增加监听队列大小
            logger.info(f"开始在 {IP}:{available_port} 处侦听")
            
            # 启动消息发送线程
            send_thread = threading.Thread(target=self.send_msg, daemon=True)
            send_thread.start()
            
            while True:
                try:
                    conn, addr = self.socket.accept()
                    conn = self.ssl_context.wrap_socket(conn, server_side=True)
                    # 设置超时
                    conn.settimeout(300)  # 5分钟超时
                    logger.info(f"新用户连接：{addr}")
                    # 使用线程池处理新连接
                    thread_pool.submit(self.recv_msg, conn, addr)
                except Exception as e:
                    logger.error(f"接受连接失败: {e}")
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"服务器运行失败: {e}")
        finally:
            try:
                self.socket.close()
            except Exception:
                pass

# 文件服务器类
class FileServer(threading.Thread):
    def __init__(self, ip, port):
        threading.Thread.__init__(self)
        self.addr = (ip, port)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.path = r'resources'
        # 确保resources目录存在
        if not os.path.exists(self.path):
            os.makedirs(self.path)
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
        # 寻找可用端口
        available_port = find_available_port(PORT + 1)
        if available_port is None:
            logger.error("文件服务器无法找到可用端口，启动失败")
            return
        
        self.addr = (IP, available_port)
        
        try:
            logger.info('文件服务器运行中...')
            self.s.bind(self.addr)
            logger.info(f'文件服务器工作地址：{self.addr}')
            self.s.listen(20)
            while True:
                try:
                    conn, addr = self.s.accept()  # 处理链接
                    thread_pool.submit(self.handle_client, conn, addr)
                except Exception as e:
                    logger.error(f"文件服务器接受连接失败: {e}")
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"文件服务器运行失败: {e}")
        finally:
            try:
                self.s.close()
            except Exception:
                pass

if __name__ == "__main__":
    try:
        # 创建并启动聊天服务器
        cserver = ChatServer(IP, PORT)
        cserver.daemon = True
        cserver.start()
        
        # 创建并启动文件服务器
        fserver = FileServer(IP, PORT + 1)
        fserver.daemon = True
        fserver.start()
        
        # 保持主线程运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("服务器正在关闭...")
    finally:
        # 关闭线程池
        thread_pool.shutdown(wait=False)
        logger.info("服务器已关闭")
