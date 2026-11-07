"""
analysis/fibonacci.py
─────────────────────
Institutional Fibonacci Retracement, Extension & Golden Pocket (OTE) Engine.

Calculates key institutional Fibonacci ratios, Golden Pocket OTE (0.618 - 0.705 - 0.786),
expansion projection targets (1.272, 1.618, 2.0, 2.618), and multi-swing Fibonacci
confluence clusters (overlapping HTF and LTF fib lines).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("chanakya.analysis.fibonacci")

# Key Institutional Fibonacci Ratios
FIB_RATIOS_RETRACEMENT = [0.236, 0.382, 0.500, 0.618, 0.705, 0.786, 0.886]
FIB_RATIOS_EXTENSION = [1.272, 1.414, 1.618, 2.000, 2.618]


@dataclass
class FibLevels:
    swing_high: float
    swing_low: float
    direction: str  # "BULLISH" (pullback to demand) | "BEARISH" (pullback to supply)
    span: float

    # Retracement levels (price values)
    level_0: float  # Extreme (100% of move)
    level_236: float
    level_382: float
    level_500: float  # Equilibrium
    level_618: float  # Golden Ratio
    level_705: float  # Institutional OTE midpoint
    level_786: float  # Deep discount / premium boundary
    level_886: float  # Harmonic last defense
    level_100: float  # Origin (0% of move)

    # Extension levels (targets)
    ext_1272: float  # Liquidity target 1
    ext_1414: float
    ext_1618: float  # Golden extension / target 2
    ext_2000: float  # 1:1 Expansion
    ext_2618: float  # Trend extension runner

    # Golden Pocket (0.618 - 0.786 zone)
    golden_pocket_range: tuple[float, float] = (0.0, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "swing_high": self.swing_high,
            "swing_low": self.swing_low,
            "direction": self.direction,
            "span": round(self.span, 2),
            "retracement": {
                "0.0": round(self.level_0, 2),
                "0.236": round(self.level_236, 2),
                "0.382": round(self.level_382, 2),
                "0.500": round(self.level_500, 2),
                "0.618": round(self.level_618, 2),
                "0.705": round(self.level_705, 2),
                "0.786": round(self.level_786, 2),
                "0.886": round(self.level_886, 2),
                "1.0": round(self.level_100, 2),
            },
            "extension": {
                "1.272": round(self.ext_1272, 2),
                "1.414": round(self.ext_1414, 2),
                "1.618": round(self.ext_1618, 2),
                "2.000": round(self.ext_2000, 2),
                "2.618": round(self.ext_2618, 2),
            },
            "golden_pocket": [round(x, 2) for x in self.golden_pocket_range],
        }


@dataclass
class FibCluster:
    level: float
    direction: str
    ratios: list[str]
    count: int
    tolerance_pct: float
    description: str


def compute_fib_levels(
    swing_high: float,
    swing_low: float,
    direction: str = "BULLISH",
) -> FibLevels:
    """
    Computes institutional Fibonacci retracement and extension levels.

    direction="BULLISH":
      Upward impulse from swing_low to swing_high. Pullback retraces down towards swing_low.
      0.0 is swing_high (top), 1.0 is swing_low (bottom).
      Golden Pocket = [level_786, level_618] (buying discount).
      Extensions project above swing_high (targets for longs).

    direction="BEARISH":
      Downward impulse from swing_high to swing_low. Pullback retraces up towards swing_high.
      0.0 is swing_low (bottom), 1.0 is swing_high (top).
      Golden Pocket = [level_618, level_786] (selling premium).
      Extensions project below swing_low (targets for shorts).
    """
    sh = float(max(swing_high, swing_low))
    sl = float(min(swing_high, swing_low))
    span = max(sh - sl, 0.001)

    if direction.upper() in ("BULLISH", "LONG"):
        # Retracement levels from high down towards low
        l0 = sh
        l236 = sh - (0.236 * span)
        l382 = sh - (0.382 * span)
        l500 = sh - (0.500 * span)
        l618 = sh - (0.618 * span)
        l705 = sh - (0.705 * span)
        l786 = sh - (0.786 * span)
        l886 = sh - (0.886 * span)
        l100 = sl

        # Bullish extensions projecting above swing_high
        ext1272 = sh + (0.272 * span)
        ext1414 = sh + (0.414 * span)
        ext1618 = sh + (0.618 * span)
        ext2000 = sh + (1.000 * span)
        ext2618 = sh + (1.618 * span)

        golden_pocket = (min(l618, l786), max(l618, l786))

    else:  # BEARISH / SHORT
        # Retracement levels from low up towards high
        l0 = sl
        l236 = sl + (0.236 * span)
        l382 = sl + (0.382 * span)
        l500 = sl + (0.500 * span)
        l618 = sl + (0.618 * span)
        l705 = sl + (0.705 * span)
        l786 = sl + (0.786 * span)
        l886 = sl + (0.886 * span)
        l100 = sh

        # Bearish extensions projecting below swing_low
        ext1272 = sl - (0.272 * span)
        ext1414 = sl - (0.414 * span)
        ext1618 = sl - (0.618 * span)
        ext2000 = sl - (1.000 * span)
        ext2618 = sl - (1.618 * span)

        golden_pocket = (min(l618, l786), max(l618, l786))

    return FibLevels(
        swing_high=sh,
        swing_low=sl,
        direction=direction.upper(),
        span=span,
        level_0=l0,
        level_236=l236,
        level_382=l382,
        level_500=l500,
        level_618=l618,
        level_705=l705,
        level_786=l786,
        level_886=l886,
        level_100=l100,
        ext_1272=ext1272,
        ext_1414=ext1414,
        ext_1618=ext1618,
        ext_2000=ext2000,
        ext_2618=ext2618,
        golden_pocket_range=golden_pocket,
    )


def evaluate_fib_proximity(
    ltp: float,
    fib: FibLevels,
    proximity_pct: float = 0.50,
) -> dict[str, Any]:
    """
    Evaluates whether LTP is currently testing a critical Fibonacci level or Golden Pocket.
    """
    levels_map = {
        "0.236": fib.level_236,
        "0.382": fib.level_382,
        "0.500 (Equilibrium)": fib.level_500,
        "0.618 (Golden Ratio)": fib.level_618,
        "0.705 (OTE)": fib.level_705,
        "0.786 (Deep Discount/Prem)": fib.level_786,
        "0.886 (Last Defense)": fib.level_886,
    }

    in_golden_pocket = fib.golden_pocket_range[0] <= ltp <= fib.golden_pocket_range[1]

    nearest_name = ""
    min_dist = float("inf")
    nearest_val = 0.0

    for name, val in levels_map.items():
        dist = abs(ltp - val)
        if dist < min_dist:
            min_dist = dist
            nearest_name = name
            nearest_val = val

    dist_pct = (min_dist / max(ltp, 1.0)) * 100.0
    is_at_key_level = dist_pct <= proximity_pct

    # Determine structural target and invalidation
    if fib.direction == "BULLISH":
        invalidation_stop = round(fib.level_886 - (0.10 * fib.span), 2)
        target_1 = round(fib.ext_1272, 2)
        target_2 = round(fib.ext_1618, 2)
    else:
        invalidation_stop = round(fib.level_886 + (0.10 * fib.span), 2)
        target_1 = round(fib.ext_1272, 2)
        target_2 = round(fib.ext_1618, 2)

    return {
        "is_at_key_level": is_at_key_level,
        "in_golden_pocket": in_golden_pocket,
        "nearest_fib_level": nearest_name,
        "nearest_fib_price": round(nearest_val, 2),
        "distance_pct": round(dist_pct, 2),
        "invalidation_stop": invalidation_stop,
        "target_1_ext_1272": target_1,
        "target_2_ext_1618": target_2,
    }


def find_fib_clusters(
    swings: list[tuple[float, float, str]],
    tolerance_pct: float = 0.35,
) -> list[FibCluster]:
    """
    Finds Fibonacci Confluence Clusters across multiple swing impulses
    (e.g., HTF daily swing + ITF hourly swing).
    When 2 or more key Fibonacci levels converge within tolerance_pct, an institutional
    inflection wall is formed.
    """
    if len(swings) < 2:
        return []

    collected_levels: list[tuple[float, str, str]] = []  # (price, ratio_label, direction)

    for sh, sl, direction in swings:
        fl = compute_fib_levels(sh, sl, direction)
        key_ratios = [
            (fl.level_382, f"0.382 ({direction})", direction),
            (fl.level_500, f"0.500 ({direction})", direction),
            (fl.level_618, f"0.618 ({direction})", direction),
            (fl.level_705, f"0.705 ({direction})", direction),
            (fl.level_786, f"0.786 ({direction})", direction),
            (fl.ext_1272, f"1.272_EXT ({direction})", direction),
            (fl.ext_1618, f"1.618_EXT ({direction})", direction),
        ]
        collected_levels.extend(key_ratios)

    # Sort levels by price
    collected_levels.sort(key=lambda x: x[0])

    clusters: list[FibCluster] = []
    used_indices = set()

    for i in range(len(collected_levels)):
        if i in used_indices:
            continue
        base_price, base_label, base_dir = collected_levels[i]
        matched_group = [collected_levels[i]]
        used_indices.add(i)

        for j in range(i + 1, len(collected_levels)):
            if j in used_indices:
                continue
            cand_price, cand_label, cand_dir = collected_levels[j]
            dist_pct = abs(cand_price - base_price) / max(base_price, 1.0) * 100.0
            if dist_pct <= tolerance_pct:
                matched_group.append(collected_levels[j])
                used_indices.add(j)

        if len(matched_group) >= 2:
            avg_price = sum(x[0] for x in matched_group) / len(matched_group)
            ratios = [x[1] for x in matched_group]
            dirs = [x[2] for x in matched_group]
            dominant_dir = (
                "BULLISH" if dirs.count("BULLISH") >= dirs.count("BEARISH") else "BEARISH"
            )
            desc = f"Confluence of {len(matched_group)} Fib levels: {', '.join(ratios)}"
            clusters.append(
                FibCluster(
                    level=round(avg_price, 2),
                    direction=dominant_dir,
                    ratios=ratios,
                    count=len(matched_group),
                    tolerance_pct=tolerance_pct,
                    description=desc,
                )
            )

    return clusters
