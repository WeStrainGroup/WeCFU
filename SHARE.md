# 把 WeCFU 同步给协作者

## ✅ 已发布：Hugging Face Space（最简单，浏览器直接用）

**https://huggingface.co/spaces/WeCFU/wecfu**

发给协作者一行话即可：

> WeCFU 网页版上线了，浏览器打开直接用，无需安装：
> https://huggingface.co/spaces/WeCFU/wecfu
> 把图片拖进去就行。每次会话上限 50 张 / 200 MB，1 小时不动会自动清空。
> 想要无限制、本地长期用 → 见 INSTALL.md 的 conda 方式。

下次发新版本同步到 Space：
```bash
cd ~/claude_code_workspace/WeF/WeCFU
# 改完代码并 git commit 到 main 后：
git checkout hf-deploy
git merge main -X theirs    # 把 main 最新代码合进 hf-deploy；冲突用 main 的
cp README_HF.md README.md   # 保持 frontmatter
git add README.md && git commit -q -m "sync from main"
git push hf hf-deploy:main
git checkout main
```

---

## ✅ 已发布：WeStrainGroup anaconda channel

`wecfu` 0.1.0 已 push 到 https://anaconda.org/WeStrainGroup/wecfu 。
**协作者一行 conda install 即可：**

```bash
conda create -n wecfu -c westraingroup -c conda-forge wecfu -y
conda activate wecfu
wecfu serve
```

发给协作者的话术（直接复制粘贴）：

> WeCFU 已发到我们组的 conda channel。装上 conda 后跑这一行就能用：
> ```bash
> conda create -n wecfu -c westraingroup -c conda-forge wecfu -y && conda activate wecfu && wecfu serve
> ```
> 浏览器会自动开 http://127.0.0.1:8765 。用法看仓库里的 USAGE.md。

下次发新版本，本地：

```bash
cd ~/claude_code_workspace/WeF/WeCFU
# 改完代码、commit
# 把 meta.yaml 里 version 从 0.1.0 → 0.1.1
conda build . -c conda-forge --no-anaconda-upload
anaconda login --username westraingroup    # 密码：见你保存的笔记
anaconda upload ~/miniconda3/conda-bld/noarch/wecfu-0.1.1-py_0.conda
```

---

## 备选：其它分发渠道

按"协作者麻烦程度从低到高"列出 3 条备选路。

---

## 路 A：通过 GitHub 仓库分发（适合愿意改代码的协作者）

**优点**：协作者一句 `git clone` 拿全套；你以后改了代码 `git push` 一键同步；自带版本号。
**缺点**：需要你先把仓库推上 GitHub（10 分钟）。

### 你要做的：

跟着 `GITHUB_SETUP.md` 走三步，把本地仓库推上去。结束后再做一件事——发个 release，把预编译的 wheel 挂上去：

```bash
cd ~/claude_code_workspace/WeF/WeCFU
gh release create v0.1.0 \
  dist/wecfu-0.1.0-py3-none-any.whl \
  dist/wecfu-0.1.0.tar.gz \
  --title "WeCFU v0.1.0 — first internal release" \
  --notes "First internal test release for the WeF culturomics team. See USAGE.md."
```

### 给协作者的一段话（直接发给他们）：

> WeCFU 已发布，地址：https://github.com/你的用户名/WeCFU
>
> 安装：
> ```bash
> git clone https://github.com/你的用户名/WeCFU.git
> cd WeCFU
> conda env create -f environment.yml
> conda activate wecfu
> pip install -e .
> wecfu serve
> ```
> 详细用法看 USAGE.md。

仓库公开还是私有都行：
- 公开：直接发链接就能用
- 私有：协作者得登录 GitHub，且你要在 Settings → Collaborators 里加他

---

## 路 B：直接传文件（最快，不依赖 GitHub）

**优点**：5 分钟搞定；协作者完全不用碰 git。
**缺点**：你以后改了代码得重新打包发一次。

### 你要做的：

打一个分发包（zip）：

```bash
cd ~/claude_code_workspace/WeF/WeCFU
mkdir -p /tmp/WeCFU-v0.1.0
cp dist/wecfu-0.1.0-py3-none-any.whl  /tmp/WeCFU-v0.1.0/
cp environment.yml USAGE.md INSTALL.md README.md LICENSE  /tmp/WeCFU-v0.1.0/
( cd /tmp && zip -r WeCFU-v0.1.0.zip WeCFU-v0.1.0 )
ls -lh /tmp/WeCFU-v0.1.0.zip
```

得到一个 ~50 KB 的 zip。通过微信 / 邮件 / 网盘发给协作者。

### 给协作者的一段话：

> 收到 WeCFU-v0.1.0.zip 后，解压并执行：
> ```bash
> cd WeCFU-v0.1.0
> conda env create -f environment.yml
> conda activate wecfu
> pip install wecfu-0.1.0-py3-none-any.whl
> wecfu serve
> ```
> 浏览器会自动开 http://127.0.0.1:8765。
> 用法看 USAGE.md。

---

## 路 C：真正的 conda 包 + Anaconda 私有 channel（最重，团队大才值得）

**优点**：协作者一行 `conda install` 就齐了，不用 pip。
**缺点**：要写 `meta.yaml`、注册 anaconda.org、用 `conda-build` 构建。

只有协作者超过 5 人 + 长期维护时才推荐做。**当前阶段不建议走这条**——投资回报不划算。

骨架（如果将来真要做）：

```bash
conda install -n base conda-build anaconda-client -c conda-forge
mkdir conda-recipe && cat > conda-recipe/meta.yaml <<'EOF'
{% set version = "0.1.0" %}
package:
  name: wecfu
  version: {{ version }}
source:
  path: ..
build:
  script: "{{ PYTHON }} -m pip install . -vv"
  noarch: python
  entry_points:
    - wecfu = wecfu.cli:main
requirements:
  host:
    - python >=3.10
    - pip
    - setuptools
  run:
    - python >=3.10
    - numpy
    - scipy
    - scikit-image
    - opencv
    - pillow
    - pandas
    - fastapi
    - uvicorn
    - python-multipart
about:
  license: MIT
  summary: "WeCFU — hybrid OpenCV + SAM CFU counter for culturomics plate photos"
EOF
conda build conda-recipe -c conda-forge
# 上传到你自己的 anaconda.org channel
anaconda upload /path/from/conda-build/output.tar.bz2
```

协作者：
```bash
conda install -c 你的用户名 wecfu
```

---

## 我的建议

**先走路 B**（直传 zip），下午就能让协作者跑起来。
**等真的稳定下来**（一两周后），再走路 A 上 GitHub 做正式版本管理。
**路 C 暂时跳过。**

---

## 协作者那边的常见坑

- **`zsh: command not found: wecfu`**
  → 没 `conda activate wecfu`，先激活环境。

- **`opencv` 装失败**
  → 用 conda 装的（`environment.yml` 里的 `opencv` 走 conda-forge），不要用 pip 装 `opencv-python`，跨平台 wheel 偶尔翻车。

- **macOS 弹"无法打开来自身份不明的开发者"**
  → 这个工具是 Python 包不是 .app，不会弹。如果弹了说明协作者装错东西了。

- **Windows 用户**
  → 当前未测。让他们装 WSL2 + Ubuntu，照 Linux 路子来；或者等我们后续测了再说。

- **协作者数完想把结果发回来**
  → 让他们点 GUI 顶部 **「导出打包」** → 得到一个 `cfu_<批次>.zip`，发给你即可。zip 里 `detections/*.json` 完整保存了他们的每一次点击，你拿来可以接着审或合并。
