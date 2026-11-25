"""Run the single-process local studio."""

import argparse
import os
import platform
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="MLX Studio · Apple Silicon local AI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1234)
    parser.add_argument("--data-dir", default=os.getenv("MLX_STUDIO_DATA", ".data"))
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1") and not os.getenv("MLX_STUDIO_API_KEY"):
        parser.error("非本机监听必须配置 MLX_STUDIO_API_KEY")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("MLX 推理需要 Apple Silicon macOS 和 ARM Python")
    import uvicorn

    from .app import create_app

    app = create_app(Path(args.data_dir))
    print(f"MLX Studio: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
