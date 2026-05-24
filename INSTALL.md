# 安装指南（给协作者）

## 方式 A — 从 Git 仓库克隆（最常用）

```bash
git clone https://github.com/<你的用户名>/cfu-counter.git
cd cfu-counter

# 一次性建环境（约 3–5 分钟）
conda env create -f environment.yml
conda activate cfu-counter

# 安装本工具
pip install -e .

# 启动 GUI（自动开浏览器到 http://127.0.0.1:8765）
cfu-counter serve
```

## 方式 B — 从预编译的 wheel 安装（最快）

如果发布者提供了 `dist/cfu_counter-0.1.0-py3-none-any.whl`：

```bash
# 创建一个干净的 conda env，只装运行依赖
conda create -n cfu-counter -c conda-forge python=3.12 opencv numpy scipy scikit-image pillow pandas -y
conda activate cfu-counter

# 安装 wheel
pip install cfu_counter-0.1.0-py3-none-any.whl

cfu-counter serve
```

## 系统要求

- macOS / Linux（Windows 应该也行但未测）
- Python 3.10+，推荐 3.12
- 约 1.5 GB 磁盘（conda 环境 + 依赖）

## 可选：装 SAM 兜底（处理密集板）

只有当用户点 GUI 里的 **SAM** 按钮时才需要。**普通使用不必装**。

```bash
pip install segment-anything torch
mkdir -p ~/.cache/cfu-counter
curl -L https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth \
  -o ~/.cache/cfu-counter/sam_vit_b.pth
```

下载 ~358 MB 权重 + ~2 GB torch。

## 验证

```bash
cfu-counter --help        # 看到 batch / serve / sam 三个子命令
pytest tests              # 跑一下单元测试，应全部通过
```

## 用法

请看 [USAGE.md](USAGE.md)。
