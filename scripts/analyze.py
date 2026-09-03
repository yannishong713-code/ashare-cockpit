# -*- coding: utf-8 -*-
"""
analyze.py —— 规则引擎：把 raw.json 的行情 + overrides.json 的宏观/政策，
翻译成 7 大区域的结论，写入 site/data.json。
原则：只用抓到的真实数据；缺数据则该块标「暂无数据」，绝不臆测。
输出里每个判断都带：结论来自(自动规则/手动)、数据日期、说明。
"""
import io, json, os, sys, datetime
import common as C

C.ensure_utf8()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = json.load(open(os.path.join(ROOT, "tmp", "raw.json"), encoding="utf-8"))
OV = json.load(open(os.path.join(ROOT, "data", "overrides.json"), encoding="utf-8"))
OUT_PATH = os.path.join(ROOT, "docs", "data", "data.json")

FET = RAW.get("fetched") or {}
OVM = OV.get("manual") or {}
HOLDINGS = OV["holdings"]

YI = 1e8      # 亿
WAN_YI = 1e12  # 万亿

# ---------- 小工具 ----------
def n0(x):
    try:
        return 0.0 if x in (None, "-", "") else float(x)
    except Exception:
        return 0.0

def money(x):
    """元 -> 亿"""
    return round(n0(x) / YI, 1) if x not in (None, "-", "") else None

def safe_div(a, b):
    return a / b if b else None

def closes(kl):
    return [k["close"] for k in kl] if kl else []

def change_pct(series, n):
    """series 末位 vs n 个交易日前，涨跌幅%"""
    if len(series) > n and series[-n - 1]:
        base = series[-n - 1]
        if base:
            return (series[-1] / base - 1) * 100
    return None

def pos_in_range(series, look=40):
    if len(series) < 5:
        return None
    w = series[-look:]
    lo, hi = min(w), max(w)
    if hi == lo:
        return None
    return (series[-1] - lo) / (hi - lo)

# ---------- 特征提取 ----------
feature = {}

ind = FET.get("indices") or {}
sh_q = ind.get("sh000001") or {}
sh_name = sh_q.get("name") or "上证指数"
feature["asof_quote"] = sh_q.get("ts")
feature["market_closed"] = RAW.get("market_closed")

# 成交额（指数口径，含北证50近似）
turn = FET.get("turnover") or {}
turn_y = turn.get("y")
feature["turnover_yuan"] = turn_y
feature["turnover_wan"] = round(turn_y / WAN_YI, 2) if turn_y else None
feature["turnover_parts"] = turn.get("components")

# 上证K线（趋势/位置/量）
sh_kl = FET.get("holdings", {}).get("sh_kline")
shc = closes(sh_kl)
feature["sh_close"] = shc[-1] if shc else None
feature["sh_chg5"] = change_pct(shc, 5)
feature["sh_chg20"] = change_pct(shc, 20)
feature["sh_pos20"] = pos_in_range(shc, 20)
feature["sh_pos60"] = pos_in_range(shc, 60)
ma20 = sum(shc[-20:]) / 20 if len(shc) >= 20 else None
feature["sh_above_ma20"] = bool(shc and ma20 and shc[-1] > ma20)

# 成交量趋势（沪市口径；盘中不判）
vol_rel = None
if feature["market_closed"] and sh_kl and len(sh_kl) >= 7:
    vols = [k["vol_hand"] for k in sh_kl if k.get("vol_hand")]
    if len(vols) >= 7 and all(v for v in vols[-6:]):
        last, avg5 = vols[-1], sum(vols[-6:-1]) / 5
        vol_rel = (last / avg5 - 1) if avg5 else None
feature["vol_rel"] = vol_rel
if vol_rel is not None:
    if vol_rel > 0.05:
        feature["vol_tag"] = "放量"
    elif vol_rel < -0.05:
        feature["vol_tag"] = "缩量"
    else:
        feature["vol_tag"] = "平量"
else:
    feature["vol_tag"] = None

# 全A主力
mm = FET.get("market_main") or {}
main_y = mm.get("main_yuan")
# 覆盖率校验：主力口径成交应接近指数口径成交（误差±20%内视为可信）
if main_y is not None and turn_y:
    ratio = (mm.get("amt_yuan") or 0) / turn_y
    ok = not mm.get("incomplete") and 0.75 <= ratio <= 1.25
elif main_y is not None and not mm.get("incomplete"):
    ok = True
else:
    ok = False
feature["main_yi"] = round(main_y / YI, 1) if main_y is not None and ok else None
feature["main_ok"] = ok

# 涨跌家数
bd = FET.get("breadth") or {}
up, down, flat = n0(bd.get("up")), n0(bd.get("down")), n0(bd.get("flat"))
tot_b = up + down + flat
feature["breadth"] = {"up": int(up), "down": int(down), "flat": int(flat),
                      "qdate": bd.get("qdate")}
feature["up_ratio"] = safe_div(up, tot_b)

# 海外
g = FET.get("global") or {}

# 宏观/政策（来自 overrides）
eco = (OV.get("macro") or {}).get("economy_assessment") or {}
pol = (OV.get("policy") or {}).get("assessment") or {}

# ---------- 板块工具 ----------
BOARDS = FET.get("boards") or {}
ALL_BOARD_ROWS = list(BOARDS.get("industry") or []) + list(BOARDS.get("concept") or [])

def board_value(r, f):
    x = r.get(f)
    return n0(x) if x not in (None, "-") else None

def find_board(kws):
    """按关键词找代表性板块行。返回 row 或 None。"""
    best, best_score = None, -1
    for r in ALL_BOARD_ROWS:
        nm = r.get("f14") or ""
        for kw in kws:
            sc = 0
            if nm == kw:
                sc = 5
            elif nm.startswith(kw):
                sc = 3.5
            elif kw in nm:
                sc = 3
            elif kw[:-1] and kw[:-1] in nm and len(kw) > 2:  # 容忍“设备”缺“备”? 不用
                pass
            if sc > best_score:
                best_score = sc
                best = r
    return best if best_score >= 3 else None

def flow_scores(row):
    """今日/5日/10日主力净额(亿)"""
    return (money(board_value(row, "f62")), money(board_value(row, "f164")),
            money(board_value(row, "f174")))

def blend(row, w=(0.5, 0.3, 0.2)):
    """综合资金强度：今日为主，5/10日为连续性加成；缺失的窗口记 0（不因缺字段整行丢弃）。"""
    f0, f5, f10 = flow_scores(row)
    if f0 is None:
        return None
    return w[0] * f0 + (w[1] * (f5 or 0)) + (w[2] * (f10 or 0))

# 主流板块名单：用词尽量精确，全部落到具体板块
MAINSTREAM = [
    ("半导体", ["半导体", "芯片"]), ("半导体设备", ["半导体设备"]),
    ("人工智能", ["人工智能"]), ("算力", ["算力概念", "算力"]),
    ("数据中心", ["数据中心"]), ("通信设备", ["通信设备"]), ("光模块", ["光通信模块"]),
    ("消费电子", ["消费电子"]), ("机器人", ["机器人"]), ("人形机器人", ["人形机器人"]),
    ("电网设备", ["电网设备"]), ("特高压", ["特高压"]), ("电力", ["电力行业", "电力"]),
    ("光伏", ["光伏"]), ("风电", ["风电", "风力"]), ("电池", ["电池"]),
    ("新能源车", ["新能源车"]), ("汽车零部件", ["汽车零部件"]),
    ("黄金", ["贵金属", "黄金"]), ("有色", ["有色金属", "有色"]), ("稀土", ["稀土"]),
    ("煤炭", ["煤炭"]), ("石油", ["油气", "石油"]), ("化工", ["化工"]),
    ("军工", ["军工"]), ("机械", ["工程机械", "机械"]), ("家电", ["家电"]),
    ("白酒", ["白酒"]), ("食品饮料", ["食品饮料"]), ("养殖", ["养殖"]),
    ("银行", ["银行"]), ("证券", ["证券"]), ("保险", ["保险"]),
    ("房地产", ["房地产"]), ("计算机", ["软件开发", "计算机"]), ("游戏传媒", ["游戏"]),
    ("医药", ["创新药", "医药"]), ("港股互联网", ["恒生科技", "互联网"]),
]
# 去重：一个板块代码只算一次
SEEN_BCODE = set()

def mainstream_rows():
    rows = []
    for label, kws in MAINSTREAM:
        row = find_board(kws)
        if not row:
            continue
        code = row.get("f12")
        if code in SEEN_BCODE:
            continue
        SEEN_BCODE.add(code)
        rows.append({"label": label, "code": code, "name": row.get("f14"),
                     "row": row})
    return rows

MROWS = mainstream_rows()

def pick_flow(n, positive=True):
    scored = []
    for m in MROWS:
        b = blend(m["row"])
        if b is None:
            continue
        scored.append((b, m))
    if positive:
        scored = [x for x in scored if x[0] > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
    else:
        scored = [x for x in scored if x[0] < 0]
        scored.sort(key=lambda x: x[0])  # 最负在前
    pool = scored
    if not pool:
        return []
    out = []
    for b, m in pool[:n]:
        f0, f5, f10 = flow_scores(m["row"])
        pct = n0(m["row"].get("f3"))
        sh_pct = n0(sh_q.get("chg_pct"))
        out.append({"name": m["label"], "board": m["name"], "score_yi": round(b, 1),
                    "today_main_yi": f0, "f5_yi": f5, "f10_yi": f10,
                    "pct_today": round(pct, 2), "beats_index": bool(pct >= sh_pct)})
    return out

def sector_for_holding(h):
    """返回某持仓对应的板块行/代理指标。"""
    if h.get("proxy_us"):
        q = g.get(h["proxy_us"])
        return {"kind": "us", "q": q}
    if h.get("proxy_hk"):
        q = g.get(h["proxy_hk"])
        return {"kind": "hk", "q": q}
    row = find_board(h.get("kw") or [])
    if row:
        return {"kind": "board", "row": row}
    return {"kind": "none"}

# ---------- 资金流向特征 ----------
top_in = pick_flow(3, True)
top_out = pick_flow(3, False)
main_yi = feature["main_yi"]
feature["top_in"] = top_in
feature["top_out"] = top_out
concentrated = bool(main_yi is not None and top_in and
                    sum(x["score_yi"] for x in top_in) > 40 and abs(main_yi) < 80)

# ---------- 三变量-资金 ----------
def money_var():
    if main_yi is None and feature["vol_tag"] is None:
        return None
    pieces = []
    if turn_y:
        pieces.append(f"沪深成交{feature['turnover_wan']}万亿")
    if feature["vol_tag"]:
        pieces.append(f"较5日均{feature['vol_tag']}")
    if main_yi is not None:
        pieces.append(f"全A主力{'净流入' if main_yi >= 0 else '净流出'}{abs(main_yi)}亿")
    note = "、".join(pieces)
    if main_yi is not None and main_yi > 60 and feature["vol_tag"] == "放量":
        return {"status": "增量流入", "color": "green",
                "note": note + "；量价配合，增量资金进场迹象", "asof": feature["asof_quote"]}
    if main_yi is not None and main_yi < -150 and feature["vol_tag"] == "缩量":
        return {"status": "存量博弈", "color": "yellow",
                "note": note + "；主力撤离+缩量，资金在板块间腾挪", "asof": feature["asof_quote"]}
    return {"status": "存量博弈", "color": "yellow",
            "note": note + "；无持续放量，以板块轮动为主", "asof": feature["asof_quote"]}

money_v = money_var()

# ---------- 市场状态 & 周期阶段 ----------
STATE_LIST = [
    ("高位分歧", "orange", 5),
    ("增量确认", "green", 4),
    ("增量启动", "green", 3),
    ("风险释放", "red", 1),
    ("存量博弈", "yellow", 2),
]
def compute_state_stage():
    ur = feature["up_ratio"]
    ur = ur if ur is not None else 0.5
    vt = feature["vol_tag"]
    myi = main_yi
    br_weak = ur < 0.36
    br_ok = ur >= 0.5
    inflow = myi is not None and myi > 30
    outflow = myi is not None and myi < -80
    vol_up = vt == "放量"
    vol_dn = vt == "缩量"
    shpos = feature["sh_pos20"]
    shpos = shpos if shpos is not None else 0.5
    trend_up = (feature["sh_chg20"] or 0) > 0

    if feature["sh_close"] is None and myi is None and vt is None:
        return None, None, []
    reasons = []
    # 高位分歧
    if shpos >= 0.8 and (br_weak or vol_up) and not trend_up:
        reasons.append("指数处阶段高位但涨跌家数走弱")
        return "高位分歧", 5, reasons
    # 风险释放
    if (outflow or (vol_dn and br_weak)) and not trend_up:
        reasons.append(f"主力净流出{abs(myi or 0)}亿/缩量普跌")
        return "风险释放", 1, reasons
    # 增量确认
    if vol_up and inflow and br_ok and trend_up:
        reasons.append("放量+主力流入+涨多跌少")
        return "增量确认", 4, reasons
    # 增量启动
    if vol_up and inflow and not br_weak:
        reasons.append("开始放量、主力转流入，赚钱面待扩散")
        return "增量启动", 3, reasons
    # 资金集中（存量主线）-> 阶段3
    if concentrated and not vol_dn:
        reasons.append("成交未见持续放大，但资金向少数板块集中")
        return "存量博弈", 3, reasons
    # 默认存量/政策
    return "存量博弈", 2, reasons

state_name, stage, state_reasons = compute_state_stage()

def stage_label(s):
    return {1: "① 经济弱 / 磨底", 2: "② 政策发力初期", 3: "③ 资金开始集中",
            4: "④ 增量资金确认", 5: "⑤ 赚钱效应 / 高位"}.get(s, "—")

def state_color(sname):
    for n, c, s in STATE_LIST:
        if n == sname:
            return c
    return "yellow"

# 政策温度
pol_pos = pol.get("status") in ("预期增强", "加强", "积极")
pol_neg = pol.get("status") in ("转弱", "收紧", "风险")

# ---------- 政策二次定价信号 ----------
def double_pricing_signal():
    if not pol_pos:
        return False
    cond = []
    if feature["vol_tag"] == "放量":
        cond.append("成交连续放大")
    if main_yi is not None and main_yi > 30:
        cond.append("资金净流入")
    if concentrated:
        cond.append("板块资金连续流入")
    if feature["sh_above_ma20"]:
        cond.append("指数站上20日线")
    return (len(cond) >= 3), cond

signal_on, signal_cond = double_pricing_signal()

# ---------- 今日结论 ----------
def verdict():
    eco_weak = (eco.get("status") in ("偏弱", "走弱")) if eco else None
    sname = state_name or "存量博弈"
    if eco_weak is None and not pol:
        return "今日：数据不足", "关键宏观未录入，先看盘面，以观望为主（手动补充宏观/政策后自动出结论）"
    title = {"高位分歧": "今日：防守", "增量确认": "今日：顺势持有",
             "增量启动": "今日：谨慎乐观", "风险释放": "今日：等待企稳",
             "存量博弈": "今日：观望"}.get(sname, "今日：观望")
    line = []
    if eco:
        line.append(f"经济{eco.get('status', '')}")
    if pol:
        line.append(f"政策{pol.get('status', '')}")
    if feature["vol_tag"]:
        line.append(f"成交{feature['vol_tag']}")
    if main_yi is not None:
        line.append(f"主力{'流入' if main_yi >= 0 else '流出'}{abs(main_yi)}亿")
    if sname in ("风险释放", "高位分歧"):
        action_hint = "不增加仓位，减弱留强"
    elif stage and stage >= 4:
        action_hint = "可顺势持有强势方向"
    else:
        action_hint = "以持有和换仓为主，不提高总仓位，等成交放量确认"
    explain = "；".join(line) + "。" if line else "盘面信号不足。"
    return title, explain + " " + action_hint + "。"

# ---------- 持仓分析 ----------
def holding_signal(h):
    q = (FET.get("holdings", {}).get("quotes") or {}).get(h["code"])
    kl = (FET.get("holdings", {}).get("klines") or {}).get(h["code"])
    c = closes(kl)
    sec = sector_for_holding(h)
    info = {"kind": "个股" if h.get("kind") == "个股" else "ETF",
            "market": h.get("market"), "name": (q or {}).get("name") or h["name"],
            "price": n0((q or {}).get("price")) or None,
            "chg_pct": (q or {}).get("chg_pct"),
            "chg5": change_pct(c, 5) if c else None,
            "chg20": change_pct(c, 20) if c else None,
            "pos20": pos_in_range(c, 20),
            "quote_ts": (q or {}).get("ts"),
            "proxy_chg": None}
    # 板块/代理行情
    flow = {"today": None, "f5": None, "f10": None, "pct": None, "board": None}
    sec_kind = sec.get("kind")
    if sec_kind == "board":
        row = sec["row"]
        flow.update({"today": flow_scores(row)[0], "f5": flow_scores(row)[1],
                     "f10": flow_scores(row)[2], "pct": n0(row.get("f3")),
                     "board": row.get("f14")})
    elif sec_kind in ("us", "hk"):
        qq = sec.get("q") or {}
        flow["pct"] = qq.get("chg_pct")
        info["proxy"] = qq.get("name")
        info["proxy_chg"] = qq.get("chg_pct")
    info["flow"] = flow
    return info

def _sign_s(亿):
    """资金净额(亿) -> 强度 -1/0/+1，带1亿死区"""
    if 亿 is None:
        return 0
    if 亿 >= 1:
        return 1
    if 亿 <= -1:
        return -1
    return 0

def momentum_action(s):
    """无板块资金时的动作（用自身动量+位置）"""
    pos = s.get("pos20") if s.get("pos20") is not None else 0.5
    c5 = s.get("chg5")
    c20 = s.get("chg20")
    tdy = s.get("chg_pct") if s.get("chg_pct") is not None else 0
    c5v = c5 if c5 is not None else ((c20 or 0) / 4)
    c20v = c20 if c20 is not None else ((c5v or 0) * 4)
    if c5v is None:
        return "等待", ["无有效趋势数据"]
    if (pos >= 0.85 and c5v <= -1) or (pos >= 0.8 and c20v >= 8 and tdy <= -0.5):
        return "减仓", [f"近20日高位({int(pos*100)}%)且5日回落，先减部分锁盈"]
    if pos <= 0.28 and c5v >= 1.5:
        return "逢跌加", [f"低位({int(pos*100)}%)企稳回升(+{round(c5v,1)}%/5日)"]
    if pos <= 0.28 and c5v < -3 and c20v < -3:
        return "等待", ["处于超跌区但仍在下行，等放量企稳"]
    if c5v >= 2.5 and pos <= 0.6 and stage >= 3:
        return "加仓", [f"趋势走强(+{round(c5v,1)}%/5日)，位置不高"]
    if tdy >= 2 and c5v <= 0:
        return "持有", ["今日放量反弹，先看持续性再决定"]
    if c5v < -1 and c20v < 0:
        return "等待", ["中期偏弱，等右侧信号"]
    if c5v >= 0:
        return "持有", ["趋势平稳偏强，继续持有"]
    return "等待", ["信号中性，保持耐心"]

def decide_action(h):
    s = holding_signal(h)
    act, reason = "等待", []
    cyc = stage or 2
    flow = s["flow"]
    # 周期门控：风险释放期不做加法
    if cyc <= 1:
        act = "持有"
        reason = ["市场处风险释放期，只做防守"]
    else:
        has_flow = flow["today"] is not None
        if not has_flow:
            # 无板块资金：海外/个股/货币类，用自身动量
            act, reason = momentum_action(s)
        else:
            my, f5, f10 = flow["today"], flow["f5"], flow["f10"]
            score = _sign_s(my) + _sign_s(f5) + _sign_s(f10)
            pos = s.get("pos20") if s.get("pos20") is not None else 0.5
            c5 = s.get("chg5") if s.get("chg5") is not None else 0
            tdy = s.get("chg_pct") if s.get("chg_pct") is not None else 0
            board = flow.get("board") or s["name"]
            if score >= 2:
                if pos <= 0.55:
                    act = "逢跌加" if (c5 < 0 and pos <= 0.45) else "加仓"
                    reason = [f"{board}资金净流入今日{my}亿且5/10日同向"]
                else:
                    act, reason = "持有", [f"资金流入但位置已高({int(pos*100)}%)，持有不追"]
            elif score == 1:
                act = "持有"
                reason = [f"资金小幅流入({my}亿)，持有观察"]
            elif score == 0:
                if pos >= 0.85 and c5 <= 0:
                    act, reason = "减仓", [f"高位({int(pos*100)}%)资金中性，兑现部分"]
                elif c5 < 0 and pos <= 0.4:
                    act, reason = "等待", ["资金中性、位置低但5日仍弱，等确认"]
                elif c5 >= 0.5:
                    act, reason = "持有", ["资金中性、趋势尚可"]
                else:
                    act, reason = "等待", ["多空胶着，等量能选择方向"]
            elif score == -1:
                if pos >= 0.7:
                    act, reason = "减仓", [f"高位({int(pos*100)}%)资金转流出({abs(my)}亿)"]
                elif pos <= 0.25:
                    act, reason = "等待", ["流出但已超跌，等企稳"]
                else:
                    act, reason = "等待", [f"资金小幅流出({abs(my)}亿)，再观察一日"]
            else:  # <= -2
                if pos <= 0.3:
                    act, reason = "等待", [f"资金持续流出({abs(my)}亿/5日{abs(f5 or 0)}亿)，超跌等企稳"]
                elif score <= -3 or pos >= 0.6:
                    act, reason = "减仓", [f"资金持续流出({abs(my)}亿/5日{abs(f5 or 0)}亿)，换出"]
                else:
                    act, reason = "等待", [f"资金流出但位置不高({int(pos*100)}%)，再观察"]
    # 兜底：完全无数据
    if s.get("price") is None and s.get("chg_pct") is None:
        act, reason = "等待", ["暂无行情数据，稍后自动更新"]
    if s["market"] == "海外" and act in ("加仓", "逢跌加") and (s.get("proxy_chg") or 0) < -1.5:
        act, reason = "持有", ["海外指数回调，先观望"]
    return act, reason

def action_color(a):
    return {"加仓": "green", "逢跌加": "green", "持有": "blue",
            "等待": "yellow", "减仓": "red"}.get(a, "gray")

holdings_out = []
for h in HOLDINGS:
    info = holding_signal(h)
    act, reason = decide_action(h)
    holdings_out.append({
        "code": h["code"], "name": info["name"], "tag": h["name"] if info["name"] != h["name"] else None,
        "kind": info["kind"], "market": info["market"],
        "price": info["price"], "chg_pct": info["chg_pct"], "chg5": info["chg5"],
        "pos20": info["pos20"], "proxy": info.get("proxy"),
        "flow": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in info["flow"].items()},
        "action": act, "action_color": action_color(act), "reason": "；".join(reason or []),
    })

# ---------- 今日操作 ----------
def pos_default(stage_, signal_on_):
    if signal_on_:
        return 75, 25, "出现「政策二次定价」迹象：经济仍偏弱但政策明显加码、量能配合，可提升进攻仓位"
    return {1: (40, 60), 2: (55, 45), 3: (65, 35), 4: (75, 25), 5: (60, 40)}.get(stage_ or 2, (55, 45)), \
        "不提高总仓位" if not signal_on_ else "可提高总仓位"

def top_action():
    sell = [x for x in holdings_out if x["action"] == "减仓"]
    buys = [x for x in holdings_out if x["action"] in ("加仓", "逢跌加")]
    if sell and buys:
        s = sell[0]
        b = buys[0]
        return f"{s['name']} 减 → {b['name']} 增"
    if top_in and buys:
        return f"{buys[0]['name']} 逢低增配（资金主线）"
    if sell:
        return f"减 {sell[0]['name']}，腾出仓位等新主线"
    return "持有为主，等待成交放量确认后再动作"

# ---------- 最大机会 ----------
def opportunity():
    best = None
    if top_in:
        cand = [x for x in top_in if x["beats_index"]]
        if cand:
            best = cand[0]
    # 只有资金流入足够强、方向连续才提示机会；否则显示“暂无明确主线”
    if best is None:
        return None
    strong = (best["today_main_yi"] or 0) >= 12 and (best["f5_yi"] or 0) >= -5
    if not strong:
        return None
    reasons = [("资金", "↑" if best["today_main_yi"] and best["today_main_yi"] > 0 else "±"),
               ("5日资金", "↑" if (best["f5_yi"] or 0) > 0 else "↓"),
               ("趋势", "↑" if best["pct_today"] >= n0(sh_q.get("chg_pct")) else "→")]
    trig = []
    if feature["vol_tag"] != "放量":
        trig.append("成交额持续放大")
    trig.append(f"{best['name']}资金连续流入")
    if stage and stage < 4:
        trig.append("等放量确认后再加")
    return {"name": best["name"], "board": best["board"],
            "score_yi": best["score_yi"], "today_main_yi": best["today_main_yi"],
            "reasons": reasons,
            "trigger": " + ".join(trig) + " → 提高该方向仓位；连续两日证伪则放弃。",
            "asof": feature["asof_quote"]}

# ---------- 事件 ----------
def next_events(n=3):
    today = datetime.date.today().isoformat()
    evs = []
    for e in OV.get("events") or []:
        if str(e.get("date")) >= today:
            evs.append(e)
    return evs[:n]

# ---------- 手动覆盖 ----------
def pick(auto_val, key, auto_source="自动规则"):
    mv = OVM.get(key)
    if mv is None:
        return auto_val, auto_source
    return mv, "手动"

title_a, explain_a = verdict()
v_title, v_src = pick(title_a, "verdict_title")
v_exp, _ = pick(explain_a, "verdict_explain")
state_final, st_src = pick(state_name, "market_state")
stage_final, cyc_src = pick(stage, "cycle_stage")

# 组合输出
def asof_meta():
    metas = []
    if sh_q.get("ts"):
        metas.append(f"行情 {sh_q['ts']}")
    if feature["breadth"].get("qdate"):
        metas.append(f"涨跌分布 {feature['breadth']['qdate']}")
    return "；".join(metas)

eco_out = None
if eco:
    eco_out = dict(eco)
    eco_out["items"] = [{"name": it.get("name"), "value": it.get("value"), "mo": it.get("mo")}
                        for it in (OV.get("macro") or {}).get("items") or []]

out = {
    "meta": {
        "title": "A股资金·政策驾驶舱",
        "generated_at": RAW.get("generated_at"),
        "market_closed": feature["market_closed"],
        "asof": asof_meta(),
        "data_src": "数据：腾讯行情/东方财富；宏观政策：手动维护(带日期来源)",
        "note_holdings": OV.get("holdings_notes") or [],
    },
    "conclusion": {
        "verdict": v_title, "verdict_src": v_src,
        "explain": v_exp,
        "market_state": {"name": state_final, "color": state_color(state_final),
                         "src": st_src},
        "sh": {"name": sh_name, "price": feature["sh_close"],
               "chg_pct": n0(sh_q.get("chg_pct")) or None, "asof": sh_q.get("ts")},
        "turnover_wan": feature["turnover_wan"],
        "main_yi": main_yi,
        "breadth": feature["breadth"],
    },
    "vars": {
        "economy": eco_out or None,
        "policy": pol or None,
        "money": money_v,
        "global_risk": OV.get("global_risk") or [],
    },
    "flows": {"in": top_in, "out": top_out},
    "holdings": holdings_out,
    "cycle": {
        "stage": stage_final, "name": stage_label(stage_final or 0),
        "state": state_final,
        "reasons": state_reasons, "note": "规则判断路径：经济→政策→资金集中→放量→赚钱效应",
        "src": cyc_src,
    },
    "opportunity": opportunity(),
    "op": {
        "signal_on": signal_on, "signal_cond": signal_cond,
        "headline": None,
        "top_action": top_action(),
        "events": next_events(),
    },
}
# 仓位
(pos_pct, cash_pct), head_a = pos_default(stage_final if stage_final else 2, signal_on)
out["op"]["pos_pct"] = OVM.get("pos_pct") or pos_pct
out["op"]["cash_pct"] = OVM.get("cash_pct") or cash_pct
out["op"]["headline"], _ = pick(head_a, "op_headline")
if OVM.get("top_action"):
    out["op"]["top_action"] = OVM["top_action"]

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
with open(OUT_PATH, "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=1)

# ---------- 控制台小结 ----------
def pr(*a):
    print(*a)
pr("=" * 60)
pr("生成:", OUT_PATH)
pr(f"asof={feature['asof_quote']} closed={feature['market_closed']} 成交={feature['turnover_wan']}万亿 "
   f"主力={main_yi}亿 涨跌={int(up)}/{int(down)} up_ratio={round(feature['up_ratio']*100) if feature['up_ratio'] is not None else '-'}% "
   f"量={feature['vol_tag']} 上证20d={feature['sh_chg20']}% pos={None if feature['sh_pos20'] is None else round(feature['sh_pos20'],2)}")
pr("结论:", v_title, "|", state_final, stage_label(stage or 0))
pr("explain:", explain_a)
pr("资金三变量:", (money_v or {}).get("status"))
pr("流入TOP:", [(x['name'], x['score_yi']) for x in top_in])
pr("流出TOP:", [(x['name'], x['score_yi']) for x in top_out])
pr("持仓动作:")
for x in holdings_out:
    pr(f"  {x['name']:14s} {x['action']:4s} {(';'.join(x['reason']))[:34]} 价={x['price']} chg5={x['chg5']} pos={None if x['pos20'] is None else round(x['pos20'],2)} flow={x['flow'].get('today')}/{x['flow'].get('f5')}")
pr("机会:", (opportunity() or {}).get("name"))
pr("操作:", out["op"]["headline"], out["op"]["top_action"], f"仓位{out['op']['pos_pct']}%")
pr("信号:", signal_on, signal_cond)
