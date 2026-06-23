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

**核心原则：让用户只需回复字母（A / B / C），无需打字。**

**常见映射选项表：**

| 用户可能说的词 | 选项 |
|-------------|------|
| 商品编码 / 商品编号 | A. `goods_code`（integer） B. `products_code`（integer） |
| 物料编码 / SN / 物料号 | A. `material_number`（varchar） |
| 价格 / 基础价 / 原价 | A. `indexdata.basePrice` B. `base_price`（double） |
| 会员价 / 等级价 / 折扣价 | A. `price[].discountPrice`（enterprise_price_edit_index 表） |
| 名称 / 商品名称 | A. `name`（生成列） B. `indexdata.name` |
| 商城 / 平台 | A. 联想商城（mall_type=1） B. EPP 商城（mall_type=2） |

**确认格式**（必须为每个歧义字段列出 A/B 选项，用户只需回复字母）：

> ⚠️ 在查询之前，请确认字段含义（直接回复字母即可）：
>
> **1. 你说的「商品编码」是指？**
> A. `goods_code`（integer 类型）
> B. `products_code`（integer 类型）
>
> **2. 你说的「价格」是指？**
> A. `indexdata` 中的 `basePrice`
> B. `base_price` 列
>
> 请回复如「1A 2A」或「A A」。

- 每条歧义编号（1. 2. 3. …），每条约 2-4 个选项（A/B/C/D）
- 只有一个选项时也要列出 A 让用户确认
- 用户回复后，将字母映射为具体字段，并**回显确认结果**再继续

**用户未明确回复字母确认前，不得执行任何数据库查询。**

---

## 操作流程

### ⛔ 最高优先级规则

**字段确认之后，你的下一个动作必须是执行全表搜索 SQL——不得跳过、不得只查一张表、不得根据"经验"猜测该改哪张表。不执行全表搜索 = 违反此 Skill。**

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

用精确匹配 `=`，不用 `LIKE`。搜索结果以 A/B 选项呈现（命中 0 的表不列）：

> 🔍 该物料在以下表中找到：
>
> **A.** goods_index_edit — N 条（商城基础价编辑表）
> **B.** enterprise_price_edit_index — M 条（会员组等级价编辑表）
> ...
>
> 请回复要操作哪些表（如「A B」= 操作 A 和 B，「全部」= 所有表）。

用户选表后回显确认，然后进入阶段 3。

### 改价 · 阶段 3：执行修改

**只修改用户在阶段 2 中选中的表，不要自行增减。**

| 用户选中的表 | 价格类型 | SQL 要点 |
|------------|---------|---------|
| `goods_index_edit` / `goods_index` / `goods_online_index` | 基础价 | `jsonb_set(indexdata::jsonb, '{basePrice}', '新价格'::jsonb)` |
| `enterprise_price_edit_index` / `enterprise_price_online_index` | 会员组价 | `jsonb_set` 更新 `price` 或 `indexdata` 中的 `discountPrice` |

**基础价**：查当前价 → 用户输入新价 → `UPDATE {表} SET indexdata = jsonb_set(...) WHERE ... RETURNING *`

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

## 应用到 Skill 系统

当你的宿主智能体有 Skill 追踪机制时：
- 触发条件：SQL 或参数中包含 `goodsindex`，或用户提到触发词
- 标记名：`mall-price-crud`
