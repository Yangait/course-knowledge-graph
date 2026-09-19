# 计算机专业课程知识图谱问答系统

本项目包含九门计算机专业课程的知识图谱数据、Neo4j 增量导入工具，以及基于知识图谱和千问模型的命令行问答系统。

## 当前数据规模

- 课程：9 门
- 节点：2701 个
- 课程内部关系：10472 条
- 跨课程关系：158 条
- 关系总数：10630 条
- 实体类型：16 种
- 关系类型：18 种

## 目录结构

```text
大创/
├─ 知识图谱/                Excel 原始成果与九门课程导入审计
├─ neo4j_import_files/      CSV、Cypher 和增量导入脚本
└─ kg_qa_system/            Python 问答系统
   ├─ tests/                不联网的自动化单元测试
   ├─ api.py                FastAPI HTTP 接口
   ├─ static/               FastAPI 原生聊天网页
   ├─ live_acceptance.py    连接真实服务的端到端验收
   ├─ web_app.py            Streamlit 网页界面
   ├─ requirements.txt      Python 依赖清单
   ├─ .env.example          环境配置模板
   ├─ start.bat             Windows 命令行版启动脚本
   └─ start_web.bat         Windows 网页版启动脚本
```

## 环境要求

- Windows 10/11
- Python 3.12
- Neo4j 5 或更高版本
- 可用的千问 OpenAI 兼容接口和 API 密钥

## 首次安装

在 PowerShell 中进入问答系统目录：

```powershell
cd .\kg_qa_system
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

复制环境配置模板：

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`，填写 Neo4j 密码、千问 API 密钥和兼容接口地址。`.env` 已被 `.gitignore` 忽略，不要把真实密钥提交到版本库。

## 导入知识图谱

1. 启动 Neo4j 中用于本项目的数据库。
2. 确认 `kg_qa_system/.env` 中的 Neo4j 配置正确。
3. 在项目根目录执行：

```powershell
.\kg_qa_system\.venv\Scripts\python.exe .\neo4j_import_files\import_incremental.py
```

增量导入脚本使用 `MERGE`，重复执行不会按相同 `node_id` 或 `edge_id` 创建重复数据。详细说明见 `neo4j_import_files/README_导入步骤.txt`。

## 启动网页版问答系统

推荐双击：

```text
kg_qa_system\start_web.bat
```

脚本会启动本地 Streamlit 服务并打开浏览器。默认访问地址为：

```text
http://localhost:8501
```

也可以在 PowerShell 中执行：

```powershell
cd .\kg_qa_system
.\.venv\Scripts\python.exe -m streamlit run .\web_app.py
```

网页版支持：

- 多轮问答记录
- 示例问题快捷入口
- Neo4j 连接与数据规模展示
- 回答模式、模型、Token 和图谱结果数量展示
- 问题解析结果与图谱证据摘要
- 连接异常和模型调用异常提示

## 启动 FastAPI 接口

在 VS Code 中打开项目文件夹，然后在终端执行：

```powershell
cd .\kg_qa_system
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

服务启动后可以访问：

```text
聊天网页：http://127.0.0.1:8000/
接口文档：http://127.0.0.1:8000/docs
健康检查：http://127.0.0.1:8000/api/health
```

聊天网页和 API 使用同一个 FastAPI 服务，不需要单独启动前端，也不需要跨域配置。

PowerShell 手动测试健康检查：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/health"
```

PowerShell 手动提交问题：

```powershell
$body = @{ question = "栈有哪些操作？" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/ask" -ContentType "application/json" -Body $body
```

调用 `/api/ask` 会使用千问接口并消耗 Token；自动化测试中的问答函数均为模拟，不会产生模型费用。

## 启动命令行版问答系统

可以双击：

```text
kg_qa_system\start.bat
```

也可以在 PowerShell 中执行：

```powershell
cd .\kg_qa_system
.\.venv\Scripts\python.exe .\qa_system.py
```

输入 `退出`、`exit` 或 `quit` 可以结束程序。

## 自动化测试

单元测试不连接 Neo4j、不调用千问接口，因此不会消耗 Token：

```powershell
cd .\kg_qa_system
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

测试覆盖以下内容：

- 关系关键词和查询方向识别
- 模型解析结果的清洗与白名单校验
- 实体未找到、唯一匹配、歧义和关系上下文消歧
- 问答编排中的图谱检索与大模型回退路径

## 真实端到端验收

端到端验收会连接 Neo4j 并调用千问接口，会消耗少量 Token：

```powershell
cd .\kg_qa_system
.\.venv\Scripts\python.exe .\live_acceptance.py
```

也可以传入自定义问题：

```powershell
.\.venv\Scripts\python.exe .\live_acceptance.py "虚拟内存需要先学什么？"
```

脚本会检查数据库连接、节点数量、问答状态和答案是否为空，并以退出码 `0` 表示验收通过。

## 人工调试入口

以下脚本用于单项人工调试，不会被自动测试框架误识别：

```text
manual_entity_linker.py
manual_question_parser.py
manual_llm_client.py
```

## 常见问题

### 提示没有读取到环境变量

确认 `kg_qa_system/.env` 已创建，并且配置项名称与 `.env.example` 一致。

### Neo4j 连接失败

确认数据库已经启动，URI、用户名、密码和数据库名称正确。

### 千问连接失败

检查 API 密钥、兼容接口地址、网络权限以及模型名称是否可用。

### 系统 Python 提示缺少模块

请使用 `.venv\Scripts\python.exe`，不要直接使用未安装项目依赖的系统 Python。
