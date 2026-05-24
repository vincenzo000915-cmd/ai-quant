// Phase 14g: 统一 strategy.type / candidate_type 中文显示
//
// 支援 3 类 type:
//   1. cat_<name>                — Phase 14 catalog 原型 (30 条)
//   2. cat_<name>_u<id>_<ts>    — Phase 14 catalog clone 给 user (AI 推荐生成)
//   3. 旧 STRATEGY_TYPES 内的 value (ichimoku / vwap_reversion / ma_crossover ...)

// 30 条 catalog 的中文标签（与 scripts/seed_catalog.py 一一对应）
export const CATALOG_TYPE_LABELS = {
  // ─── Trend Following ───
  cat_donchian_turtle: { label: '海龟突破', emoji: '🐢', tag: '趋势' },
  cat_macd_ema200: { label: 'MACD × EMA200 趋势', emoji: '📈', tag: '趋势' },
  cat_supertrend_atr: { label: 'SuperTrend (ATR)', emoji: '🚀', tag: '趋势' },
  cat_ema_ribbon_gmma: { label: 'GMMA 多重 EMA 带', emoji: '🎀', tag: '趋势' },
  cat_adx_di_trend: { label: 'ADX × DI 趋势', emoji: '🎯', tag: '趋势' },
  cat_psar_flip: { label: 'Parabolic SAR 翻转', emoji: '🔄', tag: '趋势' },

  // ─── Mean Reversion ───
  cat_rsi_bb_mean_rev: { label: 'RSI + 布林均值回归', emoji: '⚖️', tag: '回归' },
  cat_zscore_returns: { label: 'Z-Score 统计套利', emoji: '📊', tag: '回归' },
  cat_vwap_pullback: { label: 'VWAP 回归', emoji: '🪞', tag: '回归' },
  cat_stoch_rsi_extremes: { label: 'StochRSI 极值反转', emoji: '🎢', tag: '回归' },
  cat_williams_r_reversal: { label: 'Williams %R 反转', emoji: '🔁', tag: '回归' },
  cat_cci_extremes: { label: 'CCI 极值反转', emoji: '🎚️', tag: '回归' },

  // ─── Breakout ───
  cat_bb_squeeze_breakout: { label: '布林挤压突破', emoji: '💥', tag: '突破' },
  cat_keltner_breakout: { label: 'Keltner 通道突破', emoji: '🚪', tag: '突破' },
  cat_atr_chandelier: { label: 'ATR Chandelier 追踪', emoji: '🕯️', tag: '突破' },
  cat_orb_opening_range: { label: '开盘区间突破 (ORB)', emoji: '🌅', tag: '突破' },
  cat_consolidation_vol_break: { label: '盘整成交量突破', emoji: '💨', tag: '突破' },
  cat_pivot_classic_break: { label: '经典 Pivot 突破', emoji: '🏛️', tag: '突破' },

  // ─── Multi-Confluence ───
  cat_macd_rsi_divergence: { label: 'MACD × RSI 背离', emoji: '🌗', tag: '多重' },
  cat_ichimoku_cloud_break: { label: 'Ichimoku 云带突破', emoji: '☁️', tag: '多重' },
  cat_triple_screen_elder: { label: 'Elder 三屏过滤', emoji: '🛡️', tag: '多重' },
  cat_heikin_ashi_ema: { label: 'Heikin-Ashi × EMA50', emoji: '🎏', tag: '多重' },

  // ─── Volatility ───
  cat_atr_vol_expansion: { label: 'ATR 波动率扩张', emoji: '🌊', tag: '波动' },
  cat_ttm_squeeze: { label: 'TTM Squeeze 释放', emoji: '🎁', tag: '波动' },
  cat_bb_width_percentile: { label: '布林宽度 Percentile', emoji: '📐', tag: '波动' },

  // ─── Momentum ───
  cat_roc_trend: { label: 'ROC 动量趋势', emoji: '⚡', tag: '动量' },
  cat_aroon_cross: { label: 'Aroon 趋势起点', emoji: '🏹', tag: '动量' },
  cat_rsi_momentum_trend: { label: 'RSI 动量 (Cardwell)', emoji: '🔋', tag: '动量' },

  // ─── Volume ───
  cat_obv_trend_confirm: { label: 'OBV 资金流确认', emoji: '💰', tag: '量价' },
  cat_volume_spike_trend: { label: '成交量暴增跟随', emoji: '🌋', tag: '量价' },
};

// 旧的非 catalog STRATEGY_TYPES 兼容
const LEGACY_LABELS = {
  ichimoku: '⭐ Ichimoku 云带',
  vwap_reversion: '⭐ VWAP 回归',
  stochastic: '✅ Stochastic 反转',
  weekly_pivot: '✅ 周枢轴点突破',
  psar: '✅ Parabolic SAR',
  tema: 'TEMA 三重 EMA',
  keltner_channel: 'Keltner 通道',
  cci_reversal: 'CCI 反转',
  atr_breakout: 'ATR 通道突破',
  heikin_ashi: 'Heikin Ashi 趋势',
  golden_cross: '黄金交叉 50/200',
  macd_trend_filter: 'MACD + 200MA 趋势',
  trend_following: '🏆 趋势跟踪 (ADX+EMA)',
  volatility_breakout: '📈 波动率突破 (Donchian)',
  supertrend: '🔽 SuperTrend',
  mean_reversion: '🧠 均值回归 (布林+RSI)',
  ma_crossover: '经典-均线交叉',
  rsi: '经典-RSI 超买超卖',
  macd: '经典-MACD',
  bollinger: '经典-布林带',
};

// 从 type string 中提取 catalog base (cat_xxx) — 兼容 cat_xxx_u<id>_<ts>
function extractCatalogBase(type) {
  if (!type || typeof type !== 'string') return null;
  // 直接命中
  if (CATALOG_TYPE_LABELS[type]) return type;
  // clone 后缀: cat_xxx_u<digits>_<digits>
  const m = type.match(/^(cat_[a-z0-9_]+?)_u\d+_\d+$/);
  if (m && CATALOG_TYPE_LABELS[m[1]]) return m[1];
  // 退一步：找最长 cat_ 前缀
  if (type.startsWith('cat_')) {
    for (const key of Object.keys(CATALOG_TYPE_LABELS)) {
      if (type.startsWith(key + '_') || type === key) return key;
    }
  }
  return null;
}

/**
 * 返回 { label, emoji, tag, raw, isCatalog, isClone }
 *   label   — 中文短标签（不含 emoji）
 *   emoji   — 视觉前缀
 *   tag     — 类别短标 (趋势/回归/突破/动量/量价/波动/多重)
 *   raw     — 原始 type 字符串（tooltip 用）
 *   isCatalog — 是否 catalog 类型
 *   isClone   — 是否 user 克隆 (cat_xxx_uN_TS)
 */
export function prettifyType(type) {
  if (!type) return { label: '—', emoji: '', tag: '', raw: '', isCatalog: false, isClone: false };

  const base = extractCatalogBase(type);
  if (base) {
    const spec = CATALOG_TYPE_LABELS[base];
    return {
      label: spec.label,
      emoji: spec.emoji,
      tag: spec.tag,
      raw: type,
      isCatalog: true,
      isClone: type !== base,
    };
  }

  // 旧 legacy
  if (LEGACY_LABELS[type]) {
    return {
      label: LEGACY_LABELS[type],
      emoji: '',
      tag: '',
      raw: type,
      isCatalog: false,
      isClone: false,
    };
  }

  // 未知 — 显示原 type
  return { label: type, emoji: '', tag: '', raw: type, isCatalog: false, isClone: false };
}

/** 简短版本 — 只要中文 label (含 emoji 前缀)，给 Chip 用 */
export function typeLabelShort(type) {
  const p = prettifyType(type);
  return p.emoji ? `${p.emoji} ${p.label}` : p.label;
}
