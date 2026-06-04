import argparse
import json
from pathlib import Path

from server.llm.openai_provider import OpenAIProvider


def main() -> None:
    parser = argparse.ArgumentParser(prog="symfluence-assistant")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Generate a SYMFLUENCE run plan from a natural-language request")
    run_parser.add_argument("request", type=str, help="Natural-language modeling request")
    run_parser.add_argument("--model", default="gpt-5", help="Model name to use")
    run_parser.add_argument("--api-key", default=None, help="OpenAI API key (optional if OPENAI_API_KEY is set)")
    run_parser.add_argument("--json-out", default=None, help="Optional path to save the generated plan JSON")

    args = parser.parse_args()

    if args.command == "run":
        try:
            provider = OpenAIProvider(api_key=args.api_key)
            plan = provider.generate_run_plan(
                model=args.model,
                user_request=args.request,
            )
            print(json.dumps(plan, indent=2))

            if args.json_out:
                with open(args.json_out, "w", encoding="utf-8") as f:
                    json.dump(plan, f, indent=2)
                print(f"Saved plan to: {args.json_out}")
                
        except Exception as e:
            print(f"Error: {e}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
