# GPT Service (Render Template) — V2 con Binance

Servicio Flask listo para Render con:
- `GET /health`
- `POST /webhook`
- `GET /api/v1/binance/price?symbol=XRP-EUR` (o `XRPEUR`)

## Local
```bash
pip install -r requirements.txt
python app.py
# http://127.0.0.1:8080/health
# http://127.0.0.1:8080/api/v1/binance/price?symbol=XRP-EUR
```

## Render (resumen)
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app --bind 0.0.0.0:$PORT`
- Health: `/health`
