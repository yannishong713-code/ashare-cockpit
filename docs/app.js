/* A股资金·政策驾驶舱 — 渲染 site 数据 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var NA = "暂无数据";
  var STAGETEXT = ["经济弱 / 磨底", "政策发力初期", "资金开始集中", "增量资金确认", "赚钱效应 / 高位"];
  var STATE_COLOR = { "风险释放": "red", "存量博弈": "yellow", "增量启动": "green", "增量确认": "green", "高位分歧": "orange" };
  var COLOR_CSS = { green: "var(--up)", yellow: "var(--amber)", red: "var(--down)", orange: "var(--orange)", blue: "var(--blue)", gray: "var(--ink-3)" };
  var ACT_CLS = { "加仓": "green", "逢跌加": "green", "持有": "blue", "等待": "yellow", "减仓": "red" };

  function esc(s) { return String(s == null ? "" : s); }

  function fmt(x, d) { return (x === null || x === undefined || isNaN(x)) ? NA : (d === undefined ? String(x) : x.toFixed(d)); }

  function sgnCls(v) { return v > 0.0001 ? "up" : (v < -0.0001 ? "down" : "flatc"); }
  function sgnTxt(v) { if (v === null || v === undefined || isNaN(v)) return NA; return (v > 0 ? "+" : "") + v; }
  function pctCls(v) { return v > 0.0001 ? "up" : (v < -0.0001 ? "down" : "flatc"); }

  function dotColor(name) { return COLOR_CSS[STATE_COLOR[name]] || "var(--amber)"; }
  function pill(html, colorName) { return '<span class="pill" style="color:' + (COLOR_CSS[colorName] || "var(--ink-2)") + ';background:' + (COLOR_CSS[colorName] || "#888") + '1a"><span class="dot" style="background:' + (COLOR_CSS[colorName] || "#888") + '"></span>' + html + "</span>"; }
  function statePill(name) { var c = STATE_COLOR[name] || "yellow"; return '<span class="statepill" style="color:' + COLOR_CSS[c] + ";background:" + COLOR_CSS[c] + "1a\">" + name + "</span>"; }

  var D = null;

  // ---------- ① 今日结论 ----------
  function renderHero() {
    var c = D.conclusion || {};
    var ms = c.market_state || {};
    var verdict = esc(c.verdict || NA);
    var vColor = COLOR_CSS[ms.color] || "var(--amber)";
    var html = '<div class="row1">' +
      '<span class="verdict" style="color:' + vColor + '">' + verdict + "</span>" +
      statePill(ms.name || "存量博弈") +
      '<span class="metaline">' + esc(c.verdict_src === "手动" ? "结论：手动" : "结论：自动规则") + "</span></div>" +
      (c.explain ? '<p class="explain">' + esc(c.explain) + "</p>" : "");

    var sh = c.sh || {};
    var mk = c.turnover_wan;
    var mainY = c.main_yi;
    var br = c.breadth || {};
    function stat(l, big, small, cls) {
      return '<div class="stat"><div class="l"><span>' + l + "</span>" + (small ? "<span>" + small + "</span>" : "") + '</div><div class="v ' + (cls || "") + '">' + big + "</div></div>";
    }
    var st = '<div class="stats">' +
      stat("上证指数", fmt(sh.price, 2), "", sgnCls(sh.chg_pct)) +
      stat("上证涨跌", sgnTxt(sh.chg_pct) + "%", sh.asof ? "收于 " + sh.asof.slice(5, 16) : "", sgnCls(sh.chg_pct)) +
      stat("成交额", mk === null ? NA : fmt(mk, 2) + '<small> 万亿</small>', "沪深京(北证50口径)") +
      stat("主力资金", mainY === null ? NA : (mainY > 0 ? "+" : "") + fmt(mainY, 0) + '<small> 亿</small>', mainY === null ? "抓取受限" : (mainY >= 0 ? "净流入" : "净流出"), sgnCls(mainY)) +
      stat("涨 / 跌", fmt(br.up, 0) + " / " + fmt(br.down, 0), br.qdate ? "日期 " + br.qdate : "", br.up >= br.down ? "" : "down") +
      "</div>";
    html += st;
    $("heroBox").innerHTML = html;
    var tagBits = [];
    if (sh.asof) tagBits.push("行情 " + sh.asof);
    if (br.qdate) tagBits.push("家数 " + br.qdate);
    $("conclTag").textContent = tagBits.length ? tagBits.join(" · ") : "-";
  }

  // ---------- ② 三大变量 ----------
  var VAR_META = [
    { key: "economy", ic: "🌾", label: "经济" },
    { key: "policy", ic: "🏛️", label: "政策" },
    { key: "money", ic: "💰", label: "资金" }
  ];
  function renderVars() {
    var vars = D.vars || {};
    var box = $("varsBox");
    var html = "";
    VAR_META.forEach(function (m) {
      var v = vars[m.key];
      var body;
      if (!v) {
        body = '<div class="varcard"><div class="varhead"><div class="ic">' + m.ic + '</div><b>' + m.label + "</b></div>" +
          '<p class="varnote">' + NA + "（手动维护项，见页脚指引）</p></div>";
      } else {
        var c = COLOR_CSS[v.color] || "var(--amber)";
        body = '<div class="varcard"><div class="varhead"><div class="ic">' + m.ic + "</div><b>" + m.label + "</b>" +
          '<span class="pill" style="color:' + c + ";background:" + c + "1a\"><span class=\"dot\" style=\"background:" + c + "\"></span>" + esc(v.status) + "</span></div>" +
          '<p class="varnote">' + esc(v.note || "") + "</p>" +
          '<div class="varasof">' + (v.asof ? "截至 " + esc(v.asof) : "") + (v.src ? " · " + esc(v.src) : "") + "</div>";
        if (m.key === "economy" && vars.economy_items && vars.economy_items.length) {
          body += '<div class="macroitems">' + vars.economy_items.map(function (mi) {
            return '<div class="mi"><span>' + esc(mi.name) + "</span><b>" + esc(mi.value) + "</b><span>(" + esc(mi.mo) + ")</span></div>";
          }).join("") + "</div>";
        }
        body += "</div>";
      }
      html += body;
    });
    box.innerHTML = html;
    // 海外扰动一行
    var gr = (D.vars && D.vars.global_risk) || [];
    if (gr.length) {
      var g = document.createElement("div");
      g.className = "basis";
      g.style.marginTop = "10px";
      g.textContent = "🌍 海外扰动：" + gr[0].note + (gr[0].src ? "（" + gr[0].src + "）" : "");
      box.parentNode.appendChild(g);
    }
  }

  // ---------- ③ 资金流向 ----------
  function flowRow(x, i, up) {
    var color = up ? "var(--up)" : "var(--down)";
    var t = x.today_main_yi;
    var f5 = x.f5_yi;
    var parts = [];
    if (t !== null && t !== undefined) parts.push("今日主力 " + (t > 0 ? "+" : "") + fmt(t, 1) + "亿");
    if (f5 !== null && f5 !== undefined) parts.push("5日 " + (f5 > 0 ? "+" : "") + fmt(f5, 0) + "亿");
    var meta = parts.join(" · ");
    return '<div class="frow"><span class="frank">' + (i + 1) + '</span>' +
      '<div><div class="fn">' + esc(x.name) + (x.pct_today === null || x.pct_today === undefined ? "" : ' <span class="' + pctCls(x.pct_today) + '" style="font-size:11px;font-weight:700">' + sgnTxt(x.pct_today) + "%</span>") + "</div>" +
      (x.board && x.board !== x.name ? '<div class="fmeta">' + esc(x.board) + "</div>" : "") + "</div>" +
      '<div class="fnum" style="color:' + color + '"><span class="m">' + (x.score_yi === null || x.score_yi === undefined ? NA : (x.score_yi > 0 ? "+" : "") + fmt(x.score_yi, 0)) + ' <small>亿(加权)</small></span><span class="s">' + meta + "</span></div></div>";
  }
  function renderFlows() {
    var fl = D.flows || {};
    var fin = fl.in || [], fout = fl.out || [];
    $("flowIn").innerHTML = fin.length ? fin.map(function (x, i) { return flowRow(x, i, true); }).join("") : '<div class="frow"><span class="fmeta">今日无净流入达标的板块</span></div>';
    $("flowOut").innerHTML = fout.length ? fout.map(function (x, i) { return flowRow(x, i, false); }).join("") : '<div class="frow"><span class="fmeta">今日无净流出明显板块</span></div>';
    $("flowBasis").textContent = "判断口径：主力净额（今日50% + 5日30% + 10日20%，缺字段按0），再叠加当日板块相对指数强弱。加权分数=连续性与相对强度后的资金流，不是当日涨跌榜。";
  }

  // ---------- ④ 持仓 ----------
  function renderHoldings() {
    var hs = (D.holdings || []).slice();
    // 按动作分组排序：减仓>等待>持有>加
    var order = { "减仓": 0, "等待": 1, "持有": 2, "逢跌加": 3, "加仓": 4 };
    hs.sort(function (a, b) { return (order[a.action] === undefined ? 2 : order[a.action]) - (order[b.action] === undefined ? 2 : order[b.action]); });
    var html = hs.map(function (h) {
      var cls = ACT_CLS[h.action] || "yellow";
      var px = h.price;
      var chg = h.chg_pct;
      var sub = [];
      if (h.chg5 !== null && h.chg5 !== undefined) sub.push("5日 " + sgnTxt(h.chg5) + "%");
      if (h.pos20 !== null && h.pos20 !== undefined) sub.push("20日位置 " + Math.round(h.pos20 * 100) + "%");
      if (h.proxy) sub.push(h.proxy);
      var f = h.flow || {};
      if (f.board && f.today !== null) sub.push(f.board + "资金 " + sgnTxt(f.today) + "/" + (f.f5 === null || f.f5 === undefined ? "?" : sgnTxt(f.f5)) + "亿");
      var mktTag = h.market === "海外" ? "海外" : (h.kind === "个股" ? "个股" : "A股");
      var clsName = pctCls(chg);
      return '<div class="hrow">' +
        '<div class="hname"><div class="t"><span>' + esc(h.name) + '</span><span class="mk">' + mktTag + "</span></div>" +
        '<div class="s">' + sub.join(" · ") + "</div></div>" +
        '<div class="hpx"><span class="p">' + (px === null ? NA : fmt(px, px < 10 ? 3 : 2)) + '</span><span class="c ' + clsName + '">' + (chg === null || chg === undefined ? NA : sgnTxt(chg) + "%") + "</span></div>" +
        '<div><span class="abtn ' + cls + '">' + esc(h.action) + "</span></div>" +
        '<div class="hwhy">' + esc(h.reason || "") + "</div></div>";
    }).join("");
    $("holdBox").innerHTML = html || '<div class="basis">' + NA + "</div>";
    var notes = (D.meta && D.meta.note_holdings) || [];
    if (notes.length) {
      var n = $("holdNotes");
      n.hidden = false;
      n.innerHTML = "⚠️ " + notes.map(esc).join("　");
    }
  }

  // ---------- ⑤ 周期 ----------
  function renderCycle() {
    var cy = D.cycle || {};
    var stage = cy.stage || 0;
    var rows = STAGETEXT.map(function (txt, i) {
      var st = i + 1;
      var on = stage === st;
      return '<div class="step' + (on ? " active" : "") + '"><span class="n">' + st + "</span><span class=\"sn\">" + txt + "</span>" +
        (on ? '<span class="cur">当前</span>' : "") + "</div>";
    }).join("");
    $("stepsBox").innerHTML = rows;
    $("cycleNow").textContent = (stage ? "当前：第 " + stage + " 阶段 · " + cy.name : NA);
    var reasons = cy.reasons || [];
    var chips = reasons.map(function (r) { return '<span class="chip">' + esc(r) + "</span>"; }).join("");
    var extra = cy.note ? '<span class="chip good">' + esc(cy.note) + "</span>" : "";
    $("cycleReason").innerHTML = chips + extra;
    $("cycleSrc").textContent = cy.src === "手动" ? "手动设定" : "规则自动";
  }

  // ---------- ⑥ 机会 ----------
  function renderOpportunity() {
    var op = D.opportunity;
    var box = $("oppBox");
    if (!op) {
      box.innerHTML = '<div class="oppempty"><b>暂无明确主线，保持现金等待。</b><br/>触发升级需要：成交额持续放大 + 某方向资金连续净流入（非单日），否则不因一根阳线追高。</div>';
      return;
    }
    var reasons = (op.reasons || []).map(function (r) {
      var on = r[1].indexOf("↑") >= 0;
      return '<span class="reason ' + (on ? "on" : "mid") + '">' + r[0] + " " + r[1] + "</span>";
    }).join("");
    var trig = op.trigger || "";
    var h = '<div class="oppname">' + esc(op.name) + "</div>" +
      (op.today_main_yi !== null && op.today_main_yi !== undefined ? '<div class="basis">今日主力净流入 ' + sgnTxt(op.today_main_yi) + " 亿（连续加权 " + fmt(op.score_yi, 0) + "）</div>" : "") +
      '<div class="reasons">' + reasons + "</div>" +
      '<div class="trigger">触发条件：' + esc(trig) + "</div>";
    box.innerHTML = h;
  }

  // ---------- ⑦ 操作 ----------
  function renderOp() {
    var op = D.op || {};
    var box = $("opBox");
    var pos = op.pos_pct, cash = op.cash_pct;
    var html = '<div class="oprow">' +
      '<div class="gauge"><div class="l">总仓位</div><div class="bar"><i style="width:' + pos + '%"></i></div><div class="v">' + fmt(pos, 0) + "%</div></div>" +
      '<div class="gauge"><div class="l">现金</div><div class="bar"><i style="width:' + cash + '%;background:linear-gradient(90deg,#f59e0b,#fbbf24)"></i></div><div class="v">' + fmt(cash, 0) + "%</div></div></div>" +
      '<div class="ophead">' + esc(op.headline || NA) + (op.signal_on ? '<span class="pill" style="color:var(--up);background:var(--up-bg)">政策二次定价信号</span>' : "") + "</div>" +
      '<div class="opswap">最优动作：<b>' + esc(op.top_action || "持有为主") + "</b></div>";
    if (op.signal_on) {
      html += '<div class="signal on">✅ ' + ((op.signal_cond || []).join("；") || "量价资金政策配合") + " → 可提高进攻仓位；若经济数据证伪或放量中断则撤回。</div>";
    } else {
      html += '<div class="signal">当前不满足「政策二次定价信号」，按存量博弈处理：卖弱买强，不提高总仓位。满足条件需同时具备：经济偏弱但政策明显加强、成交连续放大、板块资金连续流入且跑赢指数。</div>';
    }
    var evs = op.events || [];
    if (evs.length) {
      html += '<div class="events"><div style="font-size:12px;color:var(--ink-3);font-weight:700">📅 未来重要事件</div>' +
        evs.map(function (e) {
          var d = String(e.date || "");
          var dd = d.length >= 10 ? d.slice(5) : d;
          return '<div class="ev"><span class="d">' + esc(dd) + "</span>" +
            (e.est ? '<span class="est">预计</span>' : "") +
            '<span>' + esc(e.name) + "</span>" +
            (e.kind ? '<span class="k">' + esc(e.kind) + "</span>" : "") + "</div>";
        }).join("") + "</div>";
    }
    box.innerHTML = html;
    var bits = [];
    if (op.signal_on) bits.push("可加仓");
    $("opTag").textContent = bits.length ? bits.join(" · ") : "总仓位规则：存量不加 / 增量才加";
  }

  // ---------- meta / 顶栏 / 页脚 ----------
  function renderMeta() {
    var m = D.meta || {};
    var chip = $("updatedChip");
    var t = m.generated_at || "";
    $("updatedTxt").textContent = t ? "更新于 " + t.slice(5, 16) : "时间未知";
    chip.title = "数据快照 " + t;
    var asof = m.asof || "";
    var foot = [];
    foot.push("数据快照：" + (t || NA));
    if (asof) foot.push("市场截至：" + asof);
    $("footMain").textContent = foot.join("　·　");
  }

  function renderAll() {
    try {
      renderHero();
      renderVars();
      renderFlows();
      renderHoldings();
      renderCycle();
      renderOpportunity();
      renderOp();
      renderMeta();
    } catch (e) {
      console.error("render error", e);
      $("heroBox").innerHTML = '<div class="oppempty"><b>渲染出错：</b>' + esc(e.message) + "</div>";
    }
  }

  function load() {
    fetch("data/data.json?t=" + Date.now())
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { D = d; renderAll(); $("updatedChip").className = "updated live"; })
      .catch(function (e) {
        $("heroBox").innerHTML = '<div class="oppempty"><b>数据加载失败。</b><br/>请确认站点数据文件存在；或触发云端更新后重试。（' + esc(e.message) + "）</div>";
      });
  }

  // 主题
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("theme", t); } catch (e) {}
  }
  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem("theme"); } catch (e) {}
    if (!saved) saved = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
    applyTheme(saved);
  }
  $("btnTheme").addEventListener("click", function () {
    var cur = document.documentElement.getAttribute("data-theme");
    applyTheme(cur === "dark" ? "light" : "dark");
  });
  $("btnReload").addEventListener("click", function () {
    var b = $("btnReload");
    b.classList.add("spin");
    setTimeout(function () { b.classList.remove("spin"); }, 900);
    load();
  });

  // repo link (页面部署后由构建填入)
  var repo = window.location.origin.indexOf("github") >= 0 ? window.location.href.replace(/\/#.*/, "") : null;
  $("repoLink").href = repo || "https://github.com/"; // 部署后此链接指向仓库首页

  initTheme();
  load();
})();
