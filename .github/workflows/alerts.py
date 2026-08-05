"""
Day Trading Pro - Bot de alertas (corre en GitHub Actions, sin navegador)
Envia a Telegram: briefing pre-market US y BMV, movers con noticia, earnings semanal.
Secrets requeridos en el repo: FINNHUB_KEY, TG_TOKEN, TG_CHAT
"""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone

FINNHUB = os.environ.get("FINNHUB_KEY", "").strip()
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
TG_CHAT = os.environ.get("TG_CHAT", "").strip()
MODE = (sys.argv[1] if len(sys.argv) > 1 else "brief-us").lower()

US = ["AAPL","MSFT","NVDA","TSLA","AMD","META","GOOGL","AMZN","NFLX","AVGO","PLTR","COIN","SHOP",
      "UBER","SOFI","RIVN","LCID","MARA","RIOT","SMCI","MU","INTC","BABA","DIS","PYPL","SNAP",
      "PINS","ROKU","DKNG","HOOD","GME","AMC","BAC","JPM","WMT","XOM","CVX","BA","GE","SPY","QQQ","IWM"]
BMV = ["AMXL.MX","WALMEX.MX","FEMSAUBD.MX","GMEXICOB.MX","BIMBOA.MX","CEMEXCPO.MX","ALSEA.MX",
       "ALFAA.MX","GFNORTEO.MX","GAPB.MX","ASURB.MX","TLEVISACPO.MX","KOFUBL.MX","MEGACPO.MX",
       "PE&OLES.MX","GRUMAB.MX","LIVEPOLC-1.MX","ELEKTRA.MX","VESTA.MX","ORBIA.MX","GENTERA.MX",
       "GCARSOA1.MX","CUERVO.MX","BBAJIOO.MX","CHDRAUIB.MX","QUALITAS.MX","FUNO11.MX","PINFRA.MX",
       "KIMBERA.MX","VOLARA.MX","GCC.MX","LACOMERUBC.MX","R.MX","BOLSAA.MX","HERDEZ.MX"]

def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def ahora_cdmx():
    return datetime.now(timezone(timedelta(hours=-6)))

ETIQUETAS = {
    "watch":     "MOVIMIENTO DETECTADO",
    "brief-us":  "BRIEFING US",
    "brief-bmv": "BRIEFING BMV",
    "movers":    "MOVERS CON NOTICIA",
    "positions": "VIGILANCIA DE POSICIONES",
    "earnings":  "EARNINGS SEMANAL",
    "test":      "PRUEBA",
}

def encabezado():
    """Linea de identificacion que va al inicio de cada mensaje."""
    mx = ahora_cdmx()
    et = datetime.now(timezone(timedelta(hours=-4 if 3 <= mx.month <= 10 else -5)))
    return (f"[{ETIQUETAS.get(MODE, MODE.upper())}]\n"
            f"{mx:%a %d/%m} - {mx:%H:%M} CDMX  ({et:%H:%M} ET)\n")

def tg(text):
    if not TG_TOKEN or not TG_CHAT:
        print("[!] Sin credenciales de Telegram"); return False
    for chunk in split_msg(text):
        data = urllib.parse.urlencode({
            "chat_id": TG_CHAT, "text": chunk, "disable_web_page_preview": "true"
        }).encode()
        try:
            req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=data)
            with urllib.request.urlopen(req, timeout=20) as r:
                json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            print("[!] Telegram error:", e.read().decode()[:300]); return False
        time.sleep(0.4)
    return True

def split_msg(msg, limit=3800):
    out, cur = [], ""
    for line in msg.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            out.append(cur); cur = ""
        cur += line + "\n"
    if cur: out.append(cur)
    return out

def yahoo_quotes(symbols):
    """Yahoo v7 quote con reintentos y proxies."""
    out = []
    for i in range(0, len(symbols), 25):
        batch = symbols[i:i+25]
        url = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=" + ",".join(batch)
        tries = [url,
                 "https://api.allorigins.win/raw?url=" + urllib.parse.quote(url, safe=""),
                 "https://corsproxy.io/?" + urllib.parse.quote(url, safe="")]
        for u in tries:
            try:
                d = get(u)
                for q in (d.get("quoteResponse", {}) or {}).get("result", []) or []:
                    if q.get("regularMarketPrice") is None: continue
                    avg = q.get("averageDailyVolume10Day") or q.get("averageDailyVolume3Month")
                    vol = q.get("regularMarketVolume")
                    out.append({
                        "symbol": q.get("symbol"), "name": q.get("shortName") or q.get("symbol"),
                        "price": q.get("regularMarketPrice"), "chg": q.get("regularMarketChangePercent") or 0,
                        "pm": q.get("preMarketChangePercent"), "post": q.get("postMarketChangePercent"),
                        "vol": vol, "rvol": (vol/avg) if (avg and vol) else None,
                        "hi52": q.get("fiftyTwoWeekHigh"), "lo52": q.get("fiftyTwoWeekLow"),
                        "pe": q.get("trailingPE"), "mcap": q.get("marketCap"),
                    })
                break
            except Exception as e:
                continue
        time.sleep(0.3)
    return out

def finnhub_quotes(symbols):
    if not FINNHUB: return []
    out = []
    for s in symbols:
        try:
            q = get(f"https://finnhub.io/api/v1/quote?symbol={s}&token={FINNHUB}")
            if not q or q.get("c") in (None, 0): continue
            out.append({"symbol": s, "name": s, "price": q.get("c"), "chg": q.get("dp") or 0,
                        "pm": None, "post": None, "vol": None, "rvol": None,
                        "hi52": q.get("h"), "lo52": q.get("l"), "pe": None, "mcap": None})
        except Exception: pass
        time.sleep(0.9)   # respetar 60 req/min
    return out

def news_for(sym, hours=48):
    clean = sym.replace(".MX", "")
    # 1) Finnhub company-news
    if FINNHUB:
        try:
            frm = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
            to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            arr = get(f"https://finnhub.io/api/v1/company-news?symbol={clean}&from={frm}&to={to}&token={FINNHUB}")
            arr = [n for n in (arr or []) if n.get("headline")]
            arr.sort(key=lambda n: n.get("datetime", 0), reverse=True)
            cutoff = time.time() - hours * 3600
            arr = [n for n in arr if n.get("datetime", 0) >= cutoff]
            if arr:
                return [{"title": n["headline"], "url": n.get("url", ""), "src": n.get("source", "")} for n in arr[:2]]
        except Exception: pass
    # 2) Yahoo search
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={clean}&newsCount=3&quotesCount=0"
        d = get("https://api.allorigins.win/raw?url=" + urllib.parse.quote(url, safe=""))
        cutoff = time.time() - hours * 3600
        arr = [n for n in (d.get("news") or []) if n.get("providerPublishTime", 0) >= cutoff]
        return [{"title": n["title"], "url": n.get("link",""), "src": n.get("publisher","")} for n in arr[:2]]
    except Exception:
        return []

def score(it):
    s = min(40, abs(it.get("chg") or 0) * 4)
    s += min(30, (it["rvol"] * 6)) if it.get("rvol") else 5
    if it.get("hi52") and it.get("lo52") and it.get("price") and it["hi52"] > it["lo52"]:
        pos = (it["price"] - it["lo52"]) / (it["hi52"] - it["lo52"])
        s += 15 if pos > 0.9 else 10 if pos > 0.7 else 8 if pos < 0.1 else 3
    else: s += 5
    if it.get("pm") is not None: s += min(15, abs(it["pm"]) * 3)
    return round(min(100, s))

def levels(it):
    vol = 2.0
    if it.get("hi52") and it.get("lo52") and it["lo52"]:
        vol = max(1.0, min(8.0, (it["hi52"] - it["lo52"]) / it["lo52"] * 100 / 25))
    stop_pct = min(3, vol * 0.6)
    return it["price"] * (1 - stop_pct/100), it["price"] * (1 + stop_pct*2/100), stop_pct, stop_pct*2

def fmt_price(p):
    if p is None: return "-"
    return f"{p:,.2f}" if p >= 1 else f"{p:.4f}"
def fmt_pct(p):
    return "-" if p is None else f"{p:+.2f}%"

def briefing(market, top=20):
    syms = US if market == "us" else BMV
    flag = "🇺🇸" if market == "us" else "🇲🇽"
    title = "NUEVA YORK (NYSE/NASDAQ)" if market == "us" else "BOLSA MEXICANA (BMV)"
    print(f"[i] Obteniendo cotizaciones {market}...")
    items = yahoo_quotes(syms)
    if not items and market == "us":
        print("[i] Yahoo fallo, usando Finnhub...")
        items = finnhub_quotes(syms[:25])
    if not items:
        tg(f"{flag} BRIEFING {title}\n\n⚠️ No se pudieron obtener cotizaciones (fuentes caidas).")
        return
    for it in items: it["score"] = score(it)
    items.sort(key=lambda x: x["score"], reverse=True)
    items = items[:top]

    print(f"[i] Buscando noticias de {len(items)} tickers...")
    for it in items:
        it["news"] = news_for(it["symbol"])
        time.sleep(0.5)

    withnews = sum(1 for it in items if it["news"])
    now = datetime.now(timezone(timedelta(hours=-6)))
    msg = encabezado()
    msg += f"{flag} {title}\n"
    msg += f"⏰ Mercado abre {'7:30' if 3 <= now.month <= 10 else '8:30'} CDMX\n"
    msg += f"📰 {withnews}/{len(items)} con catalizador\n"
    msg += "━━━━━━━━━━━━━━━━\n\n"
    for i, it in enumerate(items, 1):
        st, tp, sp, tpp = levels(it)
        msg += f"{i}. {it['symbol'].replace('.MX','')}  ${fmt_price(it['price'])}"
        msg += "  🔥\n" if it["news"] else "\n"
        msg += f"   {fmt_pct(it['chg'])}"
        if it.get("pm") is not None: msg += f" | PM {fmt_pct(it['pm'])}"
        if it.get("rvol"): msg += f" | RVOL {it['rvol']:.2f}x"
        msg += f" | Sc {it['score']}\n"
        msg += f"   🛑 ${fmt_price(st)} (-{sp:.1f}%)  🎯 ${fmt_price(tp)} (+{tpp:.1f}%)\n"
        if it["news"]:
            n = it["news"][0]
            t = n["title"][:85] + "…" if len(n["title"]) > 85 else n["title"]
            msg += f"   📰 {t}\n   {n['url']}\n"
        else:
            msg += "   ⚠️ sin catalizador\n"
        msg += "\n"
    msg += "━━━━━━━━━━━━━━━━\n⚠️ Info objetiva, NO recomendacion.\nSin catalizador + volumen, mejor no operar."
    print("[i] Enviando a Telegram...")
    print("[OK]" if tg(msg) else "[FAIL]")

def movers_with_news(min_score=60):
    items = yahoo_quotes(US + BMV)
    if not items: print("[!] sin datos"); return
    for it in items: it["score"] = score(it)
    hot = [it for it in items if it["score"] >= min_score or abs(it.get("chg") or 0) >= 4]
    hot.sort(key=lambda x: x["score"], reverse=True)
    hot = hot[:10]
    sent = 0
    for it in hot:
        news = news_for(it["symbol"])
        if not news: continue
        st, tp, sp, tpp = levels(it)
        flag = "🇲🇽" if it["symbol"].endswith(".MX") else "🇺🇸"
        msg = encabezado() + f"\n⭐ SCORE {it['score']}/100 + NOTICIA\n\n{flag} {it['symbol'].replace('.MX','')}  ${fmt_price(it['price'])}\n"
        msg += f"{it['name']}\nCambio: {fmt_pct(it['chg'])}"
        if it.get("rvol"): msg += f" | RVOL {it['rvol']:.2f}x"
        msg += f"\n🛑 Stop sug: ${fmt_price(st)}  🎯 Target: ${fmt_price(tp)}\n"
        msg += f"\n📰 {news[0]['title']}\n{news[0]['url']}\n"
        msg += "\n⚠️ Info objetiva, NO recomendacion."
        tg(msg); sent += 1
        time.sleep(1)
    print(f"[OK] {sent} alertas enviadas")
    if sent == 0:
        mx = datetime.now(timezone(timedelta(hours=-6)))
        tg(encabezado() + f"\nRevise {len(items)} tickers. Ninguno con score>={min_score} + noticia reciente.")

def earnings(days=7):
    if not FINNHUB:
        tg("📅 EARNINGS\n\n⚠️ Falta FINNHUB_KEY en los secrets del repo."); return
    frm = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    to = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        d = get(f"https://finnhub.io/api/v1/calendar/earnings?from={frm}&to={to}&token={FINNHUB}")
        cal = d.get("earningsCalendar") or []
    except Exception as e:
        tg(f"📅 EARNINGS\n\n⚠️ Error: {e}"); return
    if not cal:
        tg(f"📅 EARNINGS\n\nSin reportes programados {frm} a {to}."); return
    big = set(US)
    cal.sort(key=lambda e: (e.get("date",""), -(e.get("revenueEstimate") or 0)))
    bydate = {}
    for e in cal: bydate.setdefault(e.get("date"), []).append(e)
    days_es = ["Lunes","Martes","Miercoles","Jueves","Viernes","Sabado","Domingo"]
    msg = encabezado() + f"\n📅 EARNINGS PROXIMOS {days} DIAS\n{frm} a {to}\n━━━━━━━━━━━━━━━━\n"
    for dt in sorted(bydate.keys()):
        try: dd = datetime.strptime(dt, "%Y-%m-%d")
        except Exception: continue
        rel = [e for e in bydate[dt] if e.get("symbol") in big]
        others = [e for e in bydate[dt] if e.get("symbol") not in big]
        show = rel + others[:max(0, 12 - len(rel))]
        if not show: continue
        msg += f"\n📆 {days_es[dd.weekday()]} {dd.day}/{dd.month}\n"
        for e in show:
            h = "🌅" if e.get("hour") == "bmo" else "🌙" if e.get("hour") == "amc" else "  "
            star = "⭐" if e.get("symbol") in big else ""
            eps = f"  EPS est ${e['epsEstimate']:.2f}" if e.get("epsEstimate") is not None else ""
            msg += f"  {h} {e.get('symbol')}{star}{eps}\n"
        if len(bydate[dt]) > len(show):
            msg += f"  (+{len(bydate[dt]) - len(show)} mas)\n"
    msg += "\n━━━━━━━━━━━━━━━━\n🌅 antes de abrir | 🌙 despues del cierre | ⭐ en tu watchlist"
    msg += "\n⚠️ Earnings mueven 10-40%. Muchos traders evitan operar justo antes."
    print("[OK]" if tg(msg) else "[FAIL]")


def load_positions():
    """Lee positions.json del repo."""
    for path in ("positions.json", "../../positions.json", os.path.join(os.path.dirname(__file__), "..", "..", "positions.json")):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
                return [p for p in (d.get("posiciones") or []) if p.get("ticker") and p.get("entry")]
        except Exception:
            continue
    return []

def monitor_positions():
    """Vigila stop-loss / take-profit / trailing de positions.json. Corre sin navegador."""
    pos = load_positions()
    if not pos:
        print("[i] Sin posiciones en positions.json"); return
    print(f"[i] Vigilando {len(pos)} posiciones...")
    syms = list({p["ticker"] for p in pos})
    quotes = {q["symbol"]: q for q in yahoo_quotes(syms)}
    if not quotes:
        quotes = {q["symbol"]: q for q in finnhub_quotes(syms)}
    alerts_sent = 0

    for p in pos:
        tk = p["ticker"]
        q = quotes.get(tk)
        if not q or q.get("price") is None:
            print(f"[!] Sin precio para {tk}"); continue
        price = q["price"]; entry = float(p["entry"]); qty = float(p.get("qty") or 1)
        stop = p.get("stop"); target = p.get("target")
        prox = float(p.get("proximity_pct") or 25) / 100
        fric = (entry + price) * qty * 0.0007
        pnl = (price - entry) * qty - fric
        pnl_pct = (price - entry) / entry * 100
        fired = []

        if stop is not None:
            stop = float(stop)
            if price <= stop:
                fired.append(("🛑", "STOP-LOSS CRUZADO", "critico"))
            elif stop < entry:
                dist = entry - stop; trav = entry - price
                if trav > 0 and trav >= dist * (1 - prox):
                    fired.append(("⚠️", f"CERCA DEL STOP (falta {abs(price-stop)/price*100:.2f}%)", "aviso"))
        if target is not None:
            target = float(target)
            if price >= target:
                fired.append(("🎯", "TAKE-PROFIT ALCANZADO", "bueno"))
            elif target > entry:
                dist = target - entry; trav = price - entry
                if trav > 0 and trav >= dist * (1 - prox):
                    fired.append(("🔔", f"CERCA DEL TARGET (falta {abs(target-price)/price*100:.2f}%)", "bueno"))
        if p.get("trailing_pct") and q.get("hi52"):
            tp = float(p["trailing_pct"])
            hi = max(float(p.get("highest") or entry), price)
            trail = hi * (1 - tp/100)
            if price <= trail and price > entry:
                fired.append(("🔻", f"TRAILING STOP ${trail:.2f}", "aviso"))

        if not fired: 
            print(f"[i] {tk} ${price:.2f} ({pnl_pct:+.2f}%) - sin alertas")
            continue

        for emoji, label, kind in fired:
            msg = f"{emoji} {label}\n\n"
            msg += f"{tk}  {int(qty)} @ entrada ${entry:.2f}\n"
            msg += f"Precio actual: ${price:.2f} ({pnl_pct:+.2f}%)\n"
            msg += f"P&L estimado: {'+' if pnl>=0 else ''}${pnl:.2f}\n"
            if stop is not None: msg += f"Stop: ${float(stop):.2f}\n"
            if target is not None: msg += f"Target: ${float(target):.2f}\n"
            if p.get("notas"): msg += f"Nota: {p['notas']}\n"
            msg += "\n⚠️ GBM Trading USA no tiene stop automatico: si operas alli, entra y vende manual."
            tg(msg); alerts_sent += 1
            time.sleep(0.6)
        print(f"[OK] {tk}: {len(fired)} alertas")
    print(f"[OK] Total {alerts_sent} alertas enviadas")


# ============================================================
#  MODO WATCH: vigilancia continua, mismo criterio que la app
#  de Windows. Alerta cualquier movimiento >= umbral.
# ============================================================
STATE_FILE = "/tmp/dt_alerted.json"

def _load_state():
    try:
        d = json.load(open(STATE_FILE, encoding="utf-8"))
        hoy = ahora_cdmx().strftime("%Y-%m-%d")
        return d.get("dia") == hoy and d.get("tickers") or {}
    except Exception:
        return {}

def _save_state(st):
    try:
        json.dump({"dia": ahora_cdmx().strftime("%Y-%m-%d"), "tickers": st},
                  open(STATE_FILE, "w", encoding="utf-8"))
    except Exception:
        pass

def watch(umbral=2.0, cooldown_min=45):
    """Revisa todo y alerta lo que se mueva >= umbral. Un mensaje por ticker."""
    mx = ahora_cdmx()
    if mx.weekday() > 4:
        print("[i] fin de semana"); return

    items = yahoo_quotes(US + BMV)
    fuente = "Yahoo"
    if not items:
        items = finnhub_quotes(US)
        fuente = "Finnhub"
    if not items:
        print("[!] sin datos de ninguna fuente"); return
    print(f"[i] {len(items)} tickers desde {fuente}")

    st = _load_state()
    ahora = time.time()
    enviados = 0
    movidos = []

    for it in items:
        chg = it.get("chg") or 0
        if abs(chg) < umbral:
            continue
        movidos.append(it)
        tk = it["symbol"]
        if st.get(tk, 0) + cooldown_min * 60 > ahora:
            continue
        st[tk] = ahora

        it["score"] = score(it)
        news = news_for(tk, hours=48)
        st_price, tp_price, sp, tpp = levels(it)
        flecha = "SUBE" if chg > 0 else "BAJA"
        flag = "MX" if tk.endswith(".MX") else "US"

        msg = encabezado()
        msg += f"\n{'📈' if chg > 0 else '📉'} {flecha} {tk.replace('.MX','')} {chg:+.2f}%  ({flag})\n"
        msg += f"{it.get('name','')}\n\n"
        msg += f"Precio: ${fmt_price(it['price'])}\n"
        if it.get("rvol"): msg += f"RVOL: {it['rvol']:.2f}x\n"
        msg += f"Score: {it['score']}/100\n"
        if it.get("pm") is not None: msg += f"Pre-market: {fmt_pct(it['pm'])}\n"
        msg += f"\n🛑 Stop sug: ${fmt_price(st_price)} (-{sp:.1f}%)\n"
        msg += f"🎯 Target sug: ${fmt_price(tp_price)} (+{tpp:.1f}%)\n"
        if news:
            msg += f"\n📰 {news[0]['title']}\n{news[0]['url']}\n"
        else:
            msg += "\n⚠️ sin catalizador reciente (48h)\n"
        msg += "\n⚠️ Info objetiva, NO recomendacion."
        tg(msg)
        enviados += 1
        print(f"  [ALERTA] {tk} {chg:+.2f}% score {it['score']}")
        time.sleep(1)

    _save_state(st)
    print(f"[OK] {len(movidos)} superaron {umbral}%, {enviados} alertas nuevas enviadas")
    if not movidos:
        top = sorted(items, key=lambda x: abs(x.get("chg") or 0), reverse=True)[:3]
        print("[i] mayores: " + ", ".join(f"{t['symbol']} {t.get('chg',0):+.2f}%" for t in top))

if __name__ == "__main__":
    print(f"[i] Modo: {MODE} | Finnhub: {'si' if FINNHUB else 'no'} | TG: {'si' if TG_TOKEN else 'no'}")
    if MODE == "brief-us":   briefing("us", 20)
    elif MODE == "brief-bmv": briefing("bmv", 20)
    elif MODE == "movers":    movers_with_news(60)
    elif MODE == "earnings":  earnings(7)
    elif MODE == "positions": monitor_positions()
    elif MODE == "watch":     watch(float(os.environ.get("UMBRAL", "2")), int(os.environ.get("COOLDOWN", "45")))
    elif MODE == "test":
        print("[OK]" if tg(encabezado() + "\n✅ GitHub Actions conectado.\nRecibiras alertas automaticas sin navegador abierto.") else "[FAIL]")
    else: print("Modos: brief-us | brief-bmv | movers | earnings | positions | watch | test")
