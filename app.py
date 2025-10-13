import os
import io
import datetime as dt
import requests
import pandas as pd
import numpy as np

# usar backend sin display para Render
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from flask import Flask, jsonify, request, Response

app = Flask(__name__)

# =======================
# Config
# =======================
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else ""

BINANCE_BASE = "https://api.binance.com"

# =======================
# Helpers
# =======================
def normalize_symbol(raw: str) -> str:
    """Convierte 'XRP-EUR' / 'XRP/EUR' -> 'XRPEUR'."""
    return (raw or "").upper().replace("-", "").replace("/", "")

def tg_send_message(chat_id, text):
    if not TELEGRAM_TOKEN: 
        return
    try:
        requests.post(f"{TELEGRAM_URL}/sendMessage",
                      json={"chat_id": chat_id, "text": text}, timeout=8)
    except requests.RequestException:
        pass

def tg_send_photo(chat_id, photo_url, caption=""):
    if not TELEGRAM_TOKEN:
        return
    try:
        requests.post(f"{TELEGRAM_URL}/sendPhoto",
                      json={"chat_id": chat_id, "photo": photo_url, "caption": caption}, timeout=12)
    except requests.RequestException:
        pass

# =======================
# Básicos
# =======================
@app.get("/")
def root():
    return "Trader-GPT API online", 200

@app.get("/favicon.ico")
def favicon():
    return Response(status=204)

@app.get("/health")
def health():
    return jsonify(status="ok"), 200

# =======================
# Market: Price
# =======================
@app.get("/api/v1/binance/price")
def binance_price():
    raw_symbol = request.args.get("symbol", "").strip()
    if not raw_symbol:
        return jsonify(error="Missing 'symbol' (e.g. XRP-EUR o XRPEUR)"), 400

    sym = normalize_symbol(raw_symbol)
    try:
        r = requests.get(f"{BINANCE_BASE}/api/v3/ticker/price",
                         params={"symbol": sym}, timeout=8)
        if r.status_code != 200:
            return jsonify(error="Binance response", status=r.status_code, detail=r.text), 502
        data = r.json()
        return jsonify(symbol=data.get("symbol", sym), price=float(data.get("price"))), 200
    except requests.RequestException as e:
        return jsonify(error="Request to Binance failed", detail=str(e)), 502

# --- KLlNES ---
@app.get("/api/v1/binance/klines")
def binance_klines():
    symbol = request.args.get("symbol","").upper().replace("-","").replace("/","")
    interval = request.args.get("interval","1h")
    limit = request.args.get("limit","100")
    if not symbol: return jsonify(error="Missing 'symbol'"), 400
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    if r.status_code != 200: return jsonify(error="Binance", status=r.status_code, detail=r.text), 502
    return jsonify(r.json()), 200


# =======================
# Charts: PNG OHLC + EMA20/50 + RSI + Volumen
# =======================
@app.get("/api/v1/chart")
def chart():
    raw_symbol = request.args.get("symbol", "XRP-EUR").strip()
    interval   = request.args.get("interval", "1h").strip()
    limit      = int(request.args.get("limit", 100))

    sym = normalize_symbol(raw_symbol)
    try:
        r = requests.get(f"{BINANCE_BASE}/api/v3/klines",
                         params={"symbol": sym, "interval": interval, "limit": limit},
                         timeout=12)
        if r.status_code != 200:
            return jsonify(error="Binance response", status=r.status_code, detail=r.text), 502
        data = r.json()
        if not data:
            return jsonify(error="Sin datos"), 404
    except requests.RequestException as e:
        return jsonify(error="Request to Binance failed", detail=str(e)), 502

    # a DataFrame
    df = pd.DataFrame(data, columns=[
        "open_time","open","high","low","close","volume","close_time",
        "qav","trades","tbbav","tbqav","ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df.astype({"open":float,"high":float,"low":float,"close":float,"volume":float})

    # RSI(14)
    delta = df["close"].diff()
    gain  = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # EMAs
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    # Plot
    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(10, 7), sharex=True,
        gridspec_kw={"height_ratios": [3, 1, 1]}
    )

    ax1.plot(df["open_time"], df["close"], label="Cierre", linewidth=1.2)
    ax1.plot(df["open_time"], df["ema20"], "--", label="EMA20")
    ax1.plot(df["open_time"], df["ema50"], "--", label="EMA50")
    ax1.fill_between(df["open_time"], df["low"], df["high"], alpha=0.12)
    ax1.set_title(f"{raw_symbol} ({interval})")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.plot(df["open_time"], df["rsi"])
    ax2.axhline(70, linestyle="--")
    ax2.axhline(30, linestyle="--")
    ax2.set_title("RSI 14")
    ax2.grid(True, alpha=0.3)

    ax3.bar(df["open_time"], df["volume"], alpha=0.5)
    ax3.set_title("Volumen")
    ax3.grid(True, alpha=0.3)

    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate()

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")

# =======================
# Webhook seguro (Bearer)
# =======================
@app.post("/webhook")
def webhook():
    auth = request.headers.get("Authorization", "")
    if not WEBHOOK_TOKEN or auth != f"Bearer {WEBHOOK_TOKEN}":
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    msg = data.get("message", "")
    return jsonify(reply=f"Eco: {msg}"), 200

# =======================
# Telegram Bot webhook
# =======================
@app.post("/telegram")
def telegram_webhook():
    data = request.get_json(silent=True) or {}
    msg = data.get("message", {})
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()

    if not chat_id:
        return jsonify(ok=False), 400

    reply = "🤖 Bot activo. Usa /precio ADA/EUR o /grafico XRP/EUR"

    try:
        low = text.lower()
        if low.startswith("/start"):
            reply = "✅ Bot listo. Comandos: /precio <par> | /grafico <par>"
        elif low.startswith("/precio"):
            parts = text.split()
            if len(parts) >= 2:
                symbol = parts[1].upper()
                sym = normalize_symbol(symbol)
                r = requests.get(f"{BINANCE_BASE}/api/v3/ticker/price",
                                 params={"symbol": sym}, timeout=8)
                if r.status_code == 200:
                    p = r.json().get("price", "?")
                    reply = f"💰 Precio {symbol}: {p}"
                else:
                    reply = "⚠️ Error al consultar el precio."
            else:
                reply = "Uso: /precio ADA/EUR"
        elif low.startswith("/grafico"):
            parts = text.split()
            if len(parts) >= 2:
                symbol = parts[1].upper()
                url = f"https://{request.host}/api/v1/chart?symbol={symbol}&interval=1h&limit=100"
                tg_send_photo(chat_id, url, f"📊 Gráfico {symbol} (1h)")
                return jsonify(ok=True)
            else:
                reply = "Uso: /grafico ADA/EUR"
    except Exception as e:
        reply = f"Error: {e}"

    tg_send_message(chat_id, reply)
    return jsonify(ok=True)

# =======================
# Privacy (requerido por GPT público)
# =======================
@app.get("/privacy")
def privacy():
    html = """
    <html><head><meta charset="utf-8"><title>Privacy Policy</title></head>
    <body style="font-family:system-ui;max-width:800px;margin:40px auto;line-height:1.5">
      <h1>Privacy Policy — mundo cripto</h1>
      <p>Este servicio expone endpoints públicos para datos de mercado y bots conectados a GPT/Telegram.</p>
      <p>No se almacenan datos personales. Los logs técnicos (IP/fecha/ruta/código) se usan sólo para operación y seguridad.</p>
      <p>Endpoints sensibles requieren Authorization: Bearer &lt;token&gt;.</p>
      <p>Contacto: propietario del repositorio GitHub taznarll-code/trader-GPT.</p>
      <p>Última actualización: 2025-10-13</p>
    </body></html>
    """
    return Response(html, mimetype="text/html")

# =======================
# Diagnóstico: rutas
# =======================
@app.get("/routes")
def list_routes():
    rules = [
        {"rule": str(r), "methods": sorted(r.methods - {"HEAD", "OPTIONS"})}
        for r in app.url_map.iter_rules()
    ]
    return jsonify(routes=sorted(rules, key=lambda x: x["rule"]))

# =======================
# Main
# =======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
