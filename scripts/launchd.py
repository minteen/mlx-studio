"""Generate (but do not register) a macOS LaunchAgent."""

import argparse
import os
import plistlib
from pathlib import Path

parser = argparse.ArgumentParser(description="生成 MLX Studio launchd 配置，不自动安装")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=1234)
parser.add_argument("--output", type=Path, default=Path("dist/com.local.mlx-studio.plist"))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
executable = root / ".venv/bin/mlx-studio"
if not executable.exists():
    parser.error("请先在仓库运行 uv sync")
if args.host not in ("127.0.0.1", "localhost", "::1") and not os.getenv("MLX_STUDIO_API_KEY"):
    parser.error("非本机监听需先配置 MLX_STUDIO_API_KEY，密钥将写入600权限的配置文件")
logs = root / ".data/logs"
logs.mkdir(parents=True, exist_ok=True)
env = {k: os.environ[k] for k in ("MLX_STUDIO_API_KEY", "HF_ENDPOINT") if k in os.environ}
config = {
    "Label": "com.local.mlx-studio",
    "ProgramArguments": [
        str(executable),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--data-dir",
        str(root / ".data"),
    ],
    "WorkingDirectory": str(root),
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 10,
    "EnvironmentVariables": env,
    "StandardOutPath": str(logs / "stdout.log"),
    "StandardErrorPath": str(logs / "stderr.log"),
}
args.output.parent.mkdir(parents=True, exist_ok=True)
fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "wb") as stream:
    os.fchmod(stream.fileno(), 0o600)
    plistlib.dump(config, stream)
print(f"配置已生成：{args.output.resolve()}")
print("安装与启停命令见 README.md。")
