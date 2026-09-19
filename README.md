# 计算机专业知识图谱问答与导图系统

当前使用已导入 Neo4j 的26门课程统一知识图谱，沿用原有千问模型配置。支持按课程检索、指定知识点问答、来源定位和完整课程导图浏览。

## 快速使用

1. 启动 Neo4j 数据库。
2. 双击 `kg_qa_system/start_web.bat`。
3. 问答页面：http://127.0.0.1:8000
4. 导图页面：http://127.0.0.1:8000/graph

详细操作与限制见 [26门课程使用说明](使用说明_26门课程.md)。旧版 Streamlit 网页已停用并归档，当前统一使用 `kg_qa_system/start_web.bat`。

## 数据规模

- 26门课程，18,391个新版主知识节点。
- 统一包22,891个实体、32,606条关系，包括旧版补充内容、注释及辅助结构。
- 1,039张配图，保存路径与知识点归属；未进行图片内容识别。
- 原九门课数据库数据保留，新版使用独立标签和版本编号。

## 目录

- `unified_kg/`：统一数据、课程导图、校验与导入报告。
- `kg_qa_system/`：问答、网页、Neo4j检索及测试。
- `tools/`：数据整理、校验和导入程序。
- `26门课程知识图谱_最终数据_含图片/`：原始解析成果与图片，需要保留。
- `neo4j_import_files/`、`知识图谱/`：旧版导入文件与Excel资料。

## 安装与配置

使用 Python 3.12，在 `kg_qa_system` 中创建 `.venv`，安装 `requirements.txt`，从 `.env.example` 复制出 `.env` 并填写已有的 Neo4j 与千问配置。实际模型由 `.env` 中 `FAST_MODEL` 和 `STRONG_MODEL` 决定。

```powershell
cd kg_qa_system
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

已有配置时不要覆盖 `.env`。版本库不要包含真实密钥。

## 验证与导入

离线测试：

```powershell
cd kg_qa_system
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

数据整理、校验与Neo4j导入见 [接入说明](unified_kg/Neo4j接入说明.md)。普通测试不联网、不调用模型。真实问答会将问题与检索证据发送到配置的模型接口并消耗Token。

API文档：http://127.0.0.1:8000/docs

旧版文档保留为 `README_九门课程旧版.md`，仅供历史对照。
