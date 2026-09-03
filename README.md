# xixi-weread-skill

把微信读书的书架和笔记整理成本地 HTML 阅读库，安装为 Agent Skill 后直接在对话里使用。

## 效果预览

**书架页**

![书架页](images/shelf.png)

**书籍整理页**

![书籍整理页](images/book-basic.png)

## 安装

**方式一：npx（推荐）**

支持 Kiro、Claude Code、Codex、Cursor 等 70+ 个 agent，自动安装到已检测到的 agent：

```bash
npx skills add gaoxi-hub/xixi-skills
```

**方式二：手动**

```bash
git clone https://github.com/gaoxi-hub/xixi-skills.git
```

把 `xixi-weread-skill/` 目录放到对应 agent 的 skills 目录下：

| Agent | Skills 目录 |
|-------|-------------|
| Kiro | `~/.kiro/skills/` |
| Workbuddy | `~/.workbuddy/skills/` |
| 其他支持 SKILL.md 的 agent | 参考对应 agent 的文档 |

**在 WorkBuddy 中安装**

把 `xixi-weread-skill/` 目录放入 `~/.workbuddy/skills/`，即可在 WorkBuddy 对话中直接调用；也可在 WorkBuddy 的技能市场搜索并一键安装：

![WorkBuddy 安装](images/workbuddy-skill.png)

## 使用

安装后直接在对话里说就行，不需要手动跑命令：

- "帮我初始化微信读书笔记库"
- "同步一下我的书架"
- "整理一下《纳瓦尔宝典》的笔记"

Agent 会自动识别意图并引导完成，包括首次使用时获取 API Key。

## 两条命令

| 命令 | 做什么 | 产出 |
|------|--------|------|
| `init` | 建好笔记库目录，同步书架数据 | `我的书架.html` |
| `read <书名>` | 整理某本书的章节、划线、想法 | `书籍整理/《书名》.html` |

## 依赖

- `python3`（系统自带即可，无需安装第三方包）
- 微信读书账号
- 微信读书 API Key（首次使用时 agent 会引导获取）

## Star History

<a href="https://www.star-history.com/?repos=gaoxi-hub%2Fxixi-skills&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=gaoxi-hub/xixi-skills&type=date&theme=dark&legend=top-left&sealed_token=b6vo5J3P0e-RUTMNFE3ZOIU7YY9lMol0uN64ihJHZjBq19vsVzjKq6rhGcSNjtPs7mEcT6eyikC0dAg_xJIAtmi1MCC__mAwqPqDJccaGzxssC3WiGzrXp7XomTSW20mc3TmjTGyFyLi_0pTCEodV4856I05ntnI1orVU8GYL4dkW8pJIFYLLcs_EoaY" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=gaoxi-hub/xixi-skills&type=date&legend=top-left&sealed_token=b6vo5J3P0e-RUTMNFE3ZOIU7YY9lMol0uN64ihJHZjBq19vsVzjKq6rhGcSNjtPs7mEcT6eyikC0dAg_xJIAtmi1MCC__mAwqPqDJccaGzxssC3WiGzrXp7XomTSW20mc3TmjTGyFyLi_0pTCEodV4856I05ntnI1orVU8GYL4dkW8pJIFYLLcs_EoaY" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=gaoxi-hub/xixi-skills&type=date&legend=top-left&sealed_token=b6vo5J3P0e-RUTMNFE3ZOIU7YY9lMol0uN64ihJHZjBq19vsVzjKq6rhGcSNjtPs7mEcT6eyikC0dAg_xJIAtmi1MCC__mAwqPqDJccaGzxssC3WiGzrXp7XomTSW20mc3TmjTGyFyLi_0pTCEodV4856I05ntnI1orVU8GYL4dkW8pJIFYLLcs_EoaY" />
 </picture>
</a>