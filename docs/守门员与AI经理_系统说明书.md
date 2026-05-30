# 守门员 × AI 经理 系统说明书

> Phase 15「守门员唯一范式」的权威说明书。讲清楚:每个组件**职责 / 输入 / 输出 / 怎么被调用**,
> 以及**整个系统从触发到开仓到出场的先后逻辑**。出问题先看这份快速定位。
> 维护:改了下面任一组件的职责/接口/时序,**同步更新本文件**。最后更新 2026-05-30 (commit 6b6c1f3 后)。

---

## 0. 一句话定位

> **守门员(gatekeeper)= 操盘指挥官**(管组合、资金、扫描、执行、出场);
> **AI 经理(ai_manager)= 神枪手大脑**(给单笔的最优参数 + 期望R)。
> 守门员每抓到一个触发信号,就问经理"这一单怎么打",经理给参数,守门员回测把关、按资金闸放行、下单、管出场、回填结果。

```
cron */15  ──>  守门员扫描循环 (gatekeeper_live_cycle)
                  │
   每个币 ──┬─> [资金闸] 还有子弹吗? ──否──> skip(不问经理)
            │
            ├─> ① 市场感知 perceive_market   (我现在看到什么行情)
            ├─> ② 精准配对 match_with_perception (这行情该用哪些策略)
            ├─> ③ 信号检测 get_signal         (高分策略里谁此刻触发)
            ├─> ④ 问 AI 经理 ai_manager_params (这一单参数: lev/SL/TP-R/仓位)
            ├─> ⑤ 回测把关 _ev_for_params      (期望R 达标吗? 选 edge 最强那个)
            └─> 下单 _execute_live_enter        (按真实成交量记仓 + 挂原生 SL/TP)
                                                       │
cron */5   ──>  出场管理 gatekeeper_exit_manage  <─────┘ (棍轮移止损/分批止盈/全平)
                  └─> 平仓回填真盈亏 record_outcome ──> 学习飞轮 ──> 喂回 AI 经理(下次更准)
```

---

## 1. 角色与职责(谁管什么 — 别越界)

| | **AI 经理** `ai_manager.py` | **守门员** `gatekeeper.py` + `gatekeeper_live.py` |
|---|---|---|
| 视角 | **单笔**:就这一个信号 | **组合**:整个账户、所有持仓、还有多少子弹 |
| 负责 | leverage / init_sl_pct / tp1~3_r / position_size(保证金) / skip | 扫描、感知、配对、信号检测、**资金闸**、EV 把关、路由、下单、出场、回填 |
| 看得到 | 难度信封 · **可用额度** · **合约规格+费率** · 富感知 · 策略画像 · **自己的历史战绩** | 全账户权益、所有持仓、市场、cron 节奏 |
| 不该做 | 不管组合资金分配(那是守门员的)、不接管自己的结果(改不准就改能力/prompt) | 不替经理拍单笔参数(只把关 EV + 资金) |

**铁律(user 定)**:
- AI 决策不精准 → **改经理的能力(prompt/输入)让它下次自己做对**,不要在守门员贴护栏接管结果。见记忆 `feedback_dont_override_ai`。
- 资金感知是**守门员**的活:经理是单笔视角,会"当子弹无限",必须守门员在组合层管预算。

---

## 2. 组件逐个说明

### ① 富市场感知 `market_perception.perceive_market`
- **职责**:把 K 线翻译成"现在是什么行情"——经理和配对的眼睛。
- **调用**:`perceive_market(symbol, base_candles, aux_candles, base_tf)`
- **输入**:base TF(15m)K线 + aux TF(5m)K线。
- **输出 dict**:`{ok, regime(trend/range/unknown), direction(up/down/flat), volatility(high/mid/low)+vol_pct, volume+vol_ratio, mtf_aligned(base与aux regime一致?)+aux_regime, price_action{pattern, pattern_dir, hunt(猎杀针), momentum}, funding(资金费), orderbook{imbalance,spread_bps}, indicators(各技术指标 state)}`
- **谁用**:守门员决策第①步;经理 prompt 的"市场富感知"段。
- 关键:`regime_from_candles` 定 regime;`candle_patterns.read_price_action` 出形态/猎杀/动能;5m 是微观维度(看反转/猎杀)。

### ② 策略画像 `StrategyProfile` (模型) / `llm_prompts/strategy_profile.py` (生成)
- **职责**:让经理"懂这个策略在做什么"——不是瞎套公式。
- **结构** `StrategyProfile.profile`:`{entry_logic(进场逻辑), edge_source(edge来源/为何有效), weakness(什么环境失效), regime_fit{trend,range: good/ok/bad}, timeframe_fit[], direction}`
- **每个 strategy_type 一行**,由 AI 基于策略代码生成(prompt 在 strategy_profile.py)。
- **谁用**:② 配对(regime_fit/timeframe_fit/direction 做硬过滤);④ 经理 prompt 的"策略画像"段(entry_logic/edge_source/weakness)。

### ③ 精准配对(规则层)`gatekeeper.match_with_perception`
- **职责**:当前市场富画像 × 每个策略画像 → 匹配度评分排序。"这行情该用哪些策略"。
- **调用**:`match_with_perception(perception, timeframe)` → `[{strategy, score, reasons}]` 按分降序。
- **规则**:**硬过滤**(regime 冲突 / 周期不合 / 方向冲突 → 淘汰)+ **软加分**(指标对齐 / MTF 对齐 / 猎杀针)。
- **谁用**:守门员第②步;配出来的高分候选再进③信号检测。

### ④ AI 经理 `ai_manager.ai_manager_params` 【EV 核心钥匙】
- **职责**:给这一单的参数。带着难度基调 + 可用资金 + 合约规格费率 + 富感知 + 策略画像 + 自己战绩,临场判断。
- **调用**:`ai_manager_params(symbol, strategy_type, perception, profile, target_pct, days_remaining, user_id=1, exchange='hyperliquid', base_tf='15m', available_usdt=None)`
- **它的五只眼睛**(prompt 输入):
  1. **难度信封** `profit_difficulty`:月目标 → leverage_cap、R 缩放、blocked。
  2. **可用额度** `available_usdt`:守门员资金闸算好的(已扣安全垫+已开仓);经理在此额度内下注。None=offline 回退拉总权益。
  3. **合约规格+费率** `instrument_constraints(exchange, symbol, lev)`:最小名义 / 最小颗数(防灰尘仓)/ taker 费率(算 EV 含成本)。HL=$10最小名义+szDecimals精度;OKX=minSz×ctVal×price+lotSz步进;费率 HL 0.035% / OKX 0.05%。
  4. **富感知**(见①)。
  5. **策略画像**(见②)+ **历史战绩** `_manager_track_record`(学习飞轮:本策略×当前格子的实测均pnl/胜率/ev_bias)。
- **输出**:`{ok, skip, leverage, init_sl_pct, tp1_r, tp2_r, tp3_r, position_size_usdt(保证金), reason_zh, fee_pct}`。
- **硬约束(双保险 clamp)**:leverage ≤ lev_cap;保证金 ∈ [最小名义÷杠杆, 可用额度];资金连最小单都开不起 → skip。
- 失败/异常 → `ok=False` → 守门员回退机械 `_optimize_params`(只扫 SL,不阻断)。

### ⑤ EV 把关(期望R)`gatekeeper._ev_for_params` / `_manager_params_and_ev`
- **职责**:用经理给的具体参数回测,验证 edge,**用期望R选最优**(不被仓位/杠杆放大)。
- **期望R**:`ev_r = 每笔期望pnl(USDT,已净扣费率) ÷ 每笔风险金(名义×初始SL%)`。剥掉仓位/杠杆/SL宽度 = 纯 edge。
- **选择**:`ev_r ≥ MIN_EV_R(0.1)` 且选 ev_r 最大的那个策略。
- ⚠️ `expected_ev` 仍记**原始 USDT**(学习飞轮 ev_bias 要和 realized_pnl 同口径)。

### ⑥ 守门员 live 执行 `gatekeeper_live.py`
- `gatekeeper_live_cycle()` (cron */15):灰度档判断 → halted 闸 → 逐币 [资金闸→感知→配对→信号→经理→EV] → enter 则下单。
- `_free_budget(user_id, exchange, reserve=0.2)`:**组合层资金闸** = 权益×(1−20%垫) − 已开仓占用保证金。逐币重算(前一个币开了这个就看到减少)。
- `_execute_live_enter(...)`:独占 first-mover(该币已有持仓→跳过)→ 取经理参数 → `_place_order`(paper=模拟/live=真单)→ **按真实成交量(部分成交时<请求量)记 Position** → 挂原生 SL+分批TP trigger(`_place_native_brackets`)→ TG 通知。
- `gatekeeper_exit_manage()` (cron */5):每个 open 守门员持仓:
  - **native(live真单)**:`_manage_native_position` — 按 HL/OKX 真实持仓 size 减少判定成交(非猜价)→ 棍轮移止损(`_compute_native_sl`:保本/锁TP台阶/trailing)→ size≈0 全平 → `_native_realized_pnl` 拉真盈亏 → `record_outcome`。
  - **paper**:逐新 5m bar 跑 `segment_exit.exit_step` 模拟分批出场。

### ⑦ 学习飞轮 `gatekeeper_learning.py`
- `record_decision` → 每次决策留痕 `gatekeeper_decisions`(regime/direction/tf/strategy/params/expected_ev/source)。
- `record_outcome(decision_id, realized_pnl)` → 平仓回填真盈亏。
- `summarize_experience` → 按 (regime,direction,tf,strategy) 分桶:样本数/实测均pnl/胜率/avg_expected_ev/**ev_bias(实测−预期, 负=高估)**。
- `experience_block`(喂合成新策略 AI)/ `_manager_track_record`(喂 AI 经理)→ **闭合飞轮**:经理看到自己战绩,下次更准。

---

## 3. 整个系统的先后逻辑(完整时序)

**开仓链(cron */15 `gatekeeper-live-scan`)**
1. 灰度档 = `config.gatekeeper_live_mode`(off/shadow/paper/live);`halted` → 直接 skip。
2. 解析路由所 `_primary_exchange`、难度 lev_cap。
3. 对每个 `WATCHED_SYMBOLS`(现 ETH+AVAX):
   1. **资金闸** `_free_budget`:可用 < 最小可开(10÷lev_cap)→ skip,不问经理。
   2. ① `perceive_market` → ② `match_with_perception` → ③ `get_signal`(配对高分里谁触发)。
   3. 对每个触发的策略:④ `ai_manager_params`(带 available_usdt+规格费率+战绩)→ ⑤ `_ev_for_params`(期望R)。
   4. 选 `ev_r ≥ MIN_EV_R` 且最大的 → action=enter。
   5. `record_decision`(留痕)。
   6. live/paper → `_execute_live_enter`(独占检查 → 下单 → 真实成交量记仓 → 挂原生 SL/TP → TG)。shadow → 只通知不下单。
**出场链(cron */5 `gatekeeper-exit-scan`)**
4. `gatekeeper_exit_manage` 逐 open 守门员持仓:native 棍轮移止损/检测真成交/全平;全平 → `record_outcome` 回填真盈亏。
**飞轮闭合**
5. `record_outcome` → `gatekeeper_decisions.realized_pnl` → `summarize_experience` → `_manager_track_record` → 下次 ④ 经理 prompt 带上"本格子历史战绩+ev_bias"。

---

## 4. 资金 & EV 规则(硬规矩)

- **EV 标准 = 期望R**(不是原始 USDT):选策略剥掉仓位/杠杆。门槛 `MIN_EV_R=0.1`(税后期望R缓冲)。
- **资金感知分两层**:经理(单笔:保证金≤可用额度)+ 守门员(组合:权益×80%−已占用,留 **20% 安全垫**,**全账户统一**预算,仓数按资金自动算)。
- **保证金 = 本金**;名义 = 本金×杠杆。Position 记的是**交易所真实成交量**(部分成交时 < 请求量,否则出场对账全错)。
- **规格/费率感知**:经理按路由所的最小名义/最小颗数定仓(防 <最小单被跳过 / 留灰尘仓),按 taker 费率算 EV。

---

## 5. 灰度档 & 安全闸

- 灰度:`off`(不动)/`shadow`(扫+记+通知,不下单)/`paper`(全套机器跑通,模拟成交真价格)/`live`(真单真钱)。
- 安全闸:`halted` kill switch、独占 first-mover(一个币最多一个守门员仓)、20% 安全垫、保证金≤可用额度、最小名义可行性、HL agent 过期→强制 paper。
- **当前状态(2026-05-30)**:`gatekeeper_live_mode=paper`(真钱事故后暂停,见 `project_gatekeeper_live_incident`)。

---

## 6. 已知开口

已修(2026-05-30 这轮):
- ✅ 经理**分批比例控制权**(tp1_frac/tp2_frac, 夹 0.2~0.6 且尾段≥0.15)→ 补全"吃头中段不贪尾"。
- ✅ **资金费进 EV**:经理 prompt 当成本+信号 + 回测 `funding_apr` 按持仓时长扣(短线影响小、长线累积)。
- ✅ **方向集中**:由资金闸天然管住(没钱就停、有钱才开),不加方向硬上限(币种本就不同=真分散,user 定)。

仍开口:
- 灰尘仓:全平阈值 `cur_size ≤ orig×2%` 仍可能留 <最小单的残仓(部分缓解,根因 orig_size 已修)。

---

## 7. 关键文件索引

| 组件 | 文件 |
|---|---|
| AI 经理(钥匙) | `app/services/ai_manager.py` |
| 守门员决策 | `app/services/gatekeeper.py` |
| 守门员 live 执行/出场 | `app/services/gatekeeper_live.py` |
| 市场感知 | `app/services/market_perception.py` |
| 策略画像 | `app/services/llm_prompts/strategy_profile.py` + `StrategyProfile` 模型 |
| 学习飞轮 | `app/services/gatekeeper_learning.py` |
| 出场状态机 | `app/services/segment_exit.py` / `segment_backtest.py` |
| 交易所规格 | `app/services/hl_meta.py` / `app/services/okx_meta.py` |
| 下单分派 | `app/tasks/strategy_tasks.py` `_place_order` + `hyperliquid_service.py` |
| cron 排程 | `app/celeryconfig.py`(live-scan */15 · exit-scan */5)|

> 相关记忆:`project_phase15_blueprint`(蓝图哲学)、`project_gatekeeper_live_incident`(真钱事故+修复)、
> `feedback_dont_override_ai`(修AI不接管)、`reference_diagnostics`(诊断速查)。
