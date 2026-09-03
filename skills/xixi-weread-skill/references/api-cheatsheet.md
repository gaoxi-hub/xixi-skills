# 接口速查与口径陷阱

只覆盖 `init` / `read` 用到的接口。搜书、阅读统计、书评、推荐这些不在这里，
去读官方 `~/.workbuddy/skills/weread-skills/references/`。

**改 `scripts/weread.py` 或 `build_book.py` 之前先看「口径陷阱」那节**，
里面每一条都是已经出过问题的地方，不是理论风险。

## 目录

- [调用规范](#调用规范)
- [用到的接口](#用到的接口)
- [口径陷阱](#口径陷阱)
- [深度链接](#深度链接)
- [模板数据结构](#模板数据结构)

## 调用规范

```
POST https://i.weread.qq.com/api/agent/gateway
Authorization: Bearer $WEREAD_API_KEY
Content-Type: application/json
```

Body 里 `api_name`、`skill_version` 和业务参数**平铺在同一层**：

```json
{"api_name": "/book/bookmarklist", "bookId": "44026191", "skill_version": "1.0.5"}
```

包进 `params` 是最常见的错误写法。后端不会报错，而是丢掉被包住的参数按默认值返回，
症状是「分页永远是第一页」，很难查。

`errcode` 非 0 即失败。回包出现 `upgrade_info` 表示服务端要求升级 skill，
应当停下来先升级再重跑。API Key 绑定用户身份（vid），需要身份的接口自动注入，不用手动传。

发 `{"api_name": "/_list"}` 可以拿到全部可用接口和参数定义，探索新接口时用它。

## 用到的接口

| 接口 | 参数 | 取什么 |
|------|------|--------|
| `/shelf/sync` | — | `books[]`、`albums[]`、`mp`。书架全量 |
| `/book/getprogress` | `bookId` | `book.progress` / `readingTime` / `updateTime` / `summary` |
| `/book/info` | `bookId` | 书名、作者、译者、出版社、ISBN、简介、评分、字数 |
| `/book/chapterinfo` | `bookId` | `chapters[]`：`chapterUid` / `chapterIdx` / `title` / `level` / `wordCount` |
| `/book/bookmarklist` | `bookId` | `updated[]`：我的划线，含 `markText` / `chapterUid` / `range` / `createTime` |
| `/book/bestbookmarks` | `bookId`, `chapterUid=0` | `items[]`：热门划线，含 `totalCount` 热度 |
| `/review/list/mine` | `bookid`, `synckey`, `count` | `reviews[].review`：我的想法。**注意参数名是小写 `bookid`** |

`/review/list/mine` 要靠 `synckey` 游标翻页：把回包的 `synckey` 回传，`hasMore` 为假才停。
它也是唯一能拿到 `userVid` 的地方，而 `userVid` 是拼划线深链要用的。

## 口径陷阱

**1. 书架条目数 = `books.length + albums.length + (mp 非空 ? 1 : 0)`**

`albums[]` 是专辑/有声书，它们同样占书架格子。漏掉会让页面总数和 App 里对不上。
`mp` 是「文章收藏」入口，非空时算一个条目。

**2. `progress` 是 0-100 的整数**

`1` 表示 1%，不是 100%。

**但「读完」不能只看 `progress >= 100`。** 用户可以在没读到 100% 时手动标记读完，
这批书 `finishReading == 1` 而 `progress` 停在 99%、90%、63%，甚至 5%。
当前这个账号里 `finishReading == 1` 有 33 本，而 `progress == 100` 只有 23 本 —— 差 10 本。
`finishTime` 的数量和 `finishReading` 严格一致，所以书架标记才是权威判据：

```python
finished = (b.get("finishReading") == 1) or progress >= 100
```

只按字面理解「progress=100 才算读完」会少算 10 本。`build_shelf_items()` 里已经这么处理，
并把 `progress` 归一化成 100，所以下游按 `progress >= 100` 判断是安全的 —— 但别绕过它自己重算。

**3. `isStartReading` 不可信，不要用它判断阅读状态**

实测同样 0% 的书，有的返 1 有的返 0。据此判「在读」会让书架页环形图的数量和卡片上印的百分比自相矛盾。
阅读状态只认 `progress` + `readingTime` 这两个字段，四格互斥：

| 状态 | 判据 |
|------|------|
| 已读完 | `progress >= 100`（或 `finishReading == 1`） |
| 在读 | `1 <= progress <= 99` |
| 翻过 | `progress == 0` 且 `readingTime > 0` |
| 未读 | `progress == 0` 且 `readingTime == 0` |

四格合计必须恒等于书架条目数 —— `init_shelf.py` 每次跑完都打这行自检。
**别引入第五种判据**，这套口径是收敛过的。

**4. `/book/getprogress` 没有批量接口**

只吃单个 `bookId`。136 本就要发 136 次，只能并发逐本拉。8 并发实测稳定，
每个 bookId 失败重试 3 次、退避 1.5s×n。这也是 `init` 慢的原因（约一两分钟），属正常。

**5. 文本里混着零宽字符**

微信读书和 Obsidian 导出的文本常含 `\u200b\u200c\u200d\ufeff\u00ad`，
会把 `**加粗**` 之类的标记打断。一切进模板的文本先过 `weread.clean()`。

**6. 时间戳和时长要转成人话**

所有 Unix 时间戳（`updateTime` / `createTime` / `finishTime` / `readUpdateTime`）展示成 `YYYY-MM-DD`；
`readingTime` 单位是秒，展示成「X 小时 Y 分钟」。用 `weread.fmt_date()` / `weread.fmt_dur()`。

**7. 字段名不要直译**

解释回包时以说明文档为准。回包做过字段裁剪，名字和直觉含义对不上的情况不少。

## 深度链接

| 用途 | 格式 |
|------|------|
| 打开书（续读） | `weread://reading?bId={bookId}` |
| 跳到章节 | `weread://reading?bId={bookId}&chapterUid={chapterUid}` |
| 跳到划线位置 | `weread://bestbookmark?bookId={bookId}&chapterUid={chapterUid}&rangeStart={a}&rangeEnd={b}&userVid={vid}` |

`range` 字段形如 `"900-2004"`，按 `-` 拆开填 `rangeStart` / `rangeEnd`。
想法（review）不一定有划线位置，只有同时具备 `chapterUid` 和 `range` 时才生成这个链接。

`userVid` 可省，但有它体验更好。它只从 `/review/list/mine` 的回包里拿。

**注意**：书内定位用 `weread://` 是对的，但**书架页和书籍页的「去阅读」入口必须用浏览器
`https://weread.qq.com/...`**（来自 `/shelf/sync` 的 `deepLink`），这是用户明确定的规则，
见 `vault-layout.md`。

## 模板数据结构

`assets/shelf_template.html` 消费 `/*__DATA__*/`：

```
{ generatedAt, totalItems, bookCount, albumCount, mpCount, notesAvailable,
  items: [{ id, title, author, cover, category, cat1, cat2, progress, status,
            readingTime, readingTimeText, secret, isTop, lastRead, lastReadTs,
            summary, url, webUrl, noteUrl, isAlbum?, isMp? }] }
```

`assets/book_template.html` 消费 `/*__BOOK__*/`：

```
{ generatedAt,
  book:     { id, title, author, translator, cover, category, publisher,
              publishTime, isbn, intro, rating, ratingCount, wordCount, webUrl },
  reading:  { progress, status, readingTimeText, lastRead, secret },
  counts:   { chapters, best, mine, thoughts },
  chapters: [{ uid, idx, title, level, wc, url }],
  best:     [{ text, ch, count, url }],
  mine:     [{ text, ch, idx, date, url }],
  thoughts: [{ content, abstract, ch, date, url }],
  notesHtml: "<...个人笔记 md 转成的 HTML...>" }
```

模板里的前端逻辑（比如「翻过」那一档）会读 `readingTime`，所以哪怕看着没用也要原样传出去。
加字段是安全的，删字段或改名会静默让页面某块空掉 —— 改完务必按 SKILL.md 的无头 Chrome 断言复验。
