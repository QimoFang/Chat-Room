import socket
import pickle
import json
import time
import random
import string
import threading
import statistics
from datetime import datetime


IP = "127.0.0.1"
PORT = 50000


def generate_random_string(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


class StressTestClient(threading.Thread):
    def __init__(self, client_id, num_messages=10):
        threading.Thread.__init__(self)
        self.client_id = client_id
        self.num_messages = num_messages
        self.username = f"stress_user_{client_id}"
        self.password = "test123"
        self.response_times = []
        self.login_success = False
        self.signup_success = False
        self.message_success = 0
        self.error_count = 0
        self.socket = None

    def run(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)
            self.socket.connect((IP, PORT))

            if random.random() < 0.5:
                self.test_signup()
            else:
                self.test_login()

            if self.login_success or self.signup_success:
                self.test_messaging()

            self.socket.close()
        except Exception as e:
            self.error_count += 1

    def test_signup(self):
        try:
            message = pickle.dumps(["sign up", self.username, self.password])
            start = time.time()
            self.socket.send(str(len(message)).encode())
            self.socket.send(message)

            head = self.socket.recv(1024)
            head = json.loads(head.decode())
            response = self.socket.recv(head["size"])
            response = response.decode()

            elapsed = time.time() - start
            self.response_times.append(elapsed)

            if response == "Sign Up Success":
                self.signup_success = True
                print(f"[Client {self.client_id}] Signup successful in {elapsed:.4f}s")
            else:
                print(f"[Client {self.client_id}] Signup failed: {response}")
        except Exception as e:
            print(f"[Client {self.client_id}] Signup error: {e}")
            self.error_count += 1

    def test_login(self):
        try:
            message = pickle.dumps(["login", self.username, self.password])
            start = time.time()
            self.socket.send(str(len(message)).encode())
            self.socket.send(message)

            head = self.socket.recv(1024)
            head = json.loads(head.decode())
            response = self.socket.recv(head["size"])
            response = response.decode()

            elapsed = time.time() - start
            self.response_times.append(elapsed)

            if response == "Login Success":
                self.login_success = True
                print(f"[Client {self.client_id}] Login successful in {elapsed:.4f}s")
            elif response == "Repeated Login":
                self.login_success = True
                print(f"[Client {self.client_id}] Already logged in")
            else:
                print(f"[Client {self.client_id}] Login failed: {response}")
        except Exception as e:
            print(f"[Client {self.client_id}] Login error: {e}")
            self.error_count += 1

    def test_messaging(self):
        try:
            for i in range(self.num_messages):
                msg = f"Test message {i} from client {self.client_id}"
                target_user = (self.username, self.socket.getsockname())

                message = pickle.dumps(["text", msg, [target_user], target_user])
                start = time.time()
                self.socket.send(str(len(message)).encode())
                self.socket.send(message)

                head = self.socket.recv(1024)
                if head:
                    elapsed = time.time() - start
                    self.response_times.append(elapsed)
                    self.message_success += 1

                time.sleep(0.01)
        except Exception as e:
            print(f"[Client {self.client_id}] Messaging error: {e}")
            self.error_count += 1


def run_stress_test(num_clients=50, messages_per_client=5):
    print("=" * 60)
    print("              服务器压力测试报告")
    print("=" * 60)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"并发客户端数: {num_clients}")
    print(f"每个客户端消息数: {messages_per_client}")
    print("-" * 60)

    print("\n正在启动压力测试...")

    clients = []
    start_time = time.time()

    for i in range(num_clients):
        client = StressTestClient(i, messages_per_client)
        clients.append(client)
        client.start()

        if (i + 1) % 10 == 0:
            print(f"已启动 {i + 1}/{num_clients} 个客户端...")

        time.sleep(0.01)

    print(f"\n已启动全部 {num_clients} 个客户端，等待完成...")

    for client in clients:
        client.join()

    total_time = time.time() - start_time

    all_response_times = []
    total_login_success = 0
    total_signup_success = 0
    total_message_success = 0
    total_errors = 0

    for client in clients:
        all_response_times.extend(client.response_times)
        total_login_success += 1 if client.login_success else 0
        total_signup_success += 1 if client.signup_success else 0
        total_message_success += client.message_success
        total_errors += client.error_count

    print("\n" + "=" * 60)
    print("                    测试结果统计")
    print("=" * 60)

    print(f"\n【总体统计】")
    print(f"  总测试时间: {total_time:.2f} 秒")
    print(f"  成功登录: {total_login_success}/{num_clients}")
    print(f"  成功注册: {total_signup_success}/{num_clients}")
    print(f"  成功消息: {total_message_success}")
    print(f"  总错误数: {total_errors}")

    if all_response_times:
        print(f"\n【响应时间统计】")
        print(f"  最小响应时间: {min(all_response_times)*1000:.2f} ms")
        print(f"  最大响应时间: {max(all_response_times)*1000:.2f} ms")
        print(f"  平均响应时间: {statistics.mean(all_response_times)*1000:.2f} ms")
        if len(all_response_times) > 1:
            print(f"  标准差: {statistics.stdev(all_response_times)*1000:.2f} ms")
            print(f"  中位数: {statistics.median(all_response_times)*1000:.2f} ms")

        p95 = sorted(all_response_times)[int(len(all_response_times) * 0.95)]
        p99 = sorted(all_response_times)[int(len(all_response_times) * 0.99)]
        print(f"  95%分位: {p95*1000:.2f} ms")
        print(f"  99%分位: {p99*1000:.2f} ms")

    throughput = len(all_response_times) / total_time if total_time > 0 else 0
    print(f"\n【吞吐量】")
    print(f"  总请求数/秒: {throughput:.2f}")

    print("\n" + "=" * 60)
    print("                    测试完成")
    print("=" * 60)


def quick_connect_test(num_clients=100):
    print("\n【快速连接测试】")
    print(f"尝试创建 {num_clients} 个并发连接...")

    start_time = time.time()
    success = 0
    failed = 0

    def quick_connect(client_id):
        nonlocal success, failed
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((IP, PORT))
            sock.close()
            success += 1
        except Exception:
            failed += 1

    threads = []
    for i in range(num_clients):
        t = threading.Thread(target=quick_connect, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    elapsed = time.time() - start_time

    print(f"完成时间: {elapsed:.2f} 秒")
    print(f"成功连接: {success}/{num_clients}")
    print(f"失败连接: {failed}/{num_clients}")
    print(f"连接速率: {num_clients/elapsed:.2f} 连接/秒")


if __name__ == "__main__":
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 15 + "服务器压力测试工具 v1.0" + " " * 17 + "║")
    print("╚" + "═" * 58 + "╝")
    print()

    print("请选择测试模式:")
    print("  1. 完整压力测试 (多客户端登录+消息)")
    print("  2. 快速连接测试 (仅测试并发连接)")
    print("  3. 退出")
    print()

    choice = input("请输入选项 (1/2/3): ").strip()

    if choice == "1":
        try:
            num_clients = int(input("输入并发客户端数 (默认50): ") or "50")
            messages = int(input("每个客户端消息数 (默认5): ") or "5")
            run_stress_test(num_clients, messages)
        except ValueError:
            print("输入无效，使用默认值...")
            run_stress_test(50, 5)

    elif choice == "2":
        try:
            num_connections = int(input("输入并发连接数 (默认100): ") or "100")
            quick_connect_test(num_connections)
        except ValueError:
            print("输入无效，使用默认值...")
            quick_connect_test(100)

    elif choice == "3":
        print("退出测试")

    else:
        print("无效选项")