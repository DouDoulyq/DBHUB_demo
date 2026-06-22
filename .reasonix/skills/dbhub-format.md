---
name: dbhub-format
description: 约束 DBHub 输出格式：Markdown 表格 + 行限制 + 类型感知格式化（日期/金额/NULL/JSON）
triggers:
  - execute_sql
  - search_objects
  - SELECT
  - 查询
  - 格式化
---

# dbhub-format — SQL 查询结果格式化规范

每次调用 `execute_sql` 或 `search_objects` 后，**必须**按以下规则格式化输出再呈现给用户。

---

## 1. 自动 LIMIT

在生成 SELECT 语句时：
- **未指定 LIMIT** → 自动追加 `LIMIT 50`
- **用户指定 LIMIT ≤500** → 尊重用户
- **用户指定 LIMIT >500** → 提示 `⚠️ LIMIT N 超过推荐上限 500，可能影响性能`
- INSERT/UPDATE/DELETE 不追加 LIMIT

检测方法：移除 SQL 中的字符串常量后，用 `\bLIMIT\s+\d+` 检查。

---

## 2. Markdown 表格输出

所有查询结果以 Markdown 表格呈现：

```
**查询：** `SELECT ...`
**返回：** N 行

| **col1** | **col2** | ... |
|------|------|------|
| val1 | val2 | ... |
```

顶部必须包含查询 SQL 和行数。

---

## 3. 类型感知格式化

根据列名和列类型智能格式化每个单元格：

### NULL
任何 `NULL` 值 → 显示 `-`

### 日期/时间
列类型含 `date`/`timestamp`/`timestamptz` → 格式化为 `YYYY-MM-DD HH:MM:SS` 或 `YYYY-MM-DD`

### 金额
列名含 `price`/`amount`/`cost`/`fee`/`money`/`baseprice`/`discount`（不区分大小写）且值为数字 → `¥1,234.00`

### 布尔
列类型为 `bool`/`boolean` → `✅` (true) / `❌` (false)

### JSON
列类型为 `json`/`jsonb`，或字符串值以 `{`/`[` 开头 → 美化展开（indent=2，最多 2 层）

### 长文本
字符串长度 >100 字符 → 截断到 100 字符 + `...`

### 其他
直接转为字符串

---

## 4. 列数提示

查询返回 **>8 列**时，在表格后追加：
```
> ⚠️ 返回 N 列，是否需要仅展示关键列？
```

---

## 5. 空结果

无结果时输出：
```
**查询：** `SELECT ...`

*(无结果)*
```

---

## 6. search_objects 格式化

`search_objects` 返回的 JSON 数组同样转为 Markdown 表格。单个对象则用 JSON 美化输出。

---

## 7. 输出结构模板

最终输出按此顺序组装：

```
**查询：** `<SQL>`
**返回：** <行数> 行[ · <耗时>ms]

<Markdown 表格>

<列数提示（如有）>
```

---

## 应用到 Skill 系统

当你的宿主智能体有 Skill 追踪机制时：
- 每次成功格式化后标记使用了 `dbhub-format`
- 触发条件：任何 `execute_sql` 或 `search_objects` 调用后执行格式化
