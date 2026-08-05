/* ============================================================
   CONFIGURACION COMPARTIDA - Day Trading Pro
   ------------------------------------------------------------
   Este archivo lo leen LOS TRES sistemas:
     1. Dashboard HTML (navegador)
     2. App de notificaciones Windows (alertas_windows.py)
     3. Bot de GitHub Actions (si lo subes al repo sin credenciales)

   Editas aqui una vez y los tres quedan sincronizados.

   NO se sube a GitHub (esta en .gitignore) para proteger tus llaves.
   ============================================================ */
window.DT_PRESET = {

  /* ---------- CREDENCIALES ----------
     Ya NO van aqui. Estan en mis_credenciales.js
     (ese archivo no lo sobrescribo nunca).            */

  /* ---------- UMBRALES (los usan los tres) ---------- */
  threshold:   2,      // % de movimiento para alertar
  rvolMin:     1.5,    // volumen relativo minimo (info extra)
  scoreMin:    60,     // score alternativo para alertar
  intervalSec: 60,     // refresco del dashboard (segundos)
  intervalMin: 5,      // refresco de la app Windows (minutos)
  cooldownMin: 30,     // no repetir el mismo ticker en X minutos
  exigirNoticia: false,// true = solo alerta si hay catalizador

  /* ---------- AUTOMATIZACION ---------- */
  autoBrief:   true,   // briefing automatico antes de apertura
  briefOffset: 10,     // minutos antes de que abra el mercado
  autoScore:   true,   // alertas de score alto + noticia
  sound:       true,

  /* ---------- CANALES DE NOTIFICACION ---------- */
  notifWindows:  true, // toasts nativos de Windows (app)
  notifTelegram: true, // mensajes de Telegram (app + dashboard)
  notifNavegador:true, // notificaciones del navegador (dashboard)

  /* ---------- WATCHLISTS COMPARTIDAS ---------- */
  us: [
    "AAPL","MSFT","NVDA","TSLA","AMD","META","GOOGL","AMZN","NFLX","AVGO",
    "PLTR","COIN","SHOP","UBER","SOFI","RIVN","LCID","MARA","RIOT","SMCI",
    "MU","INTC","BABA","DIS","PYPL","SNAP","PINS","ROKU","DKNG","HOOD",
    "GME","AMC","BAC","JPM","WMT","XOM","CVX","BA","GE"
  ],

  etf: [
    "SPY","QQQ","IWM","DIA","VTI","VOO","ARKK","XLK","XLF","XLE",
    "XLV","GLD","SLV","TLT","SOXX","SMH","TQQQ","SQQQ","UVXY"
  ],

  bmv: [
    "AMXL.MX","WALMEX.MX","FEMSAUBD.MX","GMEXICOB.MX","BIMBOA.MX","CEMEXCPO.MX",
    "ALSEA.MX","ALFAA.MX","GFNORTEO.MX","GAPB.MX","ASURB.MX","TLEVISACPO.MX",
    "KOFUBL.MX","MEGACPO.MX","PE&OLES.MX","GRUMAB.MX","LIVEPOLC-1.MX","ELEKTRA.MX",
    "VESTA.MX","ORBIA.MX","GENTERA.MX","GCARSOA1.MX","CUERVO.MX","BBAJIOO.MX",
    "CHDRAUIB.MX","QUALITAS.MX","FUNO11.MX","PINFRA.MX","KIMBERA.MX","VOLARA.MX",
    "GCC.MX","LACOMERUBC.MX","R.MX","BOLSAA.MX","HERDEZ.MX","ARA.MX","LAB.MX"
  ],

  crypto: [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
    "AVAXUSDT","LINKUSDT","DOTUSDT","MATICUSDT","LTCUSDT","SHIBUSDT","UNIUSDT",
    "ATOMUSDT","NEARUSDT","APTUSDT","ARBUSDT","OPUSDT","INJUSDT","SUIUSDT"
  ]
};
