import socket
import asyncio
import time
import os
import base64
import json
import pickle
import sqlite3
import requests
import unicodedata
import hashlib
import secrets
import logging
import aiosqlite
from contextlib import asynccontextmanager

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


try:
    IP = socket.gethostbyname(socket.gethostname())
except Exception:
    IP = '0.0.0.0'
PORT = 50000
OLLAMA_API_URL = "http://localhost:11434/api/chat"

onlines = []
onlines_lock = asyncio.Lock()
conversation_history = []


class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_msg(
                    user_name TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    icon_data BLOB,
                    PRIMARY KEY(user_name)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_name
                ON user_msg(user_name)
            """)
            await db.commit()

    @asynccontextmanager
    async def get_connection(self):
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    async def verify_login(self, username, password):
        async with self.get_connection() as db:
            cursor = await db.execute(
                "SELECT user_name, password FROM user_msg WHERE user_name = ?",
                (username,)
            )
            row = await cursor.fetchone()
            if row and verify_password(password, row[1]):
                return True
            return False

    async def check_user_exists(self, username):
        async with self.get_connection() as db:
            cursor = await db.execute(
                "SELECT user_name FROM user_msg WHERE user_name = ?",
                (username,)
            )
            result = await cursor.fetchall()
            return len(result) > 0

    async def register_user(self, username, password):
        async with self.get_connection() as db:
            try:
                hashed = hash_password(password)
                await db.execute(
                    "INSERT INTO user_msg (user_name,password) VALUES(?,?)",
                    (username, hashed)
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def update_user(self, old_username, old_password, new_username, new_password, icon_data):
        async with self.get_connection() as db:
            cursor = await db.execute(
                "SELECT user_name, password FROM user_msg WHERE user_name = ?",
                (old_username,)
            )
            row = await cursor.fetchone()
            if not row or not verify_password(old_password, row[1]):
                return False, "User not found"

            new_hashed = hash_password(new_password)
            if icon_data:
                await db.execute(
                    "UPDATE user_msg SET user_name = ?, password = ?, icon_data = ? WHERE user_name = ?",
                    (new_username, new_hashed, icon_data, old_username)
                )
            else:
                await db.execute(
                    "UPDATE user_msg SET user_name = ?, password = ? WHERE user_name = ?",
                    (new_username, new_hashed, old_username)
                )
            await db.commit()
            return True, "Success"

    async def delete_user(self, username):
        async with self.get_connection() as db:
            await db.execute("DELETE FROM user_msg WHERE user_name = ?", (username,))
            await db.commit()
            return True


db_manager = DatabaseManager("user_message.db")


def call_robot(question, think):
    answer = ""
    conversation_history.append({"role": "user", "content": question})

    payload = {
        "model": "deepseek-r1",
        "messages": conversation_history,
        "stream": True,
        "think": think,
    }

    try:
        with requests.post(OLLAMA_API_URL, json=payload, stream=True) as response:
            response.raise_for_status()

            logger.info("deepseek: ")

            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode('utf-8'))
                    content = chunk['message']['content']
                    answer += content

                    if chunk.get('done', False):
                        conversation_history.append({"role": "assistant", "content": answer})
                        print(answer)
                        return answer

    except requests.exceptions.RequestException as e:
        logger.error(f"无法连接到Ollama API: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"解析JSON响应失败: {e}")
    except Exception as e:
        logger.error(f"调用机器人失败: {e}")
    return answer


def split_str(string: str, max_width):
    parts = []
    current_width = 0
    buffer = []

    for char in string:
        width = unicodedata.east_asian_width(char)
        char_width = 2 if width in 'FW' else 1
        if current_width + char_width > max_width:
            parts.append(''.join(buffer))
            buffer = [char]
            current_width = char_width
        else:
            buffer.append(char)
            current_width += char_width
    if buffer:
        parts.append(''.join(buffer))

    text = '\n'.join(parts)
    return text


async def send_header_and_data(writer, header_type, data_bytes):
    head = json.dumps({"type": header_type, "size": len(data_bytes)}).encode()
    padding = 1024 - len(head)
    writer.write(head + b' ' * padding)
    writer.write(data_bytes)
    await writer.drain()


async def broadcast_message(data, targets=None):
    if targets is None:
        targets = onlines
    data_bytes = pickle.dumps(data)
    header_type = data[0] if isinstance(data[0], str) else "update"
    if header_type == "invite_v":
        header_type = "update"
    if header_type == "invite_a":
        header_type = "update"

    head = json.dumps({"type": header_type, "size": len(data_bytes)}).encode()
    padding = 1024 - len(head)

    for user in (targets if targets is not onlines else onlines):
        try:
            user[0].write(head + b' ' * padding)
            user[0].write(data_bytes)
        except Exception:
            pass

    for user in (targets if targets is not onlines else onlines):
        try:
            await user[0].drain()
        except Exception:
            pass


async def handle_client(reader, writer):
    global onlines
    conn = writer
    addr = writer.get_extra_info('peername')
    logger.info(f"新用户连接：{addr}")
    login_msg = None
    current_username = None

    async def recv_exactly(num_bytes):
        data = b''
        while len(data) < num_bytes:
            chunk = await reader.read(num_bytes - len(data))
            if not chunk:
                raise ConnectionResetError
            data += chunk
        return data

    try:
        msg_len_bytes = await recv_exactly(1024)
        msg_len = int(msg_len_bytes.decode())
        login_msg_bytes = await recv_exactly(msg_len)
        login_msg = pickle.loads(login_msg_bytes)
        logger.debug(f"收到来自 {addr} 的消息: {login_msg[0]}")

        if login_msg[0] == "login":
            try:
                async with onlines_lock:
                    for user in onlines:
                        if user[1] == login_msg[1]:
                            await send_header_and_data(conn, "login_echo", "Repeated Login".encode())
                            break
                    else:
                        success = await db_manager.verify_login(login_msg[1], login_msg[2])
                        if success:
                            await send_header_and_data(conn, "login_echo", "Login Success".encode())
                            logger.info(f"用户 {login_msg[1]} 从 {addr} 登录成功")
                            async with onlines_lock:
                                onlines.append((conn, login_msg[1], addr))
                                users = [(user[1], user[2]) for user in onlines]
                            logger.info(f"用户 {login_msg[1]} 加入在线列表，当前在线用户数: {len(onlines)}")
                            await broadcast_message(users)
                        else:
                            await send_header_and_data(conn, "login_echo", "Login Failed".encode())
                            logger.warning(f"用户 {login_msg[1]} 从 {addr} 登录失败: 用户名或密码错误")
            except Exception as e:
                logger.error(f"数据库登录验证失败: {e}")
                await send_header_and_data(conn, "login_echo", "Login Failed".encode())
        elif login_msg[0] == "sign up":
            try:
                exists = await db_manager.check_user_exists(login_msg[1])
                if not exists:
                    success = await db_manager.register_user(login_msg[1], login_msg[2])
                    if success:
                        await send_header_and_data(conn, "sign up_echo", "Sign Up Success".encode())
                        logger.info(f"用户 {login_msg[1]} 从 {addr} 注册成功")
                    else:
                        await send_header_and_data(conn, "sign up_echo", "Sign Up Failed".encode())
                else:
                    await send_header_and_data(conn, "sign up_echo", "Repeated Sign Up".encode())
                    logger.warning(f"用户 {login_msg[1]} 从 {addr} 注册失败: 用户名已存在")
            except Exception as e:
                logger.error(f"用户 {login_msg[1]} 注册失败: {e}")
                await send_header_and_data(conn, "sign up_echo", "Sign Up Failed".encode())

        logger.debug(f"当前在线用户: {onlines}")
        while True:
            msg_len_bytes = await recv_exactly(1024)
            msg_len = int(msg_len_bytes.decode())
            data_bytes = await recv_exactly(msg_len)
            data = pickle.loads(data_bytes)
            logger.debug(f"收到来自 {addr} 的消息: {data[0]}")

            if isinstance(data[0], str):
                if data[0] == "text":
                    logger.info(f"收到来自 {login_msg[1]} 的文本消息，目标: {data[2]}")
                elif data[0] == "update":
                    logger.info(f"用户 {login_msg[1]} 更新个人信息")
                    old_username, old_password = data[1][0], data[1][1]
                    new_username, new_password = data[2][0], data[2][1]
                    icon_data = base64.b64decode(data[2][2]) if len(data[2]) > 2 and data[2][2] else None

                    success, _ = await db_manager.update_user(old_username, old_password, new_username, new_password, icon_data)

                    if success:
                        async with onlines_lock:
                            for i, user in enumerate(onlines):
                                if user[1] == old_username:
                                    onlines[i] = (user[0], new_username, user[2])
                                    break
                        await send_header_and_data(conn, "update_echo", "Update Success".encode())
                        async with onlines_lock:
                            users = [(u[1], u[2]) for u in onlines]
                        await broadcast_message(users)
                    else:
                        await send_header_and_data(conn, "update_echo", "Update Failed".encode())
                    continue
                elif data[0] == "delete":
                    logger.info(f"用户 {login_msg[1]} 请求注销账号")
                    target_user = data[1]
                    success = await db_manager.delete_user(target_user)
                    if success:
                        await send_header_and_data(conn, "delete_echo", "Delete Success".encode())
                        logger.info(f"用户 {target_user} 已注销")
                    else:
                        await send_header_and_data(conn, "delete_echo", "Delete Failed".encode())
                    continue
                elif data[0] == "vchat":
                    logger.info(f"用户 {login_msg[1]} 请求视频聊天，目标: {data[2]}")
                elif data[0] == "achat":
                    logger.info(f"用户 {login_msg[1]} 请求语音聊天，目标: {data[2]}")
                elif data[2] == "robot":
                    logger.info(f"用户 {login_msg[1]} 向机器人发送消息")
                    question = data[1]
                    think = data[4] if len(data) > 4 else False
                    answer = await asyncio.to_thread(call_robot, question, think)
                    async with onlines_lock:
                        for user in onlines:
                            if user[1] == login_msg[1] and user[2] == addr:
                                response = ['text', split_str(str(answer), 30), [(user[1], user[2])], "robot"]
                                await broadcast_message(response, [user])
                                break
                    continue

                targets = []
                for target_info in data[2]:
                    async with onlines_lock:
                        for user in onlines:
                            if user[1] == target_info[0] and user[2] == target_info[1]:
                                targets.append(user)
                                break
                if targets:
                    await broadcast_message(data, targets)
                else:
                    await broadcast_message(data)

    except ConnectionResetError:
        logger.info(f"用户 {addr} 下线")
    except Exception as e:
        logger.error(f"接收消息失败: {e}")
    finally:
        try:
            async with onlines_lock:
                for i, user in enumerate(onlines):
                    if user[2] == addr:
                        onlines.pop(i)
                        break
            async with onlines_lock:
                users = [(u[1], u[2]) for u in onlines]
            if users:
                await broadcast_message(users)
        except Exception:
            pass
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def handle_file_client(reader, writer):
    addr = writer.get_extra_info('peername')
    conn = writer
    logger.info(f'文件服务器：客户机地址：{addr}')
    current_path = r'resources'

    try:
        while True:
            data = await reader.read(1024)
            if not data:
                break
            data = data.decode()
            if data == 'quit':
                logger.info(f'文件服务器：客户机 {addr} 文件服务结束！')
                break

            order = data.split()[0]
            if order == 'get':
                try:
                    name = data.split()[1]
                    fileName = r'./' + name
                    with open(fileName, 'rb') as f:
                        while True:
                            a = f.read(1024)
                            if not a:
                                break
                            conn.write(a)
                            await conn.drain()
                    await asyncio.sleep(0.1)
                    conn.write('EOF'.encode())
                    await conn.drain()
                    logger.info(f"发送文件成功: {name}")
                except Exception as e:
                    logger.error(f"发送文件失败: {e}")
            elif order == 'put':
                try:
                    name = data.split()[1]
                    fileName = r'./' + name
                    with open(fileName, 'wb') as f:
                        while True:
                            chunk = await reader.read(1024)
                            if chunk == b'EOF':
                                break
                            f.write(chunk)
                    logger.info(f"接收文件成功: {name}")
                except Exception as e:
                    logger.error(f"接收文件失败: {e}")
            elif order == 'dir':
                try:
                    listdir = os.listdir('.')
                    listdir_json = json.dumps(listdir)
                    conn.write(listdir_json.encode())
                    await conn.drain()
                    logger.info(f"发送目录列表成功")
                except Exception as e:
                    logger.error(f"发送目录列表失败: {e}")
            elif order == 'cd':
                try:
                    message = data.split()[1]
                    if message != 'same':
                        f = r'./' + message
                        os.chdir(f)
                    path = os.getcwd().split('\\')
                    for i in range(len(path)):
                        if path[i] == 'resources':
                            break
                    pat = ''
                    for j in range(i, len(path)):
                        pat = pat + path[j] + ' '
                    pat = '\\'.join(pat.split())
                    conn.write(pat.encode())
                    await conn.drain()
                except Exception as e:
                    logger.error(f"切换目录失败: {e}")
    except Exception as e:
        logger.error(f"文件服务器处理客户端失败: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def run_chat_server():
    await db_manager.init_db()
    server = await asyncio.start_server(handle_client, IP, PORT)
    logger.info(f"开始在 {IP} 处侦听")
    async with server:
        await server.serve_forever()


async def run_file_server():
    file_port = PORT + 1
    original_path = os.getcwd()
    os.chdir(r'resources')

    server = await asyncio.start_server(handle_file_client, IP, file_port)
    logger.info(f"文件服务器工作地址：{IP}:{file_port}")
    async with server:
        await server.serve_forever()


async def main():
    await db_manager.init_db()
    chat_task = asyncio.create_task(run_chat_server())
    file_task = asyncio.create_task(run_file_server())
    logger.info("服务器启动完成")
    await asyncio.gather(chat_task, file_task)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("服务器关闭")
    except Exception as e:
        logger.error(f"服务器运行失败: {e}")
