#!/usr/bin/env python3
"""
auto_issue_tracker.py - 自动 Bug 跟踪

功能：
- 捕获选股系统异常
- 自动创建 GitHub Issue
- 记录错误上下文（股票代码、评分步骤、堆栈）

用法：
    from auto_issue_tracker import report_bug
    
    try:
        result = run_v22_scoring(...)
    except Exception as e:
        report_bug(e, context={"code": "600519", "step": "technical_score"})
"""

import os
import sys
import traceback
import subprocess
from datetime import datetime
from typing import Dict, Optional

# GitHub 仓库
REPO = "vereyorikad776-byte/a-share-momentum-screener"


def report_bug(
    exception: Exception,
    context: Optional[Dict] = None,
    auto_create: bool = True
) -> str:
    """
    报告 Bug，可选自动创建 GitHub Issue
    
    Args:
        exception: 异常对象
        context: 上下文信息（股票代码、步骤等）
        auto_create: 是否自动创建 GitHub Issue
    
    Returns:
        Issue URL 或错误摘要
    """
    
    # 构建错误信息
    error_type = type(exception).__name__
    error_msg = str(exception)
    stack_trace = traceback.format_exc()
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 构建 Issue 标题和内容
    title = f"🐛 {error_type}: {error_msg[:50]}"
    
    body = f"""## 错误报告

**时间**: {timestamp}
**异常类型**: `{error_type}`
**错误信息**: {error_msg}

### 上下文
"""
    
    if context:
        for key, value in context.items():
            body += f"- **{key}**: {value}\n"
    else:
        body += "- 无额外上下文\n"
    
    body += f"""
### 堆栈跟踪

```python
{stack_trace}
```

### 系统信息

- Python: {sys.version.split()[0]}
- 平台: {sys.platform}

---

> 此 Issue 由 auto_issue_tracker.py 自动生成
"""
    
    print(f"🐛 Bug 捕获: {error_type}")
    print(f"   信息: {error_msg[:100]}")
    if context:
        print(f"   上下文: {context}")
    
    if not auto_create:
        print(f"   ⚠️  auto_create=False，未创建 Issue")
        return ""
    
    # 创建 GitHub Issue
    try:
        result = subprocess.run(
            ["gh", "issue", "create",
             "--repo", REPO,
             "--title", title,
             "--body", body],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            issue_url = result.stdout.strip()
            print(f"   ✅ Issue 已创建: {issue_url}")
            return issue_url
        else:
            print(f"   ❌ 创建失败: {result.stderr}")
            return ""
            
    except FileNotFoundError:
        print(f"   ⚠️  gh CLI 未安装，无法自动创建 Issue")
        return ""
    except subprocess.TimeoutExpired:
        print(f"   ⚠️  创建 Issue 超时")
        return ""
    except Exception as e:
        print(f"   ⚠️  创建 Issue 异常: {e}")
        return ""


def report_data_error(
    code: str,
    name: str,
    error: str,
    data_source: str = "unknown"
) -> str:
    """
    专门报告数据获取错误
    
    Args:
        code: 股票代码
        name: 股票名称
        error: 错误描述
        data_source: 数据源（akshare/iFinD等）
    
    Returns:
        Issue URL
    """
    context = {
        "股票代码": code,
        "股票名称": name,
        "数据源": data_source,
        "错误类型": "数据获取失败"
    }
    
    # 创建一个简化的异常
    class DataFetchError(Exception):
        pass
    
    exc = DataFetchError(f"{name}({code}) 数据获取失败: {error}")
    
    return report_bug(exc, context=context)


# 装饰器：自动捕获异常并报告
def auto_report_bug(context_func=None):
    """
    装饰器：自动捕获函数异常并创建 Issue
    
    用法:
        @auto_report_bug()
        def my_function(code):
            ...
        
        @auto_report_bug(context_func=lambda *a, **k: {"code": a[0]})
        def score_stock(code, name):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # 构建上下文
                context = {}
                if context_func:
                    try:
                        context = context_func(*args, **kwargs)
                    except:
                        pass
                
                context["function"] = func.__name__
                
                report_bug(e, context=context)
                raise  # 重新抛出，不吞异常
        
        return wrapper
    return decorator


# 测试
if __name__ == "__main__":
    print("测试自动 Bug 跟踪...")
    
    try:
        1 / 0
    except Exception as e:
        url = report_bug(e, context={"code": "600519", "step": "测试"}, auto_create=False)
        print(f"测试完成 (auto_create=False)")
