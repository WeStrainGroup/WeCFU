# 分发 WeCFU 给协作者

三个渠道都已上线。给协作者只需发链接；给维护者（你）下面也有发新版的完整流程。

---

## 给协作者：三种用法

### 1. 网页版（最简单，零安装）

**https://huggingface.co/spaces/WeCFU/wecfu**

> WeCFU 网页版，浏览器打开直接用，无需安装：
> https://huggingface.co/spaces/WeCFU/wecfu
> 把图片拖进去就行。每次会话上限 100 张 / 400 MB，1 小时不动会自动清空。
> 想要无限制、本地长期用 → 用下面的 conda 方式。

### 2. 本地 conda

**https://anaconda.org/WeStrainGroup/wecfu**

> 装上 conda（Windows 用 Anaconda Prompt）后两行搞定：
> ```bash
> conda install westraingroup::wecfu
> wecfu serve
> ```
> 浏览器自动开 http://127.0.0.1:8765 。详细用法看仓库 USAGE.md。

### 3. GitHub 源码

**https://github.com/WeStrainGroup/WeCFU**

> ```bash
> git clone https://github.com/WeStrainGroup/WeCFU.git
> cd WeCFU
> conda env create -f environment.yml
> conda activate wecfu
> pip install -e .
> wecfu serve
> ```

---

## 给维护者：发一个新版本

每次改完代码，按这套流程把版本同步到全部三处。把 `<版本>` 换成新版本号（例如 `1.0.8`）。

### 第 0 步：改版本号 + 提交

```bash
cd ~/claude_code_workspace/WeF/WeCFU
# 三个文件的 version 一起改成 <版本>：
#   wecfu/__init__.py   pyproject.toml   meta.yaml
git add -A && git commit -m "v<版本>: 改了什么的简短说明"
```

### 第 1 步：GitHub（main + release）

```bash
python -m build                       # 产出 dist/wecfu-<版本>-py3-none-any.whl + .tar.gz
git push github main
gh release create v<版本> dist/wecfu-<版本>-py3-none-any.whl dist/wecfu-<版本>.tar.gz \
    --title "v<版本>" --notes "改了什么"
```

### 第 2 步：conda channel

```bash
conda build . -c conda-forge --no-anaconda-upload
anaconda login --username westraingroup           # 用户名必须小写；密码见你保存的笔记
anaconda upload ~/miniconda3/conda-bld/noarch/wecfu-<版本>-py_0.conda
anaconda logout
```

### 第 3 步：Hugging Face Space

HF 的 pre-receive hook 会扫整段 git 历史并拒绝大二进制文件，所以 **hf-deploy 分支不能含 `hardware/`**（里面有实拍大图）。用这套"从 hf 当前状态重建"的流程，绕过历史污染：

```bash
git fetch hf
git checkout hf-deploy
git reset --hard hf/main
# 把 main 的最新内容覆盖进来，但排除 hardware/
git checkout main -- $(git ls-tree -r --name-only main | grep -v '^hardware/')
cp README_HF.md README.md             # HF 需要带 frontmatter 的 README
git add -A && git commit -m "v<版本> (hf-deploy)"
git push hf hf-deploy:main
git checkout main
```

HF 自动重新构建，约 2–3 分钟。

> 纯文档改动（只动仓库根的 .md，不动 `wecfu/` 代码）可以跳过第 2 步——conda 包里不含这些文件，版本号也不必动。

---

## 协作者那边的常见坑

- **`command not found: wecfu`** → 忘了 `conda activate wecfu`。
- **`opencv` 装失败** → 用 conda 装（`environment.yml` 里的 `opencv` 走 conda-forge），别用 pip 的 `opencv-python`。
- **Windows** → 已支持。在「Anaconda Prompt」里跑（不是 cmd / PowerShell）。导入图片用拖拽最稳。
- **macOS 弹"身份不明的开发者"** → 这是 Python 包不是 .app，不会弹；弹了说明装错东西。
- **协作者想把结果发回来** → 让他点顶部 **「Export bundle」** 得到 zip（CSV + 标注图 + 每张图 JSON 状态档），发给你即可，你能接着审或合并。
