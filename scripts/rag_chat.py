#!/usr/bin/env python
"""
rag_chat.py — Interactive CLI for the NetGraphX RAG pipeline.

Usage:
    python rag_chat.py                  # full mode (with embedder)
    python rag_chat.py --no-embed       # skip embedder load (faster startup)
    python rag_chat.py --verbose        # print intermediate steps
    python rag_chat.py --query "..."    # single query and exit

Example queries:
    "Mạng có thiết bị SPOF nào không?"
    "Cho tôi biết thông tin SW-CORE-FT-01"
    "Có lỗi VLAN mismatch ở đâu không?"
    "SW-AGG-POD0-NODE1 có vấn đề gì không và mạng có vòng lặp nào không?"
"""

import argparse
import io
import sys

# Force UTF-8 output so Vietnamese characters render correctly on Windows terminals
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from src.rag.pipeline import RAGPipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NetGraphX RAG Chat — Vietnamese network intelligence assistant"
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip loading the sentence-transformer embedder (faster startup, no vector search)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print intermediate pipeline steps (parsed intents, retrieval context)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Run a single query and exit (non-interactive mode)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("   NetGraphX RAG Assistant — Viettel Labs")
    print("   Trợ lý phân tích mạng thông minh")
    print("=" * 60)

    load_embedder = not args.no_embed
    try:
        with RAGPipeline(load_embedder=load_embedder) as pipeline:

            # Non-interactive single-query mode
            if args.query:
                print(f"\n❓ Câu hỏi: {args.query}\n")
                answer = pipeline.query(args.query, verbose=args.verbose)
                print("💬 Trả lời:")
                print(answer)
                return

            # Interactive REPL loop
            print("\nGõ câu hỏi của bạn (tiếng Việt hoặc tiếng Anh).")
            print("Gõ 'exit' hoặc 'quit' để thoát.\n")

            while True:
                try:
                    user_input = input("❓ Câu hỏi: ").strip()
                except (KeyboardInterrupt, EOFError):
                    print("\n[Thoát]")
                    break

                if not user_input:
                    continue
                if user_input.lower() in {"exit", "quit", "thoát", "q"}:
                    print("👋 Tạm biệt!")
                    break

                print()
                answer = pipeline.query(user_input, verbose=args.verbose)
                print("💬 Trả lời:")
                print(answer)
                print()

    except ValueError as exc:
        print(f"\n❌ Lỗi cấu hình: {exc}")
        print("Hãy kiểm tra file .env và đảm bảo GEMINI_API_KEY đã được thiết lập.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌ Lỗi khởi động pipeline: {exc}")
        raise


if __name__ == "__main__":
    main()
