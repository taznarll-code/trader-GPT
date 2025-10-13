import os, io, requests
from flask import Flask, jsonify, request, Response
import pandas as pd, numpy as np

# --- Matplotlib en modo headless (necesario en Render) ---
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

app = Flask(__name__)

# ====== CONFIG ======
WEBHOOK_TOKEN  = os.environ.get("WEBHOOK_TOKEN", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_URL   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else ""

# ====== HELPERS ======
def _normalize_symbol(raw: str) -> str:
    return (raw or "").upper().replace("-", "").replace("/", "")

def send_message(chat_id, text):
    if TELEGRAM_URL:
        requests.post(f"{TELEGRAM_URL}/sendMessage", json={"chat_id": chat_id, "text": text})

def send_photo(chat_id, photo_url, caption=""):
    if TELEGRAM_URL:
        requests.post(f"{TELEGRAM_URL}/sendPhoto", json={"chat_id": chat_id, "photo": photo_url, "caption": caption})

# ====== BASE ======
@app.get("/")
def root():
    return "GPT service online", 200

@app.get("/health")
def health():
    return jsonify(status="ok"), 200

@app.get("/favicon.ico")
def favicon():
    return Response(status=204)

# ====== PRIVACY ======
@app.get("/privacy")
def privacy():
    html = """
    <html><head><meta charset='utf-8'><title>Privacy Policy</title></head>
    <body style='font-family:system-ui;max-width:800px;margin:40px auto;line-height:1.5'>
      <h1>Privacy Policy — mundo cripto</h1>
      <p>Este servicio expone endpoints para datos públicos de mercado y recepción de webhooks.</p>
      <ul>
        <li>No almacenamos datos personales.</li>
        <li>Se guardan logs técnicos mínimos (fecha, IP, ruta) para seguridad y depuración.</li>
      </ul>
      <p>Endpoints sensibles usan token Bearer. No envíes secretos por URL.</p>
      <p>Owner: taznarll-code / trader-GPT</p>
    </body></html>
    """
    return Response(html, mimetype="text/html")

# ====== BINANCE: PRICE ======
@app.get("/api/v1/binance/price")
def binance_price():
    raw = request.args.get("symbol", "").strip()
    if not raw:
        return jsonify(error="Missing 'symbol'"), 400
    sym = _normalize_symbol(raw)

    r = requests.get("https://api.binance.com/api/v3/ticker/price",
                     params={"symbol": sym}, timeout=8)
    if r.status_code != 200:
        return jsonify(error="Binance response", status=r.status_code, detail=r.text), 502

    data = r.json()
    return jsonify(symbol=data.get("symbol"), price=float(data.get("price"))), 200

# ====== BINANCE: KLINES ======
@app.get("/api/v1/binance/klines")
def binance_klines():
    sym = _normalize_symbol(request.args.get("symbol", ""))
    interval = request.args.get("interval", "1h")
    limit = request.args.get("limit", "100")

    if not sym:
        return jsonify(error="Missing 'symbol'"), 400

    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": sym, "interval": interval, "limit": limit},
                     timeout=10)
    if r.status_code != 200:
        return jsonify(error="Binance response", status=r.status_code, detail=r.text), 502

    return jsonify(r.json()), 200

# ====== CHART PNG (RSI + EMA20/EMA50 + Volumen) ======
@app.get("/api/v1/chart")
def chart():
    raw = request.args.get("symbol", "XRP-EUR").strip()
    interval = request.args.get("interval", "1h").strip()
    limit = int(request.args.get("limit", "100"))
    sym = _normalize_symbol(raw)

    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": sym, "interval": interval, "limit": limit},
                     timeout=10)
    if r.status_code != 200:
        return jsonify(error="Binance response", status=r.status_code, detail=r.text), 502
    data = r.json()
    if not data:
        return jsonify(error="Sin datos"), 404

    df = pd.DataFrame(data, columns=[
        "open_time","open","high","low","close","volume","close_time",
        "qav","trades","tbbav","tbqav","ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df.astype({"open":float,"high":float,"low":float,"close":float,"volume":float})

    # RSI(14)
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean().replace(0, np.nan)
    rs = gain / loss
    df["rsi"] = 100 - (100/(1+rs))

    # EMAs
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    # Plot
    fig, (ax1, ax2, ax3) = plt.subplots(3,1,figsize=(10,7), sharex=True,
                                        gridspec_kw={"height_ratios":[3,1,1]})
    ax1.plot(df["open_time"], df["close"], label="Close", linewidth=1.2)
    ax1.plot(df["open_time"], df["ema20"], "--", label="EMA20")
    ax1.plot(df["open_time"], df["ema50"], "--", label="EMA50")
    ax1.fill_between(df["open_time"], df["low"], df["high"], alpha=0.1)
    ax1.set_title(f"{raw} ({interval})")
    ax1.legend(); ax1.grid(True, alpha=0.3)

    ax2.plot(df["open_time"], df["rsi"], linewidth=1)
    ax2.axhline(70, linestyle="--"); ax2.axhline(30, linestyle="--")
    ax2.set_title("RSI 14"); ax2.grid(True, alpha=0.3)

    ax3.bar(df["open_time"], df["volume"], alpha=0.5)
    ax3.set_title("Volume"); ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    fig.autofmt_xdate()

    buf = io.BytesIO()
    plt.tight_layout(); plt.savefig(buf, format="png"); plt.close(fig); buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")

# ====== WEBHOOK (Bearer) ======
@app.post("/webhook")
def webhook():
    if request.headers.get("Authorization","") != f"Bearer {WEBHOOK_TOKEN}":
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    msg = data.get("message", "")
    return jsonify(reply=f"Eco: {msg}"), 200

# ====== TELEGRAM ======
@app.post("/telegram")
def telegram_webhook():
    payload = request.get_json(silent=True) or {}
    msg = payload.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip().lower()
    if not chat_id:
        return jsonify(ok=False), 400

    try:
        if text.startswith("/start"):
            send_message(chat_id, "✅ Bot listo. Usa /precio ADA/EUR o /grafico XRP/EUR")
        elif text.startswith("/precio"):
            sym = _normalize_symbol(text.split()[1].upper())
            r = requests.get("https://api.binance.com/api/v3/ticker/price",
                             params={"symbol": sym}, timeout=8)
            if r.status_code == 200:
                send_message(chat_id, f"💰 {sym}: {r.json()['price']}")
            else:
                send_message(chat_id, "⚠️ Error al obtener precio.")
        elif text.startswith("/grafico"):
            sym = (text.split()[1] or "XRP/EUR").upper()
            url = f"https://trader-gpt.onrender.com/api/v1/chart?symbol={sym}&interval=1h&limit=100"
            send_photo(chat_id, url, f"📊 Gráfico {sym} (1h)")
        else:
            send_message(chat_id, "Comandos: /precio <PAR> | /grafico <PAR>")
        return jsonify(ok=True)
    except Exception as e:
        send_message(chat_id, f"Error: {e}")
        return jsonify(ok=False), 200

# ====== DIAGNÓSTICO DE RUTAS ======
@app.get("/routes")
def list_routes():
    rules = [{"rule": str(r), "methods": sorted(r.methods - {'HEAD','OPTIONS'})} for r in app.url_map.iter_rules()]
    return jsonify(routes=sorted(rules, key=lambda x: x["rule"]))

# ====== MAIN ======
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
