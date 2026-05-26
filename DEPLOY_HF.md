# 部署到 Hugging Face Spaces（你自己来，不用把账号密码给我）

部署完成后，任何人浏览器打开
`https://huggingface.co/spaces/<你的用户名>/wecfu`
就能直接使用 WeCFU，无需安装 conda。

预计时间：**15 分钟**（含 HF 注册账号；如果已有账号，5 分钟）。

---

## 第 1 步：注册 / 登录 Hugging Face

打开 https://huggingface.co/join 注册（用学校邮箱也行）。如果你想用组的账号
（推荐发表论文用），可以建一个 Organization：
https://huggingface.co/organizations/new ，名字建议填 `WeStrainGroup` 保持
和 anaconda 一致。

---

## 第 2 步：新建一个 Space

1. 打开 https://huggingface.co/new-space
2. **Owner**：你自己 或 WeStrainGroup
3. **Space name**：`wecfu`（小写）
4. **License**：`mit`
5. **Select the Space SDK**：选 **Docker**，然后下面的"Choose a Docker template"选 **Blank**
6. **Hardware**：保持默认 **CPU basic - 2 vCPU / 16 GB RAM / Free**
7. **Visibility**：Public（也可以选 Private，但 Private 别人就要登录 HF 才能看）
8. 点 **Create Space**

页面会跳到一个空 Space 的 README 编辑界面，**先别动 README**，跳到第 3 步。

---

## 第 3 步：在 macOS 配 HF 认证（只配一次）

```bash
pip install --user huggingface_hub
huggingface-cli login
```

会让你贴一个 token：
1. 浏览器打开 https://huggingface.co/settings/tokens
2. 点 **Create new token** → 类型选 **Write**
3. Name 随便填（比如 `wecfu-deploy`），保存
4. 复制 token，粘到终端

看到 `Login successful` 就完成了。

---

## 第 4 步：把代码推到 Space

新空 Space 本质上是个 git 仓库。把本地 WeCFU 推过去：

```bash
cd ~/claude_code_workspace/WeF/WeCFU

# 把上一步建好的 Space 加成第二个远端（与 GitHub 的 origin 不冲突）
git remote add hf https://huggingface.co/spaces/<你的用户名>/wecfu

# HF Spaces 的 README 需要带特殊 frontmatter。
# 把仓库里准备好的 README_HF.md 作为 Space 的 README:
cp README_HF.md /tmp/wecfu-hf-README.md
git add Dockerfile .dockerignore README_HF.md
git commit -m "Add HF Spaces deployment files (Dockerfile + frontmatter README)"

# 推到 HF。HF 会立即开始构建 Docker 镜像。
git push hf main
```

如果 push 时 HF 要求认证，会自动用你 `huggingface-cli login` 时存的 token，不会再问。

---

## 第 5 步：把 README 替换成带 frontmatter 的版本

HF 用仓库根目录的 `README.md` 当 Space 的 metadata。我们仓库的 README.md
没有 frontmatter，HF 会用默认的 UI。**只在 HF 那边推一个特殊 README**：

最干净的做法是为 HF 单独建一个分支：

```bash
# 把 README_HF.md 复制成 README.md，但只在 hf 远端的 main 上做这个修改
git checkout -b hf-deploy
cp README_HF.md README.md
git add README.md
git commit -m "HF: use README_HF as Space README"
git push hf hf-deploy:main --force

# 回到 main 分支继续开发
git checkout main
```

这样 GitHub 上 main 分支保持原 README，HF Space 上则有 frontmatter 控制图标、
颜色、端口等。

> **简化版**（不分支）：直接把 `README_HF.md` 重命名成 `README.md`
> 推上 HF，但你 GitHub 那边原 README 就被覆盖了。除非你不在乎，否则用分支方案。

---

## 第 6 步：等 Docker 构建

回到浏览器，打开你的 Space 页面（顶部 **Building** 标签）。HF 会显示构建日志，
首次约 **3–5 分钟**。看到 **Running** 状态变绿后，点 **App** 标签就是 WeCFU 主界面。

URL 直接发给协作者：
```
https://huggingface.co/spaces/<你的用户名>/wecfu
```
他们不需要登录、不需要装任何东西。

---

## 升级到新版本

以后改了代码：

```bash
cd ~/claude_code_workspace/WeF/WeCFU
# 改完代码，commit
git push hf main             # 或者 git push hf hf-deploy:main --force
```

HF 自动重新构建并部署，约 2–3 分钟。

---

## 常见问题

**Q：构建失败怎么办？**
A：HF 的 Logs 标签会显示完整 Docker build log。最常见原因：
- `pip install` 因为网络超时 → 重新 push 触发构建即可
- 缺系统库 → 编辑 Dockerfile 加 `apt-get install ...`

**Q：Space 一段时间不用会被休眠吗？**
A：免费 CPU Space 默认**不会休眠**，但如果 48 小时无访问会进 sleep。访问就会重启，
约 30 秒冷启动。

**Q：协作者上传时报"Per-session limit is 50 images"？**
A：每个会话最多 50 张、200 MB。让他分批上传，或者每次跑完导出 zip 后让他刷新页面（清空 session）。

**Q：我想把限制改大？**
A：编辑 `wecfu/server/app.py` 顶部的 `WEB_MAX_BYTES` / `WEB_MAX_IMAGES`，再 push。
但 HF 免费层只有 16 GB 临时存储，所以总上限其实是被这个硬限制住的。

**Q：会泄漏数据吗？**
A：每个访问者通过浏览器 cookie 隔离，互相看不到对方的图片或结果。
1 小时无活动后，session 目录被自动 `rm -rf`。
Space 重启时所有 sessions 也会清空（在 `/tmp/`）。
**不会**写入任何持久化数据库。

**Q：URL 太长，能用自定义域名吗？**
A：HF 免费 Space 不支持自定义域名。如果你有自己的服务器，可以反向代理过去。

---

发给协作者用的话术：

> WeCFU 网页版上线了，浏览器打开就能用：
>
> https://huggingface.co/spaces/&lt;你的用户名&gt;/wecfu
>
> 把图片拖进去就行。每次会话上限 50 张图 / 200 MB，1 小时不动会自动清空。
> 详细操作打开右上 Help 按钮。

