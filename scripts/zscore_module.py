#!/usr/bin/env python3
"""
Z-Score防雷模块
基于Altman Z'-Score（非上市公司版，适用于A股）
"""

def calc_zscore(bs_data: dict, is_data: dict) -> dict:
    """
    计算Z'-Score防雷指标
    
    公式: Z' = 0.717*X1 + 0.847*X2 + 3.107*X3 + 0.420*X4 + 0.998*X5
    
    X1 = 营运资金 / 总资产 = (流动资产 - 流动负债) / 总资产
    X2 = 留存收益 / 总资产 = (盈余公积 + 未分配利润) / 总资产
    X3 = EBIT / 总资产 = (营业利润 + 利息费用) / 总资产
    X4 = 股东权益 / 总负债
    X5 = 销售收入 / 总资产
    
    判别标准:
    - Z' > 2.9: 🟢 安全区 (破产风险低)
    - 1.23 < Z' < 2.9: 🟡 灰色区 (需关注)
    - Z' < 1.23: 🔴 危险区 (高破产风险)
    """
    
    # 从balance sheet获取
    current_assets = bs_data.get('ths_total_current_assets_stock')
    current_liab = bs_data.get('ths_total_current_liab_stock')
    total_assets = bs_data.get('ths_total_assets_stock')
    total_liab = bs_data.get('ths_total_liab_stock')
    equity = bs_data.get('ths_total_owner_equity_stock')
    earned_surplus = bs_data.get('ths_earned_surplus_stock')  # 盈余公积
    undistributed = bs_data.get('ths_undstrbtd_profit_stock')  # 未分配利润
    
    # 从income statement获取
    revenue = is_data.get('ths_revenue_stock')
    operating_profit = is_data.get('ths_op_stock')  # 营业利润
    interest_expense = is_data.get('ths_finance_cost_interest_fee_stock')  # 利息费用
    
    # 检查关键数据
    missing = []
    if total_assets is None or total_assets <= 0:
        missing.append('总资产')
    if total_liab is None or total_liab <= 0:
        missing.append('总负债')
    
    if missing:
        return {
            'z_score': None,
            'zone': 'unknown',
            'risk_level': '⚪ 数据缺失',
            'x1': None, 'x2': None, 'x3': None, 'x4': None, 'x5': None,
            'missing': missing,
        }
    
    # 计算X1: 营运资金/总资产
    if current_assets is not None and current_liab is not None:
        x1 = (current_assets - current_liab) / total_assets
    else:
        x1 = 0
    
    # 计算X2: 留存收益/总资产
    retained_earnings = 0
    if earned_surplus is not None:
        retained_earnings += earned_surplus
    if undistributed is not None:
        retained_earnings += undistributed
    x2 = retained_earnings / total_assets
    
    # 计算X3: EBIT/总资产
    if operating_profit is not None:
        ebit = operating_profit
        if interest_expense is not None:
            ebit += interest_expense
        x3 = ebit / total_assets
    else:
        x3 = 0
    
    # 计算X4: 股东权益/总负债
    if equity is not None and total_liab > 0:
        x4 = equity / total_liab
    else:
        x4 = 0
    
    # 计算X5: 销售收入/总资产
    if revenue is not None:
        x5 = revenue / total_assets
    else:
        x5 = 0
    
    # 计算Z'-Score
    z_score = 0.717 * x1 + 0.847 * x2 + 3.107 * x3 + 0.420 * x4 + 0.998 * x5
    
    # 判别区域 (A股适用调整版)
    # 说明: A股公司普遍Z-Score偏低(因留存收益结构和融资环境差异)
    # 参考国内研究，阈值较美国标准放宽
    if z_score > 1.8:
        zone = 'safe'
        risk_level = '🟢 安全'
    elif z_score > 0.9:
        zone = 'gray'
        risk_level = '🟡 灰色'
    else:
        zone = 'danger'
        risk_level = '🔴 危险'
    
    return {
        'z_score': round(z_score, 2),
        'zone': zone,
        'risk_level': risk_level,
        'x1': round(x1, 3),
        'x2': round(x2, 3),
        'x3': round(x3, 3),
        'x4': round(x4, 3),
        'x5': round(x5, 3),
        'missing': [],
    }


def get_zscore_v22_action(zscore_result: dict) -> dict:
    """
    根据Z-Score返回v22引擎处理建议
    
    A股适用版阈值（考虑A股Z-Score普遍偏低）:
    - Z >= 1.5: 安全，无惩罚
    - 0.5 <= Z < 1.5: 灰色，轻微惩罚
    - 0 <= Z < 0.5: 危险，惩罚
    - Z < 0: 极高风险，大幅惩罚
    
    返回: {
        'exclude': bool,  # 是否排除
        'warning': str,   # 警告信息
        'score_penalty': float,  # 得分乘数
    }
    """
    zone = zscore_result.get('zone', 'unknown')
    z = zscore_result.get('z_score', 0)
    
    if zscore_result.get('z_score') is None:
        return {
            'exclude': False,
            'warning': "Z-Score数据缺失",
            'score_penalty': 1.0,
        }
    
    if z >= 1.5:
        return {
            'exclude': False,
            'warning': "",
            'score_penalty': 1.0,
        }
    elif z >= 0.5:
        return {
            'exclude': False,
            'warning': f"Z-Score {z} 灰色区，财务需关注",
            'score_penalty': 0.98,
        }
    elif z >= 0:
        return {
            'exclude': False,
            'warning': f"Z-Score {z} 危险区，财务风险较高",
            'score_penalty': 0.95,
        }
    else:
        return {
            'exclude': True,
            'warning': f"Z-Score {z} < 0，极高破产风险，建议排除",
            'score_penalty': 0.90,
        }
