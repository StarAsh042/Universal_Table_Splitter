# 发布与打包（GitHub Actions）

本文档说明自动化打包 / 发布流程，以及**在 GitHub 仓库上需要做的一次性配置**。

> 工作流**不运行任何测试**：CI 只负责打包与发布。
> lint 与 pytest 请在本地跑（`pre-commit install` + `pytest`）。

---

## 1. 工作流做了什么

文件：`.github/workflows/release.yml`

**全部作业都跑在 `windows-latest` 上**——本项目只发布 Windows 产物，不在 Ubuntu / Linux 上打包，
也不产出任何 Linux 制品（无容器镜像、无 `ubuntu-latest`）。

| 作业 | 运行环境 | 产物 | 触发条件 |
|---|---|---|---|
| `windows-exe` | `windows-latest` | 单文件 `exe` + `.sha256` | 标签 `v*` / 手动 |
| `python-dist` | `windows-latest` | `*.whl`、`*.tar.gz`、`SHA256SUMS.txt`（纯 Python，跨平台） | 标签 `v*` / 手动 |
| `release` | `windows-latest` | 创建/更新 **GitHub Release** 并附上前两个作业的全部产物 | 仅标签 `v*` |

> **附件名说明**：`gh` 会把非 ASCII 附件名改写成 `default.<ext>`（实测复现），
> 因此发布用的 exe 统一命名为 **`UniversalTableSplitter.exe`**（并附同名 `.sha256`）。
> exe **内部**的产品名与版本资源仍是「通用表格分割器」，本地 `packaging\build.bat`
> 也照旧输出 `表格分割器.exe` —— 只有上传到 Release 的文件名是 ASCII。

打包用的是仓库里的 `packaging/table_splitter.spec`，与本地 `packaging\build.bat`
是同一份配置：exe 内置 Python 与全部依赖，自带版本资源（属性里能看到版本号）。

---

## 2. 一次性配置（在 GitHub 网页上操作）

### 2.1 令牌：仓库 Secret `Splitter`（推荐配置）

工作流创建 Release 时使用的令牌是：

```yaml
GH_TOKEN: ${{ secrets.Splitter || secrets.GITHUB_TOKEN }}
```

即：**已配置 `Splitter` 就优先用它**；没配置则自动回退到内置 `GITHUB_TOKEN`。
每次运行都会在日志里打印一行 `使用的令牌来源：Splitter` 或 `…：GITHUB_TOKEN`，便于确认。

**创建步骤**

1. 先生成个人访问令牌（PAT）：

   | 类型 | 地址 | 需要的权限 |
   |---|---|---|
   | Fine-grained（推荐） | <https://github.com/settings/personal-access-tokens> | 仓库访问选本仓库；`Contents` → **Read and write** |
   | Classic | <https://github.com/settings/tokens> | 勾 `public_repo`（公开仓库足够）或 `repo` |

2. 添加仓库 Secret：

   ```
   https://github.com/StarAsh042/Universal_Table_Splitter/settings/secrets/actions
   ```

   `New repository secret` → 名称填 **`Splitter`**（大小写敏感，必须完全一致）→ 值粘贴刚才的令牌 → `Add secret`。
   Secret 内容会被 GitHub 自动打码，不会出现在日志里。

**为什么要用 PAT 而不是只用内置令牌**：内置 `GITHUB_TOKEN` 的权限受仓库设置约束，
若仓库（或组织策略）停留在 `Read repository contents and packages permissions`，
`release` 作业会报 `403 Resource not accessible by integration`。PAT 不受该设置约束。

**如果你选择只用内置令牌**（不配置 `Splitter`）：把默认权限放开即可——
`https://github.com/StarAsh042/Universal_Table_Splitter/settings/actions`（即
`Settings` → 左侧 `Actions` → `General`）→ 页面靠下的 **Workflow permissions** →
选 `Read and write permissions` → `Save`。

> 找不到 `Workflow permissions` 时按顺序排查：
> 1. **你没有管理员权限**——`Settings` 标签只对 admin 可见。
> 2. **进了组织设置而不是仓库设置**——地址必须是 `github.com/<用户>/<仓库>/settings/actions`。
> 3. **被组织 / 企业策略接管**——选项被强制选中且「宽松」项变灰，需 org owner 在组织层放开；
>    这种情况直接用 §2.1 的 `Splitter` 令牌即可绕开。
> 4. **新版设置页需要滚动**——该区块在页面靠下位置，用 Ctrl+F 搜 `Workflow` 最快。

### 2.2 其它检查项

- `Settings` → `Actions` → `General` → **Allow all actions and reusable workflows**（默认即是）。
- 计费提醒：`windows-latest` 的计费倍率是 2×，本流程每次发布大约消耗 5–10 分钟额度；
  免费额度用尽后发布作业会排队失败。
- 想同时发布到 PyPI / Docker Hub 等其它平台，需要另外新增作业与对应的 Secret（默认未启用）。

---

## 3. 发布一个版本

### 3.1 触发条件（二选一）

**A. 推送标签（推荐，会自动建 Release）**

```bash
# 1) 先把版本号改好（唯一来源）
#    universal_table_splitter/__init__.py  ->  __version__ = "1.1.0"
# 2) 打标签并推送
git tag -a v1.1.0 -m "1.1.0"
git push origin v1.1.0
```

**B. 手动运行**

`Actions` → `Release` → `Run workflow`：

- 在**标签**上手动运行 → 与 A 等价（会创建 Release）
- 在**分支**上手动运行 → 只产出构建物（Artifacts），不创建 Release，适合先试跑
- `draft`：勾选则创建草稿 Release（不公开，确认后再手动发布）

### 3.2 标签与版本号必须一致

`windows-exe` 作业在标签触发时会**校验** `v1.1.0` 与包内 `__version__` 是否相同；
不一致会直接失败并提示改哪里。这样不会出现"Release 写着 v1.2.0、exe 属性里还是 1.1.0"。

标签形如 `v1.1.0-rc1` 时只比较 `1.1.0` 部分；不是 `x.y.z` 形式的标签会跳过校验。

### 3.3 发布结果

- Release 页面：<https://github.com/StarAsh042/Universal_Table_Splitter/releases>
- Release 附件：`exe`、`exe.sha256`、`*.whl`、`*.tar.gz`、`SHA256SUMS.txt`
- 每次运行的构建物：`Actions` → 选中那次运行 → 底部 `Artifacts`（保留 30 天）

### 3.4 撤回

- 删除 Release：网页上删除，或 `gh release delete v1.1.0`
- 删除标签：`git push --delete origin v1.1.0`（本地 `git tag -d v1.1.0`）

---

## 4. 本地等价操作（不依赖 CI）

```bat
packaging\build.bat                 :: 单文件 exe，输出到 packaging\output\dist
packaging\build.bat -o D:\发布       :: 自定义输出目录
packaging\build.bat -i assets\app.ico -n 表格分割器
```

```bash
python -m build                     # 本地打 wheel / sdist
```

---

## 5. 常见问题

| 现象 | 原因与处理 |
|---|---|
| `403 Resource not accessible by integration` | 令牌没拿到写权限：确认 Secret `Splitter` 的权限（classic 需 `repo`／fine-grained 需 `Contents: Read and write`）与有效期；若没配 `Splitter`，则按 §2.1 放开 `Workflow permissions` |
| 日志显示 `使用的令牌来源：GITHUB_TOKEN` | 说明 `Splitter` 没配上（名称拼写、是否建在**本仓库**下），按 §2.1 添加即可 |
| 找不到 `Workflow permissions` | 见 §2.1 的四条排查；也可以不改它，直接配 `Splitter` 令牌绕开 |
| 版本校验失败 | 标签与 `__version__` 不一致，先改版本号再重新打标签 |
| 手动运行没有产出 Release | 在分支上运行只出 Artifacts；请在标签上运行或直接推标签 |
| exe 在别人机器上被杀软拦截 | PyInstaller 单文件 exe 的常见误报，发布时附上 `.sha256` 便于核对 |
