# -*- coding: utf-8 -*-
"""
数据层公共工具：多镜像 + 重试的 HTTP 客户端；腾讯 / 东财行情解析。
所有函数绝不伪造数据：抓不到就返回 None，由上层显示「暂无数据」。
"""
import json, time, datetime
import sys, io
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"}

_cw = None  # 常驻引用，防止包装器被 GC 关闭共享 buffer


def ensure_utf8():
    """幂等：把 stdout 包成 UTF-8。跨模块只包装一次、持有全局引用。"""
    global _cw
    enc = getattr(sys.stdout, "encoding", "") or ""
    if enc.lower() not in ("utf-8", "utf8", "cp65001"):
        if _cw is None:
            _cw = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stdout = _cw

EM_HOSTS = [
    "push2.eastmoney.com",
    "1.push2.eastmoney.com",
    "20.push2.eastmoney.com",
    "push2delay.eastmoney.com",
]
EM_HIS_HOSTS = [
    "push2his.eastmoney.com",
    "push2.eastmoney.com",
    "push2delay.eastmoney.com",
]

_session = None

def _sess():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.trust_env = False  # 本机代理时好时坏，全部走直连
        _session.headers.update(UA)
    return _session

def http_get(url, host, timeout=10):
    """尝试特定 host，成功返回 resp。"""
    r = _sess().get(url.replace("HOST", host), timeout=timeout)
    r.raise_for_status()
    return r

def em_get(path, hosts, retries=1, timeout=6):
    """在 hosts 间轮询（每主机最多 retries 次）。返回解析后的 dict/None。"""
    for host in hosts:
        for _ in range(retries):
            try:
                r = http_get(f"https://{host}{path}", host, timeout=timeout)
                j = r.json()
                if isinstance(j, dict) and (j.get("data") or j.get("rc") is not None):
                    return j
            except Exception:
                pass
    return None

def em_data(path, hosts=None):
    """返回东财响应里的 data 段，失败返回 None。"""
    j = em_get(path, hosts or EM_HOSTS)
    return (j or {}).get("data")

def tencent_quote(symbols):
    """symbols: list like ['sh000001','sz399106']; 返回 {sym: dict(fields)} 或部分。
    使用原样 '~' 拆分；行情自带时间戳。"""
    q = ",".join(symbols)
    try:
        r = _sess().get("https://qt.gtimg.cn/q=" + q, timeout=10)
        txt = r.content.decode("gbk", errors="replace")
    except Exception:
        return {}
    out = {}
    for seg in txt.strip().split(";"):
        if "=" not in seg:
            continue
        var, body = seg.split("=", 1)
        sym = var.strip()
        if not sym.startswith("v_"):
            continue
        body = body.strip().strip('"')
        if not body:
            continue
        f = body.split("~")
        out[sym[2:]] = f
    return out

def _fnum(x):
    try:
        return float(x)
    except Exception:
        return None

def parse_tq_a_share(f):
    """A股/ETF/指数通用字段 -> dict。索引基于腾讯标准布局。"""
    n = len(f)
    def get(i):
        return f[i] if i < n and f[i] not in ("", None) else None
    composite = get(35)
    amt_yuan = None
    if composite and "/" in composite:
        parts = composite.split("/")
        if len(parts) >= 3:
            try:
                amt_yuan = float(parts[2])
            except Exception:
                amt_yuan = None
    return {
        "name": get(1), "price": _fnum(get(3)), "pre_close": _fnum(get(4)),
        "open": _fnum(get(5)), "high": _fnum(get(33)), "low": _fnum(get(34)),
        "time": get(30), "chg": _fnum(get(31)), "chg_pct": _fnum(get(32)),
        "amt_yuan": amt_yuan,
        "ts": _parse_ts(get(30)),
    }

def parse_tq_us(f):
    """美股/海外指数（usDJI 等）布局。"""
    n = len(f)
    def get(i):
        return f[i] if i < n and f[i] not in ("", None) else None
    return {
        "name": get(1), "price": _fnum(get(3)), "pre_close": _fnum(get(4)),
        "time": get(30), "chg": _fnum(get(31)), "chg_pct": _fnum(get(32)),
        "ts": None,
    }

def _parse_ts(s):
    """20260903161401 or 2026-09-02 16:42 -> 'YYYY-MM-DD HH:MM' 或 None"""
    if not s:
        return None
    s = str(s).strip()
    if len(s) == 14 and s.isdigit():
        try:
            return time.strftime("%Y-%m-%d %H:%M", time.strptime(s, "%Y%m%d%H%M%S"))
        except Exception:
            return None
    if len(s) >= 16 and s[4] == "-":
        return s[:16]
    return None

def tencent_daily_kl(symbol, days=40):
    """symbol 形如 sh000001；返回 [{date, close, high, low, vol_hand}] 由旧到新。失败 None。"""
    try:
        r = _sess().get(
            f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{days},qfq",
            timeout=10,
        )
        j = r.json()
        node = (j.get("data") or {}).get(symbol) or {}
        k = node.get("qfqday") or node.get("day") or []
        out = []
        for row in k:
            # [date, open, close, high, low, volume(手), ...]
            try:
                out.append({
                    "date": row[0],
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "vol_hand": float(row[5]) if len(row) > 5 and row[5] else None,
                })
            except Exception:
                continue
        return out if out else None
    except Exception:
        return None

def cn_now_str():
    """北京时间字符串（不引入 tz 依赖，直接用 UTC+8）。"""
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

def cn_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")

def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=1)
