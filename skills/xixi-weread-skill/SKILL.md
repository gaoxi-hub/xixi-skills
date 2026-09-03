---
name: xixi-weread-skill
version: 1.0.5
display_name: 微信读书笔记库整理
display_name_en: WeRead Notes Vault Organizer
description: 把微信读书的书架和划线笔记整理成本地 HTML 阅读库。提供两条命令：init（引导获取 API Key 并生成「我的书架.html」）、read <书名>（把某本书的章节/热门划线/个人划线/想法整理成「书籍整理/《书名》.html」并接回书架页）。只要用户提到微信读书、weread、我的书架、读书笔记库、划线、想法、书籍整理、阅读进度同步，或者说「同步一下书架」「整理下这本书的笔记」「初始化读书库」「read 某本书」——即使没点名这个 skill，也要用它。用户在 Obsidian 读书笔记库（含 Agent.md / 书籍整理/ / 我的书架.html）里干活时同样优先用它。
description_zh: 把微信读书的书架和划线笔记整理成本地 HTML 阅读库。提供两条命令：init（引导获取 API Key 并生成「我的书架.html」）、read <书名>（把某本书的章节/热门划线/个人划线/想法整理成「书籍整理/《书名》.html」并接回书架页）。只要用户提到微信读书、weread、我的书架、读书笔记库、划线、想法、书籍整理、阅读进度同步，或者说「同步一下书架」「整理下这本书的笔记」「初始化读书库」「read 某本书」——即使没点名这个 skill，也要用它。用户在 Obsidian 读书笔记库（含 Agent.md / 书籍整理/ / 我的书架.html）里干活时同样优先用它。
description_en: >-
  Turns a WeRead (WeChat Reading) account's bookshelf and highlights into a
  local, browsable HTML reading vault. Offers two commands - init (walks the
  user through obtaining an API key and generates 我的书架.html, the shelf
  page) and read followed by a book title (compiles a single book's chapters,
  popular and personal highlights, and thoughts into a page under
  书籍整理/ and re-links it from the shelf page). Should be used whenever the
  user mentions WeRead or 微信读书, their bookshelf, a reading notes vault,
  highlights, thoughts, book organizing, or reading-progress syncing, or says
  things like sync my shelf, organize notes for this book, initialize my
  reading vault, or read this book, even without naming this skill
  explicitly. Also takes priority when the user is working inside an
  Obsidian reading-notes vault (one containing Agent.md, 书籍整理/, and
  我的书架.html).
---

# xixi-weread-skill

把微信读书账号里的数据落成一个本地可浏览的读书库。两条命令覆盖全部固定流程：

| 命令 | 做什么 | 产出 |
|------|--------|------|
| `init` | 先搭好笔记库目录 + 骨架书架页（不需要 Key），再让用户选「现在同步」还是「稍后同步」 | `我的书架.html` |
| `read <书名>` | 整理单本书的章节、划线、想法、个人笔记 | `书籍整理/《书名》.html`（并重新生成书架页） |

脚本在 `scripts/`，模板在 `assets/`。零第三方依赖，只要 python3 —— 这台机器的系统 python 是
externally-managed，`pip install` 会失败，所以别给这个 skill 引依赖，标准库够用。

**下面所有命令里的 `$SK` 都指这个 skill 的 `scripts/` 目录，路径因安装方式而不同**：
装在 Kiro 里通常是 `~/.kiro/skills/xixi-weread-skill/scripts`；如果是直接 clone 到别处、
或者用别的 agent/runtime 跑，就是那个仓库对应的 `scripts/` 目录。不要把 Kiro 的默认路径
当成唯一路径抄进命令里 —— 先确认这份 SKILL.md 自己所在的仓库根在哪，`$SK` 就是
`<仓库根>/scripts`。

```bash
SK=<这份 SKILL.md 所在仓库根>/scripts
python3 $SK/init_shelf.py --check          # 探测密钥和库位置，不写文件
python3 $SK/init_shelf.py                  # 建目录 + 生成骨架页；首次运行会停下来问要不要现在同步
python3 $SK/init_shelf.py --sync           # 建目录 + 立即同步真实书架数据
python3 $SK/init_shelf.py --later          # 建目录 + 明确选择稍后同步
python3 $SK/build_book.py 纳瓦尔            # 整理单本
```

## 退出码就是交互协议

脚本跑在非交互环境里，需要用户参与的地方一律用退出码表达。**别把它们当崩溃**，
每个码对应一个明确的下一步动作：

| 码 | 含义 | 你该做什么 |
|----|------|-----------|
| 3 | 没有可用的 API Key | 把脚本打印的引导转达给用户，拿到 Key 后用 `--api-key` 重跑 |
| 4 | 关键词命中多本书 | 把脚本列出的候选给用户选，再用 `--pick N` 重跑 |
| 5 | 书架里没有这本书 | 建议换关键词，或加 `--refresh` 重拉书架 |
| 6 | 骨架已生成，等着用户选「现在同步」还是「稍后同步」 | 把 `CHOICE_PROMPT` 转达给用户，按选择带 `--sync` 或 `--later` 重跑 |

退出码 4 尤其别自己拍板。同系列书选错会生成一份内容对不上的页面，而它看起来是成功的
（文件在、样式对、有内容），用户不一定当场发现。宁可多问一句。

退出码 6 同理，**不要替用户默认选「现在同步」**。同步要一两分钟还要 API Key，
用户可能只是想先看看目录长什么样，或者手头没有 Key 想先整理笔记。把两个选项原样转达，
等用户明确说了再带对应参数重跑。

## init

```bash
cd <笔记库目录>
python3 $SK/init_shelf.py
```

`init` 分两步，中间有一个必须让用户参与的决策点：

**第一步：搭架子。** 不需要 API Key，不发任何网络请求。在当前目录（或 `--vault` 指定的目录）
按 `Agent.md` 规范建出 `个人笔记/` `书籍整理/` `.weread-cache/`，并生成一个空的骨架版
`我的书架.html`——打开能看到目录已经就位，但书架卡片是空的，页面上有一条「还没同步」的提示。

**新建库不需要额外参数。** `init` 的语义是「把这个目录变成笔记库」，所以在一个空目录里
直接跑就行。只有当你想操作的库不是当前目录时才需要 `--vault <路径>`。

**第二步：决策点。** 架子搭好后，如果这个库从没同步过、且没带 `--sync`/`--later`/`--api-key`，
脚本会打印「现在同步 / 稍后同步」两个选项然后以退出码 6 停下。**把这个决策转达给用户，
不要自己拍板**：

- 用户想现在看真实数据 → `python3 $SK/init_shelf.py --sync`（如果还没有 Key，会走密钥引导）
- 用户想先整理笔记，晚点再同步 → `python3 $SK/init_shelf.py --later`

已经同步过的库，`init`（不带参数）等价于刷新重渲染；`--later` 在已同步的库上表示
「这次不刷新，用现有缓存重渲染」；`--sync` 表示「重新拉一次」。

**退出码 3** → 同步阶段需要 Key 但没有。把脚本打印的引导原样转达，核心是三步：

1. 浏览器打开 <https://weread.qq.com/r/weread-skills>
2. 微信扫码登录，在「快速配置 → 2 获取 API Key」处复制那串 `wrk-` 开头的字符
3. 让用户粘贴回对话

拿到后 `python3 $SK/init_shelf.py --api-key wrk-xxxxxxxx`（等价于带 `--sync`）。脚本会先发一次
`/shelf/sync` 确认 Key 真能用，再存到 `~/.config/weread/api_key`（权限 600），然后同步并生成书架页。

**密钥等同账号凭证：不要写进任何会被提交的文件，也不要在回复里回显完整值**，
提到时说「已保存的 API Key」就够了。解析顺序是
`环境变量 WEREAD_API_KEY` → `~/.config/weread/api_key` → 用户的 shell rc（`~/.zshrc` 等）。
读 shell rc 是因为 agent 起的子进程一般不 source 它，但很多人的 key 就 export 在那儿。

同步跑完会打一行自检：

```
书架条目 137 = 书 136 + 专辑 0 + 文章收藏 1
已读完 33 | 在读 55 | 翻过 34 | 未读 15  合计 137  ✓
```

四格互斥、合计必须等于条目数。看到 `✗` 说明口径算错了，别把页面当成功交付。

**这些数字不要自己另算一遍。** 里面有两个反直觉的地方：专辑和「文章收藏」也占书架格子；
「读完」认 `finishReading` 而不是 `progress == 100`（用户会在没读满时手动标记读完，
这个账号里差 10 本）。绕过脚本自己统计，八成会得出一组对不上的数。细节见
`references/api-cheatsheet.md`。

其他参数：`--no-refresh` 复用缓存只重渲染页面（改完模板或手动重命名整理页后用它，几秒就好）。

## read <书名>

```bash
cd <笔记库目录>
python3 $SK/build_book.py 纳瓦尔
```

关键词模糊匹配书架，书名完全一致时自动选中。书架数据默认走 `<库>/.weread-cache/`，
所以连续整理多本很快；书架有变动（新买、新读）时加 `--refresh`。

整理完脚本会自动重新生成 `我的书架.html`。这一步不能省：书架卡片上的「📝 笔记」入口是靠扫
`书籍整理/` 目录、用书名精确匹配回填的，不重新生成就挂不上。

个人笔记 md 会被嵌进页面。支持的 markdown 子集（标题、表格、折叠块、列表）见
`references/vault-layout.md`，那张表是权威的 —— 如果用户笔记里的某种写法没渲染出来，
先查表确认是不是真不支持，再决定是补 `render_md` 还是改笔记。

## 交付前的验证

页面是内嵌数据 + JS 渲染的，文件存在说明不了什么。本机装了 Chrome，用无头模式 dump
渲染后的 DOM 来断言真实数字，比读源码或用 Node 打桩靠谱：

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless --disable-gpu --virtual-time-budget=4000 \
  --dump-dom "file://<库>/我的书架.html" > /tmp/shelf.dom
```

至少确认这几条，它们对应用户反复强调过的硬规则：

- 书架卡片的书籍跳转必须是浏览器 `https://weread.qq.com/...`，**`href="weread://"` 出现次数为 0**
- 「📝 笔记」链接指向 `书籍整理/《书名》.html`，数量等于该目录下的整理页数
- 四格状态文案和总条目数都渲染出来了，且和脚本自检的数字一致
- **骨架页**（还没同步，`shelf_data.json` 里 `synced: false`）：`#syncBanner` 可见、
  `#panels`/`#controls` 是 `hidden`，且没有环形图/分类图顶着空数据渲染出一堆 0%——
  骨架页的验收标准是「看起来像『还没同步』」，不是「看起来像『同步了 0 本书』」

书籍页则确认书名、作者、个人笔记板块的小标题都在，笔记正文里没有 `<p>###` 或 `<p>|`
这类 markdown 字面量泄漏，划线深链 `weread://bestbookmark` 有生成（书内定位用 App 协议是对的，
只有书架/详情入口才要求走浏览器）。

数 DOM 里的标签时注意一个坑：`--dump-dom` 的输出同时包含内嵌的 JSON 数据和渲染后的节点，
同一段内容会出现两次。要精确计数就先把 `id="notesbody"` 这类容器切出来再数。
另外 `--headless` 的窗口最小宽约 500px，要测 390px 移动端得先用一个宽 390 的 iframe 套一层
再量 `scrollWidth`。

## 想改样式

改 `assets/book_template.html` 或 `assets/shelf_template.html`，重跑脚本所有页面同步生效。
生成链路统一是「Python 拉数据 → JSON → 替换模板占位符」，占位符是 `/*__BOOK__*/` 和 `/*__DATA__*/`。
不要绕开模板直接手写 HTML，下次重跑就被覆盖了。模板消费的数据结构见
`references/api-cheatsheet.md` 末尾。

笔记正文的样式集中在模板里 `.notes` 那一段。给 `render_md` 加新语法时记得同步加 CSS，
不然新元素会渲染成没样式的裸标签。

## 和官方 weread-skills 的分工

这个 skill **不依赖**官方 `weread-skills` 也能跑：`init` / `read` 的接口调用和数据口径都固化在
`scripts/weread.py` 里。这是刻意的 —— 这两条命令是用户天天用的固定流程，不该因为另一个 skill
没装就失效，也不该每次现场重新推导「书架怎么计数」这种已经收敛过的问题。

但**临时查询要委托出去**：搜书、阅读时长统计、书评、个性化推荐、阅读偏好分析这些是开放式的，
接口多、参数杂，本 skill 不复制那些文档。遇到这类请求：

1. 先看 `~/.workbuddy/skills/weread-skills/references/` 是否存在（`search.md` / `readdata.md` /
   `notes.md` / `review.md` / `discover.md` / `profile.md`），有就读对应那份再调接口；
2. 不存在就让用户装：`npx skills add Tencent/WeChatReading -g`，
   或到 <https://weread.qq.com/r/weread-skills> 按页面指引装。

鉴权和参数平铺规则跟本 skill 一致，可以直接复用 `weread.py` 的 `api()`，不用另写客户端：

```bash
python3 -c "
import sys; sys.path.insert(0, '$SK')
import weread as W, json
print(json.dumps(W.api('/store/search', keyword='三体', count=5), ensure_ascii=False)[:800])
"
```

`skill_version` 默认 `1.0.5`，用 `WEREAD_SKILL_VERSION` 覆盖。**不要去抄官方 SKILL.md 的
version 字段**，那里写的是 1.0.3，比实际可用版本旧，照抄等于降级。回包出现 `upgrade_info` 时
`api()` 会打印告警，看到就提示用户升级官方 skill，再用新版本号重跑。

## 深入

- `references/api-cheatsheet.md` — 接口、参数，以及那些反直觉的字段口径（**改脚本前先读**）
- `references/vault-layout.md` — 目录规范、书架页硬规则、个人笔记 md 支持的语法表
