# MCP Tool Reference

> 本文档是 Nocturne Memory MCP Server 提供的 7 个工具的完整参数说明。
> 安装 MCP 后，AI 可以直接通过 tool docstring 获取这些信息，无需手动查阅。

---

## `read_memory(uri)`
读取一条记忆。返回内容、metadata 和子节点列表。

| 参数 | 类型 | 说明 |
|------|------|------|
| `uri` | `str` | 记忆的 URI，如 `"core://agent"` |

**特殊系统 URI：**
- `system://boot` — 加载 Dashboard Settings / `config.json` 中配置的 Boot URIs；使用命名空间时优先读取当前 namespace 的配置，未设置时降级到全局 Boot URIs
- `system://index/<domain>` — 特定域名记忆索引
- `system://recent` — 最近修改的 10 条记忆
- `system://recent/N` — 最近修改的 N 条记忆
- `system://glossary` — 全量关键词库及节点引用映射
- `system://diagnostic/<domain>` — 记忆健康诊断报告（检出过时、拥挤、孤儿节点等结构性问题）

---

## `create_memory(parent_uri, content, priority, disclosure, title?)`
在指定父节点下创建新记忆。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `parent_uri` | `str` | ✅ | 父节点 URI。强调联想相关性（What/主题），如 `core://user/health`，不要用无意义的容器如 `core://logs`。 |
| `content` | `str` | ✅ | 记忆内容（支持 Markdown） |
| `priority` | `int` | ✅ | 优先级（0=最高，数字越小越优先） |
| `disclosure` | `str` | ✅ | 触发条件：描述"在什么情况下该想起这条记忆" |
| `title` | `str` | ❌ | 路径名称（仅限 `a-z`, `0-9`, `_`, `-`）。不填则自动分配序号 |

```
create_memory("core://", "Bluesky 使用规则...", priority=2, disclosure="当我准备发 Bluesky 时", title="bluesky_manual")
```

---

## `update_memory(uri, ...)`
更新已有记忆。支持两种互斥的内容编辑模式：

**Patch 模式**（精确替换）：
| 参数 | 说明 |
|------|------|
| `old_string` | 要替换的原文（必须在内容中唯一匹配） |
| `new_string` | 替换后的新文本。设为 `""` 可删除该段落 |

**Append 模式**（追加）：
| 参数 | 说明 |
|------|------|
| `append` | 追加到内容末尾的文本 |

**Metadata 更新（可与上述模式组合）：**
| 参数 | 说明 |
|------|------|
| `priority` | 新的优先级 |
| `disclosure` | 新的触发条件 |

> ⚠️ **没有全量替换模式。** 必须通过 `old_string/new_string` 显式指定修改内容，防止意外覆盖。
> ⚠️ **更新前必须先 `read_memory`**，确认你知道自己在改什么。

---

## `delete_memory(uri)`
删除一条记忆的一条访问路径（不伤及记忆的正文）。

| 参数 | 类型 | 说明 |
|------|------|------|
| `uri` | `str` | 要删除的 URI |

---

## `add_alias(new_uri, target_uri, priority, disclosure)`
为已有记忆创建别名路径。**不是复制**——是同一段内容的新入口，可以设置独立的 priority 和 disclosure。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `new_uri` | `str` | ✅ | 新的别名 URI |
| `target_uri` | `str` | ✅ | 指向的目标 URI |
| `priority` | `int` | ✅ | 此别名的独立优先级 |
| `disclosure` | `str` | ✅ | 此别名的独立触发条件 |

---

## `manage_triggers(uri, add?, remove?)`
为记忆节点绑定触发词，为记忆增加超越父子层级的横向召回通道。当任何记忆正文中出现该触发词时，系统会自动在底部显示指向该节点的超链接。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `uri` | `str` | ✅ | 目标节点 URI |
| `add` | `List[str]` | ❌ | 要绑定的触发词列表，如 `["Salem", "User"]` |
| `remove` | `List[str]` | ❌ | 要解绑的触发词列表 |

> 💡 **查询全局触发词库：** 执行 `read_memory("system://glossary")`

---

## `search_memory(query, domain?, limit?)`
按关键词搜索记忆内容和路径。使用**全文检索**，不是语义搜索。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | `str` | ✅ | 搜索关键词（词项全文检索） |
| `domain` | `str` | ❌ | 限定搜索域（如 `"core"`, `"writer"`） |
| `limit` | `int` | ❌ | 最大返回数量（默认 10） |
