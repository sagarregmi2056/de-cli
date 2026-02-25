"""
CLI app for scanning Polymarket markets and processing them with Gemini
and the external prediction API, reusing DEBot's prompts and behavior but
storing everything in MongoDB for later inspection.

Usage examples:

    python cli-app/main.py scan-markets
    python cli-app/main.py process-markets --max 10
    python cli-app/main.py interactive
    python cli-app/main.py show-market --mongo-id <id>  # view saved data
"""

import argparse
import json
import sys

from bson import ObjectId

from markets_scanner import scan_markets
from market_processor import process_markets
from db import get_db
from gamma_client import get_market_token_ids, get_market_token_ids_for_slug
from clob_client import get_market_spreads, place_buy_order
from py_clob_client.clob_types import OrderType
from ui_helpers import (
    print_header,
    print_success,
    print_info,
    print_warning,
    print_market_card,
    print_structured_summary,
    prompt_choice,
    prompt_yes_no,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DEBot-style CLI pipeline (scan, process, inspect markets)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser(
        "scan-markets",
        help="Fetch upcoming Polymarket markets and store them in MongoDB.",
    )
    scan.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Page size for Polymarket events API (default: 100).",
    )
    scan.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Maximum number of batches to fetch (default: unlimited).",
    )

    proc = sub.add_parser(
        "process-markets",
        help="Run Gemini + edge case analysis and prediction on stored markets.",
    )
    proc.add_argument(
        "--max",
        type=int,
        default=None,
        help="Maximum number of markets to process (default: all 'new' markets).",
    )
    proc.add_argument(
        "--non-interactive",
        action="store_true",
        help="Process markets without asking for confirmation.",
    )

    interactive = sub.add_parser(
        "interactive",
        help="Guided mode: scan markets then process 1v1 or team markets step-by-step.",
    )
    interactive.add_argument(
        "--scan-limit",
        type=int,
        default=200,
        help="How many events per page to fetch from Polymarket in interactive mode (default: 200).",
    )
    interactive.add_argument(
        "--scan-batches",
        type=int,
        default=3,
        help="How many pages to fetch from Polymarket in interactive mode (default: 3).",
    )

    show = sub.add_parser(
        "show-market",
        help="Show saved structured, edge-case, and prediction data for a market.",
    )
    group = show.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--mongo-id",
        help="MongoDB ObjectId of the market document.",
    )
    group.add_argument(
        "--source-id",
        help="Original Polymarket event id (source_event_id).",
    )
    group.add_argument(
        "--slug",
        help="Polymarket event slug.",
    )

    place_order = sub.add_parser(
        "place-order",
        help="Place a buy order directly via CLOB API.",
    )
    place_order.add_argument(
        "--token-id",
        required=True,
        help="Token ID for the outcome to buy.",
    )
    place_order.add_argument(
        "--amount",
        type=float,
        required=True,
        help="Amount to invest in USD (e.g., 1.0 for $1).",
    )
    place_order.add_argument(
        "--price",
        type=float,
        default=None,
        help="Limit price (0.00-1.00). If not provided, uses current market price.",
    )
    place_order.add_argument(
        "--order-type",
        choices=["GTC", "GTD", "FOK", "FAK"],
        default="GTC",
        help="Order type: GTC (Good Till Cancel), GTD (Good Till Date), FOK (Fill Or Kill), FAK (Fill And Kill). Default: GTC",
    )

    sub.add_parser(
        "help",
        help="Show available commands and descriptions.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "help":
        print_header("Available Commands")
        print(
            """
  scan-markets      Fetch upcoming Polymarket markets and store them in MongoDB.
                    Args: --limit <page size>, --max-batches <num pages>

  process-markets   Run Gemini (1v1/Teams) + EdgeCase + prediction on stored markets.
                    Args: --max <count>, --non-interactive

  interactive       Guided mode: choose type (1v1/Teams/All), optionally scan,
                    then process markets one by one with prompts.
                    Args: --scan-limit, --scan-batches

  show-market       Show saved data for a single market (structured, edge_case,
                    prediction_result).
                    Args: --mongo-id <ObjectId> | --source-id <polymarket id> | --slug <slug>

  place-order       Place a buy order directly via CLOB API.
                    Args: --token-id <id> --amount <usd> [--price <0.00-1.00>] [--order-type <GTC|GTD|FOK|FAK>]
"""
        )
        sys.exit(0)

    if args.command == "scan-markets":
        scan_markets(limit=args.limit, max_batches=args.max_batches)
    elif args.command == "process-markets":
        process_markets(
            max_count=args.max,
            interactive=not args.non_interactive,
        )
    elif args.command == "interactive":
        print_header("DEBot CLI - Interactive Mode")
        
        choice = prompt_choice(
            "What type of markets do you want to work with?",
            [
                "1v1 (e.g. tennis)",
                "Team sports (all)",
                "Team sports (select sport)",
                "All types",
                "Help (list commands)",
            ],
            allow_exit=True,
        )
        
        if choice is None:
            print_success("Exiting. Goodbye!")
            sys.exit(0)
        
        auto_mode = False
        sport_keywords: list[str] | None = None
        if choice == "1":
            etype = "1v1"
            # For 1v1 pipeline, also support fully automatic prediction + investment.
            auto_mode = True
        elif choice == "2":
            etype = "teams"
            # For teams pipeline, run fully automatic (no per‑market prompts).
            auto_mode = True
        elif choice == "3":
            etype = "teams"
            auto_mode = True
            # Let the user narrow to a specific team sport family via simple text input.
            # For now we support only "football" and "cricket".
            while True:
                raw = input(
                    "Enter sport to focus on ('football' or 'cricket', or 'x' to exit): "
                ).strip().lower()
                if raw in ("x", "exit"):
                    print_success("Exiting. Goodbye!")
                    sys.exit(0)
                if raw in ("football", "soccer"):
                    sport_keywords = [
                    "epl",
                    "premier league",
                    "la liga",
                    "bundesliga",
                    "serie a",
                    "serie b",
                    "ucl",
                    "champions league",
                    "efl",
                    "efl cup",
                    "mls",
                    "football",
                    "soccer",
                    "football league",
                    "football championship",
                    "football cup",
                    "football tournament",
                    "football competition",
                    "football event",
                    "football game",
                    "football match",
                    "football series",
                    "football tournament",
                  
                    "football competition",
                ]
                    break
                if raw == "cricket":
                    sport_keywords = [
                    "cricket",
                    "odi",
                    "t20",
                    "test match",
                    "ipl",
                    "big bash",
                    "international",
                    "world cup",
                    "european championship",
                    "asian championship",
                    "africa championship",
                    "north america championship",
                    "south america championship",
                    "oceania championship",
                    "world championship",
                    "world cup",
                ]
                    break
                print_warning("Invalid sport. Please type 'football' or 'cricket', or 'x' to exit.")
        elif choice == "4":
            etype = None  # all types
        else:
            # Show help and return to main menu
            print_header("Available Commands")
            print(
                """
  scan-markets      Fetch upcoming Polymarket markets and store them in MongoDB.
                    Args: --limit <page size>, --max-batches <num pages>

  process-markets   Run Gemini (1v1/Teams) + EdgeCase + prediction on stored markets.
                    Args: --max <count>, --non-interactive

  interactive       Guided mode: choose type (1v1/Teams/All), optionally scan,
                    then process markets one by one with prompts.
                    Args: --scan-limit, --scan-batches

  show-market       Show saved data for a single market (structured, edge_case,
                    prediction_result).
                    Args: --mongo-id <ObjectId> | --source-id <polymarket id> | --slug <slug>

  place-order       Place a buy order directly via CLOB API.
                    Args: --token-id <id> --amount <usd> [--price <0.00-1.00>] [--order-type <GTC|GTD|FOK|FAK>]
"""
            )
            return

        scan_label = "all types"
        if etype:
            scan_label = f"type {etype}"
            if etype == "teams" and sport_keywords:
                scan_label += " (filtered by selected sport)"

        scan_prompt = (
            f"Start Polymarket market scan now for {scan_label} "
            f"(limit={args.scan_limit}, batches={args.scan_batches})?"
        )
        ans = prompt_yes_no(scan_prompt, default=True, allow_back=False)
        
        if ans is None:
            print_success("Exiting. Goodbye!")
            sys.exit(0)
        elif ans == "y":
            scan_markets(limit=args.scan_limit, max_batches=args.scan_batches)
        else:
            print_info("Skipping scan step (will use already stored markets).")

        process_markets(
            max_count=None,
            # For teams in interactive menu we want a non-interactive,
            # fire‑and‑forget run that auto‑invests and logs to Mongo.
            interactive=not auto_mode,
            event_type=etype,
            sport_keywords=sport_keywords,
        )
    elif args.command == "show-market":
        db = get_db()
        coll = db.markets

        if args.mongo_id:
            try:
                query = {"_id": ObjectId(args.mongo_id)}
            except Exception:
                print("Invalid Mongo ObjectId.")
                sys.exit(1)
        elif args.source_id:
            query = {"source_event_id": args.source_id}
        else:
            query = {"slug": args.slug}

        doc = coll.find_one(query)
        if not doc:
            print("No market found for given identifier.")
            sys.exit(1)

        raw_event = doc.get("raw_event", {}) or {}
        title = doc.get("title") or raw_event.get("title")
        end_date = doc.get("end_date") or raw_event.get("endDate")
        market_type = doc.get("type", "unknown")
        slug = doc.get("slug") or raw_event.get("slug")
        source_event_id = doc.get("source_event_id") or raw_event.get("id")

        # Fetch real-time spreads for this market (your \"odds\" signal)
        current_odds = None
        if source_event_id:
            try:
                print_info("Fetching real-time spreads...")
                # For teams (sports), prefer slug-based CLOB lookup
                if market_type == "teams" and slug:
                    token_ids = get_market_token_ids_for_slug(slug)
                else:
                    token_ids = get_market_token_ids(source_event_id)
                if token_ids:
                    current_odds = get_market_spreads(token_ids)
                    if current_odds:
                        print_success("Real-time spreads fetched successfully")
                    else:
                        print_warning("Could not fetch spreads (market may be inactive or illiquid)")
                else:
                    print_warning("Could not find token IDs for this market")
            except Exception as e:
                print_warning(f"Could not fetch real-time odds: {e}")

        print_header("Saved Market Details")
        print_market_card(
            title=str(title),
            market_type=str(market_type),
            end_date=str(end_date),
            market_id=str(doc["_id"]),
            slug=slug,
            source_event_id=str(source_event_id) if source_event_id else None,
            odds=current_odds,
        )

        structured = doc.get("structured_event")
        if structured:
            print_structured_summary(structured)
        else:
            print_info("No structured_event saved for this market yet.")

        edge_case = doc.get("edge_case")
        if edge_case:
            print_info("Edge case analysis:")
            print(json.dumps(edge_case, indent=2))
        else:
            print_info("No edge case analysis saved for this market.")

        prediction = doc.get("prediction_result")
        if prediction:
            print_info("Prediction result:")
            print(json.dumps(prediction, indent=2))
        else:
            print_info("No prediction result saved for this market.")
    elif args.command == "place-order":
        print_header("Place Order via CLOB API")
        
        # Map order type string to enum
        order_type_map = {
            "GTC": OrderType.GTC,
            "GTD": OrderType.GTD,
            "FOK": OrderType.FOK,
            "FAK": OrderType.FAK,
        }
        order_type = order_type_map.get(args.order_type, OrderType.GTC)
        
        print_info(f"Token ID: {args.token_id}")
        print_info(f"Amount: ${args.amount:.2f}")
        if args.price:
            print_info(f"Price: {args.price:.4f}")
        else:
            print_info("Price: Market price (will be fetched)")
        print_info(f"Order Type: {args.order_type}")
        print()
        
        try:
            print_info("Placing order...")
            response = place_buy_order(
                token_id=args.token_id,
                amount_usd=args.amount,
                price=args.price,
                order_type=order_type,
            )
            
            print_success("Order placed successfully!")
            print_info("Order response:")
            print(json.dumps(response, indent=2))
        except Exception as e:
            print_warning(f"Failed to place order: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()


