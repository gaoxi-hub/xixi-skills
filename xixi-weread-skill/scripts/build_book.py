#!/usr/bin/env python3
"""
read <书名>：整理一本书 -> 书籍整理/《书名》.html，并把书架页的「📝 笔记」入口接上

用法:
    python3 build_book.py 纳瓦尔
    python3 build_book.py 5%的改变 --refresh          # 顺带重新拉整个书架
    python3 build_book.py 财务自由 --pick 2            # 多本同名时选第 2 个
    python3 build_book.py 纳瓦尔 --vault ~/Desktop/读书

流程:
    1. 在书架里按关键词找书（书名完全一致的自动选中；否则列候选、退出码 4）
    2. 并发拉 详情 / 章节 / 热门划线 / 个人划线，再游标翻页拉个人想法
    3. 读 个人笔记/ 下同名 md，转成 HTML 一起嵌进去
    4. 渲染 书籍整理/《书名》.html
    5. 重新生成 我的书架.html，让这本书的「📝 笔记」入口生效

退出码：3 = 缺 API Key，4 = 关键词命中多本需要用户选，5 = 书架里没这本书。
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weread as W  # noqa: E402


# ---------------------------------------------------------------- 个人笔记 md -> HTML
#
# 一个刻意做窄的 markdown 子集，只认这个库里实际在用的语法。不引通用渲染器是为了
# 让整个 skill 零第三方依赖（用户机器上的 python 是 externally-managed，pip 装不进去，
# 引依赖会逼出一个 venv，那太重了）。
#
# 支持范围见 references/vault-layout.md 的表格 —— 新增语法记得同步那张表，
# 否则下一个人会以为不支持而绕路。

CODE_LANGS = {"py", "python", "js", "javascript", "ts", "bash", "sh", "zsh",
              "json", "yaml", "yml", "sql", "html", "css", "java", "go", "rust", "c", "cpp"}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(s):
    """行内标记。先转义再套标签，顺序反了会把生成的标签自己转义掉。"""
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s.strip()


def _is_table_sep(line):
    """markdown 表格的分隔行，如 | --- | :--: |"""
    t = line.strip()
    return bool(t.startswith("|") and re.fullmatch(r"[|\s:-]+", t) and "-" in t)


def _row_cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def render_md(lines):
    """把已按行切好的 markdown 渲染成 HTML。围栏块内部会递归调用自己。"""
    html, ol, ul = [], [], False
    i = 0

    def flush():
        nonlocal ol, ul
        if ol:
            html.append("<ol>" + "".join(f"<li>{x}</li>" for x in ol) + "</ol>")
            ol = []
        if ul:
            html.append("</ul>")
            ul = False

    while i < len(lines):
        raw_line = lines[i].rstrip()
        st = raw_line.strip()
        if not st:
            i += 1
            continue
        ind = len(raw_line) - len(raw_line.lstrip())

        # --- 围栏块。这个库里 ```markdown 装的是「展开解释」而不是代码，
        #     按代码块渲染会糊成一大坨等宽字，所以折叠起来并递归渲染内层。
        if st.startswith("```"):
            lang = st[3:].strip().lower()
            j = i + 1
            body = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                body.append(lines[j])
                j += 1
            flush()
            if lang in CODE_LANGS:
                html.append("<pre><code>" + esc("\n".join(body)) + "</code></pre>")
            else:
                html.append('<details class="md-expand"><summary>展开</summary>'
                            f'<div class="inner">{render_md(body)}</div></details>')
            i = j + 1
            continue

        # --- ATX 标题。模板里板块标题已经是 h2，所以 #/## 落 h3，### 及更深落 h4。
        m = re.match(r"^(#{1,6})\s+(.*)$", st)
        if m:
            flush()
            tag = "h3" if len(m.group(1)) <= 2 else "h4"
            html.append(f"<{tag}>{inline(m.group(2))}</{tag}>")
            i += 1
            continue

        # --- 表格：表头行 + 分隔行 + 若干数据行
        if st.startswith("|") and i + 1 < len(lines) and _is_table_sep(lines[i + 1]):
            flush()
            head = _row_cells(st)
            rows, j = [], i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(_row_cells(lines[j]))
                j += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            body = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            html.append(f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>")
            i = j
            continue

        # --- 无序列表
        if re.match(r"^[-*]\s+", st):
            if ol:
                flush()
            if not ul:
                html.append("<ul>")
                ul = True
            html.append(f"<li>{inline(re.sub(r'^[-*]\s+', '', st))}</li>")
            i += 1
            continue

        # --- 有序列表 / 加粗小标题
        m = re.match(r"^(\d+)\.\s+(.*)$", st)
        if m:
            content = m.group(2).strip()
            bold_only = re.fullmatch(r"\*\*(.+?)\*\*[：:]?", content)
            # 顶格且整行就是一个加粗短语时才当小标题。以前只判「含 **」，
            # 于是「1. **本质**：主动求己、尊重规律…」整句被塞进 h4，读起来很怪。
            if ind == 0 and bold_only:
                flush()
                html.append(f"<h4>{inline(bold_only.group(1))}</h4>")
            else:
                if ul:
                    flush()
                ol.append(inline(content))
            i += 1
            continue

        flush()
        html.append(f"<p>{inline(st)}</p>")
        i += 1

    flush()
    return "\n".join(html)


def parse_md(path):
    if not path or not Path(path).exists():
        return ""
    raw = W.clean(Path(path).read_text(encoding="utf-8"))
    return render_md(raw.split("\n"))


def find_note_md(vault: Path, title: str):
    """在 个人笔记/ 里找这本书的 md。文件名规范是「书名-xxx.md」，所以按书名前缀匹配。"""
    d = vault / W.NOTES_DIRNAME
    if not d.is_dir():
        return None
    stem = W.nfkc(re.split(r"[（(：:]", title)[0]).strip()
    if not stem:
        return None
    probes = [stem, stem[:6], stem[:4]]
    for probe in probes:
        if len(probe) < 2:
            continue
        for p in sorted(d.glob("*.md")):
            if probe in W.nfkc(p.name):
                return p
    return None


# ---------------------------------------------------------------- 拉一本书的全部内容

def fetch_book(book_id):
    jobs = {
        "info": lambda: W.api("/book/info", bookId=book_id),
        "chapters": lambda: W.api("/book/chapterinfo", bookId=book_id),
        "bookmarks": lambda: W.api("/book/bookmarklist", bookId=book_id),
        "best": lambda: W.api("/book/bestbookmarks", bookId=book_id, chapterUid=0),
    }
    D = {}
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fn): k for k, fn in jobs.items()}
        for f in cf.as_completed(futs):
            D[futs[f]] = f.result()

    # 想法要靠 synckey 游标翻页，一次拿不完
    revs, sk, page = [], 0, 0
    while page < 10:
        d = W.api("/review/list/mine", bookid=book_id, synckey=sk, count=100)
        if not d:
            break
        revs.extend(d.get("reviews", []) or [])
        if not d.get("hasMore"):
            break
        sk = d.get("synckey", sk)
        page += 1
    D["reviews"] = revs
    return D


def build_payload(vault: Path, me, D):
    info = D.get("info") or {}
    revs = D.get("reviews") or []
    title = W.clean(info.get("title") or me["title"])
    book_id = me["id"]

    chs = (D.get("chapters") or {}).get("chapters", []) or []
    ch_title = {c["chapterUid"]: W.clean(c.get("title", "")) for c in chs}
    ch_idx = {c["chapterUid"]: c.get("chapterIdx", 999) for c in chs}

    # userVid 只在想法回包里出现；有它划线深链才能定位到「谁的」划线
    vid = ""
    for r in revs:
        v = (r.get("review") or {}).get("userVid")
        if v:
            vid = str(v)
            break

    def mark_url(uid, rng):
        """range 形如 "900-2004"，拆成 rangeStart / rangeEnd 才能拼深链。"""
        if not rng or "-" not in str(rng):
            return ""
        a, b = str(rng).split("-")[:2]
        u = f"weread://bestbookmark?bookId={book_id}&chapterUid={uid}&rangeStart={a}&rangeEnd={b}"
        return u + (f"&userVid={vid}" if vid else "")

    def fdate(ts):
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""

    chapters = [{
        "uid": c["chapterUid"], "idx": c.get("chapterIdx"),
        "title": W.clean(c.get("title", "")), "level": c.get("level", 1),
        "wc": c.get("wordCount", 0),
        "url": f"weread://reading?bId={book_id}&chapterUid={c['chapterUid']}",
    } for c in chs]

    best = sorted([{
        "text": W.clean(i.get("markText")).strip(),
        "ch": ch_title.get(i.get("chapterUid"), ""),
        "count": i.get("totalCount", 0),
        "url": mark_url(i.get("chapterUid"), i.get("range", "")),
    } for i in (D.get("best") or {}).get("items", []) or []], key=lambda x: -x["count"])

    mine = sorted([{
        "text": W.clean(b.get("markText")).strip(),
        "ch": ch_title.get(b.get("chapterUid"), ""),
        "idx": ch_idx.get(b.get("chapterUid"), 999),
        "date": fdate(b.get("createTime")),
        "url": mark_url(b.get("chapterUid"), b.get("range", "")),
    } for b in (D.get("bookmarks") or {}).get("updated", []) or []], key=lambda x: x["idx"])

    thoughts = [{
        "content": W.clean(rv.get("content")).strip(),
        "abstract": W.clean(rv.get("abstract")).strip(),
        "ch": W.clean(rv.get("chapterName") or ch_title.get(rv.get("chapterUid"), "")),
        "date": fdate(rv.get("createTime")),
        "url": mark_url(rv.get("chapterUid"), rv.get("range", "")),
    } for r in revs for rv in [r.get("review") or {}]]

    note_md = find_note_md(vault, title)
    notes_html = parse_md(note_md)
    print(f"📝 个人笔记：{note_md.name if note_md else '（无，该板块留空）'}")

    return title, {
        "generatedAt": W.now_str(),
        "book": {
            "id": book_id, "title": title,
            "author": W.clean(info.get("author", "")) or me["author"],
            "translator": W.clean(info.get("translator", "")),
            "cover": info.get("cover") or me["cover"],
            "category": info.get("category", "") or me.get("category", ""),
            "publisher": info.get("publisher", ""),
            "publishTime": (info.get("publishTime") or "")[:10],
            "isbn": info.get("isbn", ""),
            "intro": W.clean(info.get("intro")).strip(),
            "rating": round((info.get("newRating") or 0) / 100, 2),
            "ratingCount": info.get("newRatingCount", 0),
            "wordCount": info.get("wordCount") or sum(c["wc"] for c in chapters),
            # 硬规则：书架/书籍页上「去阅读」一律走浏览器 webUrl，不用 weread:// 协议
            "webUrl": me.get("webUrl") or f"https://weread.qq.com/book-detail?bId={book_id}",
        },
        "reading": {
            "progress": me["progress"], "status": me["status"],
            "readingTimeText": me["readingTimeText"], "lastRead": me["lastRead"],
            "secret": me["secret"],
        },
        "counts": {"chapters": len(chapters), "best": len(best),
                   "mine": len(mine), "thoughts": len(thoughts)},
        "chapters": chapters, "best": best, "mine": mine,
        "thoughts": thoughts, "notesHtml": notes_html,
    }


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("keyword", nargs="*")
    ap.add_argument("--vault")
    ap.add_argument("--pick", type=int)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.help or not a.keyword:
        print(__doc__)
        return
    keyword = " ".join(a.keyword)

    if not W.resolve_api_key()[0]:
        print(f"❌ 缺少 WEREAD_API_KEY，先跑 init：{W.script_cmd('init_shelf.py')}")
        sys.exit(3)

    vault = W.find_vault(a.vault)
    print(f"📁 笔记库：{vault}")
    raw, prog = W.load_shelf(vault, refresh=a.refresh)
    items = W.build_shelf_items(raw, prog)

    hits = W.match_books(items, keyword)
    if not hits:
        print(f"❌ 书架里没有包含「{keyword}」的书。换个关键词，或加 --refresh 重新拉书架。")
        sys.exit(5)

    exact = W.nfkc(hits[0]["title"]).lower() == W.nfkc(keyword).lower()
    if len(hits) > 1 and not a.pick and not exact:
        print(f"🔎 命中 {len(hits)} 本，请指定要哪一本（--pick N）：")
        for n, i in enumerate(hits, 1):
            print(f"  {n}. {i['title']} — {i['author']}（{i['progress']}%）")
        sys.exit(4)
    me = hits[(a.pick - 1) if a.pick else 0]
    if a.pick and not (1 <= a.pick <= len(hits)):
        W.die(f"❌ --pick 超出范围，命中 {len(hits)} 本")

    print(f"\n📖 {me['title']} — {me['author']}（bookId {me['id']}，进度 {me['progress']}%）")
    if me.get("isAlbum") or me.get("isMp"):
        print("⚠️  这是专辑/文章收藏，没有章节和划线接口，整理页会大面积留空。")

    print("📥 拉取详情 / 章节 / 划线 / 想法…")
    D = fetch_book(me["id"])
    title, data = build_payload(vault, me, D)

    tpl = W.ASSETS / "book_template.html"
    if not tpl.exists():
        W.die(f"❌ 缺模板: {tpl}")
    out_dir = vault / W.BOOKS_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"《{title}》.html"
    out.write_text(
        tpl.read_text(encoding="utf-8").replace(
            "/*__BOOK__*/", json.dumps(data, ensure_ascii=False, indent=1)),
        encoding="utf-8")

    c = data["counts"]
    print(f"\n✅ 已生成 {out}")
    print(f"   章节 {c['chapters']} | 热门划线 {c['best']} | 我的划线 {c['mine']} | 我的想法 {c['thoughts']}")

    # 书架页必须重生成，否则新整理页的「📝 笔记」入口挂不上
    payload, hit = W.write_shelf_html(vault, raw, prog)
    print(f"🔗 已重新生成 {W.SHELF_FILENAME}：{hit}/{payload['totalItems']} 个条目挂上了「📝 笔记」入口")


if __name__ == "__main__":
    main()
