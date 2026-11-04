# 数据结构与适配说明

本项目只读取 OpenCode 本地数据库里的这几张表。上游改结构时，需要动的地方都在
`src/oc_tps/source.py`。

## 用到的表

| 表 | 用到的列 | 用途 |
|---|---|---|
| `session` | `id`, `model`, `time_updated` | 找最近有活动的会话；`model` 是 JSON 字符串 |
| `message` | `id`, `session_id`, `time_created`, `data` | `data` 里的 `role` 区分 user/assistant，`time.completed` 判断这一步是否结束 |
| `part` | `id`, `message_id`, `time_created`, `data` | `data.type` 区分 part 类型 |

## 一条 assistant 消息 = 一个模型步骤

```
message(role=assistant)
  ├─ part(type=step-start)                  起点时间 time_created
  ├─ part(type=reasoning)                   text 字段为增量后的全文
  ├─ part(type=text)                        text 字段同上
  ├─ part(type=tool)                        工具调用（不计入速度）
  └─ part(type=step-finish)                 tokens.output / tokens.reasoning + 结束时间
```

由此得到两个口径：

```
精确速度 = (tokens.output + tokens.reasoning) / (finish.time_created − start.time_created)
```

流式过程中的实时值无法拿到逐 token 计数，因此用字符数折算：

```
实时速度 ≈ Δ加权字符 × 校准系数 / Δt
加权字符 = CJK 字符数 + 其余字符数 × 0.25
```

校准系数按模型学习（每完成一步更新一次，EWMA 0.3），存在 `calibration.json`。

## 自己查一眼

SQLite 只读打开即可，不会影响客户端：

```sql
-- 最近的会话
select id, model, time_updated from session order by time_updated desc limit 3;

-- 最近一条 assistant 消息的 part 类型
select json_extract(data,'$.type') as t, time_created
from part
where message_id = (
  select id from message
  where session_id = (select id from session order by time_updated desc limit 1)
  order by time_created desc limit 1
)
order by time_created;

-- 上一步的精确 token 数
select json_extract(data,'$.tokens.output')  as out_tokens,
       json_extract(data,'$.tokens.reasoning') as reasoning
from part
where json_extract(data,'$.type') = 'step-finish'
order by rowid desc limit 3;
```

## 上游改结构时怎么适配

1. 用上面的 SQL 看新版还有没有 `step-start` / `step-finish`，字段名有没有变；
2. 改 `Source.fetch()` 里那段解析（part 循环）与 SQL；
3. `Engine` 只依赖 `fetch()` 返回的字典，字段含义见下，不需要跟着改：

| 字段 | 含义 |
|---|---|
| `state` | `run` / `done` / `queued` / `idle` |
| `mid` | 步骤唯一 id（用于检测换步） |
| `model` | 模型标识（校准分桶用） |
| `wchars` | 加权字符数（实时估算用） |
| `start` / `finish` | 起止毫秒时间戳 |
| `tokens` | 该步 output + reasoning（结束时才有） |

4. 若新版本连表名都换了，`Source.check_schema()` 会抛 `SchemaError`，界面会显示
   “数据库结构不支持 / 请检查 OpenCode 版本”，不会静默给出错误数字。

## 已知的结构依赖

- 依赖 SQLite 的 **JSON1** 扩展（Python 自带 sqlite3 通常已编译进去）。缺失时会明确报错。
- 依赖 `message.data` 是 JSON 字符串、`part.data` 里 `text` 为累积全文（不是增量片段）。
- 若某版本把 part 存成增量 delta，`wchars` 的算法需要改成累加。
