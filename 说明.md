# 子宫孕育 发布包 1.35.239

这个包包含三个互相关联、但各自独立安装的部分：

```text
受孕插件发布包_1.35.239/
├─ 受孕/                        受孕插件（astrbot_plugin_conception）
├─ 暗涌/                        暗涌总开关（astrbot_plugin_desire_owner）
├─ 暗涌引擎/
│  ├─ astrbot_plugin_longing/   暗涌的 AstrBot 注入桥接插件
│  └─ runtime/                  暗涌 Node 引擎（runner.mjs + dsh-longing）
└─ 说明.md
```

受孕插件本身不包含鱼之心、PC、记忆插件；它们属于**外部关联插件**，按需安装，不安装时受孕插件会跳过对应联动，不会因此崩溃。

---

## 一、安装位置

把文件夹放进 AstrBot 的 `data/plugins/`：

| 包内目录 | 建议安装为 |
|---|---|
| `受孕/` | `data/plugins/astrbot_plugin_conception/` |
| `暗涌/` | `data/plugins/astrbot_plugin_desire_owner/` |
| `暗涌引擎/astrbot_plugin_longing/` | `data/plugins/astrbot_plugin_longing/` |
| `暗涌引擎/runtime/` | 独立目录，例如 `C:\DeepSeek\longing\` |

`runtime/` 不需要放进 AstrBot 插件目录，它由 Node 独立运行。

---

## 一·补 安装前必须改的作者本地路径

这个包是从作者本机直接打出来的。**暗涌相关的几个文件里有作者本地路径，安装到别的机器前必须改**；受孕插件本身不需要改。

### 1. `暗涌/main.py`

文件顶部：

```python
SWITCH = Path(r"C:\DeepSeek\desire_switch.json")
LONGING_DIR = Path(r"C:\DeepSeek\longing")
NODE = Path(r"C:\DeepSeek\SnowLuma\node.exe")
```

改成对方机器上的实际路径：

- `SWITCH`：任意固定位置，例如 `Path(r"D:\AstrBot\data\desire_switch.json")`；
- `LONGING_DIR`：本包 `暗涌引擎/runtime/` 解压后的目录；
- `NODE`：对方机器的 `node.exe`，Windows 可用 `where node` 查。

### 2. `暗涌引擎/astrbot_plugin_longing/main.py`

文件顶部：

```python
SWITCH_FILE = r"C:\DeepSeek\desire_switch.json"
```

必须和 `暗涌/main.py` 里的 `SWITCH` **完全一致**，否则两边读写的不是同一份归属开关。

### 3. `暗涌引擎/runtime/desire_switch.py`

文件顶部：

```python
SWITCH = Path(r"C:\DeepSeek\desire_switch.json")
```

同样改成和上面一致。这个脚本只用于手动查看/切换归属，不改也能跑引擎，但手动命令会读错文件。

### 4. `暗涌引擎/astrbot_plugin_longing/_conf_schema.json`

`fallback_file` 的默认值：

```text
C:\DeepSeek\暗涌\data\欲望注入.qq.txt
```

改成对方机器上 `runtime/data/欲望注入.qq.txt` 的实际路径；装好后也可以在 AstrBot 插件配置页直接改 `fallback_file`，不改 JSON 也行。

### 5. PC 兼容补丁（不是受孕插件的一部分）

如果对方要看到 ASMR 的睡眠压力，需要给 PC 的：

```text
companion_v2/role_work/life/physiology.py
```

加一个读取 `asmr_sleep_boost.json` 的函数，具体见下面「兼容补丁」一节。**包里没有附带 PC 的整份文件**，因为不同 PC 版本不一样，直接覆盖容易坏；请按对方版本手动加，改前备份。

### 6. 不需要改的

- `受孕/` 里的路径由 AstrBot 的 `data/plugin_data/astrbot_plugin_conception/` 自动决定；
- `暗涌引擎/runtime/runner.mjs` 和 `dsh-longing/` 用的是相对自身目录的路径，不用改；
- 端口默认 `6399`，如果被占用，改 `runner.mjs` 配置里的 `port`，并同步改 `astrbot_plugin_longing` 的 `runner_url`。

---

## 二、受孕插件

- 版本：`1.35.239`
- 目录：`受孕/`
- 安装后重载插件即可。
- 面板在「受孕」卡片里，所有数值都可以在面板/配置页里调。
- 依赖 AstrBot 4.20–4.x；没有额外的 Python 包依赖。

受孕插件会主动读取/写入的关联：

### 1. 鱼之心 `astrbot_plugin_fish_heart`（强关联，建议装）

用途：

- 读取成人层是否打开、当前同意/场景状态；
- 读取「欲」作为欲望来源；
- 写入九维里的依恋、亲密、欲；
- 写入「责怪」；
- 夜袭、魅魔收益等会用到它的状态。

找不到鱼之心时：相关联动跳过，成人层门禁会按受孕插件自己的规则处理，不会报错。

### 2. PC `astrbot_plugin_private_companion`（强关联，建议装）

用途：

- 读取/写入周期暂停；
- 写入 PC 精力；
- 读取睡眠状态和睡眠压力；
- 写 `asmr_sleep_boost.json`，让 PC 读到 ASMR 助眠压力；
- 夜袭时写 `night_raid_bypass.json`，临时解除睡眠发言限制；
- 写 PC 条件/状态。

**注意：** PC 原版如果没有 ASMR 读取逻辑，`asmr_sleep_boost.json` 会正常写出，但 PC 面板不会计入。需要给 PC 的 `companion_v2/role_work/life/physiology.py` 加一个兼容读取函数；这不属于受孕插件的安装步骤，具体见下面的「兼容补丁」。

### 3. 蔗糖记忆 `astrbot_plugin_sugarmemory`（可选）

- 主动消息会挂 `_sugarmemory_bridge` 标签，避免它把主动消息当成回声；
- 可写入 L2 事实、孩子出生/成年记录；
- 没装时跳过。

### 4. 天使之魂 `astrbot_plugin_angel_memory`（可选）

- 只做插件可用性检测；
- 不直接写它的内部数据。

### 5. 暗涌 `astrbot_plugin_longing` + 暗涌总开关（可选）

- 受孕插件只读取暗涌的 `lust` 作为欲望来源之一；
- 不写暗涌状态；
- 需要暗涌时再装，见下一节。

---

## 三、暗涌与暗涌引擎

暗涌是「欲望归谁管」的独立体系，和受孕插件不是强绑定。只装受孕也能用；要试暗涌再装这一套。

### 1. 暗涌总开关

目录：`暗涌/` → `astrbot_plugin_desire_owner`

它负责：

- 写入共享开关文件 `desire_switch.json`；
- 启动/停止 Node 引擎；
- 选择「暗涌全权 / 分工 / 只有鱼之心」。

默认是作者本地路径：

```python
SWITCH = Path(r"C:\DeepSeek\desire_switch.json")
LONGING_DIR = Path(r"C:\DeepSeek\longing")
NODE = Path(r"C:\DeepSeek\SnowLuma\node.exe")
```

发布给别人时，请按对方机器修改 `暗涌/main.py` 顶部这三行，或者把这三个路径改成配置文件读取。

### 2. 暗涌桥接插件

目录：`暗涌引擎/astrbot_plugin_longing/`

它负责：

- 把主人说的话推给引擎；
- 把引擎生成的欲望注入块拼进 system prompt；
- 引擎没跑时读取兜底文件，再不行就不注入。

默认端口：`http://127.0.0.1:6399`

默认兜底文件：

```text
C:\DeepSeek\暗涌\data\欲望注入.qq.txt
```

这个路径可以在插件配置 `fallback_file` 里改。

共享开关默认：

```text
C:\DeepSeek\desire_switch.json
```

在 `暗涌引擎/astrbot_plugin_longing/main.py` 顶部：

```python
SWITCH_FILE = r"C:\DeepSeek\desire_switch.json"
```

### 3. Node 引擎

目录：`暗涌引擎/runtime/`

包含：

- `runner.mjs`
- `dsh-longing/`（原版引擎源码）
- `desire_switch.py`

启动：

```bash
cd <runtime 目录>
node runner.mjs
```

或在「暗涌」卡片里让 `astrbot_plugin_desire_owner` 自动启动。自动启动要求：

- `NODE` 指向有效的 `node.exe`；
- `LONGING_DIR` 指向 `runtime/`；
- 本机 `6399` 端口未被别的程序占用。

引擎会在 `runtime/data/` 下生成：

- `欲望状态.json`
- `暗涌配置.json`
- `欲望注入.txt` / `欲望注入.qq.txt`

这些是运行数据，不要提交到公开仓库。

### 4. 两套欲望不能同时全开

- 默认：暗涌全权（鱼之心只保留九维等，欲冻结）；
- 分工：鱼之心九维 + 暗涌欲望；
- 只有鱼之心：关闭暗涌，鱼之心恢复完整。

选「只有鱼之心」时不要同时开暗涌，否则同一件事会出现两套矛盾数值。

---

## 四、兼容补丁：PC 读取 ASMR 助眠压力

受孕插件会写：

```text
data/plugin_data/astrbot_plugin_conception/asmr_sleep_boost.json
```

内容示例：

```json
{"amount": 12.0, "at": 1795362430.9, "until": 1795405630.9}
```

PC 侧需要一个读取函数，把 `amount` 计入睡眠压力。兼容逻辑大意：

```python
def _asmr_relief(now):
    path = ... / "astrbot_plugin_conception" / "asmr_sleep_boost.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    until = float(data.get("until") or 0)
    if until and now.timestamp() <= until:
        return max(0.0, min(100.0, float(data.get("amount") or 0)))
    return 0.0
```

然后把返回值加进 PC 的 `sleep_pressure` 计算。

注意：

- PC 处于「正在睡眠」时，原版逻辑会直接返回 0 睡眠压力，ASMR 的数值要等它醒来后才参与计算；
- 这是 PC 侧补丁，不是受孕插件自带功能；不同 PC 版本文件位置可能不同，打补丁前先备份。

---

## 五、最小安装组合

### 只想用受孕

```text
受孕/
```
+ 可选：鱼之心、PC

### 想用受孕 + 暗涌

```text
受孕/
暗涌/
暗涌引擎/astrbot_plugin_longing/
暗涌引擎/runtime/
```

并在「暗涌」卡片里选好归属，启动引擎。

### 想用记忆联动

再装：

```text
astrbot_plugin_sugarmemory
astrbot_plugin_angel_memory
```

---

## 六、隐私与发布注意

- 这个包里**没有**包含作者的 `state.json`、日志、聊天记录、API key、QQ 号或 PC 数据；
- 引擎的 `data/` 和 PC 的 `plugin_data/` 是运行后生成的，不要一起打包；
- 如果要把本包公开发布，请先确认：
  - 三个插件和暗涌引擎的授权/署名；
  - 是否允许再分发 `dsh-longing` 源码；
  - 是否要把作者本地路径改成通用配置；
  - 是否移除任何个人信息/服务器地址。

---

## 七、当前验证状态

- 卡片名：子宫孕育

- 发布人：Nyakori/DeepSeek

- 受孕插件自测：**3556 项通过，0 失败**
- AstrBot host 测试：**535 项通过，0 失败**
- 版本：`1.35.239`
- 备份：`315_受孕_主动请求判断`
