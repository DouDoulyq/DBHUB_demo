---
name: mall-price-crud
description: 联想商城/EPP 商城物料价格增删改查 — goodsindex schema 专用，含生成列处理、会员组价、确认流程
---

# mall-price-crud — 商城价格管理

管理联想商城和 EPP 商城的商品价格数据。涉及 `goodsindex` schema 下所有表的操作。

---

## 数据模型

| 表 | 用途 | 关键字段 |
|---|------|---------|
| `goodsindex.goods_index_edit` | 商城基础价 | `indexdata` (JSON) 含 `basePrice`、`name`、`mall_type` 等 |
| `goodsindex.enterprise_price_edit_index` | 会员组等级价 | `indexdata` (JSON) 含各等级折扣价 |

---

## ⚠️ 生成列（最重要）

`goodsindex` 下所有**名称类字段**（name、goods_name、title 等）都是 **生成列（generated column）**，由 `indexdata` JSON 自动生成，**禁止直接 UPDATE 列值**。

| 操作目标 | 正确做法 |
|---------|---------|
| 修改名称 | `jsonb_set(indexdata::jsonb, '{name}', '"新名称"'::jsonb)` |
| 修改价格 | `jsonb_set(indexdata::jsonb, '{basePrice}', '99.9'::jsonb)` |
| 修改其他属性 | 更新 `indexdata` JSON 中对应字段 |

错误示例：`UPDATE goodsindex.goods_index_edit SET name='xxx'` → ❌
正确示例：`UPDATE goodsindex.goods_index_edit SET indexdata = jsonb_set(indexdata::jsonb, '{name}', '"xxx"'::jsonb)::json WHERE ... RETURNING *` → ✅

报错 "cannot be updated because it is a generated column" 时，说明你试图直接更新生成列 → 立即改为更新 `indexdata` JSON。

---

## 触发词（强制激活）

用户消息包含以下**任一关键词**时，必须进入价格管理模式：

`改价` `新增物料` `修改商城价格` `调整会员组价` `价格` `物料编码` `SN` `mall_type` `修改名称` `改名字` `商品名称`

SQL 涉及 `goodsindex` schema 下的表时也必须激活。

---

## 操作流程

### 步骤 0：选表（所有操作前必须执行）

用 `search_objects` 遍历 `goodsindex` schema 下所有表，列出表名和用途，让用户确认要操作哪张表。用户未明确选择前，不得执行后续操作。

### 步骤 0.5：查物料分布（改/删时必须执行）

用户给出物料编码后，用 SELECT **在所有 goodsindex 表**中搜索该编码：

```sql
SELECT 'goods_index_edit' AS table_name, COUNT(*) AS cnt FROM goodsindex.goods_index_edit WHERE indexdata::text LIKE '%物料编码%'
UNION ALL
SELECT 'enterprise_price_edit_index', COUNT(*) FROM goodsindex.enterprise_price_edit_index WHERE indexdata::text LIKE '%物料编码%';
```

列出每张表中是否存在该物料、有几条记录。然后问用户：
> 该物料出现在 N 张表中，是否对所有表操作？还是只修改其中某几张？

用户明确选择后才能继续。

### 步骤 1：选择操作类型

增 / 改 / 删 / 查

### 步骤 2：新增物料

依次引导：
1. 物料编码 →
2. 业务类型（mall_type：1=联想商城，2=EPP商城）→
3. 商品名称 →
4. 基础价格 →
5. 代理价（可选）→
6. **预览确认** → 展示完整 INSERT 语句
7. 用户确认后执行 `INSERT INTO ... RETURNING *`

### 步骤 3：改价

1. 先执行**步骤 0.5** 确认范围
2. 选择价格类型：

| 商城类型 | 可选价格类型 |
|---------|------------|
| 联想商城 (mall_type=1) | 基础价 / 会员组价 |
| EPP 商城 (mall_type=2) | 基础价 / 会员组价 |

3. **基础价**：
   - 查对应表，`SELECT indexdata->>'basePrice' AS basePrice FROM goodsindex.goods_index_edit WHERE indexdata::text LIKE '%物料编码%'`
   - 展示当前价格 → 用户输入新价格 →
   - `UPDATE ... SET indexdata = jsonb_set(indexdata::jsonb, '{basePrice}', '新价格'::jsonb)::json WHERE ...`
   - 不要 SET `update_time`（生成列只读）

4. **会员组价**：
   - 查 `enterprise_price_edit_index`，展开 JSON 等级 → 用户选等级 → 输入新折扣价
   - 同样用 `jsonb_set`

5. **展示 diff**：旧值 → 新值汇总表
6. **确认后执行**，末尾加 `RETURNING *`

### 步骤 4：确认机制

所有 INSERT / UPDATE / DELETE **必须先预览 SQL** → 等待用户明确回复「确认」「执行」「OK」等 → 才能执行。

### 步骤 5：验证结果

- INSERT/UPDATE/DELETE 语句末尾必须加 `RETURNING *`
- 从返回值直接确认结果，**不要额外发 SELECT 查询**
- 向用户展示变更后的记录

---

## 价格类型映射

| mall_type | 商城 | 价格类型 |
|-----------|------|---------|
| 1 | 联想商城 | 基础价 / 会员组价 |
| 2 | EPP 商城 | 基础价 / 会员组价 |

---

## 约束

- 仅限 `goodsindex` schema 下的表
- 单次操作 ≤200 条物料编码
- 所有写操作必须 **先预览 → 用户确认 → 执行**
- 修改前必须确认物料在哪些表中存在，用户选择范围后再执行
- 名称类字段是生成列，必须通过修改 `indexdata` JSON 来更新

---

## 应用到 Skill 系统

当你的宿主智能体有 Skill 追踪机制时：
- 触发条件：SQL 或参数中包含 `goodsindex`，或用户提到触发词
- 标记名：`mall-price-crud`
