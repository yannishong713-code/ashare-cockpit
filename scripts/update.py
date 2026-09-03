# -*- coding: utf-8 -*-
"""update.py —— 一键更新：抓行情 -> 规则引擎 -> 写 docs/data/data.json
用法:
  python scripts/update.py             # 完整流程（抓取最新行情）
  python scripts/update.py --no-fetch  # 用已有 tmp/raw.json 只重算判断
"""
import argparse
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="跳过抓取，仅重新分析")
    args = ap.parse_args()
    if not args.no_fetch:
        import fetch_data
        print("==> 抓取行情")
        fetch_data.main()
    else:
        raw = os.path.join(ROOT, "tmp", "raw.json")
        if not os.path.exists(raw):
            print("tmp/raw.json 不存在，先运行完整流程")
            sys.exit(1)
        print("==> 跳过抓取，用已有行情")
    import analyze  # 模块顶层执行：读取 raw + overrides -> 生成 docs/data/data.json


if __name__ == "__main__":
    main()
