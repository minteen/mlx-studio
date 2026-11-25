# Research

## Native inference
- Decision: mlx-lm load + stream_generate，make_sampler 控制温度；chat template 用 tokenize=False，避免 token 格式版本差异。
- Rationale: 官方推理库，返回增量文本。
- Alternatives: 外部代理进程增加管理成本；非 MLX 后端不满足用户要求。
- Source: https://github.com/ml-explore/mlx-lm#streaming

## Embeddings
- Decision: mlx_embeddings.load 和 generate(..., texts=[...], max_length=512)，读取 outputs.text_embeds，求值后转换 Python list。
- Rationale: 官方支持量化向量模型；不可将 generate 返回值当裸数组。
- Source: https://github.com/Blaizzy/mlx-embeddings/blob/main/mlx_embeddings/utils.py

## Threading
- Decision: 固定单线程 executor 处理所有 MLX 调用；async queue 桥接 SSE；断连通过 threading.Event 停止；有界队列限制缓冲。
- Rationale: MLX stream 与线程关联；不能直接将同步生成器交给不同 ASGI 线程逐次执行。
- Source: https://ml-explore.github.io/mlx/build/html/python/devices_and_streams.html

## Models and hosting
- Decision: 验证使用 mlx-community/Qwen2.5-0.5B-Instruct-4bit 和 mlx-community/all-MiniLM-L6-v2-4bit。
- Rationale: 小模型降低真实验证成本；组织范围校验、远端代码默认禁用。
- Decision: Mac 原生 launchd 托管，配置由脚本生成，不自动安装；不用 Linux Docker 承诺 Metal 可用。
- Source: https://ml-explore.github.io/mlx/build/html/install.html
