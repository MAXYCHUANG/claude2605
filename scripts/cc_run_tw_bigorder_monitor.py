#!/usr/bin/env python3
"""Monitor and record large options and stock orders via Fubon WebSocket.

TXO threshold: >= 100 contracts
Stock threshold: >= 500 shares

Records to: log/bigorder_YYYYMMDD.jsonl (NDJSON format)
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_DIR / "log"
LOG_DIR.mkdir(exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(LOG_DIR / f"bigorder_monitor_{dt.date.today():%Y%m%d}.log"),
    ],
)
logger = logging.getLogger(__name__)

# Thresholds
TXO_BIGORDER_THRESHOLD = 100  # contracts
STOCK_BIGORDER_THRESHOLD = 500  # shares
SYMBOLS_TO_MONITOR = ["2330", "00891", "00830", "2881"]

# Global state
should_stop = False
bigorder_file = None


def handle_signal(signum, frame):
    global should_stop
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    should_stop = True


def save_bigorder(record: dict) -> None:
    global bigorder_file
    if bigorder_file:
        bigorder_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        bigorder_file.flush()


def parse_trade_message(msg: dict, symbol: str, is_futopt: bool = False) -> dict | None:
    """Parse a trades channel message from WebSocket."""
    if not isinstance(msg, dict):
        return None

    # WebSocket trades format: {"trade": {"price": ..., "size": ..., "bid": ..., "ask": ..., "time": ...}}
    trade_data = msg.get("trade")
    if not trade_data:
        return None

    price = trade_data.get("price")
    size = trade_data.get("size")
    ask = trade_data.get("ask")
    bid = trade_data.get("bid")

    if price is None or size is None:
        return None

    # Determine direction (主動買/主動賣)
    direction = None
    if ask is not None and bid is not None:
        if abs(price - ask) < abs(price - bid):
            direction = "ask"  # 主動買
        elif abs(price - bid) < abs(price - ask):
            direction = "bid"  # 主動賣

    ts = dt.datetime.now().isoformat()

    if is_futopt:
        # Extract call/put from symbol (e.g., "TXO20260520C40400")
        opt_type = None
        if "C" in symbol:
            opt_type = "call"
        elif "P" in symbol:
            opt_type = "put"
        return {
            "ts": ts,
            "symbol": symbol,
            "type": opt_type or "unknown",
            "price": price,
            "size": size,
            "direction": direction,
        }
    else:
        # Stock
        return {
            "ts": ts,
            "symbol": symbol,
            "type": "stock",
            "price": price,
            "size": size,
            "direction": direction,
        }


def on_futopt_message(data: dict) -> None:
    """Handle futopt WebSocket message."""
    if isinstance(data, bytes):
        try:
            data = json.loads(data.decode("utf-8", errors="replace"))
        except Exception:
            return
    elif isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return

    if not isinstance(data, dict):
        return

    symbol = data.get("symbol")
    if not symbol:
        return

    record = parse_trade_message(data, symbol, is_futopt=True)
    if record and record.get("size", 0) >= TXO_BIGORDER_THRESHOLD:
        logger.info(f"TXO Large order: {symbol} {record['size']} @ {record['price']}")
        save_bigorder(record)


def on_stock_message(data: dict) -> None:
    """Handle stock WebSocket message."""
    if isinstance(data, bytes):
        try:
            data = json.loads(data.decode("utf-8", errors="replace"))
        except Exception:
            return
    elif isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return

    if not isinstance(data, dict):
        return

    symbol = data.get("symbol")
    if not symbol:
        return

    record = parse_trade_message(data, symbol, is_futopt=False)
    if record and record.get("size", 0) >= STOCK_BIGORDER_THRESHOLD:
        logger.info(f"Stock large order: {symbol} {record['size']} @ {record['price']}")
        save_bigorder(record)


def main() -> int:
    global bigorder_file

    # Load environment
    env_keys = ("FUBON_ID", "FUBON_PASSWORD", "FUBON_CERT_PATH", "FUBON_CERT_PASSWORD")
    if not all(os.environ.get(k) for k in env_keys):
        logger.error("Missing Fubon environment variables")
        return 1

    # Try to import SDK
    try:
        from fubon_neo.sdk import FubonSDK
    except ImportError:
        logger.error("Fubon Neo SDK not installed")
        return 1

    # Initialize SDK and WebSocket
    try:
        sdk = FubonSDK()
        sdk.login(
            os.environ["FUBON_ID"],
            os.environ["FUBON_PASSWORD"],
            os.environ["FUBON_CERT_PATH"],
            os.environ["FUBON_CERT_PASSWORD"],
        )
        sdk.init_realtime()
    except Exception as exc:
        logger.error(f"Failed to login Fubon SDK: {exc}")
        return 1

    ws_stock = sdk.marketdata.websocket_client.stock
    ws_futopt = sdk.marketdata.websocket_client.futopt

    # Get TXO near-month symbols
    txo_symbols = []
    try:
        products = sdk.marketdata.rest_client.futopt.intraday.products()
        for prod in (products.get("products") or []):
            if "TXO" in prod.get("code", ""):
                txo_symbols.append(prod["code"])
        if not txo_symbols:
            logger.warning("No TXO near-month contracts found, using fallback")
            txo_symbols = ["TXO20260520C40000", "TXO20260520P40000"]  # Fallback
    except Exception as exc:
        logger.warning(f"Failed to query TXO products: {exc}, using fallback")
        txo_symbols = ["TXO20260520C40000", "TXO20260520P40000"]

    logger.info(f"Monitoring {len(txo_symbols)} TXO contracts and {len(SYMBOLS_TO_MONITOR)} stocks")

    # Open log file
    today = dt.date.today()
    bigorder_path = LOG_DIR / f"bigorder_{today:%Y%m%d}.jsonl"
    bigorder_file = open(bigorder_path, "a")

    # Write PID
    pid_file = LOG_DIR / "bigorder_monitor.pid"
    pid_file.write_text(str(os.getpid()))
    logger.info(f"PID: {os.getpid()}")

    # Setup signal handlers
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Register handlers
    ws_stock.on("connect", lambda: logger.info("Stock WebSocket connected"))
    ws_stock.on("authenticated", lambda msg: [
        ws_stock.subscribe({"channel": "trades", "symbol": sym})
        for sym in SYMBOLS_TO_MONITOR
    ])
    ws_stock.on("message", on_stock_message)
    ws_stock.on("error", lambda exc: logger.error(f"Stock WS error: {exc}"))

    ws_futopt.on("connect", lambda: logger.info("FutOpt WebSocket connected"))
    ws_futopt.on("authenticated", lambda msg: [
        ws_futopt.subscribe({"channel": "trades", "symbol": sym})
        for sym in txo_symbols
    ])
    ws_futopt.on("message", on_futopt_message)
    ws_futopt.on("error", lambda exc: logger.error(f"FutOpt WS error: {exc}"))

    # Connect
    try:
        logger.info("Connecting to WebSocket...")
        ws_stock.connect()
        logger.info("Stock WS authenticated, proceeding to futopt...")
        ws_futopt.connect()
        logger.info("All WebSocket connected and authenticated")
    except Exception as exc:
        logger.error(f"Failed to connect WebSocket: {exc}")
        bigorder_file.close()
        return 1

    # Keep running until signal received
    try:
        while not should_stop:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        logger.info("Closing WebSocket and log file...")
        try:
            ws_stock.disconnect()
            ws_futopt.disconnect()
        except Exception:
            pass
        if bigorder_file:
            bigorder_file.close()
        logger.info("Monitoring stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
