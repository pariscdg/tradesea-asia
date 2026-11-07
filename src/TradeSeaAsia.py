"""Window by default; scheduled invocations perform one request per selected account."""
import argparse
import logging
from logging.handlers import RotatingFileHandler

from asia_service import AsiaService
from asia_check import installation_check
from tradesea_lockout import ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description="TradeSea Asia account and schedule panel")
    parser.add_argument("--run", action="store_true", help="apply the saved schedule settings once and exit")
    parser.add_argument("--headless", action="store_true", help="compatibility option for the existing scheduled task")
    parser.add_argument("--login-only", action="store_true", help="open the panel and refresh the saved login")
    parser.add_argument("--self-check", action="store_true", help="run the installation check without contacting TradeSea")
    parser.add_argument("--preview", action="store_true", help="show the new panel with sample accounts, offline")
    parser.add_argument("--ui-check", action="store_true", help="verify native corner transparency with offline sample accounts")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[
        RotatingFileHandler(ROOT / "asia-lockout.log", maxBytes=200_000, backupCount=2, encoding="utf-8")])
    if args.self_check:
        return installation_check()
    service = AsiaService()
    if args.run or args.headless:
        return service.run()
    from qt_panel import show_panel
    return show_panel(service, preview=args.preview or args.ui_check, check=args.ui_check)


if __name__ == "__main__":
    raise SystemExit(main())
