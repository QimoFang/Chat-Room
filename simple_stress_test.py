import socket
import threading
import time
import pickle
import json
import random
import string

# 服务器配置
SERVER_IP = socket.gethostbyname(socket.gethostname())
SERVER_PORT = 50000

# 测试配置
MAX_CLIENTS = 50  # 最大并发客户端数
MESSAGES_PER_CLIENT = 5  # 每个客户端发送的消息数

# 测试结果
results = {
    'start_time': 0,
    'end_time': 0,
    'total_connections': 0,
    'successful_connections': 0,
    'failed_connections': 0,
    'total_messages': 0,
    'successful_messages': 0,
    'failed_messages': 0,
    'avg_response_time': 0,
    'max_response_time': 0,
    'min_response_time': float('inf')
}

# 生成随机用户名和密码
def generate_random_string(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# 客户端测试函数
def client_test(client_id):
    global results
    
    # 生成唯一的用户名和密码
    username = f"test_user_{client_id}_{generate_random_string(4)}"
    password = generate_random_string(8)
    
    try:
        # 创建套接字并连接服务器
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_IP, SERVER_PORT))
        results['total_connections'] += 1
        results['successful_connections'] += 1
        
        # 注册用户
        register_msg = pickle.dumps(["sign up", username, password])
        sock.send(str(len(register_msg)).encode() + b'\n')
        sock.send(register_msg)
        
        # 接收注册响应
        try:
            head = sock.recv(1024)
            print(f"客户端 {client_id} 收到注册响应头: {head}")
            if head == b'':
                print(f"客户端 {client_id} 连接失败: 服务器返回空响应")
                results['failed_connections'] += 1
                sock.close()
                return
            head = json.loads(head.decode())
            echo_msg = sock.recv(head["size"])
            echo_msg = echo_msg.decode()
            
            print(f"客户端 {client_id} 收到注册响应: {echo_msg}")
            
            if echo_msg == "Sign Up Success":
                print(f"客户端 {client_id} 注册成功")
                results['successful_connections'] += 1
            else:
                print(f"客户端 {client_id} 注册失败: {echo_msg}")
                results['failed_connections'] += 1
        except json.JSONDecodeError as e:
            print(f"客户端 {client_id} JSON解析失败: {e}")
            results['failed_connections'] += 1
        except Exception as e:
            print(f"客户端 {client_id} 处理注册响应失败: {e}")
            results['failed_connections'] += 1
        finally:
            sock.close()
        
        # 关闭连接
        sock.close()
        
    except Exception as e:
        print(f"客户端 {client_id} 连接失败: {e}")
        results['failed_connections'] += 1

# 运行测试
def run_stress_test():
    print(f"开始压力测试...")
    print(f"服务器: {SERVER_IP}:{SERVER_PORT}")
    print(f"最大并发客户端: {MAX_CLIENTS}")
    print(f"每个客户端消息数: {MESSAGES_PER_CLIENT}")
    print("=" * 60)
    
    # 记录开始时间
    results['start_time'] = time.time()
    
    # 启动客户端线程
    client_threads = []
    for i in range(MAX_CLIENTS):
        time.sleep(0.5)
        # 控制并发连接数，避免瞬间创建太多连接
        if i > 0 and i % 10 == 0:
            time.sleep(1)
        
        thread = threading.Thread(target=client_test, args=(i,))
        client_threads.append(thread)
        thread.start()
    
    # 等待所有客户端线程完成
    for thread in client_threads:
        thread.join()
    
    # 记录结束时间
    results['end_time'] = time.time()
    
    # 打印测试结果
    print("=" * 60)
    print("测试结果:")
    print(f"测试持续时间: {results['end_time'] - results['start_time']:.2f}秒")
    print(f"总连接数: {results['total_connections']}")
    print(f"成功连接数: {results['successful_connections']}")
    print(f"失败连接数: {results['failed_connections']}")
    print(f"连接成功率: {(results['successful_connections'] / results['total_connections'] * 100):.2f}%")
    print(f"总消息数: {results['total_messages']}")
    print(f"成功消息数: {results['successful_messages']}")
    print(f"失败消息数: {results['failed_messages']}")
    if results['total_messages'] > 0:
        print(f"消息成功率: {(results['successful_messages'] / results['total_messages'] * 100):.2f}%")
        print(f"平均响应时间: {results['avg_response_time']:.4f}秒")
        print(f"最大响应时间: {results['max_response_time']:.4f}秒")
        print(f"最小响应时间: {results['min_response_time']:.4f}秒")
        print(f"消息吞吐量: {results['successful_messages'] / (results['end_time'] - results['start_time']):.2f}消息/秒")
    else:
        print("消息成功率: 0.00%")
        print("平均响应时间: 0.0000秒")
        print("最大响应时间: 0.0000秒")
        print("最小响应时间: 0.0000秒")
        print("消息吞吐量: 0.00消息/秒")

# 主函数
if __name__ == "__main__":
    # 检查服务器是否运行
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_IP, SERVER_PORT))
        sock.close()
        print("服务器连接正常，可以开始测试")
    except Exception as e:
        print(f"无法连接到服务器: {e}")
        print("请先启动服务器，然后再运行压力测试")
        exit(1)
    
    # 运行测试
    run_stress_test()
