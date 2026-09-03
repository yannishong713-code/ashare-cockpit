# -*- coding: utf-8 -*-
"""
fetch_data.py —— 抓取全部行情，输出 tmp/raw.json
原则：绝不编造；抓不到就置 null，由 analyze/前端显示「暂无数据」。
抓取项：
 1) 指数行情(腾讯)：上证/深成/沪深300 + 成交额(沪全/深全/北50)
 2) 涨跌家数(东财)  3) 全A主力净流入(东财分页求和)  4) 板块全集+资金字段(东财)
 5) 持仓行情+历史K线(腾讯)  6) 海外指数(腾讯/东财)
"""
import io, json, os, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import common as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, "tmp")
DATA = os.path.join(ROOT, "data")
os.makedirs(TMP, exist_ok=True)

OV = json.load(open(os.path.join(DATA, "overrides.json"), encoding="utf-8"))
HOLDINGS = OV["holdings"]

# ---------- 帮助函数 ----------
def q_syms(*xs):
    """腾讯行情，容忍失败（多轮重试）。"""
    d = {}
    for attempt in range(8):
        d = C.tencent_quote(list(xs))
        if d:
            break
        time.sleep(1.5)
    return d

def _num(x):
    try:
        return float(x) if x not in (None, "-", "") else None
    except Exception:
        return None

# ---------- 1. 指数 / 成交额 ----------
def fetch_indices():
    syms = ["sh000001", "sz399001", "sz399006", "sh000300", "sz399106", "bj899050"]
    q = q_syms(*syms)
    idx = {}
    for s, tag in [("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指"),
                   ("sh000300", "沪深300"), ("sz399106", "深证综指"), ("bj899050", "北证50")]:
        f = q.get(s)
        idx[s] = C.parse_tq_a_share(f) if f else None
        idx[s]["name"] = tag if idx[s] else None
        idx[s]["code"] = s
    # 成交额：沪(000001 覆盖沪全) + 深(399106 覆盖深全) + 北(899050 北证50成分口径)
    parts = []
    for s in ["sh000001", "sz399106", "bj899050"]:
        it = idx.get(s) or {}
        parts.append(it.get("amt_yuan"))
    turnover_yuan = sum(parts) if all(p is not None for p in parts) else None
    return {"idx": idx, "turnover_yuan": turnover_yuan,
            "turnover_components": {"sh": parts[0], "sz": parts[1], "bj": parts[2]},
            "asof": (idx.get("sh000001") or {}).get("ts")}

# ---------- 2. 涨跌家数 ----------
def fetch_breadth():
    j = C.em_get("/getTopicZDFenBu?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt",
                 ["push2ex.eastmoney.com", "push2.eastmoney.com"], retries=2)
    if not j or not j.get("data"):
        return None
    d = j["data"]
    up = down = flat = 0
    for row in d.get("fenbu") or []:
        for k, v in row.items():
            try:
                ki = int(k)
            except Exception:
                continue
            if ki > 0:
                up += v
            elif ki < 0:
                down += v
            else:
                flat += v
    return {"qdate": str(d.get("qdate")), "up": up, "down": down, "flat": flat}

# ---------- 3. 板块全集 ----------
def _clist_page(fs, pn, pz, fields):
    path = (f"/api/qt/clist/get?pn={pn}&pz={pz}&po=1&np=1&fltt=2&invt=2&fid=f62"
            f"&fs={fs}&fields={fields}")
    d = C.em_data(path)
    return ((d or {}).get("diff") or [])

def fetch_boards():
    fields = "f12,f14,f3,f6,f62,f164,f174,f184"
    out = {"industry": [], "concept": []}
    for tag, fs, big in [("industry", "m:90+t:2", 600), ("concept", "m:90+t:3+f:!50", 600)]:
        seen = set()
        for pn in range(1, 60):
            rows = _clist_page(fs, pn, 100, fields)
            if not rows:
                break
            for r in rows:
                if r.get("f12") in seen:
                    continue
                seen.add(r.get("f12"))
                out[tag].append(r)
            if len(rows) < 100:
                break
        # 与 data.total 核对，若翻页异常会导致数量偏差，交由 analyze 判断字段空缺
    return out

# ---------- 4. 全A主力净流入（分页求和） ----------
A_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:1+t:81"

def fetch_market_main_flow(deadline=60):
    """全A(沪深) 主力净流入与成交额：按 f12 升序稳定分页求和。"""
    total_main = 0.0
    total_amt = 0.0
    n = 0
    incomplete = False
    t0 = time.time()
    for pn in range(1, 60):
        if time.time() - t0 > deadline:
            incomplete = True
            break
        path = (f"/api/qt/clist/get?pn={pn}&pz=100&po=0&np=1&fltt=2&invt=2&fid=f12"
                f"&fs={A_FS}&fields=f6,f62,f12,f14")
        d = C.em_data(path)
        rows = ((d or {}).get("diff") or [])
        if not rows:
            break
        for r in rows:
            a = _num(r.get("f6"))
            m = _num(r.get("f62"))
            if a is not None and r.get("f12"):
                n += 1
            total_amt += a or 0
            total_main += m or 0
        if len(rows) < 100:
            incomplete = incomplete or pn > 1
            break
        time.sleep(0.02)
    return {"main_yuan": total_main, "amt_yuan": total_amt, "stocks": n, "incomplete": incomplete}

# ---------- 5. 海外指数 ----------
def fetch_global():
    q = q_syms("usDJI", "usIXIC", "usINX", "hkHSI", "hkHSTECH")
    out = {k: C.parse_tq_us(q[k]) for k in q}
    # 日经225 用东财全球
    d = C.em_data("/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f3,f12,f13,f14&secids=100.N225")
    rows = ((d or {}).get("diff") or [])
    for r in rows:
        if r.get("f14"):
            out["jpN225"] = {"name": r["f14"], "price": r.get("f2"),
                             "chg_pct": r.get("f3"), "ts": None, "code": "100.N225"}
    return out

# ---------- 6. 持仓行情 + 历史K线 ----------
def fetch_holdings():
    # 一次性批量行情（分块），缺失代码单独补抓
    codes = [h["code"] for h in HOLDINGS]
    q = {}
    for i in range(0, len(codes), 25):
        q.update(q_syms(*codes[i:i + 25]))
    for c in codes:
        if not q.get(c):
            q.update(q_syms(c))
    quotes = {}
    for h in HOLDINGS:
        f = q.get(h["code"])
        quotes[h["code"]] = C.parse_tq_a_share(f) if f else None
    # 历史K线
    kl = {}
    for h in HOLDINGS:
        c = h["code"]
        rows = None
        for _ in range(3):
            rows = C.tencent_daily_kl(c, 70)
            if rows:
                break
            time.sleep(0.6)
        kl[c] = rows
        time.sleep(0.15)
    # 指数K线：上证(用于相对强弱与趋势)
    sh_kl = C.tencent_daily_kl("sh000001", 90)
    return {"quotes": quotes, "klines": kl, "sh_kline": sh_kl}

# ---------- 组装 ----------
def main():
    raw = {"generated_at": C.cn_now_str(), "market_closed": None,
           "fetched": {}}
    t0 = time.time()
    # 并行抓取顺序执行（保守但稳健）
    r = fetch_indices()
    raw["fetched"]["indices"] = r["idx"]
    raw["fetched"]["turnover"] = {"y": r["turnover_yuan"], "components": r["turnover_components"],
                                  "asof": r["asof"]}
    # 判断收盘
    ts = (r["idx"].get("sh000001") or {}).get("ts")
    closed = None
    if ts:
        try:
            hh = int(ts[11:13]); mm = int(ts[14:16])
            closed = (hh * 60 + mm) >= (15 * 60)
        except Exception:
            closed = None
    raw["market_closed"] = closed
    print(f"[fetch] indices+turnover done in {time.time()-t0:.0f}s")

    b = fetch_breadth()
    raw["fetched"]["breadth"] = b
    print("[fetch] breadth:", (b or {}).get("qdate"))

    # 板块 与 主力（先板块后主力，板块失败也要主力）
    boards = fetch_boards()
    raw["fetched"]["boards"] = boards
    print(f"[fetch] boards industry={len(boards['industry'])} concept={len(boards['concept'])}")

    mainf = None
    for _ in range(4):
        try:
            mainf = fetch_market_main_flow()
            if mainf and not mainf.get("incomplete") and mainf.get("stocks", 0) > 3000:
                break
        except Exception as e:
            print("[fetch] market_main FAIL", e)
            mainf = None
        time.sleep(1.5)
    raw["fetched"]["market_main"] = mainf
    if mainf:
        print(f"[fetch] market_main stocks={mainf['stocks']} main={mainf['main_yuan']/1e8:+.1f}亿 "
              f"amt={mainf['amt_yuan']/1e8:.0f}亿 incomplete={mainf['incomplete']}")

    raw["fetched"]["global"] = fetch_global()
    raw["fetched"]["holdings"] = fetch_holdings()
    raw["asof"] = {
        "quote": (raw["fetched"]["indices"].get("sh000001") or {}).get("ts"),
        "breadth": (b or {}).get("qdate"),
    }
    C.save_json(os.path.join(TMP, "raw.json"), raw)
    print(f"[fetch] total {time.time()-t0:.0f}s -> tmp/raw.json  market_closed={closed}")

if __name__ == "__main__":
    main()
