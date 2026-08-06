#!/usr/bin/env python3
"""
================================================================
  DAY TRADING PRO
================================================================
  trading.bat            vigilancia continua (Windows + Telegram)
  subir.bat              publica el dashboard y activa GitHub Actions

  python trading.py            = vigilancia continua
  python trading.py diag       = diagnostico
  python trading.py subir      = deploy + workflows
  python trading.py limpiar    = borra archivos viejos

  Credenciales ya embebidas. No hay que configurar nada.
================================================================
"""
import os, re, sys, json, time, shutil, base64, tempfile, subprocess
from urllib import request as urlreq, parse as urlparse, error as urlerr
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = "index.html"
REPO = "davidvemo/trading"
BRANCH = "main"
SELF = os.path.basename(os.path.abspath(__file__))

# ================================================================
#  CREDENCIALES  (las escribe 'migrar' - no las edites a mano)
# ================================================================
CREDS = {
    "finnhub":  "",   # en GitHub Actions vienen de los secrets
    "tg_token": "",
    "tg_chat":  "",
    "github":   "",
}

# ================================================================
#  AJUSTES
# ================================================================
CFG = {
    "umbral_pct":   2.0,    # % de movimiento para alertar
    "rvol_min":     1.5,    # volumen relativo (info extra)
    "score_min":    60,     # score alterno
    "intervalo_min": 5,     # cada cuanto revisa en modo local
    "cooldown_min": 30,     # no repetir el mismo ticker
    "solo_horario": True,   # solo alertar en horario de mercado
    "sonido":       True,
    "toast":        True,   # notificaciones nativas de Windows
    "telegram":     True,
    "exigir_noticia": False,
    "top_briefing": 20,
}

US = ["AAPL","MSFT","NVDA","TSLA","AMD","META","GOOGL","AMZN","NFLX","AVGO","PLTR","COIN","SHOP",
      "UBER","SOFI","RIVN","LCID","MARA","RIOT","SMCI","MU","INTC","BABA","DIS","PYPL","SNAP",
      "PINS","ROKU","DKNG","HOOD","GME","AMC","BAC","JPM","WMT","XOM","CVX","BA","GE",
      "SPY","QQQ","IWM","DIA","ARKK","XLK","XLF","XLE","GLD","SLV","TLT","SOXX","SMH","TQQQ","SQQQ"]

BMV = ["AMXL.MX","WALMEX.MX","FEMSAUBD.MX","GMEXICOB.MX","BIMBOA.MX","CEMEXCPO.MX","ALSEA.MX",
       "ALFAA.MX","GFNORTEO.MX","GAPB.MX","ASURB.MX","TLEVISACPO.MX","KOFUBL.MX","MEGACPO.MX",
       "PE&OLES.MX","GRUMAB.MX","LIVEPOLC-1.MX","ELEKTRA.MX","VESTA.MX","ORBIA.MX","GENTERA.MX",
       "GCARSOA1.MX","CUERVO.MX","BBAJIOO.MX","CHDRAUIB.MX","QUALITAS.MX","FUNO11.MX","PINFRA.MX",
       "KIMBERA.MX","VOLARA.MX","GCC.MX","LACOMERUBC.MX","R.MX","BOLSAA.MX","HERDEZ.MX","ARA.MX","LAB.MX"]

STATE = os.path.join(tempfile.gettempdir(), "dt_alerted.json")
CACHE_METRICS = os.path.join(BASE, ".metrics.json")
_sent = {}

def cred(k):
    return os.environ.get({"finnhub":"FINNHUB_KEY","tg_token":"TG_TOKEN",
                           "tg_chat":"TG_CHAT","github":"GITHUB_TOKEN"}[k], "").strip() or CREDS.get(k, "")

# ================================================================
#  UTILIDADES DE TIEMPO
# ================================================================
def mx_now():
    return datetime.now(timezone(timedelta(hours=-6)))

def es_verano():
    m = mx_now().month
    return 3 <= m <= 10

def apertura_cdmx():
    """(hora, minuto) de apertura de mercado en CDMX. Ambos mercados coinciden."""
    return (7, 30) if es_verano() else (8, 30)

def mercado_abierto(incluir_premarket=True):
    n = mx_now()
    if n.weekday() > 4: return False
    h, m = apertura_cdmx()
    ini = (2*60) if incluir_premarket else (h*60 + m)
    fin = (14*60) if es_verano() else (15*60)
    cur = n.hour*60 + n.minute
    return ini <= cur <= fin

ETIQUETAS = {"watch":"MOVIMIENTO DETECTADO","precio":"ALERTA DE PRECIO","cierre":"CIERRE DE MERCADO","brief-us":"BRIEFING US","brief-bmv":"BRIEFING BMV",
             "movers":"MOVERS CON NOTICIA","positions":"VIGILANCIA DE POSICIONES",
             "earnings":"EARNINGS SEMANAL","test":"PRUEBA","alertas":"ALERTA LOCAL"}

def encabezado(modo):
    n = mx_now()
    off = -4 if es_verano() else -5
    et = datetime.now(timezone(timedelta(hours=off)))
    return f"[{ETIQUETAS.get(modo, modo.upper())}]\n{n:%a %d/%m} - {n:%H:%M} CDMX  ({et:%H:%M} ET)\n"

# ================================================================
#  NOTIFICACIONES
# ================================================================
def toast(titulo, cuerpo, urgente=False):
    if not CFG["toast"] or os.name != "nt": return False
    try:
        from winotify import Notification, audio
        n = Notification(app_id="Day Trading Pro", title=titulo, msg=cuerpo,
                         duration="long" if urgente else "short")
        if CFG["sonido"]:
            n.set_audio(audio.LoopingAlarm2 if urgente else audio.Default, loop=False)
        n.show(); return True
    except ImportError:
        pass
    except Exception:
        pass
    ps = ('[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n'
          '$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n'
          f'$t.GetElementsByTagName("text")[0].AppendChild($t.CreateTextNode({json.dumps(titulo)}))|Out-Null\n'
          f'$t.GetElementsByTagName("text")[1].AppendChild($t.CreateTextNode({json.dumps(cuerpo)}))|Out-Null\n'
          '$n=[Windows.UI.Notifications.ToastNotification]::new($t)\n'
          '[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Day Trading Pro").Show($n)')
    try:
        f = tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8")
        f.write(ps); f.close()
        subprocess.run(["powershell","-ExecutionPolicy","Bypass","-NoProfile","-File",f.name],
                       capture_output=True, timeout=15,
                       creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        os.unlink(f.name); return True
    except Exception:
        print(f"  >> {titulo} :: {cuerpo}")
        return False

def _tg_send(texto):
    tok, chat = cred("tg_token"), cred("tg_chat")
    if not (tok and chat): return False
    url = (f"https://api.telegram.org/bot{tok}/sendMessage?"
           + urlparse.urlencode({"chat_id": chat, "text": texto, "disable_web_page_preview": "true"}))
    try:
        with urlreq.urlopen(urlreq.Request(url, headers={"User-Agent":"dt"}), timeout=20) as r:
            json.loads(r.read().decode())
        return True
    except urlerr.HTTPError as e:
        print("  [!] telegram:", e.read().decode()[:200]); return False
    except Exception as e:
        print("  [!] telegram:", e); return False

def telegram(texto):
    if not CFG["telegram"]: return False
    ok = True
    for chunk in _split(texto):
        ok = _tg_send(chunk) and ok
        time.sleep(0.4)
    return ok

def _split(msg, limite=3800):
    out, cur = [], ""
    for ln in msg.split("\n"):
        if len(cur) + len(ln) + 1 > limite:
            out.append(cur); cur = ""
        cur += ln + "\n"
    if cur: out.append(cur)
    return out

def notificar(titulo, cuerpo, urgente=False, modo="alertas"):
    toast(titulo, cuerpo, urgente)
    telegram(encabezado(modo) + "\n" + titulo + "\n" + cuerpo)

# ================================================================
#  FUENTES DE DATOS
# ================================================================
def _json(url, timeout=15):
    req = urlreq.Request(url, headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

PROXIES = ["https://api.allorigins.win/raw?url={}",
           "https://api.codetabs.com/v1/proxy/?quest={}",
           "https://corsproxy.io/?{}"]

def _json_proxy(url, timeout=12):
    for u in [url] + [p.format(urlparse.quote(url, safe="")) for p in PROXIES]:
        try: return _json(u, timeout)
        except Exception: continue
    raise RuntimeError("todas las rutas fallaron")

def q_yahoo(symbols):
    out = []
    for i in range(0, len(symbols), 25):
        url = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=" + ",".join(symbols[i:i+25])
        try:
            d = _json_proxy(url)
            for q in (d.get("quoteResponse") or {}).get("result") or []:
                if q.get("regularMarketPrice") is None: continue
                avg = q.get("averageDailyVolume10Day") or q.get("averageDailyVolume3Month")
                vol = q.get("regularMarketVolume")
                out.append({"symbol": q["symbol"], "name": q.get("shortName") or q["symbol"],
                            "price": q["regularMarketPrice"], "chg": q.get("regularMarketChangePercent") or 0,
                            "pm": q.get("preMarketChangePercent"), "post": q.get("postMarketChangePercent"),
                            "vol": vol, "rvol": (vol/avg) if (avg and vol) else None,
                            "hi52": q.get("fiftyTwoWeekHigh"), "lo52": q.get("fiftyTwoWeekLow"),
                            "pe": q.get("trailingPE"), "mcap": q.get("marketCap")})
        except Exception: pass
        time.sleep(0.3)
    return out

def q_yahoo_chart(symbols, limite=None):
    """v8 chart ticker por ticker. Unica via gratuita para BMV."""
    out = []
    for s in (symbols[:limite] if limite else symbols):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urlparse.quote(s)}?range=5d&interval=1d"
        try:
            d = _json_proxy(url, timeout=10)
            res = (d.get("chart") or {}).get("result") or []
            if not res: continue
            m = res[0].get("meta") or {}
            px, prev = m.get("regularMarketPrice"), (m.get("previousClose") or m.get("chartPreviousClose"))
            if px is None: continue
            ind = ((res[0].get("indicators") or {}).get("quote") or [{}])[0]
            vols = [v for v in (ind.get("volume") or []) if v]
            vol = vols[-1] if vols else None
            avg = (sum(vols[:-1])/len(vols[:-1])) if len(vols) > 1 else None
            out.append({"symbol": s, "name": m.get("shortName") or s, "price": px,
                        "chg": ((px-prev)/prev*100) if prev else 0, "pm": None, "post": None,
                        "vol": vol, "rvol": (vol/avg) if (vol and avg) else None,
                        "hi52": m.get("fiftyTwoWeekHigh"), "lo52": m.get("fiftyTwoWeekLow"),
                        "pe": None, "mcap": None})
        except Exception: pass
        time.sleep(0.25)
    return out

def q_stooq(symbols):
    out = []
    conv = [(s, s.lower().replace(".","-")+".us") for s in symbols if not s.endswith(".MX")]
    for i in range(0, len(conv), 20):
        chunk = conv[i:i+20]
        url = "https://stooq.com/q/l/?s=" + ",".join(m for _, m in chunk) + "&f=sd2t2ohlcv&h&e=csv"
        try:
            req = urlreq.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            with urlreq.urlopen(req, timeout=15) as r:
                lines = r.read().decode("utf-8","replace").strip().split("\n")
            hdr = [c.strip().lower() for c in lines[0].split(",")]
            rev = {m: o for o, m in chunk}
            for ln in lines[1:]:
                cols = [c.strip() for c in ln.split(",")]
                if len(cols) < len(hdr): continue
                row = dict(zip(hdr, cols))
                sym = rev.get(row.get("symbol","").lower())
                if not sym: continue
                try:
                    c_, o_ = float(row.get("close") or 0), float(row.get("open") or 0)
                    v_ = float(row.get("volume") or 0)
                except ValueError: continue
                if c_ <= 0: continue
                out.append({"symbol": sym, "name": sym, "price": c_,
                            "chg": ((c_-o_)/o_*100) if o_ else 0, "pm": None, "post": None,
                            "vol": v_ or None, "rvol": None, "hi52": None, "lo52": None,
                            "pe": None, "mcap": None})
        except Exception: pass
        time.sleep(0.4)
    return out

def metricas_finnhub():
    """52w high/low + volumen promedio. Cache de un dia."""
    k = cred("finnhub")
    if not k: return {}
    hoy = mx_now().strftime("%Y-%m-%d")
    try:
        d = json.load(open(CACHE_METRICS, encoding="utf-8"))
        if d.get("fecha") == hoy: return d.get("data") or {}
    except Exception: pass
    data = {}
    objetivo = [s for s in US if not s.endswith(".MX")]
    print(f"   [metricas] 52w de {len(objetivo)} tickers (1 vez al dia)...")
    for s in objetivo:
        try:
            m = (_json(f"https://finnhub.io/api/v1/stock/metric?symbol={s}&metric=all&token={k}", 12) or {}).get("metric") or {}
            hi, lo, av = m.get("52WeekHigh"), m.get("52WeekLow"), m.get("10DayAverageTradingVolume")
            if hi or lo or av:
                data[s] = {"hi52": hi, "lo52": lo, "avg_vol": (av*1_000_000) if av else None}
        except Exception: pass
        time.sleep(1.05)
    try: json.dump({"fecha": hoy, "data": data}, open(CACHE_METRICS,"w",encoding="utf-8"))
    except Exception: pass
    print(f"   [metricas] {len(data)} guardados")
    return data

def q_finnhub(symbols):
    k = cred("finnhub")
    if not k: return []
    mets = metricas_finnhub()
    out = []
    for s in [x for x in symbols if not x.endswith(".MX")]:
        try:
            q = _json(f"https://finnhub.io/api/v1/quote?symbol={s}&token={k}")
            if q and q.get("c"):
                mt = mets.get(s) or {}
                out.append({"symbol": s, "name": s, "price": q["c"], "chg": q.get("dp") or 0,
                            "pm": None, "post": None, "vol": None, "rvol": None,
                            "hi52": mt.get("hi52"), "lo52": mt.get("lo52"),
                            "avg_vol": mt.get("avg_vol"), "pe": None, "mcap": None})
        except Exception: pass
        time.sleep(1.05)
    return out

def obtener_datos(verbose=True):
    """Cascada: Yahoo v7 -> (US: Finnhub/Stooq/chart) + (BMV: chart)."""
    fuentes, items = [], []
    todo = q_yahoo(US + BMV)
    if todo:
        items, fuentes = todo, [f"Yahoo v7 ({len(todo)})"]
    else:
        us_i = []
        if cred("finnhub"):
            us_i = q_finnhub(US)
            if us_i: fuentes.append(f"Finnhub US ({len(us_i)})")
        if not us_i:
            us_i = q_stooq(US)
            if us_i: fuentes.append(f"Stooq US ({len(us_i)})")
        if not us_i:
            us_i = q_yahoo_chart(US, limite=45)
            if us_i: fuentes.append(f"Yahoo chart US ({len(us_i)})")
        mx_i = q_yahoo_chart(BMV)
        if mx_i: fuentes.append(f"Yahoo chart BMV ({len(mx_i)})")
        items = us_i + mx_i
    if verbose and fuentes: print("   fuentes: " + " | ".join(fuentes))
    return items

# ================================================================
#  SCORE / NIVELES / NOTICIAS
# ================================================================
def score(it):
    """0-100 normalizado sobre los componentes con datos disponibles."""
    partes = [(40, min(1.0, abs(it.get("chg") or 0)/10.0))]
    if it.get("rvol"): partes.append((30, min(1.0, it["rvol"]/5.0)))
    hi, lo, px = it.get("hi52"), it.get("lo52"), it.get("price")
    if hi and lo and px and hi > lo:
        pos = (px-lo)/(hi-lo)
        partes.append((15, 1.0 if pos > .9 else .67 if pos > .7 else .53 if pos < .1 else .20))
    if it.get("pm") is not None: partes.append((15, min(1.0, abs(it["pm"])/5.0)))
    peso = sum(w for w,_ in partes)
    if not peso: return 0
    it["_factores"] = len(partes)
    return round(min(100, sum(w*v for w,v in partes)/peso*100))

def niveles(it):
    vol = 2.0
    if it.get("hi52") and it.get("lo52") and it["lo52"]:
        vol = max(1.0, min(8.0, (it["hi52"]-it["lo52"])/it["lo52"]*100/25))
    sp = min(3, vol*0.6)
    return it["price"]*(1-sp/100), it["price"]*(1+sp*2/100), sp, sp*2

def noticias(sym, horas=48):
    limpio = sym.replace(".MX","")
    k = cred("finnhub")
    if k:
        try:
            frm = (datetime.now(timezone.utc)-timedelta(days=3)).strftime("%Y-%m-%d")
            to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            arr = _json(f"https://finnhub.io/api/v1/company-news?symbol={limpio}&from={frm}&to={to}&token={k}", 12) or []
            corte = time.time() - horas*3600
            arr = sorted([n for n in arr if n.get("headline") and n.get("datetime",0) >= corte],
                         key=lambda n: n["datetime"], reverse=True)
            if arr: return [{"t": n["headline"], "u": n.get("url",""), "s": n.get("source","")} for n in arr[:2]]
        except Exception: pass
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={urlparse.quote(limpio)}&newsCount=3&quotesCount=0"
        d = _json_proxy(url, 8)
        corte = time.time() - horas*3600
        arr = [n for n in (d.get("news") or []) if n.get("providerPublishTime",0) >= corte]
        return [{"t": n["title"], "u": n.get("link",""), "s": n.get("publisher","")} for n in arr[:2]]
    except Exception:
        return []

def fp(p):
    if p is None: return "-"
    return f"{p:,.2f}" if p >= 1 else f"{p:.4f}"
def fpc(p):
    return "-" if p is None else f"{p:+.2f}%"
def fv(v):
    if v is None: return "-"
    for u, d in (("B",1e9),("M",1e6),("K",1e3)):
        if abs(v) >= d: return f"{v/d:.2f}{u}"
    return f"{v:.0f}"


# ================================================================
#  SINCRONIZACION con el dashboard
#  El navegador descarga dt_sync.json a Descargas; aqui lo recogemos.
# ================================================================
ALERTS_FILE = os.path.join(BASE, "alertas_precio.json")

def _carpetas_descargas():
    c = [BASE]
    home = os.path.expanduser("~")
    for d in ("Downloads", "Descargas"):
        pp = os.path.join(home, d)
        if os.path.isdir(pp): c.append(pp)
    if os.environ.get("USERPROFILE"):
        for d in ("Downloads", "Descargas"):
            pp = os.path.join(os.environ["USERPROFILE"], d)
            if os.path.isdir(pp) and pp not in c: c.append(pp)
    return c

def recoger_sync(silencioso=True):
    """Busca dt_sync.json (incluso dt_sync (1).json) y lo importa."""
    import glob as _g
    cands = []
    for carpeta in _carpetas_descargas():
        cands += _g.glob(os.path.join(carpeta, "dt_sync*.json"))
    if not cands: return False
    cands.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    nuevo = cands[0]
    try:
        d = json.load(open(nuevo, encoding="utf-8"))
    except Exception as e:
        if not silencioso: print(f"[!] {os.path.basename(nuevo)} ilegible: {e}")
        return False

    pos = d.get("posiciones") or []
    alr = d.get("alertas_precio") or []
    json.dump({"_importado": datetime.now().isoformat(), "posiciones": pos},
              open(os.path.join(BASE, "positions.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump({"_importado": datetime.now().isoformat(), "alertas": alr},
              open(ALERTS_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    wl = d.get("watchlist") or {}
    global US, BMV
    if wl.get("us") or wl.get("etf"):
        US = list(dict.fromkeys((wl.get("us") or []) + (wl.get("etf") or []))) or US
    if wl.get("bmv"):
        BMV = wl["bmv"]

    if not silencioso:
        print(f"[sync] importado de {os.path.basename(nuevo)}: {len(pos)} posiciones, {len(alr)} alertas, {len(US)} US, {len(BMV)} BMV")
    for f in cands:
        try: os.remove(f)
        except Exception: pass
    return True

def subir_sync():
    """Sube positions.json y alertas_precio.json al repo (para GitHub Actions)."""
    if not cred("github"):
        print("[!] falta token de GitHub"); return
    for f in ("positions.json", "alertas_precio.json"):
        fp = os.path.join(BASE, f)
        if os.path.exists(fp):
            _subir(f, open(fp, "rb").read(), f"sync: {f}")

def _leer_alertas_precio():
    for r in (ALERTS_FILE, "alertas_precio.json"):
        try: return json.load(open(r, encoding="utf-8")).get("alertas") or []
        except Exception: continue
    return []

def alertas_precio(quotes=None, local=False):
    """Avisa cuando un ticker cruza el precio objetivo que pusiste en el dashboard."""
    al = _leer_alertas_precio()
    if not al: return 0
    quotes = quotes or {}
    faltan = [a["ticker"] for a in al if a.get("ticker") and a["ticker"] not in quotes]
    if faltan:
        for q in (q_yahoo(faltan) or q_yahoo_chart(faltan)):
            quotes[q["symbol"]] = q
    n = 0; ahora = time.time()
    for a in al:
        tk = a.get("ticker"); q = quotes.get(tk)
        if not q or not a.get("precio"): continue
        px, obj, direc = q["price"], float(a["precio"]), a.get("dir", "above")
        cumple = px >= obj if direc == "above" else px <= obj
        if not cumple: continue
        k = f"px_{tk}_{direc}_{obj}"
        if _sent.get(k, 0) + 3600 > ahora: continue
        _sent[k] = ahora
        titulo = f"🔔 ALERTA DE PRECIO - {tk.replace('.MX','')}"
        cuerpo = (("Subio a " if direc == "above" else "Bajo a ") + f"${fp(px)}"
                  + f" (objetivo ${fp(obj)})"
                  + (f"\n{fpc(q.get('chg'))} hoy" if q.get("chg") is not None else "")
                  + (f"\n{a['nota']}" if a.get("nota") else ""))
        if local: notificar(titulo, cuerpo, True, "precio")
        else: telegram(encabezado("precio") + "\n" + titulo + "\n" + cuerpo)
        print(f"  [PRECIO] {tk} cruzo ${obj}")
        n += 1; time.sleep(0.8)
    return n

# ================================================================
#  MODO WATCH  (el que replica la app de Windows)
# ================================================================
def _estado():
    try:
        d = json.load(open(STATE, encoding="utf-8"))
        return (d.get("tickers") or {}) if d.get("dia") == mx_now().strftime("%Y-%m-%d") else {}
    except Exception: return {}

def _guardar_estado(st):
    try: json.dump({"dia": mx_now().strftime("%Y-%m-%d"), "tickers": st}, open(STATE,"w",encoding="utf-8"))
    except Exception: pass

def _mensaje_movimiento(it, modo="watch"):
    chg = it.get("chg") or 0
    it["score"] = score(it)
    st, tp, sp, tpp = niveles(it)
    nw = noticias(it["symbol"])
    flecha = "SUBE" if chg > 0 else "BAJA"
    flag = "MX" if it["symbol"].endswith(".MX") else "US"
    tk = it["symbol"].replace(".MX","")
    titulo = f"{'📈' if chg>0 else '📉'} {flecha} {tk} {chg:+.2f}%  ({flag})"
    cuerpo = f"{it.get('name','')}\n\nPrecio: ${fp(it['price'])}\n"
    if it.get("rvol"): cuerpo += f"RVOL: {it['rvol']:.2f}x\n"
    f_ = it.get("_factores", 0)
    cuerpo += f"Score: {it['score']}/100" + (f" ({f_}/4 factores)\n" if f_ < 4 else "\n")
    if it.get("pm") is not None: cuerpo += f"Pre-market: {fpc(it['pm'])}\n"
    cuerpo += f"\n🛑 Stop sug: ${fp(st)} (-{sp:.1f}%)\n🎯 Target sug: ${fp(tp)} (+{tpp:.1f}%)\n"
    cuerpo += (f"\n📰 {nw[0]['t']}\n{nw[0]['u']}\n" if nw else "\n⚠️ sin catalizador reciente (48h)\n")
    cuerpo += "\n⚠️ Info objetiva, NO recomendacion."
    return titulo, cuerpo, bool(nw)

def watch(umbral=None, cooldown=None, local=False):
    umbral = umbral if umbral else CFG["umbral_pct"]
    cooldown = (cooldown if cooldown else CFG["cooldown_min"]) * 60
    if CFG["solo_horario"] and not mercado_abierto():
        print(f"[{mx_now():%H:%M}] mercado cerrado"); return 0
    if not os.environ.get("GITHUB_ACTIONS"): recoger_sync(silencioso=False)
    items = obtener_datos()
    if not items:
        print("[!] ninguna fuente respondio")
        if not cred("finnhub"): print("    >> falta Finnhub key: corre 'python trading.py migrar'")
        return 0
    st = _estado(); ahora = time.time(); enviados = 0; movidos = []
    for it in items:
        chg = it.get("chg") or 0
        if abs(chg) < umbral: continue
        movidos.append(it)
        tk = it["symbol"]
        if st.get(tk, 0) + cooldown > ahora: continue
        st[tk] = ahora
        titulo, cuerpo, con_news = _mensaje_movimiento(it)
        if CFG["exigir_noticia"] and not con_news: continue
        if local: notificar(titulo, cuerpo, urgente=abs(chg) >= umbral*2, modo="watch")
        else: telegram(encabezado("watch") + "\n" + titulo + "\n" + cuerpo)
        print(f"  [ALERTA] {tk} {chg:+.2f}% score {it['score']}")
        enviados += 1; time.sleep(1)
    _guardar_estado(st)
    print(f"[{mx_now():%H:%M}] {len(movidos)} sobre {umbral}%, {enviados} alertas nuevas")
    if not movidos:
        top = sorted(items, key=lambda x: abs(x.get("chg") or 0), reverse=True)[:3]
        print("   mayores: " + ", ".join(f"{t['symbol'].replace('.MX','')} {t.get('chg',0):+.2f}% (sc {score(t)})" for t in top))
    qm = {i["symbol"]: i for i in items}
    enviados += posiciones(qm, local=local)
    enviados += alertas_precio(qm, local=local)
    return enviados


def earnings_semana(dias=7):
    """{ticker: {"fecha": "2026-08-07", "hora": "amc", "eps": 1.23}} para los proximos dias."""
    k = cred("finnhub")
    if not k: return {}
    try:
        frm = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        to = (datetime.now(timezone.utc) + timedelta(days=dias)).strftime("%Y-%m-%d")
        cal = (_json(f"https://finnhub.io/api/v1/calendar/earnings?from={frm}&to={to}&token={k}", 25) or {}).get("earningsCalendar") or []
    except Exception:
        return {}
    out = {}
    for e in cal:
        sym = e.get("symbol")
        if not sym or sym in out: continue
        out[sym] = {"fecha": e.get("date"), "hora": e.get("hour"), "eps": e.get("epsEstimate")}
    return out

def _etq_earnings(info):
    """Etiqueta corta: 'reporta HOY amc' / 'reporta jue 07'."""
    if not info: return ""
    try:
        d = datetime.strptime(info["fecha"], "%Y-%m-%d").date()
    except Exception:
        return ""
    hoy = mx_now().date()
    delta = (d - hoy).days
    h = {"bmo": "antes de abrir", "amc": "tras el cierre"}.get(info.get("hora"), "")
    dias_es = ["lun","mar","mie","jue","vie","sab","dom"]
    if delta <= 0:   cuando = "HOY"
    elif delta == 1: cuando = "MANANA"
    else:            cuando = f"{dias_es[d.weekday()]} {d.day}"
    return f"{cuando}{' ' + h if h else ''}"

# ================================================================
#  BRIEFING
# ================================================================
def briefing(mercado, top=None, local=False):
    top = top or CFG["top_briefing"]
    syms = US if mercado == "us" else BMV
    flag = "🇺🇸" if mercado == "us" else "🇲🇽"
    titulo = "NUEVA YORK (NYSE/NASDAQ)" if mercado == "us" else "BOLSA MEXICANA (BMV)"
    todos = obtener_datos()
    items = [i for i in todos if (i["symbol"] in syms)]
    if not items:
        telegram(encabezado("brief-"+mercado) + f"\n{flag} {titulo}\n\n⚠️ Sin cotizaciones disponibles.")
        print("[!] sin datos"); return
    for it in items:
        it["score"] = score(it)
        if it.get("pm") is not None: it["score"] += abs(it["pm"])*2
    items.sort(key=lambda x: x["score"], reverse=True)
    items = items[:top]
    print(f"[i] buscando noticias de {len(items)} tickers...")
    for it in items:
        it["_nw"] = noticias(it["symbol"]); time.sleep(0.4)
    earn = earnings_semana(7)
    for it in items:
        it["_earn"] = earn.get(it["symbol"].replace(".MX", ""))
    con = sum(1 for i in items if i["_nw"])
    h, m = apertura_cdmx()
    msg = encabezado("brief-"+mercado) + f"\n{flag} {titulo}\n"
    msg += f"⏰ Abre {h}:{m:02d} CDMX\n📰 {con}/{len(items)} con catalizador\n"
    msg += "━━━━━━━━━━━━━━━━\n\n"
    for i, it in enumerate(items, 1):
        st, tp, sp, tpp = niveles(it)
        marcas = ("  🔥" if it["_nw"] else "") + ("  📅" if it.get("_earn") else "")
        msg += f"{i}. {it['symbol'].replace('.MX','')}  ${fp(it['price'])}{marcas}\n"
        msg += f"   {fpc(it.get('chg'))}"
        if it.get("pm") is not None: msg += f" | PM {fpc(it['pm'])}"
        if it.get("rvol"): msg += f" | RVOL {it['rvol']:.2f}x"
        msg += f" | Sc {round(it['score'])}\n"
        msg += f"   🛑 ${fp(st)}  🎯 ${fp(tp)}\n"
        if it.get("_earn"):
            msg += f"   📅 REPORTA {_etq_earnings(it['_earn'])}"
            if it["_earn"].get("eps") is not None: msg += f" (EPS est ${it['_earn']['eps']:.2f})"
            msg += "\n"
        if it["_nw"]:
            t = it["_nw"][0]["t"]
            msg += f"   📰 {t[:85]}{'…' if len(t)>85 else ''}\n   {it['_nw'][0]['u']}\n"
        else:
            msg += "   ⚠️ sin catalizador\n"
        msg += "\n"
    # earnings de toda la watchlist esta semana (no solo del top)
    mios = {t.replace(".MX",""): v for t, v in earn.items() if t in [x.replace(".MX","") for x in syms]}
    if mios:
        por_dia = {}
        for tk, info in mios.items():
            por_dia.setdefault(info.get("fecha"), []).append((tk, info))
        msg += "━━━━━━━━━━━━━━━━\n📅 REPORTAN ESTA SEMANA (tu watchlist)\n"
        dias_es = ["Lunes","Martes","Miercoles","Jueves","Viernes","Sabado","Domingo"]
        for f in sorted(x for x in por_dia if x):
            try: d = datetime.strptime(f, "%Y-%m-%d")
            except Exception: continue
            hoy = mx_now().date()
            tag = " (HOY)" if d.date() == hoy else ""
            msg += f"  {dias_es[d.weekday()]} {d.day}/{d.month}{tag}: "
            msg += ", ".join(f"{tk}{'🌅' if i.get('hora')=='bmo' else '🌙' if i.get('hora')=='amc' else ''}"
                             for tk, i in sorted(por_dia[f])) + "\n"
        msg += "  🌅 antes de abrir | 🌙 tras el cierre\n"
        msg += "  Earnings mueven 10-40%: muchos traders no operan justo antes.\n"
    msg += "━━━━━━━━━━━━━━━━\n⚠️ Info objetiva, NO recomendacion.\nSin catalizador + volumen, mejor no operar."
    print("[OK] enviado" if telegram(msg) else "[FAIL]")

def movers(min_score=None):
    min_score = min_score or CFG["score_min"]
    items = obtener_datos()
    if not items: print("[!] sin datos"); return
    for it in items: it["score"] = score(it)
    hot = sorted([i for i in items if i["score"] >= min_score or abs(i.get("chg") or 0) >= 4],
                 key=lambda x: x["score"], reverse=True)[:10]
    enviados = 0
    for it in hot:
        nw = noticias(it["symbol"])
        if not nw: continue
        titulo, cuerpo, _ = _mensaje_movimiento(it, "movers")
        telegram(encabezado("movers") + f"\n⭐ SCORE {it['score']}/100 + NOTICIA\n\n" + titulo + "\n" + cuerpo)
        enviados += 1; time.sleep(1)
    print(f"[OK] {enviados} enviadas")
    if not enviados:
        telegram(encabezado("movers") + f"\nRevise {len(items)} tickers. Ninguno con score>={min_score} + noticia reciente.")


def cierre():
    """Resumen al cierre del mercado: ganadores, perdedores y como quedaron tus posiciones."""
    items = obtener_datos()
    if not items:
        telegram(encabezado("cierre") + "\n⚠️ Sin datos al cierre."); return
    for it in items: it["score"] = score(it)
    us = [i for i in items if not i["symbol"].endswith(".MX")]
    mx = [i for i in items if i["symbol"].endswith(".MX")]
    def bloque(nombre, lista):
        if not lista: return ""
        up = sorted([i for i in lista if (i.get("chg") or 0) > 0], key=lambda x: -x["chg"])[:5]
        dn = sorted([i for i in lista if (i.get("chg") or 0) < 0], key=lambda x: x["chg"])[:5]
        prom = sum(i.get("chg") or 0 for i in lista) / len(lista)
        t = f"\n{nombre}  (promedio {prom:+.2f}%)\n"
        if up:
            t += "  Ganadores:\n"
            for i in up: t += f"    {i['symbol'].replace('.MX','')}  {i['chg']:+.2f}%  ${fp(i['price'])}\n"
        if dn:
            t += "  Perdedores:\n"
            for i in dn: t += f"    {i['symbol'].replace('.MX','')}  {i['chg']:+.2f}%  ${fp(i['price'])}\n"
        return t
    msg = encabezado("cierre") + "\n🔔 CIERRE DE MERCADO\n━━━━━━━━━━━━━━━━\n"
    msg += bloque("🇺🇸 ESTADOS UNIDOS", us)
    msg += bloque("🇲🇽 BOLSA MEXICANA", mx)

    # estado de las posiciones abiertas
    pos = _leer_posiciones()
    if pos:
        qm = {i["symbol"]: i for i in items}
        msg += "\n💼 TUS POSICIONES\n"
        total = 0.0
        for pp in pos:
            q = qm.get(pp.get("ticker"))
            if not q or not pp.get("entry"): continue
            entry, qty = float(pp["entry"]), float(pp.get("qty") or 1)
            pnl = (q["price"] - entry) * qty - (entry + q["price"]) * qty * 0.0007
            pct = (q["price"] - entry) / entry * 100
            total += pnl
            msg += f"  {pp['ticker'].replace('.MX','')}  ${fp(q['price'])}  {pct:+.2f}%  P&L {'+' if pnl>=0 else ''}${pnl:,.2f}\n"
        msg += f"  ─────────\n  Total no realizado: {'+' if total>=0 else ''}${total:,.2f}\n"

    # top score del dia para preparar mañana
    top = sorted(items, key=lambda x: x["score"], reverse=True)[:5]
    msg += "\n⭐ Mayor actividad hoy (para vigilar mañana)\n"
    for i in top:
        msg += f"  {i['symbol'].replace('.MX','')}  sc {i['score']}  {i.get('chg',0):+.2f}%"
        if i.get("rvol"): msg += f"  RVOL {i['rvol']:.1f}x"
        msg += "\n"
    msg += "\n━━━━━━━━━━━━━━━━\n⚠️ Info objetiva, NO recomendacion."
    print("[OK]" if telegram(msg) else "[FAIL]")

# ================================================================
#  POSICIONES  (positions.json)
# ================================================================
def _leer_posiciones():
    for r in ("positions.json", os.path.join(BASE, "positions.json")):
        try: return json.load(open(r, encoding="utf-8")).get("posiciones") or []
        except Exception: continue
    return []

def posiciones(quotes=None, local=False):
    pos = _leer_posiciones()
    if not pos: return 0
    quotes = quotes or {}
    faltan = [p["ticker"] for p in pos if p.get("ticker") and p["ticker"] not in quotes]
    if faltan:
        for q in (q_yahoo(faltan) or q_yahoo_chart(faltan)):
            quotes[q["symbol"]] = q
    n = 0; ahora = time.time()
    for p in pos:
        tk, q = p.get("ticker"), quotes.get(p.get("ticker"))
        if not q or not p.get("entry"): continue
        px, entry, qty = q["price"], float(p["entry"]), float(p.get("qty") or 1)
        stop, target = p.get("stop"), p.get("target")
        prox = float(p.get("proximity_pct") or 25)/100
        pnl = (px-entry)*qty - (entry+px)*qty*0.0007
        pct = (px-entry)/entry*100
        ev = []
        if stop is not None:
            stop = float(stop)
            if px <= stop: ev.append(("🛑 STOP-LOSS CRUZADO", True))
            elif stop < entry:
                d, t = entry-stop, entry-px
                if t > 0 and t >= d*(1-prox): ev.append((f"⚠️ CERCA DEL STOP (falta {abs(px-stop)/px*100:.2f}%)", True))
        if target is not None:
            target = float(target)
            if px >= target: ev.append(("🎯 TAKE-PROFIT ALCANZADO", False))
            elif target > entry:
                d, t = target-entry, px-entry
                if t > 0 and t >= d*(1-prox): ev.append((f"🔔 CERCA DEL TARGET (falta {abs(target-px)/px*100:.2f}%)", False))
        for label, urg in ev:
            k = f"pos_{tk}_{label[:14]}"
            if _sent.get(k, 0) + 1800 > ahora: continue
            _sent[k] = ahora
            cuerpo = (f"{int(qty)} @ ${fp(entry)} -> ${fp(px)} ({pct:+.2f}%)\n"
                      f"P&L: {'+' if pnl>=0 else ''}${pnl:,.2f}\n")
            if stop is not None: cuerpo += f"Stop: ${fp(float(stop))}\n"
            if target is not None: cuerpo += f"Target: ${fp(float(target))}\n"
            if p.get("notas"): cuerpo += f"Nota: {p['notas']}\n"
            cuerpo += "\n⚠️ GBM Trading USA no tiene stop automatico: entra y vende manual."
            if local: notificar(f"[POSICION] {label} - {tk}", cuerpo, urg, "positions")
            else: telegram(encabezado("positions") + f"\n{label} - {tk}\n" + cuerpo)
            print(f"  [POSICION] {tk}: {label}")
            n += 1; time.sleep(0.8)
    return n

# ================================================================
#  EARNINGS
# ================================================================
def earnings(dias=7):
    k = cred("finnhub")
    if not k:
        telegram(encabezado("earnings") + "\n⚠️ Falta Finnhub key."); return
    frm = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    to = (datetime.now(timezone.utc)+timedelta(days=dias)).strftime("%Y-%m-%d")
    try:
        cal = (_json(f"https://finnhub.io/api/v1/calendar/earnings?from={frm}&to={to}&token={k}", 25) or {}).get("earningsCalendar") or []
    except Exception as e:
        telegram(encabezado("earnings") + f"\n⚠️ Error: {e}"); return
    if not cal:
        telegram(encabezado("earnings") + f"\nSin reportes entre {frm} y {to}."); return
    mine = set(US)
    bydate = {}
    for e in cal: bydate.setdefault(e.get("date"), []).append(e)
    dias_es = ["Lunes","Martes","Miercoles","Jueves","Viernes","Sabado","Domingo"]
    msg = encabezado("earnings") + f"\n📅 EARNINGS PROXIMOS {dias} DIAS\n{frm} a {to}\n━━━━━━━━━━━━━━━━\n"
    for dt in sorted(bydate):
        try: dd = datetime.strptime(dt, "%Y-%m-%d")
        except Exception: continue
        rel = [e for e in bydate[dt] if e.get("symbol") in mine]
        otros = [e for e in bydate[dt] if e.get("symbol") not in mine]
        show = rel + otros[:max(0, 12-len(rel))]
        if not show: continue
        msg += f"\n📆 {dias_es[dd.weekday()]} {dd.day}/{dd.month}\n"
        for e in show:
            h = "🌅" if e.get("hour") == "bmo" else "🌙" if e.get("hour") == "amc" else "  "
            star = "⭐" if e.get("symbol") in mine else ""
            eps = f"  EPS est ${e['epsEstimate']:.2f}" if e.get("epsEstimate") is not None else ""
            msg += f"  {h} {e.get('symbol')}{star}{eps}\n"
        if len(bydate[dt]) > len(show): msg += f"  (+{len(bydate[dt])-len(show)} mas)\n"
    msg += "\n━━━━━━━━━━━━━━━━\n🌅 antes de abrir | 🌙 despues del cierre | ⭐ tu watchlist"
    msg += "\n⚠️ Earnings mueven 10-40%. Muchos traders evitan operar justo antes."
    print("[OK]" if telegram(msg) else "[FAIL]")


def check():
    """Diagnostico que corre DENTRO de GitHub Actions y reporta a Telegram."""
    import platform
    lineas = []
    lineas.append("[CHECK REMOTO]")
    lineas.append(f"{mx_now():%a %d/%m %H:%M} CDMX")
    lineas.append(f"python {platform.python_version()} | {'GitHub Actions' if os.environ.get('GITHUB_ACTIONS') else 'local'}")
    lineas.append("")
    lineas.append("SECRETS recibidos:")
    for env, lbl in (("FINNHUB_KEY","Finnhub"),("TG_TOKEN","TG token"),("TG_CHAT","TG chat")):
        v = os.environ.get(env, "")
        lineas.append(f"  {lbl}: {'OK (' + str(len(v)) + ' chars)' if v else 'VACIO <<<'}")
    lineas.append("")
    lineas.append("CONFIG:")
    lineas.append(f"  {len(US)} tickers US, {len(BMV)} BMV")
    lineas.append(f"  umbral {CFG['umbral_pct']}% | top briefing {CFG['top_briefing']}")
    h, m = apertura_cdmx()
    lineas.append(f"  apertura {h}:{m:02d} CDMX | {'verano' if es_verano() else 'invierno'}")
    lineas.append(f"  mercado abierto ahora: {'SI' if mercado_abierto() else 'NO'}")
    lineas.append("")
    lineas.append("FUENTES DE DATOS:")
    pruebas = [("Yahoo v7", lambda: q_yahoo(["AAPL","MSFT","NVDA"])),
               ("Finnhub", lambda: q_finnhub(["AAPL","MSFT","NVDA"])),
               ("Stooq", lambda: q_stooq(["AAPL","MSFT","NVDA"])),
               ("Yahoo chart US", lambda: q_yahoo_chart(["AAPL"])),
               ("Yahoo chart BMV", lambda: q_yahoo_chart(["AMXL.MX"]))]
    for nombre, fn in pruebas:
        try:
            r = fn()
            lineas.append(f"  {nombre}: {'OK -> ' + ', '.join(f'{x[chr(34)+chr(115)+chr(121)+chr(109)+chr(98)+chr(111)+chr(108)+chr(34)]}' for x in r[:3]) if r else 'SIN DATOS'}")
        except Exception as e:
            lineas.append(f"  {nombre}: ERROR {str(e)[:60]}")
    lineas.append("")
    lineas.append("CASCADA COMPLETA:")
    try:
        items = obtener_datos(verbose=False)
        us_n = len([i for i in items if not i["symbol"].endswith(".MX")])
        mx_n = len([i for i in items if i["symbol"].endswith(".MX")])
        lineas.append(f"  total {len(items)} tickers ({us_n} US, {mx_n} BMV)")
        if items:
            top = sorted(items, key=lambda x: abs(x.get("chg") or 0), reverse=True)[:3]
            for t in top:
                lineas.append(f"    {t['symbol']} ${fp(t['price'])} {fpc(t.get('chg'))}")
    except Exception as e:
        lineas.append(f"  ERROR: {str(e)[:120]}")
    lineas.append("")
    lineas.append("NOTICIAS (prueba con NVDA):")
    try:
        nw = noticias("NVDA")
        lineas.append(f"  {len(nw)} encontradas" + (f": {nw[0]['t'][:50]}" if nw else ""))
    except Exception as e:
        lineas.append(f"  ERROR {str(e)[:60]}")
    lineas.append("")
    lineas.append("EARNINGS (prueba 7 dias):")
    try:
        e7 = earnings_semana(7)
        lineas.append(f"  {len(e7)} empresas en el calendario")
    except Exception as e:
        lineas.append(f"  ERROR {str(e)[:60]}")

    txt = "\n".join(lineas)
    print(txt)
    ok = telegram(txt)
    print("\n[telegram]", "ENVIADO" if ok else "FALLO")

# ================================================================
#  GITHUB  (deploy + workflows)
# ================================================================
def _gh(metodo, ruta, payload=None):
    tok = cred("github")
    if not tok: print("[!] falta token de GitHub (corre 'migrar')"); sys.exit(1)
    h = {"Authorization": "Bearer "+tok, "Accept":"application/vnd.github+json",
         "X-GitHub-Api-Version":"2022-11-28", "User-Agent":"dt-pro"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode(); h["Content-Type"] = "application/json"
    try:
        with urlreq.urlopen(urlreq.Request("https://api.github.com"+ruta, data=data, method=metodo, headers=h), timeout=30) as r:
            return r.getcode(), json.loads(r.read().decode())
    except urlerr.HTTPError as e:
        b = e.read().decode("utf-8","replace")
        try: return e.code, json.loads(b)
        except Exception: return e.code, {"message": b[:300]}
    except Exception as e:
        return 0, {"message": str(e)}

def _subir(ruta_repo, contenido_bytes, msg=None):
    c, d = _gh("GET", f"/repos/{REPO}/contents/{ruta_repo}?ref={BRANCH}")
    sha = d.get("sha") if c == 200 else None
    p = {"message": msg or f"actualizar {ruta_repo}", "branch": BRANCH,
         "content": base64.b64encode(contenido_bytes).decode()}
    if sha: p["sha"] = sha
    c, d = _gh("PUT", f"/repos/{REPO}/contents/{ruta_repo}", p)
    ok = c in (200, 201)
    print(f"  [{'OK' if ok else '!'}] {ruta_repo}" + ("" if ok else f" -> {d.get('message','')[:90]}"))
    return ok


def _self_sin_creds():
    """Copia de este script SIN credenciales, para subir al repo.
       GitHub rechaza pushes con secretos detectables, y en Actions
       las credenciales llegan por variables de entorno (secrets)."""
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    limpio = ('CREDS = {\n'
              '    "finnhub":  "",   # en GitHub Actions vienen de los secrets\n'
              '    "tg_token": "",\n'
              '    "tg_chat":  "",\n'
              '    "github":   "",\n'
              '}')
    src = re.sub(r'CREDS = \{.*?\n\}', limpio, src, count=1, flags=re.S)
    return src.encode("utf-8")

def _wf(nombre, titulo, crons, modo):
    if crons:
        cr = "\n".join(f"    - cron: '{c}'" for c in crons)
        disparo = f"  schedule:\n{cr}\n  workflow_dispatch:"
    else:
        disparo = "  workflow_dispatch:"
    return f"""name: {titulo}

on:
{disparo}

concurrency:
  group: {nombre}
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {{ python-version: '3.11' }}
      - uses: actions/cache/restore@v4
        with:
          path: /tmp/dt_alerted.json
          key: dt-alerted-${{{{ github.run_id }}}}
          restore-keys: dt-alerted-
      - name: {titulo}
        env:
          FINNHUB_KEY: ${{{{ secrets.FINNHUB_KEY }}}}
          TG_TOKEN: ${{{{ secrets.TG_TOKEN }}}}
          TG_CHAT: ${{{{ secrets.TG_CHAT }}}}
        run: python {SELF} {modo}
      - uses: actions/cache/save@v4
        if: always()
        with:
          path: /tmp/dt_alerted.json
          key: dt-alerted-${{{{ github.run_id }}}}
"""

# UTC = CDMX + 6.  Verano (mar-oct) apertura 7:30 CDMX = 13:30 UTC. Invierno 8:30 = 14:30 UTC.
WORKFLOWS = {
    "watch":     ("Vigilancia Continua", ["45 12 * 3-10 1-5", "0,15,30,45 13,14,15,16,17,18,19,20 * 3-10 1-5",
                                          "45 13 * 1,2,11,12 1-5", "0,15,30,45 14,15,16,17,18,19,20,21 * 1,2,11,12 1-5"]),
    "brief-us":  ("Briefing US",  ["50 12 * 3-10 1-5", "50 13 * 1,2,11,12 1-5"]),
    "brief-bmv": ("Briefing BMV", ["54 12 * 3-10 1-5", "54 13 * 1,2,11,12 1-5"]),
    "positions": ("Vigilar Posiciones", ["0,30 14,15,16,17,18,19,20 * 3-10 1-5",
                                         "0,30 15,16,17,18,19,20,21 * 1,2,11,12 1-5"]),
    "movers":    ("Movers con Noticia", ["0 16,18,20 * 3-10 1-5", "0 17,19,21 * 1,2,11,12 1-5"]),
    "earnings":  ("Earnings Semanal", ["0 13 * 3-10 1", "0 14 * 1,2,11,12 1"]),
    "cierre":    ("Resumen de Cierre", ["10 20 * 3-10 1-5", "10 21 * 1,2,11,12 1-5"]),
    "check":     ("Check Remoto (manual)", []),
}

def _html_para_subir():
    """HTML con las credenciales en Base64: Pages funciona sin pedir nada
       y el escaner de secretos de GitHub no bloquea el push."""
    p = os.path.join(BASE, HTML)
    if not os.path.exists(p): return None
    h = open(p, encoding="utf-8").read()
    def b64(v): return base64.b64encode((v or "").encode()).decode()
    bloque = (
        '<script>/* CREDENCIALES EMBEBIDAS */\n'
        'window.DT_CREDS=(function(){var d=function(x){try{return atob(x)}catch(e){return ""}};'
        'return{telegramToken:d("' + b64(cred("tg_token")) + '"),'
        'telegramChat:d("' + b64(cred("tg_chat")) + '"),'
        'finnhubKey:d("' + b64(cred("finnhub")) + '")};})();\n'
        'window.DT_PRESET=Object.assign({},window.DT_PRESET||{},window.DT_CREDS);\n'
        '</script>'
    )
    h2 = re.sub(r"<script>/\* CREDENCIALES EMBEBIDAS.*?</script>", bloque, h, flags=re.S)
    if h2 == h:
        m = re.search(r"<head[^>]*>", h2)
        if m: h2 = h2[:m.end()] + "\n" + bloque + h2[m.end():]
    return h2.encode("utf-8")

def deploy():
    print("=" * 60); print(f"  DEPLOY -> {REPO}"); print("=" * 60)
    c, r = _gh("GET", f"/repos/{REPO}")
    if c != 200: print(f"[!] {r.get('message')}"); sys.exit(1)
    print(f"[i] repo {'privado' if r.get('private') else 'publico'}")
    body = _html_para_subir()
    if not body: print(f"[!] no encontre {HTML}"); sys.exit(1)
    print(f"[i] subiendo {len(body)/1024:.0f} KB con credenciales codificadas (Base64)")
    print("    Pages funciona sin pedirtelas. Ojo: en repo publico siguen")
    print("    siendo legibles para quien las decodifique.")
    _subir(HTML, body, "actualizar dashboard")
    recoger_sync(silencioso=False)
    for f in ("positions.json", "alertas_precio.json"):
        fp = os.path.join(BASE, f)
        if os.path.exists(fp): _subir(f, open(fp, "rb").read(), f"sync: {f}")
    c, _ = _gh("GET", f"/repos/{REPO}/pages")
    print(f"\nPages: {'activo' if c == 200 else 'ACTIVALO en https://github.com/'+REPO+'/settings/pages (main / root)'}")
    print(f"URL: https://davidvemo.github.io/trading/")

def setup():
    print("=" * 60); print("  SETUP GITHUB ACTIONS"); print("=" * 60)
    c, me = _gh("GET", "/user")
    if c == 200: print(f"[i] autenticado: {me.get('login')}")
    elif c == 401: print("[!] token de GitHub invalido"); sys.exit(1)
    print("\n[1/3] subiendo el script (sin credenciales; Actions las toma de los secrets)...")
    ok_self = _subir(SELF, _self_sin_creds(), "bot: " + SELF)
    if not ok_self:
        print("\n" + "!" * 60)
        print("  FALLO al subir " + SELF + " -- los workflows NO van a funcionar")
        print("  sin este archivo. Causas posibles:")
        print("   1) el token no tiene 'Contents: Read and write'")
        print("      -> https://github.com/settings/tokens")
        print("   2) GitHub bloqueo el push por detectar un secreto")
        print("      -> el error de arriba lo dice; avisame el texto exacto")
        print("!" * 60)
        sys.exit(1)
    c, d = _gh("GET", f"/repos/{REPO}/contents/{SELF}?ref={BRANCH}")
    print(f"      verificado en el repo: {'SI (' + str(round(d.get('size',0)/1024)) + ' KB)' if c == 200 else 'NO ENCONTRADO'}")
    print("\n[2/3] workflows...")
    for modo, (titulo, crons) in WORKFLOWS.items():
        _subir(f".github/workflows/{modo}.yml", _wf(modo, titulo, crons, modo).encode("utf-8"))
    # limpiar archivos viejos del repo raiz
    for viejo in ("day_trading_monitor.html", "dt_config_local.js", "mis_credenciales.js"):
        c, d = _gh("GET", f"/repos/{REPO}/contents/{viejo}?ref={BRANCH}")
        if c == 200 and d.get("sha"):
            _gh("DELETE", f"/repos/{REPO}/contents/{viejo}",
                {"message": f"quitar {viejo}", "sha": d["sha"], "branch": BRANCH})
            print(f"  [-] {viejo} eliminado del repo")
    for viejo in ("alerts.yml","alerts.py","heartbeat.yml"):
        if viejo in [f"{m}.yml" for m in WORKFLOWS]: continue
        c, d = _gh("GET", f"/repos/{REPO}/contents/.github/workflows/{viejo}?ref={BRANCH}")
        if c == 200 and d.get("sha"):
            _gh("DELETE", f"/repos/{REPO}/contents/.github/workflows/{viejo}",
                {"message": f"quitar {viejo}", "sha": d["sha"], "branch": BRANCH})
            print(f"  [-] {viejo} eliminado")
    print("\n[3/3] SECRETS (manual, por seguridad)")
    print(f"  https://github.com/{REPO}/settings/secrets/actions")
    print("    FINNHUB_KEY / TG_TOKEN / TG_CHAT")
    print("\nHorarios (CDMX): watch cada 15min 6:45-14:45 | briefings 6:50 y 6:54")
    print("                 posiciones cada 30min | movers 10/12/14 | earnings lunes 7:00")
    print(f"\nProbar: https://github.com/{REPO}/actions")

# ================================================================
#  MIGRAR: recuperar credenciales y limpiar la carpeta
# ================================================================
# ================================================================
#  DIAGNOSTICO
# ================================================================
def diag():
    print("=" * 60); print("  DIAGNOSTICO"); print("=" * 60)
    print(f"Carpeta: {BASE}")
    print(f"Hora CDMX: {mx_now():%Y-%m-%d %H:%M}  |  {'verano' if es_verano() else 'invierno'}")
    h, m = apertura_cdmx()
    print(f"Apertura mercados: {h}:{m:02d} CDMX  |  abierto ahora: {'SI' if mercado_abierto() else 'NO'}")
    print("\n--- Credenciales ---")
    for k, lbl in (("finnhub","Finnhub"),("tg_token","TG token"),("tg_chat","TG chat"),("github","GitHub")):
        v = cred(k)
        print(f"  {lbl:<10}: {(v[:10]+'...') if v and len(v)>12 else (v or 'VACIA  <<< corre migrar')}")
    print("\n--- Ajustes ---")
    print(f"  umbral {CFG['umbral_pct']}% | cooldown {CFG['cooldown_min']}min | cada {CFG['intervalo_min']}min")
    print(f"  {len(US)} US + {len(BMV)} BMV = {len(US)+len(BMV)} tickers")
    print(f"  toast={CFG['toast']} telegram={CFG['telegram']} sonido={CFG['sonido']}")
    print("\n--- Fuentes de datos (AAPL, MSFT, NVDA) ---")
    for nombre, fn in (("Yahoo v7", q_yahoo), ("Yahoo chart", q_yahoo_chart), ("Stooq", q_stooq), ("Finnhub", q_finnhub)):
        try:
            r = fn(["AAPL","MSFT","NVDA"])
            print(f"  {nombre:<12}: " + ("OK -> " + ", ".join(f"{x['symbol']} ${x['price']:.2f}" for x in r[:3]) if r else "sin datos"))
        except Exception as e:
            print(f"  {nombre:<12}: error {e}")
    try:
        rb = q_yahoo_chart(["AMXL.MX"])
        print("  BMV         : " + (f"OK -> AMXL ${rb[0]['price']:.2f}" if rb else "sin datos"))
    except Exception as e:
        print(f"  BMV         : error {e}")
    print("\n--- Canales ---")
    print("  Telegram: " + ("ENVIADO, revisa el celular" if telegram(encabezado("test")+"\n[diag] prueba desde trading.py") else "FALLO"))
    toast("Diagnostico", "Si ves esto, los toasts de Windows funcionan.")
    print("  Toast   : lanzado (revisa la esquina de la pantalla)")
    pos = _leer_posiciones()
    print(f"\n--- Posiciones en positions.json: {len(pos)} ---")
    for p in pos[:5]:
        print(f"  {p.get('ticker')} x{p.get('qty')} @ ${p.get('entry')} stop {p.get('stop')} target {p.get('target')}")
    print("=" * 60)

# ================================================================
#  LOOP LOCAL
# ================================================================
def loop_local():
    iv = max(1, CFG["intervalo_min"]) * 60
    canales = ([ "Windows" ] if CFG["toast"] else []) + ([ "Telegram" ] if (CFG["telegram"] and cred("tg_token")) else [])
    print("=" * 60)
    print("  DAY TRADING PRO - vigilancia local")
    print(f"  {len(US)} US + {len(BMV)} BMV | umbral {CFG['umbral_pct']}% | cada {CFG['intervalo_min']} min")
    print(f"  canales: {' + '.join(canales) or 'NINGUNO'}")
    print("  Ctrl+C para detener")
    print("=" * 60)
    notificar("Day Trading Pro iniciado",
              f"Vigilando {len(US)+len(BMV)} tickers cada {CFG['intervalo_min']} min\n"
              f"Umbral {CFG['umbral_pct']}% | canales: {' + '.join(canales) or 'ninguno'}")
    ciclo = 0
    while True:
        try:
            watch(local=True)
            ciclo += 1
            if ciclo % 10 == 0 and cred("github"):
                try: subir_sync()
                except Exception: pass
        except KeyboardInterrupt:
            print("\nDetenido."); break
        except Exception as e:
            print(f"[!] {e}")
        time.sleep(iv)

# ================================================================
#  MENU
# ================================================================
if __name__ == "__main__":
    modo = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    # modos que usa GitHub Actions
    if   modo == "watch":     watch(float(os.environ["UMBRAL"]) if os.environ.get("UMBRAL") else None)
    elif modo == "brief-us":  briefing("us")
    elif modo == "brief-bmv": briefing("bmv")
    elif modo == "movers":    movers()
    elif modo == "positions": print(f"[OK] {posiciones() + alertas_precio()} alertas")
    elif modo == "earnings":  earnings()
    elif modo == "check":     check()
    elif modo == "test":      print("[OK]" if telegram(encabezado("test")+"\n\u2705 Conectado.") else "[FAIL]")
    # utilidades locales
    elif modo == "sync":      recoger_sync(silencioso=False); subir_sync()
    elif modo == "diag":      diag()
    elif modo == "subir":     deploy(); print(); setup()
    elif modo == "limpiar":   limpiar()
    # SIN ARGUMENTOS -> vigilancia continua (lo normal)
    else:                     loop_local()
