#!/usr/bin/env python3
"""
pool_manager.py — DuckDB版本
六池管理：bottom(底部放量)、limit_up(涨停池)、main_line(主线池)、
           strong(强势池)、user_pick(自选池)、hot(人气池)
"""

import os
import json
from datetime import datetime
from pathlib import Path
import duckdb

DB_PATH = Path('/root/.openclaw/workspace/skills/ifind-momentum-screener/data/pools/pools.duckdb')
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# 初始化数据库
def _init_db():
    conn = duckdb.connect(str(DB_PATH))
    
    # 只创建不存在的表，不删除已有数据
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pools (
            code VARCHAR,
            name VARCHAR,
            pool_type VARCHAR,
            source VARCHAR,
            sector VARCHAR,
            close_price DOUBLE,
            change_pct DOUBLE,
            volume DOUBLE,
            added_date DATE DEFAULT CURRENT_DATE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (code, pool_type, added_date)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pool_history (
            id INTEGER PRIMARY KEY,
            code VARCHAR,
            pool_type VARCHAR,
            action VARCHAR,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.close()

# 添加/更新股票到池子
def upsert_pool(pool_type: str, stocks: list):
    """
    stocks: [{code, name, source, sector, close, change_pct, volume}]
    """
    _init_db()
    conn = duckdb.connect(str(DB_PATH))
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    for s in stocks:
        code = s.get('code', '')
        name = s.get('name', '')
        source = s.get('source', '')
        sector = s.get('sector', '')
        close = s.get('close', 0.0)
        change_pct = s.get('change_pct', 0.0)
        volume = s.get('volume', 0.0)
        
        # 检查是否已存在（同一天同类型同代码）
        existing = conn.execute(f"""
            SELECT COUNT(*) FROM pools 
            WHERE code = '{code}' AND pool_type = '{pool_type}' AND added_date = '{today}'
        """).fetchone()[0]
        
        if existing > 0:
            # 更新：合并source信息
            old = conn.execute(f"""
                SELECT source FROM pools 
                WHERE code = '{code}' AND pool_type = '{pool_type}' AND added_date = '{today}'
            """).fetchone()
            old_source = old[0] if old else ''
            if source and source not in old_source:
                new_source = old_source + ';' + source if old_source else source
                conn.execute(f"""
                    UPDATE pools SET source = '{new_source}', updated_at = CURRENT_TIMESTAMP
                    WHERE code = '{code}' AND pool_type = '{pool_type}' AND added_date = '{today}'
                """)
        else:
            # 插入新记录
            conn.execute(f"""
                INSERT INTO pools (code, name, pool_type, source, sector, close_price, change_pct, volume, added_date)
                VALUES ('{code}', '{name}', '{pool_type}', '{source}', '{sector}', {close}, {change_pct}, {volume}, '{today}')
            """)
    
    conn.commit()
    conn.close()
    print(f"  ✅ {pool_type}池: 更新{len(stocks)}只")

# 读取池子
def load_pool(pool_type: str, date_str: str = None) -> list:
    """读取某池子的最新数据"""
    _init_db()
    conn = duckdb.connect(str(DB_PATH))
    
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    result = conn.execute(f"""
        SELECT code, name, pool_type, source, sector, close_price, change_pct, volume
        FROM pools 
        WHERE pool_type = '{pool_type}' AND added_date = '{date_str}'
        ORDER BY updated_at DESC
    """).fetchall()
    
    conn.close()
    
    stocks = []
    for row in result:
        stocks.append({
            'code': row[0], 'name': row[1], 'pool_type': row[2],
            'source': row[3], 'sector': row[4],
            'close': row[5], 'change_pct': row[6], 'volume': row[7]
        })
    
    return stocks

# 清空某池子
def clear_pool(pool_type: str):
    """清空某池子（用于每日更新前）"""
    _init_db()
    conn = duckdb.connect(str(DB_PATH))
    conn.execute(f"DELETE FROM pools WHERE pool_type = '{pool_type}'")
    conn.commit()
    conn.close()
    print(f"  🗑️ {pool_type}池已清空")

# 获取所有池子的统计
def get_pool_stats():
    """获取各池子数量统计"""
    _init_db()
    conn = duckdb.connect(str(DB_PATH))
    
    result = conn.execute("""
        SELECT pool_type, COUNT(*) as cnt, MAX(added_date) as latest_date
        FROM pools
        GROUP BY pool_type
        ORDER BY pool_type
    """).fetchall()
    
    conn.close()
    return {row[0]: {'count': row[1], 'latest_date': row[2]} for row in result}

# 从txt/json迁移（一次性）
def migrate_from_json(json_dir: str):
    """从旧json文件迁移到DuckDB"""
    import glob
    json_files = glob.glob(f"{json_dir}/*_pool.json")
    
    for jf in json_files:
        pool_type = Path(jf).stem.replace('_pool', '')
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            stocks = []
            if isinstance(data, list):
                for item in data:
                    stocks.append({
                        'code': item.get('code', ''),
                        'name': item.get('name', ''),
                        'source': item.get('source', ''),
                        'sector': item.get('sector', ''),
                        'close': item.get('close', 0.0),
                        'change_pct': item.get('change_pct', 0.0),
                        'volume': item.get('volume', 0.0)
                    })
            
            if stocks:
                upsert_pool(pool_type, stocks)
                print(f"  ✅ 迁移 {pool_type}: {len(stocks)}只")
        except Exception as e:
            print(f"  ⚠️ 迁移 {pool_type} 失败: {e}")


if __name__ == '__main__':
    # 测试
    _init_db()
    print("DuckDB池子系统已初始化")
    stats = get_pool_stats()
    print("当前池子状态:", stats)
