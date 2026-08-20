"""
F-Score + Z-Score 质量因子模块
用于v22引擎的基本面质量过滤
"""

def calc_fscore_from_financials(data: dict) -> dict:
    """
    计算简化版F-Score（5分制）
    输入: data中需要包含以下字段:
        - roe: ROE (%)
        - gross_margin: 毛利率 (%)
        - net_margin: 净利率 (%)
        - debt_ratio: 资产负债率 (%)
        - current_ratio: 流动比率
    输出: {
        'f_score': int,  # 0~5
        'quality_tag': str,  # '优秀'/'良好'/'中等'/'较差'
        'reasons': list,
        'warnings': list,
    }
    """
    roe = data.get('roe')
    gross = data.get('gross_margin')
    net = data.get('net_margin')
    debt = data.get('debt_ratio')
    current = data.get('current_ratio')
    
    score = 0
    reasons = []
    warnings = []
    
    # 赚钱能力 (2分)
    if roe is not None and roe > 0:
        score += 1
        reasons.append("ROE>0")
    else:
        warnings.append("ROE为负或缺失")
    
    if gross is not None and gross > 10:
        score += 1
        reasons.append("毛利率>10%")
    else:
        warnings.append("毛利率低或缺失")
    
    # 财务健康 (2分)
    if debt is not None and debt < 60:
        score += 1
        reasons.append("负债率<60%")
    else:
        if debt is not None and debt > 80:
            warnings.append(f"负债率过高({debt:.1f}%)")
    
    if current is not None and current > 1:
        score += 1
        reasons.append("流动比率>1")
    else:
        if current is not None and current < 0.8:
            warnings.append(f"流动比率低({current:.2f})")
    
    # 运营效率 (1分)
    if net is not None and net > 0:
        score += 1
        reasons.append("净利率>0")
    else:
        warnings.append("净利率为负或缺失")
    
    # 评级
    if score >= 4:
        tag = "优秀"
    elif score >= 3:
        tag = "良好"
    elif score >= 2:
        tag = "中等"
    else:
        tag = "较差"
    
    return {
        'f_score': score,
        'quality_tag': tag,
        'reasons': reasons,
        'warnings': warnings,
    }


def calc_quality_adjustment(f_score: int) -> dict:
    """
    根据F-Score计算v22评分调整
    返回: {
        'fusion_bonus': float,  # Step 4加分
        'final_multiplier': float,  # Step 8乘数
        'risk_flag': str,  # 'exclude'/'caution'/'normal'
    }
    """
    if f_score >= 4:
        return {
            'fusion_bonus': 0.5,
            'final_multiplier': 1.05,
            'risk_flag': 'normal',
        }
    elif f_score == 3:
        return {
            'fusion_bonus': 0.3,
            'final_multiplier': 1.0,
            'risk_flag': 'normal',
        }
    elif f_score == 2:
        return {
            'fusion_bonus': 0.0,
            'final_multiplier': 1.0,
            'risk_flag': 'caution',
        }
    elif f_score == 1:
        return {
            'fusion_bonus': -0.3,
            'final_multiplier': 0.95,
            'risk_flag': 'caution',
        }
    else:  # 0
        return {
            'fusion_bonus': -0.5,
            'final_multiplier': 0.90,
            'risk_flag': 'exclude',
        }
