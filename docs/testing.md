## 1. 后端测试分层

后端测试框架：

- `pytest`
- `pytest-asyncio`
- `pytest-cov`

目录结构：

- `backend/tests/unit/`
- `backend/tests/service/`
- `backend/tests/api/`
- `backend/tests/mcp/`

当前覆盖重点：

- 鉴权中间件与排除路径：`backend/tests/unit/test_auth.py`
- search terms 与查询词展开：`backend/tests/unit/test_search_terms.py`
- changeset/snapshot 的 before/after 语义：`backend/tests/unit/test_snapshot.py`
- GraphService 的创建、更新、别名、删除、版本链：`backend/tests/service/test_graph_service.py`
- GlossaryService 的关键词绑定与召回：`backend/tests/service/test_glossary_service.py`
- SearchIndexer 的索引刷新与搜索结果：`backend/tests/service/test_search_indexer.py`
- 浏览、审核、维护 API：`backend/tests/api/test_api_routes.py`
- MCP 工具与系统视图：`backend/tests/mcp/test_mcp_tools.py`

## 2. 测试隔离策略

后端测试通过 `backend/tests/conftest.py` 统一做环境隔离：

- 默认使用 SQLite 临时库
- 可通过 `TEST_DATABASE_URL` 切到 PostgreSQL
- 每轮测试都重建测试数据库和 snapshot 目录
- 测试时显式覆盖 `DATABASE_URL`、`SNAPSHOT_DIR`、`VALID_DOMAINS`、`CORE_MEMORY_URIS`
- 测试时把 `API_TOKEN` 设为空，避免被本地 `.env` 污染


## 3. 本地运行

安装后端测试依赖：

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

**Linux/macOS:**
```bash
.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

运行全部后端测试：

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\pytest backend/tests
```

**Linux/macOS:**
```bash
.venv/bin/pytest backend/tests
```

带覆盖率运行：

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\pytest backend/tests --cov=backend --cov-report=term-missing
```

**Linux/macOS:**
```bash
.venv/bin/pytest backend/tests --cov=backend --cov-report=term-missing
```

如果想单独验证 PostgreSQL 路径，可以显式指定：

**Windows (PowerShell):**
```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://user:password@127.0.0.1:5432/nocturne_memory?ssl=disable"
.\.venv\Scripts\pytest backend/tests/service backend/tests/api -q
```

**Linux/macOS:**
```bash
export TEST_DATABASE_URL='postgresql+asyncpg://user:password@127.0.0.1:5432/nocturne_memory?ssl=disable'
.venv/bin/pytest backend/tests/service backend/tests/api -q
```

## 4. GitHub Actions

- `.github/workflows/backend-tests.yml`

触发时机：

- `pull_request`
- `push`
- `workflow_dispatch`

执行内容：

1. SQLite 路径下，按 Python `3.10` / `3.12` 矩阵运行 `backend/tests`
2. 额外跑 PostgreSQL smoke
