# 实战例子：修改商品编码 1004009

## 用户需求

修改商品编码为 **1004009** 的商品：
- 名称 → `skill测试007`
- 价格 → 7199

## 步骤 0：字段语义确认

用户回复 `AAA`：
1. **商品编码** → A. `goods_code`
2. **价格** → A. `indexdata.basePrice`
3. **名称** → A. `indexdata.name`（生成列）

## 步骤 2：全表搜索 SQL

```sql
SELECT 'goods_index_edit' AS table_name, COUNT(*) AS cnt
FROM goodsindex.goods_index_edit
WHERE goods_code::text = '1004009'
UNION ALL
SELECT 'enterprise_price_edit_index', COUNT(*)
FROM goodsindex.enterprise_price_edit_index
WHERE goods_code::text = '1004009' OR goods_code2 = '1004009'
UNION ALL
SELECT 'goods_index', COUNT(*)
FROM goodsindex.goods_index
WHERE goods_code::text = '1004009'
UNION ALL
SELECT 'goods_online_index', COUNT(*)
FROM goodsindex.goods_online_index
WHERE goods_code::text = '1004009'
UNION ALL
SELECT 'enterprise_price_online_index', COUNT(*)
FROM goodsindex.enterprise_price_online_index
WHERE goods_code::text = '1004009' OR goods_code2 = '1004009';
```

### 搜索结果

| 表 | 命中 |
|---|:---:|
| goods_index_edit | 1 |
| enterprise_price_edit_index | 0 |
| goods_index | 1 |
| goods_online_index | 1 |
| enterprise_price_online_index | 0 |

用户选择「全部」（A C D 三张有数据的表）。

## 当前数据

所有三张表（goods_index_edit / goods_index / goods_online_index）：
- `name` = `AIO 520-22IKL 21.5英寸一体台式机 银色`
- `indexdata->>'name'` = `AIO 520-22IKL 21.5英寸一体台式机 银色`
- `indexdata->>'basePrice'` = `3799`
- `base_price` = 3799（生成列）

## 步骤 3：执行更新

### 关键知识：name 和 base_price 都是生成列

```sql
-- 检查生成列定义
SELECT table_name, column_name, is_generated, generation_expression
FROM information_schema.columns
WHERE table_schema = 'goodsindex'
  AND table_name IN ('goods_index_edit', 'goods_index', 'goods_online_index')
  AND column_name IN ('name', 'base_price')
ORDER BY table_name, column_name;
```

结果：三张表的 `name` 和 `base_price` 都是 `ALWAYS GENERATED`。

### 正确 SQL（同时改名称+价格，嵌套 jsonb_set）

```sql
-- ✅ 只改 indexdata JSON，name 和 base_price 自动派生
UPDATE goodsindex.goods_index_edit
SET indexdata = jsonb_set(
    jsonb_set(indexdata::jsonb, '{name}', '"skill测试007"'::jsonb),
    '{basePrice}', '7199'::jsonb
  )::json
WHERE goods_code::text = '1004009'
RETURNING id, goods_code, name, base_price;

-- 同样操作 goods_index 和 goods_online_index
```

### ❌ 错误做法（报错）

```sql
-- 报错: column "base_price" can only be updated to DEFAULT
UPDATE goodsindex.goods_index_edit SET base_price = 7199 WHERE ...;

-- 报错: column "name" can only be updated to DEFAULT  
UPDATE goodsindex.goods_index_edit SET name = 'xxx' WHERE ...;
```

### 更新后结果

三张表均成功：
- `name` = `skill测试007` ✅
- `base_price` = 7199 ✅

## 关键教训

1. **goods_index_edit / goods_index / goods_online_index** 三张表的 **`name` 和 `base_price` 都是生成列（ALWAYS GENERATED）**
2. 名称由 `(indexdata::jsonb ->> 'name')` 派生
3. 价格由 `(NULLIF((indexdata::jsonb ->> 'basePrice'), ''))::double precision` 派生
4. 必须通过 `jsonb_set()` 修改 `indexdata` JSON
5. 双重转型不可少：`indexdata::jsonb` → `jsonb_set(...)` → `::json`
6. 同时改名称+价格用嵌套 `jsonb_set(jsonb_set(...), ...)`
7. 费用相关表（`enterprise_price_edit_index` / `enterprise_price_online_index`）没有匹配数据
