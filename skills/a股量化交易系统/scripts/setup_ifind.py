#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iFinD API 配置向导
帮助用户配置 iFinD 数据源接入
"""

import os
import json


def setup_ifind():
    print("=" * 60)
    print("iFinD API 配置向导")
    print("=" * 60)
    print()
    
    # 检查现有配置
    env_file = os.path.expanduser("~/.openclaw/.env")
    existing = {}
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    existing[key] = val
    
    print("请选择接入方式:")
    print("  1) 本地终端模式 - iFinD终端开启API服务，本机或局域网调用")
    print("  2) HTTP API模式 - 直接调用iFinD云端/企业API")
    print("  3) Mock模式 - 使用模拟数据（测试用）")
    print()
    
    choice = input("选择 [1/2/3] (默认3): ").strip() or "3"
    
    config = {}
    
    if choice == "1":
        config['IFIND_MODE'] = 'terminal'
        config['IFIND_HOST'] = input(f"终端IP [默认 127.0.0.1]: ").strip() or "127.0.0.1"
        config['IFIND_PORT'] = input(f"终端端口 [默认 10080]: ").strip() or "10080"
        config['IFIND_USER'] = input("iFinD用户名: ").strip()
        config['IFIND_PASS'] = input("iFinD密码: ").strip()
        
    elif choice == "2":
        config['IFIND_MODE'] = 'http'
        config['IFIND_API_URL'] = input("API基础URL (如 https://api.ifind.com/v1): ").strip()
        config['IFIND_TOKEN'] = input("API Token/密钥: ").strip()
        config['IFIND_USER'] = input("用户名 (可选): ").strip()
        
    else:
        config['IFIND_MODE'] = 'mock'
        print("已选择Mock模式，使用模拟数据")
    
    # 保存配置
    os.makedirs(os.path.dirname(env_file), exist_ok=True)
    
    # 保留现有非iFinD配置
    with open(env_file, 'w') as f:
        f.write("# OpenClaw 环境变量配置\n")
        f.write(f"# 生成时间: {__import__('datetime').datetime.now().isoformat()}\n")
        f.write("\n# === iFinD 配置 ===\n")
        for key, val in config.items():
            f.write(f"{key}={val}\n")
        
        # 保留其他配置
        other_keys = [k for k in existing if not k.startswith('IFIND_')]
        if other_keys:
            f.write("\n# === 其他配置 ===\n")
            for key in other_keys:
                f.write(f"{key}={existing[key]}\n")
    
    print()
    print(f"配置已保存到: {env_file}")
    print()
    
    # 测试连接
    if config.get('IFIND_MODE') != 'mock':
        print("测试连接中...")
        test_connection(config)
    
    print()
    print("配置完成！你可以:")
    print("  1. 运行 python3 scripts/ifind_adapter.py 测试数据源")
    print("  2. 运行 python3 scripts/run_single_v3.py 000983 进行完整诊断")


def test_connection(config):
    """测试iFinD连接"""
    import requests
    
    mode = config.get('IFIND_MODE')
    
    try:
        if mode == 'terminal':
            host = config.get('IFIND_HOST', '127.0.0.1')
            port = config.get('IFIND_PORT', '10080')
            url = f"http://{host}:{port}/api/v1/status"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                print(f"✅ 终端API服务连接成功: {url}")
            else:
                print(f"⚠️ 终端返回状态码: {resp.status_code}")
                
        elif mode == 'http':
            api_url = config.get('IFIND_API_URL', '')
            if api_url:
                headers = {'Authorization': f"Bearer {config.get('IFIND_TOKEN', '')}"}
                resp = requests.get(f"{api_url}/status", headers=headers, timeout=5)
                if resp.status_code == 200:
                    print(f"✅ HTTP API连接成功")
                else:
                    print(f"⚠️ API返回状态码: {resp.status_code}")
            else:
                print("⚠️ 未配置API URL")
                
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("   请检查:")
        print("   - iFinD终端是否已开启API服务")
        print("   - 网络连接是否正常")
        print("   - 防火墙是否放行端口")


if __name__ == "__main__":
    setup_ifind()
