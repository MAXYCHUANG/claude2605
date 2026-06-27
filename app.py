import os
from flask import Flask, request
from scripts.cc_spot_intraday_monitor import SYMBOLS, _fetch_1m, _parse_bars, _analyze, render_html, _send

app = Flask(__name__)

@app.route("/")
def index():
    window = int(request.args.get("window", 30))
    results = []
    
    for sym in SYMBOLS:
        try:
            raw = _fetch_1m(sym)
            meta, bars = _parse_bars(raw)
            if bars:
                a = _analyze(meta, bars, window, sym)
                results.append(a)
        except Exception as e:
            print(f"ERROR fetching {sym}: {e}")

    if not results:
        return "Failed to fetch data or not a trading day.", 500

    html = render_html(results, window)
    return html

@app.route("/email")
def trigger_email():
    window = int(request.args.get("window", 30))
    to_addr = request.args.get("to", os.environ.get("RECIPIENT", "yc5780"))
    
    results = []
    for sym in SYMBOLS:
        try:
            raw = _fetch_1m(sym)
            meta, bars = _parse_bars(raw)
            if bars:
                a = _analyze(meta, bars, window, sym)
                results.append(a)
        except Exception as e:
            print(f"ERROR fetching {sym}: {e}")

    if not results:
        return "Failed to fetch data.", 500

    html = render_html(results, window)
    nvda_res = next((r for r in results if r["symbol"] == "NVDA"), results[0])
    
    subject = (
        f"[3-Layer] NVDA {window}m"
        f" | ${nvda_res['price_w']:.2f} ({nvda_res['pct_prev']:+.2f}%)"
        f" | {nvda_res['direction']}"
    )

    sent = _send(subject, html, to_addr)
    if sent:
        return f"Email sent successfully to {sent}!"
    else:
        return "Email failed to send. Check SMTP configuration.", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
