# 安装指南（给协作者）

## 方式 −1 — 不装任何东西，浏览器直接用（最快）

打开 **https://huggingface.co/spaces/WeCFU/wecfu**，把图片拖进去就行。

适合临时计数 / 偶尔用一次。单次会话上限 **100 张图 / 400 MB**，1 小时不动会自动清空。
长期使用、大批量、或想要完全离线 → 用下面的本地安装方式。

---

## 方式 0 — 一行 conda install（本地长期使用推荐）

```bash
conda create -n wecfu -c westraingroup -c conda-forge wecfu -y
conda activate wecfu
wecfu serve
```

完成。浏览器会自动开 http://127.0.0.1:8765 。详细用法见 [USAGE.md](USAGE.md)。

### Windows 用户

命令**完全一样**，只是入口不同：

1. 装 [Miniconda for Windows](https://docs.conda.io/projects/miniconda/en/latest/)（一路 Next 即可）。
2. 开始菜单里打开 **「Anaconda Prompt」**（不是 cmd / PowerShell —— 用这个 conda 才在 PATH 上）。
3. 在 Anaconda Prompt 里粘上面那三行，回车。`wecfu serve` 跑起来后浏览器自动打开 http://127.0.0.1:8765 。

> Windows 上推荐用**拖拽**导入图片（把文件或文件夹拖到网页左侧）。「Ingest path」粘路径的方式也能用——v1.0.7 起，当 Windows 不允许创建符号链接时会自动退化成复制，不再报错。

macOS / Linux 用「终端 Terminal」，命令同上。

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

如果发布者从 [GitHub Releases](https://github.com/WeStrainGroup/WeCFU/releases) 给了你一个 `wecfu-<版本>-py3-none-any.whl`（不走 conda channel 时的备选）：

```bash
conda create -n wecfu -c conda-forge python=3.12 opencv numpy scipy scikit-image pillow pandas fastapi uvicorn python-multipart -y
conda activate wecfu
pip install wecfu-*-py3-none-any.whl
wecfu serve
```

## 系统要求

- macOS / Linux / Windows
- Python 3.10+，推荐 3.12
- 约 1.5 GB 磁盘（conda 环境 + 依赖）

## 验证

```bash
wecfu --help        # 看到 batch / serve / web 三个子命令
pytest tests        # 跑一下单元测试，应全部通过（仅 Git 克隆方式有 tests/）
```

## 用法

请看 [USAGE.md](USAGE.md)。
