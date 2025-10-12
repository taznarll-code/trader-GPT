import os
from flask import Flask, request, jsonify, Response
import requests

app = Flask(__name__)

@app.get("/")
def root():
    return "GPT service online", 200

@app.get("/health")
def health():
    return jsonify(status="ok"), 200

@app.get("/favicon.ico")
def favicon():
    # Evita 404 en navegadores; no servimos icono real para mantenerlo simple
    return Response(status=204)

@app.post("/webhook")
def webhook():
    # Example JSON: {"message": "Hola GPT"}
    data = request.get_json(silent=True) or {}
    user_msg = data.get("message", "Hola")
    reply = f"Eco: {user_msg}"
    return jsonify(reply=reply), 200

@app.get("/api/v1/binance/price")
def binance_price():
    # Uso: /api/v1/binance/price?symbol=XRP-EUR  (también acepta XRPEUR)
    raw_symbol = request.args.get("symbol", "").strip()
    if not raw_symbol:
        return jsonify(error="Missing 'symbol' query param. Ej: XRP-EUR o XRPEUR"), 400

    # Normaliza: "XRP-EUR" -> "XRPEUR", "xrp/eur" -> "XRPEUR"
    sym = raw_symbol.upper().replace("-", "").replace("/", "")
    url = f"https://api.binance.com/api/v3/ticker/price"
    try:
        r = requests.get(url, params={"symbol": sym}, timeout=8)
        if r.status_code != 200:
            return jsonify(error="Binance response", status=r.status_code, detail=r.text), 502
        data = r.json()
        # Respuesta típica: {"symbol":"XRPEUR","price":"0.67210000"}
        return jsonify(symbol=data.get("symbol"), price=float(data.get("price"))), 200
    except requests.exceptions.RequestException as e:
        return jsonify(error="Request to Binance failed", detail=str(e)), 502

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
