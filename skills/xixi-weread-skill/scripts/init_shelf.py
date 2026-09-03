#!/usr/bin/env python3
"""
init：把当前目录变成读书笔记库，先搭好架子，再问要不要现在同步

用法:
    python3 init_shelf.py --check                    # 只探测密钥状态，不写任何文件
    python3 init_shelf.py                            # 建目录 + 生成书架骨架页；
                                                      #   首次运行会停下来问「现在同步 / 稍后同步」
    python3 init_shelf.py --sync                     # 建目录 + 立即同步真实书架数据
    python3 init_shelf.py --later                    # 建目录 + 只留骨架页，明确选择稍后同步
    python3 init_shelf.py --api-key wrk-xxxxxxxx      # 落盘密钥并立即同步（等价于带 --sync）
    python3 init_shelf.py --vault ~/Desktop/读书      # 指定笔记库（默认从 cwd 向上找）
    python3 init_shelf.py --no-refresh               # 已同步过时，只用本地缓存重新渲染页面

流程分两步，中间有一个决策点：
    1. 目录 + 骨架页：不需要 API Key，不发网络请求，永远先做。
    2. 同步真实数据：需要 API Key，耗时约一两分钟。首次运行且没带
       --sync/--later/--api-key 时，脚本会打印两个选项然后退出（退出码 6），
       调用方应该把选择权交给用户，再带上 --sync 或 --later 重跑。

退出码：
    3 = 缺少可用的 API Key（去引导用户拿 key，而不是当成崩溃）
    6 = 骨架已生成，等待用户选择「现在同步」还是「稍后同步」（不是失败，需要人决策）
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weread as W  # noqa: E402

GET_KEY_URL = "https://weread.qq.com/r/weread-skills"

GUIDE = f"""
🔑 还没有可用的微信读书 API Key。请按两步拿到它：

  1. 用浏览器打开   {GET_KEY_URL}
  2. 用微信扫码登录，页面「快速配置 → 2 获取 API Key」处复制那串 wrk- 开头的字符

拿到后把它贴回来，我会存到 ~/.config/weread/api_key（权限 600）并继续。
密钥绑定你的账号，数据只有你自己能读。
"""

def choice_prompt():
    """
    动态拼命令而不是写死字符串常量：命令里的路径要跟着脚本实际所在位置走
    （见 weread.script_cmd 的说明），写死会在非 Kiro 默认路径下复制粘贴就报错。
    """
    return f"""
🤔 骨架已经搭好了，现在要同步真实书架数据吗？

   现在同步：会拉取账号里的全部书籍、阅读进度、分类，耗时约一两分钟，
             首次同步还需要一个微信读书 API Key。
   稍后同步：骨架页已经能打开看目录结构了，之后随时可以回来同步。

   现在同步 → {W.script_cmd('init_shelf.py', '--sync')}
   稍后同步 → {W.script_cmd('init_shelf.py', '--later')}
"""


def bucket_stats(items):
    """
    四格互斥统计，合计必须等于书架条目数——这是页面数字有没有算错的最快自检。
    口径只认 progress + readingTime：
      已读完 >=100 / 在读 1-99 / 翻过 0% 但有阅读时长 / 未读 0% 且时长 0
    """
    f = r = s = u = 0
    for i in items:
        p, t = i.get("progress", 0), i.get("readingTime", 0)
        if p >= 100:
            f += 1
        elif p > 0:
            r += 1
        elif t > 0:
            s += 1
        else:
            u += 1
    return f, r, s, u


def resolve_and_validate_key(explicit_key):
    """密钥解析 + 校验，成功则写入 _api_key_cache 供 W.api() 复用。失败直接退出码 3。"""
    if explicit_key:
        key = explicit_key.strip()
        if not W.looks_like_key(key):
            W.die(f"❌ 这串不像 API Key（应形如 wrk-xxxxxxxx）：{key[:24]}…\n{GUIDE}", 3)
        print("🔐 校验 API Key…")
        ok, msg = W.validate_key(key)
        if not ok:
            W.die(f"❌ 校验失败：{msg}\n   请回到 {GET_KEY_URL} 重新复制完整的 Key。", 3)
        p = W.save_api_key(key)
        print(f"✅ {msg}")
        print(f"✅ 已保存到 {str(p).replace(str(Path.home()), '~')}（权限 600）")
        W._api_key_cache.update(key=key, src=str(p))
    else:
        key, src = W.resolve_api_key()
        if not key:
            print(GUIDE)
            sys.exit(3)
        print(f"🔐 找到 API Key（来源：{src}），校验中…")
        ok, msg = W.validate_key(key)
        if not ok:
            print(f"❌ 现有 Key 不可用：{msg}")
            print(GUIDE)
            sys.exit(3)
        print(f"✅ {msg}")
        W._api_key_cache.update(key=key, src=src)


def do_sync_and_render(vault, refresh=True):
    """走密钥校验 → 拉数据 → 渲染真实书架页，打印自检数字。"""
    raw, prog = W.load_shelf(vault, refresh=refresh)
    payload, hit = W.write_shelf_html(vault, raw, prog)

    f, r, s, u = bucket_stats(payload["items"])
    total = payload["totalItems"]
    print(f"\n✅ 已生成 {vault / W.SHELF_FILENAME}")
    print(f"   书架条目 {total} = 书 {payload['bookCount']} + 专辑 {payload['albumCount']} "
          f"+ 文章收藏 {payload['mpCount']}")
    print(f"   已读完 {f} | 在读 {r} | 翻过 {s} | 未读 {u}  合计 {f + r + s + u}"
          f"{'  ✓' if f + r + s + u == total else '  ✗ 与条目数不符，口径有问题'}")
    print(f"   已挂上「📝 笔记」入口：{hit} 本（{W.BOOKS_DIRNAME}/ 下现有 {payload['notesAvailable']} 个整理页）")
    if not hit:
        cmd = W.script_cmd("build_book.py", "<书名关键词>")
        print(f"\n💡 下一步：{cmd}  生成单本整理页")


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--api-key")
    ap.add_argument("--vault")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--sync", action="store_true", help="立即同步真实书架数据")
    ap.add_argument("--later", action="store_true", help="只搭骨架，明确选择稍后同步")
    ap.add_argument("--no-refresh", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.help:
        print(__doc__)
        return

    # ---- --check：只探测密钥和库位置，不创建任何目录、不写任何文件
    if a.check:
        key, src = W.resolve_api_key()
        if key:
            print(f"🔐 找到 API Key（来源：{src}），校验中…")
            ok, msg = W.validate_key(key)
            print(f"{'✅' if ok else '❌'} {msg}")
        else:
            print("🔑 未找到可用的 API Key（不影响先搭骨架，同步时才需要）")
        v = W.find_vault(a.vault, required=False)
        print(f"📁 笔记库：{v if v else '（未定位到，生成时需要 --vault）'}")
        return

    # ---- 1. 笔记库结构：永远先做，不需要 API Key，不发网络请求
    #
    # init 的语义是「把这个目录变成笔记库」，所以定位失败时落到当前目录，而不是报错。
    # 向上查找只对已有库有意义：全新的空目录里没有任何标记物，往上找只会认错祖先目录，
    # 逼得调用方必须显式带 --vault —— 而「新建库」恰恰是 init 最主要的使用场景。
    vault = W.find_vault(a.vault, required=False)
    if vault is None:
        vault = Path.cwd().resolve()
        print(f"🆕 当前目录还不是笔记库，将在这里新建：{vault}")
        print("   （如果这不是你想要的位置，Ctrl-C 后用 --vault <路径> 重跑）")
    print(f"📁 笔记库：{vault}")
    created = W.ensure_vault_layout(vault)
    if created:
        print(f"📂 已按 Agent.md 规范补齐：{'、'.join(created)}")

    # ---- 2. 决策点：架子搭好了，同步真实数据是第二步，需要用户明确选
    #
    # already_synced 只反映「以前有没有同步过」，不代表这次要不要同步。
    # --later 的语义是「这次不同步」，不管以前有没有同步过都成立：
    #   没同步过 -> 留着骨架页，之后回来跑 --sync
    #   已同步过 -> 只重渲染现有缓存，不重新拉接口
    already_synced = W.has_synced(vault)
    wants_sync = a.sync or bool(a.api_key)

    if a.later:
        if already_synced:
            do_sync_and_render(vault, refresh=False)
            print("\n（按你的选择跳过了重新同步，用的是本地缓存；要刷新数据加 --sync）")
        else:
            W.write_skeleton_shelf_html(vault)
            print(f"\n📄 已生成骨架页 {vault / W.SHELF_FILENAME}（目录结构就位，书架数据还没同步）")
            print(f"   已按你的选择先跳过同步，随时可以回来跑：{W.script_cmd('init_shelf.py', '--sync')}")
        return

    if not already_synced and not wants_sync:
        W.write_skeleton_shelf_html(vault)
        print(f"\n📄 已生成骨架页 {vault / W.SHELF_FILENAME}（目录结构就位，书架数据还没同步）")
        print(choice_prompt())
        sys.exit(6)

    # ---- 3. 同步：密钥解析 + 校验 + 拉数据 + 渲染
    resolve_and_validate_key(a.api_key)
    do_sync_and_render(vault, refresh=not a.no_refresh)


if __name__ == "__main__":
    main()
