# Implementation Plan: MLX Studio
**Branch**: 无 Git | **Date**: 2026-11-24 | **Spec**: [spec.md](spec.md)

## Summary
单进程 FastAPI 同时托管中文静态控制台与 OpenAI 兼容 API。Hugging Face 下载 mlx-community 模型，mlx-lm / mlx-embeddings 原生推理，macOS launchd 部署。

## Technical Context
**Language/Version**: Python >=3.11，浏览器原生 JavaScript/CSS
**Primary Dependencies**: FastAPI、Uvicorn、huggingface-hub、mlx-lm、mlx-embeddings
**Storage**: 本地 JSON 模型清单（原子替换）、模型目录；浏览器 localStorage 会话
**Testing**: pytest + httpx API 集成；实际小模型 smoke；浏览器交互
**Target Platform**: Apple Silicon macOS >=14，原生 ARM Python
**Project Type**: 本机 Web 应用和推理服务
**Performance Goals**: 管理请求不被推理阻塞；生成逐 token 显示
**Constraints**: 单进程/单 worker；所有 MLX 工作在固定线程内，队列桥接流输出；默认 loopback
**Scale/Scope**: 单操作员，最多一个 chat 和一个 embedding 驻留；模型操作串行

## Constitution Check
现有 constitution.md 是未填模板，不构成实质约束。设计前后通过：优先本地推理、真实错误、输入验证、默认本机访问，不引入无需求的基础设施。

## Project Structure
```text
mlx_studio/
  app.py          # REST、鉴权、SSE、静态资源
  runtime.py      # 固定线程模型运行器
  catalog.py      # 模型校验、下载、本地清单
  cli.py          # 参数、启动验证
  static/         # index.html、app.js、style.css
scripts/launchd.py
 tests/test_api.py
pyproject.toml
README.md
```
**Structure Decision**: 原生静态前端避免额外构建部署，包内静态文件与后端同源。生产启动只允许一个进程，UI 运行时启停的是推理访问开关，HTTP 控制台保持运行。
