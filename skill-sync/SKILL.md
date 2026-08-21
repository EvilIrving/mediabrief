---
name: skill-sync
description: >
  用 skillmesh 把一份 Skill 源同步到多个 AI Agent 的 skills 目录。
  每个 Agent 都有自己的安装位置；本 skill 只维护 .agents/skills 这一份源，再软链同步出去。
  Use when the user mentions skillmesh, skill-sync, 同步 Skill、跨 Agent 装 Skill、
  adopt/import skill、检查 skill 断链/冲突，or runs /skill-sync.
---

# skill-sync

多 Agent 并行时，Skill 的问题不是缺，而是安装位置割裂：同一份要装 N 遍，改一处改 N 遍，项目一切又容易拆成另一套。

理念：Skill 只该有一份源，同步给各 Agent，而不是复制粘贴。本 skill **不负责寻找或下载 Skill**；拿到本地之后，才 import / adopt / sync。

源码与入口是与本 `SKILL.md` 同级的 `skillmesh.sh`。先定位该文件再执行，不要另写一套同步逻辑。仓库根目录若还有一份同名脚本，以本 skill 目录内这份为准。

## 目录模型

未指定 `--scope` 时：当前目录是用户主目录 → global；位于 Git 项目内 → project。`--project DIR` 也视为 project。

| 作用域 | Skill 源 |
|---|---|
| global | `~/.agents/skills/<name>/SKILL.md`（`SKILLMESH_HOME` 可覆盖根目录） |
| project | `<项目>/.agents/skills/<name>/SKILL.md` |

目标是各 Agent 自己的 skills 目录。未加 `-A` / `--target` 时只处理默认 5 个：`claude` `codex` `cursor` `pi` `grok`。更多 Agent 用 `-A` 追加，或 `--target` 只打指定名单（`--target all` 为全部已支持）。完整名单见 `skillmesh.sh --help`。

项目作用域**默认不继承**全局。要叠加时加 `--include-global`，同名以项目为准。

可管理的 Skill = 源库一级目录且含 `SKILL.md`。源库条目可以是真实目录，也可以是指向外部 Skill 的软链。

## 何时跑哪条命令

用户没指定命令时，先 `status`，再按结果决定是否 `sync`。破坏性操作先 `--dry-run`。

| 意图 | 命令 |
|---|---|
| 查看谁连上了、谁缺、谁冲突、谁断链 | `status` |
| 把源同步到各 Agent（默认命令；会清当前作用域失效软链） | `sync` |
| 只启用几个 Skill | `enable SKILL ...` |
| 只从目标撤掉受管软链，源保留 | `disable` / `remove` |
| 本地目录加入当前源库（默认软链） | `import PATH` |
| 把某 Agent 里已有、源库尚未管理的 Skill 收编进来 | `adopt --from AGENT` |
| 源已删、目标还留着受管软链 | `clean` |
| 还要清其他指向已失效 `.agents/skills` 的断链 | `clean --orphaned` |
| 校验 SKILL.md、断链、冲突、缺失链接 | `doctor` |
| 列出当前作用域有效 Skill | `list` |
| 只建目录，不创建 Skill | `init` |

`import` / `adopt` 要立刻分发时加 `--sync`。`--copy` 才在源库留独立副本，默认 `--link`。

## 执行规则

1. 用 bash 跑同目录 `skillmesh.sh`，不要把脚本内容展开进对话。
2. 用户已给 Agent / 作用域 / Skill 名，原样传给 `--target`、`--scope`、`--project`、skill 参数；不要猜未提到的 Agent。
3. `sync` 会覆盖目标里的同名 Skill（受管软链、外部软链、真实目录都是）。先说明这一点，需要预览就加 `-n`。
4. `clean` 只删软链，不删源。`remove`/`disable` 默认不动外部软链，除非 `--force`。
5. 不要扫描市场、Git 仓库或压缩包去「找 Skill」。路径已经在本地，才 `import`；已经在某个 Agent 目录里，才 `adopt`。
6. 命令成功且无问题返回 0；冲突、缺失、校验失败返回 1；参数错误返回 2。把 stdout/stderr 里的冲突和断链原样告诉用户。

## 常用调用

```bash
./skillmesh.sh status
./skillmesh.sh sync --dry-run
./skillmesh.sh sync
./skillmesh.sh sync --target claude,codex,cursor,grok
./skillmesh.sh sync -A gemini -A trae
./skillmesh.sh sync --include-global --dry-run
./skillmesh.sh import /path/to/skill --sync
./skillmesh.sh adopt --from claude
./skillmesh.sh enable some-skill --target claude --target grok
./skillmesh.sh clean --orphaned --dry-run
```
