#!/usr/bin/env python
"""启动Web Dashboard。"""

import argparse

from tradingagents.web import run_server


def main():
    parser = argparse.ArgumentParser(description="启动TradingAgents Web Dashboard")

    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=5000,
        help="服务端口",
    )
    parser.add_argument(
        "--host",
        "-H",
        type=str,
        default="0.0.0.0",
        help="服务主机",
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="调试模式",
    )

    args = parser.parse_args()

    print(f"启动 Web Dashboard: http://{args.host}:{args.port}")
    print("按 Ctrl+C 停止服务")

    run_server(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()