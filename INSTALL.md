# 安装指南（给协作者）

## 方式 0 — 一行 conda install（推荐）

```bash
conda create -n wecfu -c westraingroup -c conda-forge wecfu -y
conda activate wecfu
wecfu serve
```

完成。浏览器会自动开 http://127.0.0.1:8765 。详细用法见 [USAGE.md](USAGE.md)。

> 想要 SAM 兜底（处理密集板）？激活环境后再 `pip install segment-anything torch` 并按 USAGE 5.1 节下载权重。

---

## 方式 A — 从 Git 仓库克隆（开发 / 想改代码用）

```bash
git clone https://github.com/<你的用户名>/WeCFU.git
cd WeCFU

# 一次性建环境（约 3–5 分钟）
conda env create -f environment.yml
conda activate wecfu

# 以可编辑模式安装本工具
pip install -e .

# 启动 GUI（自动开浏览器到 http://127.0.0.1:8765）
wecfu serve
```

## 方式 B — 从预编译的 wheel 安装

如果发布者提供了 `dist/wecfu-0.1.0-py3-none-any.whl`（不走 conda channel 时的备选）：

```bash
conda create -n wecfu -c conda-forge python=3.12 opencv numpy scipy scikit-image pillow pandas fastapi uvicorn -y
conda activate wecfu
pip install wecfu-0.1.0-py3-none-any.whl
wecfu serve
```

## 系统要求

- macOS / Linux（Windows 应该也行但未测）
- Python 3.10+，推荐 3.12
- 约 1.5 GB 磁盘（conda 环境 + 依赖）

## 可选：装 SAM 兜底（处理密集板）

只有当你点 GUI 里的 **SAM** 按钮时才需要。**普通使用不必装**。

```bash
pip install segment-anything torch
mkdir -p ~/.cache/wecfu
curl -L https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth \
  -o ~/.cache/wecfu/sam_vit_b.pth
```

下载 ~358 MB 权重 + ~2 GB torch。

## 验证

```bash
wecfu --help        # 看到 batch / serve / sam 三个子命令
pytest tests        # 跑一下单元测试，应全部通过（仅 Git 克隆方式有 tests/）
```

## 用法

请看 [USAGE.md](USAGE.md)。
