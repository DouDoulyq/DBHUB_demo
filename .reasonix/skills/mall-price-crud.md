---
name: mall-price-crud
description: 联想商城/EPP 商城物料价格增删改查 — goodsindex schema 专用，含生成列处理、会员组价、字段语义确认、全表覆盖
triggers:
  - 改价
  - 新增物料
  - 修改商城价格
  - 调整会员组价
  - 价格
  - 物料编码
  - SN
  - mall_type
  - 修改名称
  - 改名字
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
  - goodsindex
---

# mall-price-crud — 商城价格管理

管理联想商城和 EPP 商城的商品价格数据。涉及 `goodsindex` schema 下所有表的操作。

---

## 核心原则

1. **字段语义必须先确认**：用户使用的自然语言词汇（如「商品编码」「物料号」「价格」「名称」）在你查询数据库前，必须先逐项确认对应的数据库字段名。
2. **全表覆盖不遗漏**：查询物料时，必须在 `goodsindex` schema 下**所有相关的价格表中**搜索，不得只查单表。
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
| `name` | 商品名称 | varchar | **生成列**，由 `indexdata.name` 自动生成 |
| `mall_type` | 商城类型 | integer | 1=联想商城，2=EPP 商城 |
| `base_price` | 基础价格 | double | 冗余列 |
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

`改价` `新增物料` `修改商城价格` `调整会员组价` `价格` `物料编码` `SN` `mall_type` `修改名称` `改名字` `商品名称` `删除物料` `查询物料` `商品编码` `products_code` `物料号` `基础价` `会员价` `等级价` `折扣价`

SQL 涉及 `goodsindex` schema 下的表时也必须激活。

---

## 操作流程

### 步骤 0：字段语义确认（⚠️ 所有操作前强制执行）

用户在自然语言中提到的概念，**必须先逐一映射到数据库字段后向用户确认**，不得自行猜测。确认通过后才能进入下一步。

**常见映射表：**

| 用户可能说的词 | 可能的数据库字段 | 确认问题示例 |
|-------------|---------------|------------|
| 商品编码 / 商品编号 | `goods_code` (integer) 或 `products_code` (integer) | "你说的「商品编码」是指 `goods_code` 还是 `products_code`？" |
| 物料编码 / SN / 物料号 | `material_number` (varchar) | "你说的「物料编码」是指 `material_number` 吗？" |
| 价格 / 基础价 / 原价 | `indexdata.basePrice` 或 `base_price` | "你说的「价格」是指基础价格（basePrice）吗？" |
| 会员价 / 等级价 / 折扣价 | `price[].discountPrice` (enterprise_price_edit_index) | "你说的「会员价」是指 `enterprise_price_edit_index` 表中的等级折扣价吗？" |
| 名称 / 商品名称 | `name` (生成列) 或 `indexdata.name` | "你说的「名称」是指商品名称（indexdata 中的 name）吗？" |
| 商城 / 平台 | `mall_type` (1=联想商城, 2=EPP 商城) | "你指的是联想商城（mall_type=1）还是 EPP 商城（mall_type=2）？" |

**确认格式**（必须逐项列出，等用户回复后再继续）：

> 在查询之前，请确认以下字段映射：
> 1. 你说的「商品编码」是指 `goods_code`（integer 类型）吗？
> 2. 你说的「价格」是指 `indexdata` 中的 `basePrice` 吗？
> 3. 你指的是哪个商城？联想商城（mall_type=1）还是 EPP 商城（mall_type=2）？
>
> 请确认后我再继续。

**用户未明确确认前，不得执行任何数据库查询。**

### 步骤 1：全表搜索物料（改/删/查时必须执行）

用户确认字段映射后，必须在 **所有 4 张核心价格表** 中搜索该物料：

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

**必须用精确匹配 `=`，不要用 `LIKE` 模糊搜索**，避免误匹配。

列出每张表中是否存在该物料、有几条记录。然后问用户：
> 该物料出现在以下表中：
> - goods_index_edit: N 条
> - enterprise_price_edit_index: M 条
> - ...
>
> 是否对所有表操作？还是只修改其中某几张？

用户明确选择范围后才能继续。

### 步骤 2：选择操作类型

增 / 改 / 删 / 查

### 步骤 3：新增物料

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
INSERT INTO goodsindex.goods_index_edit (id, code, material_number, mall_type, indexdata, base_price)
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
  )::json,
  99.9
)
RETURNING *;
```

### 步骤 4：改价

1. 先执行**步骤 0**（字段确认）和**步骤 1**（全表搜索）
2. 确认用户要修改的表和价格类型：

| 商城类型 | 可选价格类型 | 对应表 |
|---------|------------|--------|
| 联想商城 (mall_type=1) | 基础价 | `goods_index_edit` |
| 联想商城 (mall_type=1) | 会员组价 | `enterprise_price_edit_index` |
| EPP 商城 (mall_type=2) | 基础价 | `goods_index_edit` |
| EPP 商城 (mall_type=2) | 会员组价 | `enterprise_price_edit_index` |

3. **基础价修改**：
   - 查询当前价格：`SELECT material_number, name, indexdata->>'basePrice' AS current_price FROM goodsindex.goods_index_edit WHERE ...`
   - 展示当前价格 → 用户输入新价格 →
   - 生成 UPDATE：`UPDATE goodsindex.goods_index_edit SET indexdata = jsonb_set(indexdata::jsonb, '{basePrice}', '新价格'::jsonb)::json WHERE material_number = '...' RETURNING *`
   - ⚠️ 不要 SET `update_time`（生成列只读）

4. **会员组价修改**：
   - 查询当前等级价：`SELECT material_number, goods_name, price FROM goodsindex.enterprise_price_edit_index WHERE ...`
   - 展开所有等级 → 用户选等级 → 输入新折扣价
   - 同样用 `jsonb_set` 更新 `price` JSON 或 `indexdata` JSON 中的 price

5. **展示 diff**：旧值 → 新值汇总表
6. **确认后执行**，末尾加 `RETURNING *`

### 步骤 5：删除物料

1. 先执行**步骤 0**（字段确认）和**步骤 1**（全表搜索）
2. 展示将删除的记录详情（至少显示 id, material_number, name, mall_type, basePrice）
3. 用户确认后执行 `DELETE FROM ... WHERE ... RETURNING *`

### 步骤 6：查询物料

1. 先执行**步骤 0**（字段确认）和**步骤 1**（全表搜索）
2. 根据用户需求展示相关字段
3. 查询结果包含：表名、物料编码、商品名称、商城类型、价格信息

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

---

## 应用到 Skill 系统

当你的宿主智能体有 Skill 追踪机制时：
- 触发条件：SQL 或参数中包含 `goodsindex`，或用户提到触发词
- 标记名：`mall-price-crud`
