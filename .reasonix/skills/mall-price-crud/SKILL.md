---
name: mall-price-crud
description: 联想商城/EPP 商城物料价格增删改查 — goodsindex schema 专用，含生成列处理、会员组价、字段语义确认、全表覆盖
triggers:
  - goodsindex
  - 商品
  - 物料
  - 商城
  - 价格
  - 改价
  - 新增物料
  - 修改商城价格
  - 调整会员组价
  - 物料编码
  - SN
  - mall_type
  - 修改名称
  - 改名字
  - 改名称
  - 商品名称
  - 删除物料
  - 查询物料
  - 商品编码
  - products_code
  - 物料号
  - 基础价
  - 会员价
  - 等级价
  - 折扣价
  - 增
  - 删
  - 改
  - 查
  - 新增
  - 删除
  - 修改
  - 查询
  - 物料号
  - 基础价格
  - 产品编码
  - 上线
  - 上架
  - 下架
  - 生成列
  - indexdata
  - basePrice
  - goods_code
  - material_number
---

# mall-price-crud — 商城价格管理

管理联想商城和 EPP 商城的商品价格数据。涉及 `goodsindex` schema 下所有表的操作。

> 🚨 **强制性要求：只要用户提到「商品」「价格」「名称」「编码」「物料」「商城」中任意词，或者你准备操作 `goodsindex` schema 下的任何表，你必须先加载此 skill 并完整执行从「步骤 0」开始的全部流程。禁止直接查询数据库。禁止跳过字段确认直接搜索。** 🚨

---

## 核心原则

1. **字段语义必须先确认**：用户使用的自然语言词汇（如「商品编码」「物料号」「价格」「名称」）在你查询数据库前，必须先逐项确认对应的数据库字段名。
2. **全表遍历，禁止默认单表**：改/删/查物料时，**第一步必须是跨表搜索**（步骤 1），在所有价格表中查找该物料。**绝对禁止未经搜索就直接修改 `goods_index_edit`**，即使你认为「大概率在那里」也不行。必须列出每张表的命中数，让用户选择操作哪些表。
3. **先预览后执行**：所有写操作（INSERT/UPDATE/DELETE）必须先展示 SQL 预览，等待用户明确确认后才能执行。

---

## 数据模型

### 价格相关核心表（按优先级排序）

| 表 | 用途 | 唯一标识字段 | 价格字段 |
|---|------|------------|---------|
| `goodsindex.goods_index_edit` | 商城基础价（编辑表） | `material_number` (varchar) / `goods_code` (integer) / `products_code` (integer) / `id` (uuid varchar) | `indexdata` JSON 内 `basePrice`；列 `base_price` (double) |
| `goodsindex.enterprise_price_edit_index` | 会员组等级价（编辑表） | `material_number` (varchar) / `goods_code` (bigint) / `goods_code2` (varchar) / `id` (uuid varchar) | `price` JSON 数组 `[{levelId, levelName, discountPrice}]`；`indexdata` JSON 内 `price` |
| `goodsindex.goods_index` | 商城基础价（主表） | 同上 | `indexdata` JSON 内 `basePrice` |
| `goodsindex.goods_online_index` | 商城基础价（线上表） | 同上 | `indexdata` JSON 内 `basePrice` |
| `goodsindex.enterprise_price_online_index` | 会员组等级价（线上表） | 同上 | `price` JSON 数组 |
| `goodsindex.goods_price_rel_index` | 价格关联表 | `goods_code` 等 | 关联价格信息 |

### goods_index_edit 关键字段详解

| 数据库字段 | 中文含义 | 类型 | 说明 |
|-----------|---------|------|------|
| `id` | 记录 UUID | varchar | 主键 |
| `material_number` | 物料编码（SN） | varchar | 用户常称「物料编码」「SN」「物料号」 |
| `goods_code` | 商品编码 | integer | 用户常称「商品编码」「goods_code」 |
| `products_code` | 产品编码 | integer | 用户常称「产品编码」「products_code」 |
| `goods_id` | 商品 ID | varchar | UUID |
| `code` | 内部序号 | bigint | 自增序号 |
| `name` | 商品名称 | varchar | **生成列**，由 `indexdata.name` 自动生成，禁止直接 UPDATE |
| `mall_type` | 商城类型 | integer | 1=联想商城，2=EPP 商城 |
| `base_price` | 基础价格 | double | **生成列**，由 `indexdata.basePrice` 自动生成，禁止直接 UPDATE |
| `fa_name` | FA 名称 | varchar | |
| `check_status` | 审核状态 | integer | |
| `online_status` | 上线状态 | integer | |
| `indexdata` | 核心 JSON | json | 包含 name/basePrice/mallType/materialNumber/productsCode 等 |
| `products_index` | 产品 JSON | json | 嵌套产品详情（含 brandName/categoryName/parameters 等） |
| `create_time` | 创建时间 | bigint | 毫秒时间戳 |
| `update_time` | 更新时间 | bigint | 毫秒时间戳 |

### indexdata JSON 内部关键字段（goods_index_edit）

| JSON 路径 | 中文含义 | 示例值 |
|-----------|---------|--------|
| `indexdata.name` | 商品名称 | `"YOGA 710-14IKB..."` |
| `indexdata.basePrice` | 基础价格 | `6099` |
| `indexdata.mallType` | 商城类型 | `1` (联想商城) / `2` (EPP 商城) |
| `indexdata.mallName` | 商城名称 | `"联想商城"` |
| `indexdata.materialNumber` | 物料编码 | `"80V4S00000"` |
| `indexdata.productsCode` | 产品编码 | `58975` |
| `indexdata.code` | 内部编码 | `58975` |
| `indexdata.cost` | 成本 | `0` |
| `indexdata.mediaPrice` | 媒体价 | `6999` |

### enterprise_price_edit_index 关键字段详解

| 数据库字段 | 中文含义 | 类型 | 说明 |
|-----------|---------|------|------|
| `id` | 记录 UUID | varchar | 主键 |
| `material_number` | 物料编码 | varchar | |
| `goods_code` | 商品编码 | bigint | |
| `goods_code2` | 商品编码 2 | varchar | 备用编码 |
| `goods_name` | 商品名称 | varchar | |
| `mall_name` | 商城名称 | varchar | |
| `group_code` | 会员组编码 | varchar | 如 `"120"` |
| `group_name` | 会员组名称 | varchar | 如 `"企业默认组"` |
| `price` | 会员等级价 | json | 数组 `[{levelId, levelName, discountPrice}]` |
| `indexdata` | 核心 JSON | json | 同上 + activity/fa 信息 |
| `activity_code` | 活动编码 | bigint | |
| `activity_name` | 活动名称 | varchar | |
| `activity_type` | 活动类型 | integer | |
| `activity_status` | 活动状态 | integer | |
| `discount_type` | 折扣类型 | integer | |

### price JSON 内部结构（enterprise_price_edit_index）

```json
[
  {"levelId": "1025", "levelName": "黄金会员", "discountPrice": "4"},
  {"levelId": "1026", "levelName": "铂金会员", "discountPrice": "4"},
  {"levelId": "1027", "levelName": "钻石会员", "discountPrice": "4"}
]
```

---

## ⚠️ 生成列 + json 类型（最重要）

`goodsindex` 下 **goods_index_edit / goods_index / goods_online_index** 三张表中，**`name` 和 `base_price` 都是生成列（ALWAYS GENERATED）**，由 `indexdata` JSON 自动派生：

| 显示列 | 生成表达式 | 对应 JSON 路径 |
|-------|-----------|---------------|
| `name` | `(indexdata::jsonb ->> 'name')` | `indexdata.name` |
| `base_price` | `(NULLIF((indexdata::jsonb ->> 'basePrice'), ''))::double precision` | `indexdata.basePrice` |

**禁止直接 UPDATE `name` 或 `base_price` 列**，否则报错：
> `column "base_price" can only be updated to DEFAULT`
> `column "name" can only be updated to DEFAULT`

**唯一正确的做法：通过更新 `indexdata` JSON 来间接修改名称和价格，两个字段一次完成。**

此外，`indexdata` 列的类型是 **`json`（不是 `jsonb`）**。`jsonb_set()` 函数只接受 `jsonb` 参数，返回 `jsonb`。因此修改 indexdata 必须**双重转型**：

```
indexdata（json） → ::jsonb → jsonb_set(...) → ::json → 写回 json 列
```

| 操作目标 | 正确 SQL 片段 |
|---------|-------------|
| 仅修改名称 | `SET indexdata = jsonb_set(indexdata::jsonb, '{name}', '"新名称"'::jsonb)::json` |
| 仅修改价格 | `SET indexdata = jsonb_set(indexdata::jsonb, '{basePrice}', '7199'::jsonb)::json` |
| **同时修改名称+价格** | `SET indexdata = jsonb_set(jsonb_set(indexdata::jsonb, '{name}', '"新名称"'::jsonb), '{basePrice}', '7199'::jsonb)::json` |
| 修改其他 JSON 属性 | 同上模式，必须带 `::jsonb` 输入转型和 `::json` 输出转型 |

错误示例：`UPDATE goodsindex.goods_index_edit SET name='xxx'` → ❌
正确示例：`UPDATE goodsindex.goods_index_edit SET indexdata = jsonb_set(indexdata::jsonb, '{name}', '"xxx"'::jsonb)::json WHERE ... RETURNING *` → ✅

报错 "cannot be updated because it is a generated column" → 你在直接改生成列，改为更新 indexdata。
报错 "function jsonb_set(json, ...) does not exist" → 你忘了 `::jsonb` 转型。
写入后数据格式异常 → 你忘了末尾的 `::json` 回转型。

---

## 触发词（强制激活）

用户消息包含以下**任一关键词**时，必须进入价格管理模式：

`改价` `新增物料` `修改商城价格` `调整会员组价` `价格` `物料编码` `SN` `mall_type` `修改名称` `改名字` `商品名称` `删除物料` `查询物料` `商品编码` `products_code` `物料号` `基础价` `会员价` `等级价` `折扣价`

SQL 涉及 `goodsindex` schema 下的表时也必须激活。

---

## 操作流程

### ⛔ 最高优先级规则

1. **字段确认之后，必须立即执行全表搜索 SQL**——不得跳过、不得只查一张表、不得根据"经验"猜测该改哪张表。
2. **全表搜索 SQL 执行完后，必须逐表汇报 5 张表的查询结果**——即使某表命中 0 条也要列出，一张都不能少。**禁止只汇报有数据的表、禁止只汇报第一张表、禁止在汇报完之前做任何其他操作。**
3. 不执行全表搜索 + 不逐表完整汇报 = 违反此 Skill。

---

## 新增物料

新增物料不需要全表搜索，但需要字段确认。

依次引导用户提供（缺一不可）：
1. **物料编码** (material_number) →
2. **业务类型**（mall_type：1=联想商城，2=EPP商城）→
3. **商品名称** →
4. **基础价格** (basePrice) →
5. 代理价（可选）→
6. **预览确认** → 展示完整 INSERT 语句，包含 `RETURNING *`
7. 用户确认后执行

INSERT 示例：
```sql
-- ❌ 错误：不能直接写 base_price（它是生成列）
-- INSERT INTO goodsindex.goods_index_edit (id, code, material_number, mall_type, indexdata, base_price)

-- ✅ 正确：只写 indexdata，base_price 和 name 自动派生
INSERT INTO goodsindex.goods_index_edit (id, code, material_number, mall_type, indexdata)
VALUES (
  gen_random_uuid(),
  (SELECT COALESCE(MAX(code), 0) + 1 FROM goodsindex.goods_index_edit),
  '物料编码',
  1,
  jsonb_build_object(
    'name', '商品名称',
    'basePrice', 99.9,
    'mallType', 1,
    'materialNumber', '物料编码'
  )::json
)
RETURNING *;
```

---

## 改价（完整流程）

改价操作分 3 个阶段，**必须按顺序执行，禁止跳过任何阶段**。

### 改价 · 阶段 1：字段语义确认

执行**步骤 0**（见上方）。用户回复字母确认字段映射后，立即进入阶段 2，**不要等用户再说"继续"**。

### 改价 · 阶段 2：全表搜索（🚫 禁止跳过）

**确认字段后，你必须立即执行以下 SQL。不能跳过、不能只查一张表、不能说"大概率在 goods_index_edit 所以我直接改那"。**

```sql
SELECT 'goods_index_edit' AS table_name, COUNT(*) AS cnt
FROM goodsindex.goods_index_edit
WHERE material_number = '用户提供的编码'
   OR goods_code::text = '用户提供的编码'
   OR products_code::text = '用户提供的编码'

UNION ALL

SELECT 'enterprise_price_edit_index', COUNT(*)
FROM goodsindex.enterprise_price_edit_index
WHERE material_number = '用户提供的编码'
   OR goods_code::text = '用户提供的编码'
   OR goods_code2 = '用户提供的编码'

UNION ALL

SELECT 'goods_index', COUNT(*)
FROM goodsindex.goods_index
WHERE material_number = '用户提供的编码'
   OR goods_code::text = '用户提供的编码'

UNION ALL

SELECT 'goods_online_index', COUNT(*)
FROM goodsindex.goods_online_index
WHERE material_number = '用户提供的编码'
   OR goods_code::text = '用户提供的编码'

UNION ALL

SELECT 'enterprise_price_online_index', COUNT(*)
FROM goodsindex.enterprise_price_online_index
WHERE material_number = '用户提供的编码'
   OR goods_code::text = '用户提供的编码';
```

用精确匹配 `=`，不用 `LIKE`。

**SQL 执行完后，你必须用以下格式逐表汇报查询结果，5 张表一张都不能少（即使命中 0 条也要列出）：**

> 🔍 全表搜索结果：
>
> **A.** goods_index_edit — N 条（商城基础价编辑表）
> **B.** enterprise_price_edit_index — M 条（会员组等级价编辑表）
> **C.** goods_index — P 条（商城基础价主表）
> **D.** goods_online_index — Q 条（商城基础价线上表）
> **E.** enterprise_price_online_index — R 条（会员组等级价线上表）
>
> 请回复要操作哪些表（如「A B」= 操作 A 和 B，「全部」= 所有表）。

**严禁只汇报部分表。即使某表命中 0 条也必须写上 "0 条"。不许多说其他内容，先汇报完 5 张表再等用户选择。**

用户选表后回显确认，然后进入阶段 3。

### 改价 · 阶段 3：执行修改

**只修改用户在阶段 2 中选中的表，不要自行增减。**

| 用户选中的表 | 价格类型 | SQL 要点 |
|------------|---------|---------|
| `goods_index_edit` / `goods_index` / `goods_online_index` | 基础价 | `UPDATE {表} SET indexdata = jsonb_set(indexdata::jsonb, '{basePrice}', '新价格'::jsonb)::json WHERE ... RETURNING *` |
| `enterprise_price_edit_index` / `enterprise_price_online_index` | 会员组价 | `jsonb_set` 更新 `price` 或 `indexdata` JSON，同样需要 `::jsonb` → `::json` 双重转型 |

**基础价**：查当前价 → 用户输入新价 → 执行 UPDATE（注意 `::jsonb` 和 `::json` 都不能省略）

**同时修改名称+价格时**，嵌套 `jsonb_set`：
```sql
UPDATE goodsindex.goods_index_edit
SET indexdata = jsonb_set(
    jsonb_set(indexdata::jsonb, '{name}', '"新名称"'::jsonb),
    '{basePrice}', '7199'::jsonb
  )::json
WHERE ...
RETURNING *;
```
无需单独改 `base_price` 或 `name` 列——它们自动从 `indexdata` 派生。

**会员组价**：查当前等级 → 用户选等级 → 输入新折扣价 → `UPDATE ... RETURNING *`

展示 diff（旧值→新值汇总表）→ 用户确认 → 执行。

---

## 删除物料（完整流程）

与改价相同的 3 阶段流程：
1. **阶段 1**：字段语义确认
2. **阶段 2**：全表搜索（同上 SQL，禁止跳过）→ 用户选表
3. **阶段 3**：展示将删除的记录 → 用户确认 → `DELETE FROM ... RETURNING *`

---

## 查询物料（完整流程）

1. **阶段 1**：字段语义确认
2. **阶段 2**：全表搜索（同上 SQL，禁止跳过）→ 展示各表命中数
3. **阶段 3**：根据用户需求查询具体数据

---

## 确认机制

所有 INSERT / UPDATE / DELETE **必须先预览 SQL** → 等待用户明确回复「确认」「执行」「OK」「可以」等 → 才能执行。

预览格式：
```
⚠️ 即将执行以下操作：

表：goodsindex.goods_index_edit
操作：UPDATE
条件：material_number = '80V4S00000'
变更：basePrice 6099 → 5599

SQL：
UPDATE goodsindex.goods_index_edit
SET indexdata = jsonb_set(indexdata::jsonb, '{basePrice}', '5599'::jsonb)::json
WHERE material_number = '80V4S00000'
RETURNING *;

是否确认执行？请回复「确认」或「取消」。
```

---

## 验证结果

- INSERT/UPDATE/DELETE 语句末尾必须加 `RETURNING *`
- 从返回值直接确认结果，**不要额外发 SELECT 查询**
- 向用户展示变更后的记录

---

## 价格类型映射

| mall_type | 商城 | 价格类型 | 对应表 |
|-----------|------|---------|--------|
| 1 | 联想商城 | 基础价 | `goods_index_edit` |
| 1 | 联想商城 | 会员组价 | `enterprise_price_edit_index` |
| 2 | EPP 商城 | 基础价 | `goods_index_edit` |
| 2 | EPP 商城 | 会员组价 | `enterprise_price_edit_index` |

---

## 约束

- 仅限 `goodsindex` schema 下的表
- 单次操作 ≤200 条物料编码
- 所有写操作必须 **先预览 → 用户确认 → 执行**
- 所有操作前必须先做**字段语义确认**（步骤 0），未确认不得查询
- 改/删/查前必须执行**全表搜索**（步骤 1），覆盖 `goods_index_edit`、`enterprise_price_edit_index`、`goods_index`、`goods_online_index`、`enterprise_price_online_index` 五张表
- 名称类字段是生成列，必须通过修改 `indexdata` JSON 来更新
- 物料搜索用精确匹配 `=`，不用 `LIKE`
- **🚫 禁止默认改单表**：绝对禁止在未执行步骤 1 全表搜索的情况下，直接修改 `goods_index_edit` 或任何单张表。即使你认为"大概率在那张表里"也不行。必须先搜索全部 5 张表 → 列出命中结果 → 让用户选择。

---

## 参考资料

| 文件 | 内容 |
|------|------|
| `references/example-code-1004009.md` | 实战例子：修改商品编码 1004009 的名称和价格，含字段确认、全表搜索 SQL、生成列更新语法、会话数据 |

---

## 应用到 Skill 系统

当你的宿主智能体有 Skill 追踪机制时：
- 触发条件：SQL 或参数中包含 `goodsindex`，或用户提到触发词
- 标记名：`mall-price-crud`