#!/usr/bin/env python3
"""
微信读书读书库 · 共享底座

这里放所有 init / read 都要用的东西：API 客户端、密钥解析、vault 定位、
书架数据构建、书架页生成。两条命令的脚本只负责编排，口径都收在这里，
这样「书架怎么计数」「什么算读过」这类结论只有一处定义，不会两边漂移。

不要单独执行本文件，它是被 init_shelf.py / build_book.py import 的。
"""
import concurrent.futures as cf
import datetime
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- 常量

GATEWAY = "https://i.weread.qq.com/api/agent/gateway"

# skill_version 必须随每个请求上报，服务端用它判断是否要求升级。
# 这里不去读官方 weread-skills/SKILL.md 的 version 字段：那份文档的版本号
# 可能落后于实际可用版本（实测 1.0.5 正常，而文档里写的是 1.0.3），
# 照抄反而会往回退。需要跟版本时用 WEREAD_SKILL_VERSION 覆盖即可，
# 另外 api() 会在回包出现 upgrade_info 时显式告警。
SKILL_VERSION = os.environ.get("WEREAD_SKILL_VERSION", "1.0.5")

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / "assets"

KEY_FILE = Path.home() / ".config" / "weread" / "api_key"
SHELL_RCS = [".zshrc", ".zprofile", ".bash_profile", ".bashrc", ".profile"]

# vault 里的目录规范（与 vault 根的 Agent.md 一致）
NOTES_DIRNAME = "个人笔记"
BOOKS_DIRNAME = "书籍整理"
SHELF_FILENAME = "我的书架.html"
CACHE_DIRNAME = ".weread-cache"

# 微信读书 / Obsidian 导出的文本里常混入零宽字符，会把 ** 加粗之类的标记打断
_ZW = re.compile(r"[\u200b\u200c\u200d\ufeff\u00ad]")


def clean(s):
    return _ZW.sub("", s or "")


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "")


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- API Key
#
# 解析顺序：环境变量 → 我们自己的密钥文件 → 用户的 shell rc。
# 之所以要读 shell rc：agent 起的子进程通常不会 source ~/.zshrc，
# 环境变量拿不到；而很多人（包括本库的原始配置）就是把 key export 在那儿的。
# 读 rc 只是为了兼容既有配置，落盘一律写我们自己的 KEY_FILE。

_KEY_RE = re.compile(r"""WEREAD_API_KEY\s*=\s*["']?(wrk-[A-Za-z0-9_\-]+)""")


def _key_from_shell_rc():
    for name in SHELL_RCS:
        p = Path.home() / name
        if not p.exists():
            continue
        try:
            m = _KEY_RE.search(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if m:
            return m.group(1), f"~/{name}"
    return None, None


def resolve_api_key():
    """返回 (key, 来源描述)；找不到返回 (None, None)。"""
    env = (os.environ.get("WEREAD_API_KEY") or "").strip()
    if env:
        return env, "环境变量 WEREAD_API_KEY"
    if KEY_FILE.exists():
        v = KEY_FILE.read_text(encoding="utf-8").strip()
        if v:
            return v, str(KEY_FILE).replace(str(Path.home()), "~")
    return _key_from_shell_rc()


def save_api_key(key):
    """写入 ~/.config/weread/api_key，权限 600（密钥等同账号凭证，别让它可读）。"""
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.strip() + "\n", encoding="utf-8")
    KEY_FILE.chmod(0o600)
    return KEY_FILE


def looks_like_key(s):
    return bool(re.fullmatch(r"wrk-[A-Za-z0-9_\-]{8,}", (s or "").strip()))


# ---------------------------------------------------------------- 调用

_api_key_cache = {"key": None, "src": None}


def _key():
    if _api_key_cache["key"]:
        return _api_key_cache["key"]
    k, src = resolve_api_key()
    if not k:
        die(
            "❌ 没找到 WEREAD_API_KEY。\n"
            "   到 https://weread.qq.com/r/weread-skills 登录后复制 API Key，\n"
            f"   然后跑：{script_cmd('init_shelf.py', '--api-key wrk-xxxxxxxx')}"
        )
    _api_key_cache.update(key=k, src=src)
    return k


def call(payload, timeout=25, key=None):
    req = urllib.request.Request(
        GATEWAY,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key or _key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


_warned_upgrade = set()


def api(name, key=None, quiet=False, **kw):
    """
    调一个 gateway 接口。业务参数必须和 api_name / skill_version 平铺在同一层
    ——包进 params 会被后端丢掉，表现是分页永远返回第一页，很难查。
    出错返回 {}，让调用方决定是重试还是降级。
    """
    payload = {"api_name": name, "skill_version": SKILL_VERSION}
    payload.update(kw)
    try:
        d = call(payload, key=key)
    except Exception as exc:  # noqa: BLE001
        if not quiet:
            print(f"  ⚠️  {name} 请求失败: {exc}")
        return {}
    if d.get("upgrade_info") and name not in _warned_upgrade:
        _warned_upgrade.add(name)
        print(
            f"  🔔 服务端要求升级 skill: {d['upgrade_info'].get('message', '')}\n"
            f"     升级后用 WEREAD_SKILL_VERSION=<新版本> 重跑本脚本。"
        )
    if d.get("errcode", 0):
        if not quiet:
            print(f"  ⚠️  {name} 返回错误 {d.get('errcode')}: {d.get('errmsg', '')}")
        return {}
    return d


def validate_key(key):
    """用最轻的一次请求确认 key 可用。返回 (ok, 说明)。"""
    try:
        d = call({"api_name": "/shelf/sync", "skill_version": SKILL_VERSION}, key=key)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "API Key 被拒绝（401/403），可能复制不全或已失效"
        return False, f"HTTP {e.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"网络异常: {exc}"
    if d.get("errcode", 0):
        return False, f"errcode {d['errcode']}: {d.get('errmsg', '')}"
    n = len(d.get("books", []) or [])
    return True, f"连接正常，书架读到 {n} 本书"


# ---------------------------------------------------------------- vault 定位
#
# vault = 读书笔记库根目录，判据是「有 Agent.md」或「有 书籍整理/ 或 我的书架.html」。
# 从 cwd 往上找，这样 skill 装在全局也能服务任意一个笔记库。


def is_vault(p: Path):
    return (p / "Agent.md").exists() or (p / BOOKS_DIRNAME).is_dir() or (p / SHELF_FILENAME).exists()


def find_vault(explicit=None, required=True):
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_dir():
            die(f"❌ --vault 指定的目录不存在: {p}")
        return p
    env = os.environ.get("WEREAD_VAULT")
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_dir():
            return p
    cur = Path.cwd().resolve()
    for p in [cur, *cur.parents]:
        if is_vault(p):
            return p
    if required:
        die(
            "❌ 没定位到读书笔记库。\n"
            f"   判据是目录里有 Agent.md 或 {BOOKS_DIRNAME}/ 或 {SHELF_FILENAME}。\n"
            "   请在库目录里执行，或加 --vault /path/to/读书"
        )
    return None


def ensure_vault_layout(vault: Path):
    """按 Agent.md 的目录规范补齐结构；已存在的不动。返回新建了什么。"""
    created = []
    for d in (NOTES_DIRNAME, BOOKS_DIRNAME, CACHE_DIRNAME):
        p = vault / d
        if not p.exists():
            p.mkdir(parents=True)
            created.append(f"{d}/")
    agent = vault / "Agent.md"
    if not agent.exists():
        agent.write_text(AGENT_MD_TEMPLATE, encoding="utf-8")
        created.append("Agent.md")
    return created


AGENT_MD_TEMPLATE = """## 目录结构

* 个人笔记/：存放个人整理的读书笔记md文件。文件名：{书籍名称}-xxx.md
* 书籍整理/：存放将书籍的基本信息、章节信息、热门划线、个人划线和想法整理成一个优美的HTML文件。文件名：{书籍名称}.html
* 我的书架.html：同步微信读书的【我的书架】内容
## 我的书架.html
* 书籍阅读按钮：点击可以跳转浏览器，微信读书【我的书架】页面
* 读书笔记，可以跳转 【书籍整理】 中对应书籍的html文件
"""


def cache_dir(vault: Path):
    d = vault / CACHE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


SCRIPT_DIR = Path(__file__).resolve().parent


def script_cmd(name, args=""):
    """
    拼一条「复制就能跑」的命令，不假设 skill 装在哪、也不假设用户站在哪个目录。

    运行时打印给用户/agent 看的提示（比如「下一步该跑什么」）如果写死裸文件名
    `python3 init_shelf.py`，只有正好站在 scripts/ 目录里才有效——SKILL.md 的建议流程
    是 cd 到笔记库目录再用绝对路径调脚本，两者对不上会让人复制粘贴就报错。
    这里用脚本自己实际所在的绝对路径（SCRIPT_DIR 在 import 时就固定了），
    不管 skill 装在 ~/.kiro/skills/ 还是别处，打印出来的命令永远能直接执行。
    """
    cmd = f"python3 {SCRIPT_DIR / name}"
    return f"{cmd} {args}".strip()


def has_synced(vault: Path):
    """
    是否已经跑过至少一次真正的书架同步。

    只认 shelf.json + progress.json 这两个由 sync_shelf() 写入的文件——
    shelf_data.json 不算，因为骨架页（未同步状态）也会写它，用它判断
    会把「刚生成的空壁架」误认成「已经同步过」。
    """
    cd = vault / CACHE_DIRNAME
    return (cd / "shelf.json").exists() and (cd / "progress.json").exists()


# ---------------------------------------------------------------- 格式化


def fmt_dur(sec):
    sec = int(sec or 0)
    if sec <= 0:
        return "0 分钟"
    h, m = sec // 3600, (sec % 3600) // 60
    return f"{h} 小时 {m} 分钟" if h and m else (f"{h} 小时" if h else f"{m} 分钟")


def fmt_date(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else None


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- 书架数据


def sync_shelf(vault: Path, workers=8):
    """拉书架 + 逐本拉进度，结果落 vault/.weread-cache/。返回 (raw, prog)。"""
    print("📥 拉取书架…")
    raw = api("/shelf/sync")
    if not raw:
        die(f"❌ 书架拉取失败。先确认 API Key 有效：{script_cmd('init_shelf.py', '--check')}")

    books = raw.get("books", []) or []
    print(f"📥 拉取 {len(books)} 本书的阅读进度…（/book/getprogress 没有批量接口，只能逐本并发）")

    def one(b):
        for attempt in range(3):
            d = api("/book/getprogress", bookId=b["bookId"], quiet=True)
            if d:
                return b["bookId"], d.get("book", {}) or {}
            time.sleep(1.5 * (attempt + 1))
        return b["bookId"], {}

    prog, done = {}, 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for bid, d in ex.map(one, books):
            prog[bid] = d
            done += 1
            if done % 25 == 0 or done == len(books):
                print(f"   {done}/{len(books)}")

    cd = cache_dir(vault)
    (cd / "shelf.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    (cd / "progress.json").write_text(json.dumps(prog, ensure_ascii=False), encoding="utf-8")
    miss = sum(1 for v in prog.values() if not v)
    print(f"✅ 进度拉取完成（{len(prog) - miss}/{len(prog)} 成功）")
    return raw, prog


def load_shelf(vault: Path, refresh=False):
    cd = cache_dir(vault)
    sf, pf = cd / "shelf.json", cd / "progress.json"
    if refresh or not (sf.exists() and pf.exists()):
        return sync_shelf(vault)
    try:
        raw = json.loads(sf.read_text(encoding="utf-8"))
        prog = json.loads(pf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("⚠️  本地缓存损坏，重新拉取…")
        return sync_shelf(vault)
    print(f"📂 用本地缓存（{len(raw.get('books', []) or [])} 本书）；要刷新加 --refresh")
    return raw, prog


def build_shelf_items(raw, prog):
    """
    raw + prog -> 前端 items。

    两个必须守住的口径：
    1. 书架条目 = books + albums + (mp 非空 ? 1 : 0)。albums 是专辑/有声书，
       它们也占书架格子，漏掉会导致页面上的总数和 App 里对不上。
    2. 阅读状态只认 progress（0-100 整数）和 readingTime，不用 isStartReading。
       该字段不可信：同样 0% 的书有的返 1 有的返 0，据此判「在读」会让环形图
       的数量和卡片上印的百分比自相矛盾。「翻过」（0% 但有时长）由前端结合
       readingTime 识别，所以这里必须把 readingTime 原样传出去。
    """
    items = []
    for b in raw.get("books", []) or []:
        p = prog.get(b["bookId"], {}) or {}
        progress = int(p.get("progress", 0) or 0)
        finished = 1 if (b.get("finishReading") == 1 or progress >= 100) else 0
        status = "finished" if finished else ("reading" if progress > 0 else "unread")
        cat = b.get("category") or "未分类"
        last = p.get("updateTime") or b.get("readUpdateTime") or 0
        items.append({
            "id": b["bookId"],
            "title": clean(b.get("title", "")),
            "author": clean(b.get("author", "")) or "佚名",
            "cover": b.get("cover", ""),
            "category": cat,
            "cat1": cat.split("-")[0],
            "cat2": cat.split("-")[1] if "-" in cat else "",
            "progress": 100 if finished else progress,
            "status": status,
            "readingTime": int(p.get("readingTime", 0) or 0),
            "readingTimeText": fmt_dur(p.get("readingTime", 0)),
            "secret": 1 if b.get("secret") == 1 else 0,
            "isTop": 1 if b.get("isTop") else 0,
            "lastRead": fmt_date(last),
            "lastReadTs": int(last or 0),
            "summary": (p.get("summary") or "").strip(),
            "url": f"weread://reading?bId={b['bookId']}",
            "webUrl": b.get("deepLink", ""),
        })

    for a in raw.get("albums", []) or []:
        info = a.get("albumInfo", {}) or {}
        extra = a.get("albumInfoExtra", {}) or {}
        last = extra.get("lectureReadUpdateTime") or info.get("updateTime") or 0
        items.append({
            "id": f"album_{info.get('albumId')}",
            "title": clean(info.get("name", "")),
            "author": clean(info.get("authorName", "")) or "佚名",
            "cover": info.get("cover", ""),
            "category": "有声书", "cat1": "有声书", "cat2": "",
            "progress": 100 if info.get("finish") == 1 else 0,
            "status": "finished" if info.get("finish") == 1 else "unread",
            "readingTime": 0, "readingTimeText": "—",
            "secret": 1 if extra.get("secret") == 1 else 0,
            "isTop": 1 if extra.get("isTop") else 0,
            "lastRead": fmt_date(last), "lastReadTs": int(last or 0),
            "summary": (info.get("intro") or "").strip()[:80],
            "url": "", "webUrl": "", "isAlbum": True,
        })

    mp = raw.get("mp")
    if mp:
        mb = mp.get("book", {}) or {}
        items.append({
            "id": "mpbook", "title": "文章收藏", "author": "微信读书",
            "cover": mb.get("cover", ""), "category": "文章收藏",
            "cat1": "文章收藏", "cat2": "",
            "progress": 0, "status": "unread",
            "readingTime": 0, "readingTimeText": "—",
            "secret": 1, "isTop": 0,
            "lastRead": fmt_date(mb.get("updateTime")),
            "lastReadTs": int(mb.get("updateTime") or 0),
            "summary": "公众号文章收藏目录",
            "url": "", "webUrl": "", "isMp": True,
        })
    return items


def scan_note_pages(vault: Path):
    """扫 书籍整理/ 得到 {书名: 相对路径}，用来给书架卡片挂「📝 笔记」入口。"""
    out_dir = vault / BOOKS_DIRNAME
    avail = {}
    if out_dir.is_dir():
        for p in sorted(out_dir.glob("*.html")):
            name = re.sub(r"^《|》$", "", p.stem).strip()
            avail[name] = f"{BOOKS_DIRNAME}/{p.name}"
    return avail


def write_shelf_html(vault: Path, raw, prog):
    """
    生成 我的书架.html。每次生成都重扫 书籍整理/ 回填 noteUrl ——
    新整理一本书之后书架页必须重生成，否则「📝 笔记」入口挂不上。
    返回 (payload, 命中笔记数)。
    """
    tpl = ASSETS / "shelf_template.html"
    if not tpl.exists():
        die(f"❌ 缺模板: {tpl}")

    items = build_shelf_items(raw, prog)
    avail = scan_note_pages(vault)
    hit = 0
    for it in items:
        it["noteUrl"] = avail.get(it["title"].strip(), "")
        hit += bool(it["noteUrl"])

    payload = {
        "generatedAt": now_str(),
        "synced": True,
        "totalItems": len(items),
        "bookCount": len(raw.get("books", []) or []),
        "albumCount": len(raw.get("albums", []) or []),
        "mpCount": 1 if raw.get("mp") else 0,
        "notesAvailable": len(avail),
        "items": items,
    }
    (cache_dir(vault) / "shelf_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    html = tpl.read_text(encoding="utf-8").replace(
        "/*__DATA__*/", json.dumps(payload, ensure_ascii=False, indent=1))
    (vault / SHELF_FILENAME).write_text(html, encoding="utf-8")
    return payload, hit


def write_skeleton_shelf_html(vault: Path):
    """
    生成一个空壁架：只有目录结构和页面外壳，没有真实书架数据，不需要 API Key，
    不发任何网络请求。

    这是 init 的第一步产出——先把「架子」搭起来，用不用马上同步交给用户决定，
    不要在没问过用户之前就顺手拉一次全量数据（一两分钟，还要先要 API Key）。
    页面里会显示一条「还没有同步」的提示，指引用户之后怎么补上真实数据。
    """
    tpl = ASSETS / "shelf_template.html"
    if not tpl.exists():
        die(f"❌ 缺模板: {tpl}")

    avail = scan_note_pages(vault)
    payload = {
        "generatedAt": now_str(),
        "synced": False,
        "totalItems": 0,
        "bookCount": 0,
        "albumCount": 0,
        "mpCount": 0,
        "notesAvailable": len(avail),
        "items": [],
    }
    (cache_dir(vault) / "shelf_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    html = tpl.read_text(encoding="utf-8").replace(
        "/*__DATA__*/", json.dumps(payload, ensure_ascii=False, indent=1))
    (vault / SHELF_FILENAME).write_text(html, encoding="utf-8")
    return payload


# ---------------------------------------------------------------- 找书


def match_books(items, keyword):
    """按关键词模糊匹配书架条目，完全一致的排前面。"""
    k = nfkc(keyword).lower().strip()
    hits = [i for i in items if k in nfkc(i["title"]).lower()]
    hits.sort(key=lambda i: (nfkc(i["title"]).lower() != k, -i.get("lastReadTs", 0)))
    return hits
