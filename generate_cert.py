"""生成自签名 SSL 证书和私钥（使用 openssl）"""

import subprocess
import os

def generate_self_signed_cert(cert_path="cert.pem", key_path="key.pem"):
    """使用 openssl 生成自签名证书"""
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ssl_cert.cfg")
    
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", key_path,
        "-out", cert_path,
        "-days", "3650",
        "-nodes",
        "-config", cfg_path,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"生成证书失败: {result.stderr}")
        return False
    
    print(f"SSL 证书已生成：{cert_path}")
    print(f"SSL 私钥已生成：{key_path}")
    return True

if __name__ == "__main__":
    generate_self_signed_cert()