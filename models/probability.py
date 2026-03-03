import math
from dataclasses import dataclass
from scipy.stats import poisson
from typing import Optional

@dataclass
class EdgeResult:
    market_id: str
    outcome: str
    market_price: float
    true_probability: float
    edge: float
    kelly_fraction: float
    confidence: str
    reasoning: str

def poisson_goal_probability(home_xg, away_xg, elapsed_minutes, total_minutes=90, current_home_goals=0, current_away_goals=0):
    remaining_fraction = max(0, (total_minutes - elapsed_minutes) / total_minutes)
    remaining_home_xg = home_xg * remaining_fraction
    remaining_away_xg = away_xg * remaining_fraction
    max_goals = 8
    home_probs = [poisson.pmf(g, remaining_home_xg) for g in range(max_goals)]
    away_probs = [poisson.pmf(g, remaining_away_xg) for g in range(max_goals)]
    p_home_win = p_draw = p_away_win = p_over_2_5 = p_btts = 0.0
    for h in range(max_goals):
        for a in range(max_goals):
            p = home_probs[h] * away_probs[a]
            final_h = current_home_goals + h
            final_a = current_away_goals + a
            if final_h > final_a: p_home_win += p
            elif final_h == final_a: p_draw += p
            else: p_away_win += p
            if (final_h + final_a) > 2.5: p_over_2_5 += p
            if final_h > 0 and final_a > 0: p_btts += p
    return {"home_win": round(p_home_win,4), "draw": round(p_draw,4), "away_win": round(p_away_win,4), "over_2_5": round(p_over_2_5,4), "btts": round(p_btts,4)}

def basketball_win_probability(home_score, away_score, seconds_remaining, possession=None):
    if seconds_remaining <= 0:
        if home_score > away_score: return {"home_win": 1.0, "away_win": 0.0}
        elif away_score > home_score: return {"home_win": 0.0, "away_win": 1.0}
        else: return {"home_win": 0.5, "away_win": 0.5}
    point_diff = home_score - away_score
    std = 0.03 * math.sqrt(seconds_remaining)
    possession_bonus = 0.5 if possession == "home" else (-0.5 if possession == "away" else 0.0)
    z = (point_diff + possession_bonus) / std if std > 0 else 0
    p_home_win = _normal_cdf(z)
    return {"home_win": round(p_home_win,4), "away_win": round(1-p_home_win,4)}

def find_edge(market_id, market_price, true_probability, outcome, min_edge=0.04, max_kelly=0.06, reasoning=""):
    edge = true_probability - market_price
    if edge < min_edge: return None
    if market_price <= 0 or market_price >= 1: return None
    odds = (1 - market_price) / market_price
    kelly = min(edge / odds, max_kelly)
    confidence = "high" if edge > 0.10 else ("medium" if edge > 0.06 else "low")
    return EdgeResult(market_id=market_id, outcome=outcome, market_price=market_price, true_probability=true_probability, edge=round(edge,4), kelly_fraction=round(kelly,4), confidence=confidence, reasoning=reasoning)

def _normal_cdf(x):
    t = 1 / (1 + 0.2316419 * abs(x))
    d = 0.3989423 * math.exp(-x * x / 2)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.7814779 + t * (-1.8212560 + t * 1.3302744))))
    return 1 - p if x > 0 else p
