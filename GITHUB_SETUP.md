# 上传到 GitHub（你自己来，全程不需要把账号密码给我）

我已经在本地把代码整理好、初始化了 git 仓库、做了首次提交。
下面三步你跟着做就行。

---

## 第 1 步：在 GitHub 网页上建一个空仓库

1. 浏览器打开 https://github.com/new
2. **Owner**：选你自己（或者你想放的组织）
3. **Repository name**：建议填 `cfu-counter`
4. **Description**（可选）：`Hybrid OpenCV + SAM colony counter with a local web GUI for culturomics plate photos.`
5. **Visibility**：
   - 想让协作者公开看到 → **Public**
   - 只在小组里分享 → **Private**（之后到 Settings → Collaborators 里加人）
6. **⚠️ 重要：下面这些都不要勾**
   - ❌ Add a README file
   - ❌ Add .gitignore
   - ❌ Choose a license

   （这些我们本地已经有了，建空仓不会冲突）

7. 点 **Create repository**

建好后页面会显示一串命令，复制其中的仓库地址（形如 `https://github.com/你的用户名/cfu-counter.git` 或 `git@github.com:你的用户名/cfu-counter.git`）。

---

## 第 2 步：在 macOS 配 GitHub 认证（只配一次）

**推荐用 GitHub CLI**（最简单，不用管 token / SSH key）：

```bash
brew install gh
gh auth login
# 按提示选 GitHub.com → HTTPS → 浏览器登录授权
```

授权后，git 就会自动用你的 GitHub 账号 push，不需要再手动输密码。

> 如果你不想装 gh，也可以走 SSH key 路径。这里就不展开了，gh 最省事。

---

## 第 3 步：把本地仓库推上去

在终端里：

```bash
cd ~/claude_code_workspace/WeF/cfu-counter

# 把仓库地址换成你刚才在第 1 步看到的那个
git remote add origin https://github.com/你的用户名/cfu-counter.git

# 第一次推：把本地 main 分支推上去并设为默认上游
git push -u origin main
```

如果输出里看到 `Branch 'main' set up to track 'origin/main'`，就完成了。
浏览器刷新 GitHub 仓库页，你会看到所有文件已经在。

---

## 之后改了代码怎么推

```bash
cd ~/claude_code_workspace/WeF/cfu-counter
git add -A
git commit -m "改了什么的简短说明"
git push
```

---

## 给协作者：怎么用

让协作者去看你 GitHub 仓库的 `INSTALL.md`。基本就是：

```bash
git clone https://github.com/你的用户名/cfu-counter.git
cd cfu-counter
conda env create -f environment.yml
conda activate cfu-counter
pip install -e .
cfu-counter serve
```

---

## 关于 release 和 wheel 分发（可选）

如果想让协作者**不用 clone 仓库**也能装：

```bash
# 在本地已经构建好的 wheel 路径：
ls dist/
# cfu_counter-0.1.0-py3-none-any.whl
# cfu_counter-0.1.0.tar.gz

# 用 gh 创建一个 release 并附上 wheel
gh release create v0.1.0 dist/cfu_counter-0.1.0-py3-none-any.whl dist/cfu_counter-0.1.0.tar.gz \
    --title "v0.1.0 — first internal release" \
    --notes "Internal test release for the WeF culturomics team. See USAGE.md."
```

发布完，协作者就能直接：

```bash
pip install https://github.com/你的用户名/cfu-counter/releases/download/v0.1.0/cfu_counter-0.1.0-py3-none-any.whl
```

---

## 常见错误

- **`fatal: remote origin already exists`**
  → 你之前已经加过 origin。删掉重加：`git remote remove origin` 再来一次。

- **`Permission denied`**
  → gh 还没登录或登录过期。重跑 `gh auth login`。

- **push 时提示 "you need to fetch first"**
  → 仓库不是全新的（GitHub 网页建仓时勾了 README/.gitignore/license）。先 `git pull origin main --allow-unrelated-histories`，处理一下冲突，再 `git push`。最稳妥还是按第 1 步全部不勾，让仓库完全为空。

---

有问题再问我，把报错原文贴过来即可。
