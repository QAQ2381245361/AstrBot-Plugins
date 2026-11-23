"""配置默认值、路径常量、带类型的配置读取。

为什么默认值写在代码里而不是只写在 _conf_schema.json：
- schema 决定面板显示什么，代码决定"读不到时按什么算"；
- 两边的键必须一一对应（AstrBot 在加载时会把 schema 里没有的键删掉），
  自检脚本会专门检查这一点。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

PLUGIN_NAME = "astrbot_plugin_conception"
PLUGIN_VERSION = "1.35.239"
PLUGIN_AUTHOR = "Nyakori/DeepSeek"

# ---------------------------------------------------------------- 目录定位

def _find_astrbot_root() -> Path:
    """从本文件往上找 AstrBot 根目录（含 data/plugin_data 的那一层）。

    找不到就退回这台机器上的部署路径；再不行退回当前工作目录。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data" / "plugin_data").is_dir():
            return parent
    for guess in (Path(r"C:\DeepSeek\AstrBot\AstrBot-4.29.4"),):
        if (guess / "data").is_dir():
            return guess
    return Path.cwd()


ASTRBOT_ROOT = _find_astrbot_root()
DATA_DIR = ASTRBOT_ROOT / "data"
PLUGIN_DATA_DIR = DATA_DIR / "plugin_data" / PLUGIN_NAME
CONFIG_DIR = DATA_DIR / "config"

# 与其它插件共享的只读数据源（路径可在配置里覆盖）
FISH_HEART_STATE = DATA_DIR / "plugin_data" / "astrbot_plugin_fish_heart" / "state.json"
FISH_HEART_CONFIG = CONFIG_DIR / "astrbot_plugin_fish_heart_config.json"
LONGING_STATE = Path(r"C:\DeepSeek\longing\data\欲望状态.json")
LONGING_ENGINE_STATE = Path(r"C:\DeepSeek\longing\engine_state.json")
DESIRE_SWITCH = Path(r"C:\DeepSeek\desire_switch.json")
DESIRE_OWNER_CONFIG = CONFIG_DIR / "astrbot_plugin_desire_owner_config.json"
PC_DB = (
    DATA_DIR
    / "plugin_data"
    / "astrbot_plugin_private_companion"
    / "installations"
    / "main"
    / "runtime"
    / "companion-v2.sqlite3"
)

STATE_FILE = PLUGIN_DATA_DIR / "state.json"
PC_CYCLE_BACKUP = PLUGIN_DATA_DIR / "pc_cycle_backup.json"
LOG_FILE = PLUGIN_DATA_DIR / "conception.log"


# ---------------------------------------------------------------- 默认值
# 结构必须和 _conf_schema.json 完全一致（自检脚本 test_schema_parity 会比对）。

DEFAULTS: dict = {
    "enabled": True,
    # 只有这个 QQ 的私聊会触发；留空 = 不做身份限制（不推荐）
    "owner_qq": "2381245361",
    # 当前人设名；用于从 AstrBot 人格里读性别。留空 = 用默认人格
    "persona_name": "DeepSeek",
    # auto / female / male / other / off
    "gender_mode": "auto",
    # 人格判不出性别时：allow（按可受孕处理）/ deny（不生效）
    "unknown_gender_policy": "allow",

    "adult_required": True,
    "adult_consent_hours": 24.0,

    "adult": {
        # 关键词只在"正在进行的亲密场景"里才参与判定，
        # 免得到时平常聊天里出现一个词就被误记一笔
        "detect_requires_scene": True,
        "scene_window_minutes": 30,
        # 鱼之心成人层怎么算"可用"：switch=总开关开即可（默认）
        # scene=还要求它自己有同意/场景（更严）
        "fish_gate_mode": "switch",
        "detect_user_message": True,
        "detect_reply": True,
        "reply_dedupe_seconds": 90,
        "ejaculation_keywords": [
            "内射", "射在里面", "射进", "射到里面", "中出", "射里面", "灌满",
        ],
        "orgasm_keywords": ["高潮", "绝顶", "潮吹"],
    },

    "conception": {
        # 单次体内射精的受孕率由「生理期基准」决定，下面的权重都作用在它上面
        "max_probability": 90.0,       # 单次判定上限（%）
        "inside_scale": 1.0,           # 体内系数
        "outside_scale": 0.002,        # 体外系数（几乎不会受孕）
        "anal_scale": 0.02,            # 肛内射精的受孕系数（很小）
        "throat_scale": 0.005,         # 口内/喉内射精的受孕系数（更小）
        "orgasm_now_multiplier": 1.8,  # 「高潮时被射」的加成
        "orgasm_window_minutes": 10,   # 高潮后多久内算「高潮时」
        "fish_desire_weight": 0.6,     # 鱼之心「欲」的权重
        "mood_desire_weight": 0.6,     # 日常情绪欲望的权重（来源选日常时才用）
        "dark_lust_weight": 0.6,       # 暗涌「lust」的权重
        "pleasure_weight": 0.5,        # 快感值权重
        "orgasm_count_weight": 0.5,    # 高潮次数权重
        "orgasm_count_cap": 5,         # 次数加成的封顶次数
        "ejaculation_count_weight": 0.15,
        "ejaculation_count_cap": 4,
        "volume_weight": 0.03,
        "volume_cap": 10.0,
        "simultaneous_weight": 0.25,
        "simultaneous_cap": 1.0,
        "simultaneous_window_seconds": 120,
        "simultaneous_pleasure": 3.0,
        "simultaneous_endurance": 2.0,
        "ejaculation_lewd": 2.0,
        "ejaculation_endurance": 3.0,
        "sleep_semen_bonus": 0.5,
        "sleep_semen_volume_cap": 10.0,
        "sleep_semen_time_cap_hours": 8.0,
    },

    # 生理期各阶段的受孕基准（百分比）——默认分布在 5% ~ 40%
    "phase_probability": {
        "menstrual": 5.0,
        "follicular": 10.0,
        "pre_ovulation": 28.0,
        "ovulation": 40.0,
        "luteal": 14.0,
        "pms": 6.0,
        "recovery": 6.0,
        "unknown": 15.0,
        "paused": 0.0,
    },

    "pleasure": {
        "max": 100.0,
        "tool_gain": 12.0,
        "orgasm_pleasure_gain": 25.0,
        "orgasm_afterglow_ratio": 0.55,
        "decay_per_hour": 8.0,
        "idle_minutes": 10,     # 多久没被碰才开始回落
        "session_timeout_minutes": 120,
        # 高潮要和快感挂钩：没到这条线就不算真到
        "orgasm_threshold": 55.0,
        "post_orgasm_minutes": 8,
    },

    # 高潮忍耐条：快感涨的同时攒忍耐，满了再刺激一下就高潮
    "endurance": {
        "sens_boost": 0.5,
        "enabled": True,
        "cap": 100.0,          # 基础条长
        "gain_at": 55.0,       # 快感到这条线以上，每次攒"正常量"；以下攒"少量"
        "gain_multiplier": 1.0, # 所有忍耐增加量的最终倍率（1=原值）
        "gain_low": 3.0,       # 低于 gain_at 时每次攒多少
        "gain_high": 9.0,      # 到了/超过 gain_at 时每次攒多少
        "combo_grow": 0.2,     # 每连续高潮一次，条变长 20%
        "combo_cap": 2.5,      # 最多长到基础条的 2.5 倍
        "reset_minutes": 30,   # 多久没高潮就缩回基础长度
        "idle_minutes": 10,    # 多久没被碰才开始回落
        "decay_per_hour": 6.0, # 回落速度
        "level_at_1": 25.0,    # 第2段起点（占条长百分比）
        "level_at_2": 50.0,    # 第3段起点
        "level_at_3": 75.0,    # 第4段起点
    },

    # 特别敏感点：活动里她身上有一处"这会儿特别敏感"，会自己换；日常玩具也有概率撞上
    "special": {
        "enabled": True,
        "every_minutes": 8,     # 多久换一个
        "rotate_on_timer": True,  # 到点会不会自己换（关掉就只在被碰 / 手动换时变）
        "jitter_percent": 25.0,   # 到点时间的浮动范围（%，0 = 每次准时）
        "pleasure_bonus": 6.0,  # 碰到时多涨多少快感
        "endurance_bonus": 4.0, # 碰到时多攒多少忍耐
        "daily_chance": 100.0,  # 用到"特别档位"那个玩具时，撞上加成的概率 %
        "daily_pleasure": 4.0,  # 日常撞上时多涨的快感
        "daily_endurance": 3.0, # 日常撞上时多攒的忍耐
    },

    # 连续高潮：短时间内的第二次、第三次会越来越容易，但次数过头会难受
    "combo": {
        "enabled": True,
        "window_minutes": 12,        # 距上次高潮多久内算"连续"
        "threshold_step": 6.0,       # 每连续多一次，高潮门槛降多少（更敏感）
        "threshold_floor": 38.0,     # 门槛最低降到多少
        "overstim_after": 3,         # 连续到第几次之后，再多就难受
        "rest_minutes": 20,          # 难受之后要缓多久
        "pain_gain_scale": 0.35,     # 难受期间快感增长速度
    },

    "children": {
        "care_mode": "family",
        "prompt_on_request": True,
        "adult_destination": "已经独立生活、自己成家了",
        "intimacy_interrupt_enabled": True,
        "intimacy_interrupt_chance": 20.0,
        "intimacy_child_max_age_years": 3,
    },

    "pregnancy": {
        "sex_differentiation_month": 4,
        "female_ratio": 0.5,
        "months": 10,
        # 预产期在自然月基础上前后浮动几天（"略微浮动"）
        "jitter_days": 10,
        "suppress_pc_cycle": True,
        "pc_write_enabled": True,
        "pc_db_path": "",              # 留空 = 自动找
        "pc_role_name": "DeepSeek",
        "backup_pc_db": True,
        "postpartum_days": 42,
        # 产后恢复期里是否禁止再次受孕（总开关）
        "postpartum_no_conception": True,
        # 两段式：前 hard 天绝对不行，后 low 天概率 ×low_scale
        "postpartum_hard_days": 14,
        "postpartum_low_days": 14,
        "postpartum_low_scale": 0.15,
        # 多胞胎：受孕时按概率决定怀几个
        "multiple_enabled": True,
        "twin_chance": 12.0,           # 双胞胎概率（%）
        "triplet_chance": 2.0,         # 三胞胎概率（%）
        "max_fetuses": 3,
        # 孕期阶段写进 PC 状态（条件 + 精力）
        "stage_pc_enabled": True,
        "stage_energy_enabled": True,
    },

    # 验孕：受孕活动后过一段时间，她可能自己起念验一下，再决定要不要说
    "self_test": {
        "enabled": True,
        "chance": 40,                  # 每次体内射精后安排一次自查的概率（%）
        "min_delay_hours": 24,
        "max_delay_hours": 48,
        "window_hours": 72,            # 起念后多久内可以验
        "early_days": 12,              # 受孕后多少天内验，结果可能很浅
        "early_negative_chance": 50,   # 早期假阴性概率（%）
        "retest_cooldown_hours": 12,   # 两次验孕最短间隔
        "tell_detect": True,           # 从她的回话里判断"已经告诉他了"
    },

    # 处女膜：初夜/破裂与完整分娩
    "hymen": {
        "blood_enabled": True,        # 破处血情节开关
        "damage_max": 100.0,         # 处女膜完全损伤阈值
        "finger_damage": 6.0,        # 手指/按压一次加多少损伤
        "toy_damage": 8.0,           # 小玩具一次加多少损伤
        "enabled": True,
        "rupture_chance": 85.0,        # 未破裂时，每次阴道内射/阴道玩具的破裂概率（%）
        "first_night_pleasure": 12.0,  # 破裂当次的额外快感
        "intact_birth": True,          # 未破裂也能怀孕/生产（并给特殊提示）
    },

    # 阴道湿润度：一直有效（不在活动里也涨/落），4 段提示词，破处时减轻疼痛
    "wetness": {
        "enabled": True,
        "base": 30.0,              # 基础湿润度（回落到底就是这里）
        "prompt_min_level": 3,     # 日常聊天至少第几档才提
        "gain_per_touch": 4.0,     # 碰一下涨多少
        "scene_step_gain": 0.4,    # 活动里每推进一步额外涨多少
        "daily_step_gain": 0.25,   # 日常小活动每推进一步额外涨多少
        "gain_per_pleasure": 0.35, # 每涨 1 点快感涨多少
        "orgasm_gain": 8.0,        # 高潮一次额外涨多少
        "idle_minutes": 10,        # 多久没被碰才开始落
        "decay_per_hour": 20.0,    # 回落速度（只会落回基础值）
        "level_at_1": 25.0,        # 第 2 段起点
        "level_at_2": 50.0,        # 第 3 段起点
        "level_at_3": 75.0,        # 第 4 段起点
        "pain_wetness_at": 60.0,   # 湿润度达到多少算"够湿"
        "pain_pleasure_at": 55.0,  # 快感达到多少算"够兴奋"
        "pain_relief": 80.0,       # 两个都够时疼痛降低多少 %（100 = 完全不疼）
        "fish_write_enabled": True,  # 湿润度上涨时同步加鱼之心「欲」
        "fish_desire_gain": 1.0,     # 每次上涨给鱼之心「欲」加多少
        "fish_desire_scale": 0.3,    # 鱼之心「欲」越高，湿润度涨得越快（0.3 = 最多 +30%）
        "fish_desire_to_wet": 1.0,   # 鱼之心「欲」每涨 1 点，湿润度也涨多少
        "fish_desire_min_minutes": 0,
        # 基础湿润度浮动：鱼之心「欲」+ 快感 + 忍耐
        "base_float_enabled": True,
        "base_float_desire": 15.0,
        "base_float_pleasure": 10.0,
        "base_float_endurance": 8.0,
        "base_float_cap": 25.0,  # 湿润度补涨最短间隔（分钟，0 = 不限）
    },

    # 写进记忆插件：默认关；开了以后在活动/突然被弄时额外写一条长期记忆
    "memory": {
        "write_events": False,
        "subject": "我",
        "event_name": "",   # 这件事她怎么叫（留空 = 不写具体名，让她自己在对话里命名）
        "min_minutes": 10,
    },

    # 主动消息：是否让模型按她的口吻重新组织，而不是直接发固定模板
    "schedule": {
        "notice_delay_seconds": 0,
        "generate_proactive": True,
        "proactive_judge": True,
        "proactive_defer_minutes": 30,
    },

    # 耳朵 / 舌吻：日常、日常小场景、受孕场景都能用
    "ear": {
        "enabled": True,
        "dev_gain": 0.3,
        "sens_gain": 0.005,
        "pleasure_gain": 3.0,
        "shame_gain": 3.0,
        "endurance_gain": 2.0,
        "wet_gain": 4.0,
        "orgasm_chance": 6.0,
    },
    "kiss": {
        "enabled": True,
        "dev_gain": 0.3,
        "sens_gain": 0.005,
        "pleasure_gain": 3.0,
        "shame_gain": 3.0,
        "endurance_gain": 2.0,
        "wet_gain": 4.0,
        "french_pleasure": 2.0,
    },

    # 吞精：外射后收集 / 射嘴里 / 吞下
    "swallow": {
        "enabled": True,
        "collect_pleasure": 4.0,
        "swallow_pleasure": 8.0,
        "desire_gain": 4.0,
        "wet_gain": 5.0,
        "swallow_desire": 6.0,
        "swallow_wet": 6.0,
        "swallow_lewd": 3.0,
        "endurance_gain": 2.0,
        "auto_enabled": True,
        "auto_chance": 35.0,
        "auto_swallow_chance": 50.0,
    },

    # Unbirth：缩小、钻进子宫、被生出来（默认关）
    "unbirth": {
        "request_enabled": True,      # 她可以主动请求进入
        "overnight_request_chance": 25.0,
        "overnight_check_minutes": 30,
        "overnight_invite_chance": 10.0,
        "overnight_invite_min_lewd": 40.0,
        "request_chance": 15.0,       # 每次检查触发概率 %
        "request_check_minutes": 30,
        "request_cooldown_minutes": 180,
        "request_wait_minutes": 10,
        "grow_step": 0.15,            # 每次「变大」加多少比例
        "birth_min_ratio": 0.04,      # 小于这个比例就生不出来
        "birth_depth_steps": 2,       # 从子宫里生比从入口生多几步
        "birth_step_minutes": 10,     # 生出过程中多少分钟掉一步
        "resist_chance": 70.0,        # 逆着来成功率
        "resist_add_steps": 1,        # 逆着来成功加几步
        "birth_giveup_after": 3,      # 连续失败几次就放弃
        "resist_keywords": ["逆着来", "按回去", "塞回去", "不让她出来",
                            "别生", "不准生", "憋回去"],
        "birth_difficulty": 60.0,     # 越小越难生
        "tube_stage2": 8.0,           # 阴茎头几乎全进来时射输卵管
        "tube_stage3": 15.0,          # 整个阴茎头都进来
        "tube_stage4": 25.0,          # 子宫被插满
        "tube_unbirth": 35.0,         # Unbirth 在子宫里
        "ovary_prob": 90.0,           # 射进卵巢的受孕概率
        "tube_flow_base_minutes": 10,  # 基准流量时间（2ml 时）
        "tube_fill_percent": 80,       # 非直射时子宫填满多少 % 才算流进输卵管
        "tube_flow_ref_ml": 2.0,       # 基准精液量
        "hymen_pass_pleasure": 6.0,  # 钻过处女膜加快感
        "hymen_pass_endurance": 4.0,  # 钻过处女膜加忍耐
        "hymen_pass_wet": 8.0,        # 钻过处女膜加湿润
        "hymen_pass_desire": 5.0,     # 钻过处女膜加欲望
        "inside_pleasure": 0.5,     # 待在里面每分钟加快感
        "inside_wet": 1.0,          # 待在里面每分钟加湿润
        "inside_endurance": 0.3,    # 待在里面每分钟加忍耐
        "inside_dev": 0.02,         # 待在里面每分钟加子宫开发度
        "inside_sens": 0.002,       # 待在里面每分钟加子宫敏感度
        "inside_max_minutes": 240,  # 一次最多结算多少分钟
        "enabled": False,
        "user_height": 170.0,
        "user_weight": 60.0,
        "shrink_ratio": 0.05,
        "limit_factor": 1.0,
        "expand_small": 0.35,
        "expand_mid": 0.7,
        "enter_pleasure": 10.0,
        "enter_endurance": 8.0,
        "enter_wet": 12.0,
        "birth_steps": 3,
        "resist_desire": 5.0,
    },

    # 衣装：默认穿搭 / 穿脱的情绪增减
    "clothing": {
        "enabled": True,
        "default_outfit": True,
        "shame_relief_enabled": True,
        "auto_sleepwear": True,
        "sleepwear_night_hour": 22,
        "sleepwear_morning_hour": 8,
        "sleepwear_notice_chance": 100.0,
        "sleepwear_seen_chance": 35.0,
        "sleepwear_seen_shame": 8.0,
        "sleepwear_seen_desire": 4.0,
        "sleepwear_seen_wet": 3.0,
        "sleepwear_seen_fish_desire": 3.0,
        "remove_adds_mood": True,
        "remove_shame": 10.0,
        "remove_shame_max": 40.0,     # 脱衣加羞耻最多加到多少（总羞耻值）
        "remove_desire": 4.0,
        "wear_shame_relief": 5.0,
        "change_minutes": 2,
        "undress_minutes": 2,
    },

    # 生产：临产期 → 生产前 → 生产中 → 完成
    "birth": {
        "enabled": True,
        "due_days": 3.0,
        "pre_minutes": 120,
        "active_minutes": 30,
        "water_wet": 40.0,
        "pain_due": 5.0,
        "pain_pre": 20.0,
        "pain_active": 35.0,
        "pain_per_minute": 0.6,
        "pain_max": 100.0,
        "comfort_relief": 8.0,
        "comfort_keywords": ["安抚", "抱", "陪", "揉", "慢点", "呼吸", "别怕", "在呢"],
        "comfort_cooldown_seconds": 30,
        "gap_minutes": 10,
        "resume_delay_seconds": 60,
        "hymen_break": True,
    },

    # 胎儿占子宫 / 漏出加羞耻
    "fetus": {"volume_ml": 20.0, "full_ratio": 0.95, "extra_room_ml": 2.0},
    "leak": {"shame_gain": 4.0, "shame_cap": 30.0, "minutes": 10},

    # 避孕套：活动中破裂/感觉不到/换新/她帮戴
    "condom": {
        "break_per_action": 3.0,
        "unfelt_pleasure": 80.0,
        "unfelt_endurance": 80.0,
        "unfelt_chance": 60.0,
        "change_ask_chance": 50.0,
        "ask_chance": 40.0,
        "renew_ask_chance": 40.0,
        "remove_ask_chance": 20.0,
        "remove_help_chance": 50.0,
        "remove_min_minutes": 5,
        "remove_cooldown_minutes": 30,
        "help_desire": 8.0,
        "help_wet": 8.0,
        "help_shame": 10.0,
        "prompt_minutes": 10,
    },

    # 潮吹喷水：水量条 + 概率 + 加成
    "squirt": {
        "enabled": True,
        "water_max": 100.0,
        "start": 60.0,
        "regen_per_minute": 2.0,
        "min_water": 15.0,
        "chance": 30.0,
        "pleasure_bonus": 30.0,
        "endurance_bonus": 20.0,
        "after_bonus": 25.0,
        "combo_bonus": 15.0,
        "volume": 15.0,
        "volume_pleasure": 0.6,
        "volume_endurance": 0.4,
        "pad_absorb_ratio": 1.0,
        "combo_volume": 0.15,
        "cost_ratio": 1.0,
        "pleasure_gain": 12.0,
        "pleasure_cap": 20.0,
        "wet_gain": 15.0,
        "endurance_gain": 8.0,
        "combo_window_minutes": 10,
        "prompt_minutes": 5,
    },

    # 高潮提示词保留多久
    "orgasm": {"minutes": 5, "message_enabled": True},

    # 润滑油：加湿润、能管一阵；也能润滑手
    "lube": {
        "enabled": True,
        "wet_gain": 20.0,
        "minutes": 30,
        "hand_wet_gain": 15.0,
        "hand_minutes": 20,
        "breast_wet_gain": 8.0,
        "nipple_wet_gain": 5.0,
        "penis_wet_gain": 10.0,
    },

    # 干燥：湿润度太低时用生殖器插入会痛
    "dry": {
        "enabled": True,
        "wet_below": 25.0,
        "pleasure_drop": 6.0,
        "endurance_drop": 8.0,
        "wet_gain": 4.0,
        "minutes": 10,
    },

    # 保持插入不抽插：多久没动就按"保持"写
    "hold": {"after_seconds": 60, "minutes": 5},

    # 内射加湿润
    "inner": {"wet_gain": 10.0, "minutes": 10},

    # 插入子宫：湿润/快感门槛、疼痛、占用容量
    "insert": {
        "wet_at": 60.0,
        "pleasure_at": 55.0,
        "pain": 4.0,
        "orgasm_pain": 0.5,
        "orgasm_window_seconds": 120,
        "force_pain": 12.0,
        "force_penalty_enabled": True,
        "force_pleasure_drop": 8.0,
        "force_endurance_drop": 10.0,
        "force_wet_gain": 3.0,
        "occupies_capacity": True,
        "capacity_ml": 10.0,
        "fetus_pain": 2.0,
    },

    # 尺寸（cm）：阴道长度会小幅浮动，生殖器太短就碰不到子宫颈
    "size": {
        "penis_length": 14.0,
        "penis_girth": 3.5,
        "penis_head_length": 3.5,
        "uterus_length": 7.0,
        "tube_width": 0.8,
        "ovary_width": 1.6,
        "vagina_width": 3.0,
        "hymen_hole": 1.0,
        "hymen_depth": 2.5,           # 处女膜大致深度 cm
        "vagina_length": 12.0,
        "float_orgasm": 0.4,
        "float_orgasm_minutes": 10,
        "float_pleasure": 0.3,
        "float_pleasure_minutes": 8,
        "float_endurance": 0.3,
        "float_endurance_minutes": 8,
        "float_fetus": 0.3,
        "fetus_uterus_max_ratio": 1.8,  # 胎儿把子宫撑长最多到基础值的几倍
        "pleasure_at": 55.0,
        "pre_orgasm_shorten": 1.0,
        "pre_orgasm_ratio": 0.85,
        "endurance_at": 50.0,
        "reach_margin": 1.0,
        "cervix_stretch_max": 1.5,
        "cervix_stretch_ratio": 0.8,
        "cervix_stretch_minutes": 10,
        "notice_chance": 35.0,
        "notice_delta": 1.5,
        "dev_sens_boost": 0.5,
    },

    # 行为（牵手、哈热气、尾巴卷起来撸）：提示词保持多久
    "behavior": {"minutes": 5},

    # 突然被弄：不在活动里点面板按钮，她会吓一跳、可能主动发消息
    "surprise": {
        "enabled": True,
        "proactive_chance": 35.0,      # 会主动发消息的概率 %
        "proactive_delay_seconds": 8,  # 延迟几秒发
        "shock_minutes": 5,            # 多久之内还算"没缓过来"
        "remember_minutes": 60,        # 多久之内还记得这件事
        "message": "",                 # 主动消息自定义（空 = 用内置短句，{kind} 替换成类型）
    },

    # 睡眠时段 × 受孕活动：活动撞上她的睡觉时间时，暂时不限制她发言
    "sleep_inside": {
        "enabled": True,
        "keywords": {
            "vagina": ["阴道", "前面", "插进来", "进来"],
            "anus": ["后面", "肛", "肛门", "后庭"],
            "tail": ["尾巴", "尾根"],
            "unbirth": ["子宫", "unbirth", "最里面", "深处"],
        },
        "overnight_request_enabled": True,
        "overnight_request_chance": 12.0,
        "overnight_min_lewd": 45.0,
        "ask_wait_minutes": 5,
        "ask_night_start_hour": 21,
        "ask_night_end_hour": 6,
        "ask_night_start_hour": 21,
        "ask_night_end_hour": 6,
        "slight_pleasure": 2.0,
        "slight_wet": 1.0,
        "slight_endurance": 0.5,
        "slight_desire": 1.0,
    },

    "sleep": {
        "allow_speaking_in_activity": True,
        "wake_grace_minutes": 30,   # 活动期间每次给多久的"暂时醒着"
        "afterglow_minutes": 20,    # 活动结束之后再继续允许发言多久（事后余韵）
    },

    # ASMR 助眠：夜间耳朵助眠、道具、计时、收益
    "asmr": {
        "enabled": True,
        "known_keywords": ["助眠", "ASMR", "asmr", "哄睡"],
        "request_enabled": True,
        "request_start_hour": 21,
        "request_end_hour": 3,
        "request_chance": 35.0,
        "request_requires_known": True,
        "request_once_per_night": True,
        "request_judge": True,
        "request_defer_minutes": 30,
        "request_generate": True,
        "request_wait_minutes": 10,
        "default_minutes": 20,
        "extend_minutes": 5,
        "max_minutes": 90,
        "sleep_relief": 8.0,
        "sleep_relief_cap": 30.0,
        "sleep_relief_daily_cap": 40.0,
        "intimacy_gain": 0.6,
        "intimacy_cap": 6.0,
        "attachment_gain": 0.8,
        "attachment_cap": 8.0,
        "ear_sens_gain": 0.01,
        "ear_sens_cap": 0.2,
        "pleasure_gain": 2.5,
        "pleasure_cap": 20.0,
        "endurance_gain": 2.0,
        "endurance_cap": 20.0,
        "shame_gain": 4.0,
        "shame_cap": 16.0,
        "shame_decay_per_session": 0.8,
        "shame_floor": 0.8,
        "wet_gain": 0.5,
        "wet_cap": 20.0,
        "pregnancy_relief": 25.0,
        "pregnancy_relief_cap": 60.0,
        "sleep_chance": 30.0,
    },

    # 避孕：药和套
    "contraception": {
        "pill_proactive_enabled": True,
        "pill_proactive_chance": 30.0,
        "pill_proactive_window_minutes": 10,
        "pill_proactive_cooldown_minutes": 180,
        "pill_proactive_delay_seconds": 0,
        "pill_cancel_keywords": ["别吃", "不要吃", "不用吃", "先别", "停", "别"],
        "pill_take_keywords": ["吃吧", "吃了", "可以吃", "吃"],
        "pill_blame_enabled": True,
        "pill_blame_chance": 40.0,
        "pill_blame_amount": 6.0,
        "pill_blame_window_minutes": 240,
        "pill_blame_require_promise": True,
        "pill_blame_once": True,
        "pill_inside_promise_keywords": ["不会射在里面", "不射在里面", "不内射",
                                         "射在外面", "体外", "不会内射"],
        "pill_enabled": True,
        "pill_effectiveness": 92.0,    # 吃药后每次受孕概率乘 (1-92%) = 8%
        "pill_hours": 24.0,
        "condom_enabled": True,
        "condom_effectiveness": 98.0,  # 戴套时受孕概率乘 2%
        "condom_break_chance": 2.0,    # 每次使用的破裂概率（%）
    },

    # 魅魔：欲望更强、吸收更快，完成后给 PC 精力和鱼之心依恋/亲密
    "succubus": {
        "enabled": False,
        # 淫纹等级：0-5；等级越高欲望涨得越快，加成也越高
        "tattoo_level": 1,
        "tattoo_gain_per_level": 0.25,  # 每级让所有加成 ×(1+这个值)
        "exp_gain": 10,                # 每次榨取涨多少经验
        "exp_per_level": 100,          # 升一级需要的经验
        # 欲望增长（每一次活动，基础值 + 等级加成）
        "desire_base_gain": 3.0,
        "desire_gain_per_level": 1.0,
        # 每天榨取次数：0 = 不限
        "daily_limit": 0,
        # 每次高潮（她到）的加成
        "pc_energy_gain": 12,
        "fish_attachment_gain": 2.0,
        "fish_intimacy_gain": 2.0,
        "fish_desire_gain": 4.0,
        # 每次射出（不管射哪）的加成
        "ejaculation_energy_gain": 6,
        "ejaculation_attachment_gain": 1.0,
        "ejaculation_intimacy_gain": 1.0,
        "ejaculation_desire_gain": 2.0,
        # 受孕难度：魅魔开启后先乘 hard_to_conceive；
        # 她愿意怀再乘 willing_bonus，明确不愿意乘 unwilling_factor
        "hard_to_conceive": 0.25,
        "unwilling_factor": 0.02,
        "willing_bonus": 4.0,
        "willing_conception_energy": 30,
        "willing_conception_fish_gain": 3.0,
        "pleasure_scale": 1.35,
        "absorption_multiplier": 12.0,
        "tail_sensitivity_scale": 1.5,  # 魅魔尾巴的敏感度倍率
        # 魅魔尾巴：关了也不影响「敏感点·尾巴」；开着的话角色没尾巴也能启用尾巴，
        # 而且算魅魔尾巴（敏感度 × tail_sensitivity_scale）
        "tail_enabled": False,
        "pc_write_enabled": True,
        "fish_write_enabled": True,
    },

    # 敏感点：每个部位独立的开发度与敏感度，
    # 一次触碰快感 = 基础 × (0.4 + 0.8×开发度/100) × 敏感度
    "zones": {
        "enabled": True,
        "keyword_detect": True,
        "sens_decay_after_minutes": 720,
        "sens_decay_per_hour": 0.05,
        # 亲吻
        "kiss_enabled": True,
        "kiss_dev": 20,
        "kiss_sensitivity": 0.7,
        "kiss_pleasure": 5,
        # 乳房
        "breast_enabled": True,
        "breast_dev": 25,
        "breast_sensitivity": 0.9,
        "breast_pleasure": 6,
        # 乳头
        "nipple_enabled": True,
        "nipple_dev": 30,
        "nipple_sensitivity": 1.2,
        "nipple_pleasure": 7,
        # 外阴
        "vulva_enabled": True,
        "vulva_dev": 30,
        "vulva_sensitivity": 1.1,
        "vulva_pleasure": 8,
        # 阴道
        "vagina_enabled": True,
        "vagina_dev": 35,
        "vagina_sensitivity": 1.1,
        "vagina_pleasure": 9,
        # G点
        "gspot_enabled": True,
        "gspot_dev": 25,
        "gspot_sensitivity": 1.3,
        "gspot_pleasure": 10,
        # 子宫颈
        "cervix_enabled": True,
        "cervix_dev": 20,
        "cervix_sensitivity": 1.4,
        "cervix_pleasure": 11,
        # 肛
        "anus_enabled": True,
        "anus_dev": 15,
        "anus_sensitivity": 0.9,
        "anus_pleasure": 6,
        # 嘴/喉咙
        "mouth_enabled": True,
        "mouth_dev": 20,
        "mouth_sensitivity": 0.8,
        "mouth_pleasure": 5,
        # 耳朵：轻碰就很有反应，基础涨幅不高，敏感度偏上
        "ear_enabled": True,
        "ear_dev": 25,
        "ear_sensitivity": 1.3,
        "ear_pleasure": 4,
        # 脚：足心/脚趾比脚背敏感，整体介于亲吻和乳头之间（一次 ≈ +2.8）
        "foot_enabled": True,
        "foot_dev": 20,
        "foot_sensitivity": 1.0,
        "foot_pleasure": 5,
        # 尾巴：魅魔的尾巴，天生比普通部位敏感；魅魔开启时再乘倍率
        "tail_enabled": True,
        "tail_dev": 20,
        "tail_sensitivity": 1.8,
        "tail_pleasure": 9,
        # 手：牵手、十指相扣、舔手、手淫这类；开发度低、敏感度偏低
        "hand_enabled": True,
        "hand_dev": 15,
        "hand_sensitivity": 0.9,
        "hand_pleasure": 4,
        # 子宫：最深处，敏感度最高（插入机制后面单独做）
        "uterus_enabled": True,
        "uterus_dev": 10,
        "uterus_sensitivity": 1.6,
        "uterus_pleasure": 13,
        # 阴蒂：外阴顶端，敏感度高
        "clitoris_enabled": True,
        "clitoris_dev": 25,
        "clitoris_sensitivity": 1.5,
        "clitoris_pleasure": 10,
        # 处女膜：只有在 Unbirth 通过/被撑到时才直接碰
        "hymen_enabled": True,
        "hymen_dev": 5,
        "hymen_sensitivity": 1.2,
        "hymen_pleasure": 6,
        # 输卵管：只有顶到最里面 / Unbirth 时才碰得到
        "tube_enabled": True,
        "tube_dev": 5,
        "tube_sensitivity": 1.4,
        "tube_pleasure": 9,
        # 卵巢：很深，只有揉小腹 / 筋膜枪 / Unbirth / 顶到最里面时才碰得到
        "ovary_enabled": True,
        "ovary_dev": 5,
        "ovary_sensitivity": 1.3,
        "ovary_pleasure": 11,
    },

    # 日常情绪：欲望度 / 羞耻度（主要在日常小场景里起作用，见 core/mood.py）
    "mood": {
        "enabled": True,
        # 羞耻度一开局就有一点（因为要碰小玩具），之后可以一直降到 0
        "shame_initial": 20.0,
        # 每次激发小玩具：欲望 / 羞耻各涨多少
        "desire_gain": 8.0,
        "self_approach_after_scene_minutes": 30,
        "shame_gain": 12.0,
        # 每小时自然回落：欲望比羞耻快一点点
        "desire_decay_per_hour": 12.0,
        "shame_decay_per_hour": 8.0,
        # 安慰 / 摸摸头 / 亲吻：一次降多少
        "comfort_relief": 10.0,
        "comfort_desire_relief": 4.0,
        # 正常进行日常（每聊一轮，有冷却）：羞耻降多少
        "daily_relief": 3.0,
        "daily_relief_minutes": 5,
        # 羞耻满溢：进羞耻期，这段时间她自己不肯用玩具
        "shame_period_minutes": 30,
        # 羞耻满溢时给鱼之心加多少「责怪」（0 = 不加）
        "shame_blame": 4.0,
        # 面板「道歉」按钮每按一次，帮鱼之心降多少责怪
        "apology_blame": 4.0,
        # 允许写鱼之心（责怪）
        "fish_write_enabled": True,
        # 从对话里识别安慰 / 摸摸头 / 亲吻
        "keyword_detect": True,
    },

    # 子敏感度：只在受孕活动（亲密场景）里生效的第二层条。
    # 碰一次只涨这里的条（0–100，三段：初起/发烫/将溢），条满了溢出一次：
    # 给主敏感点加开发度/敏感度、额外补一笔快感，然后条在几秒内回落到 0。
    "sub_zones": {
        "enabled": True,
        # 只在受孕活动里涨；关掉就变成"随时随地都能涨"（一般不需要）
        "scene_only": True,
        "max": 100.0,                    # 条满值
        # 一次触碰涨多少：34 × (0.8 + sensitivity_scale × 敏感度)
        # 亲吻约 +35.6、乳头约 +41.9、尾巴约 +49.3 —— 活动里两三下就满，不卡进度
        "gain": 34.0,
        "sensitivity_scale": 0.35,
        "scene_decay_per_minute": 0.0,    # 活动里不碰时的自然回落
        "idle_decay_per_minute": 30.0,    # 不在活动里：1 分钟左右掉一半、3 分钟见底
        # 溢出的奖励（"稍多一点"：比普通碰一次的开发度/快感都高）
        "burst_dev": 6,                  # 主敏感点开发度 +6
        "burst_sensitivity": 0.12,       # 主敏感点敏感度 +0.12
        "burst_pleasure": 12.0,          # 额外快感 +12
        "burst_fall_seconds": 2.4,       # 满了之后多久回落到 0（越快越"一下子上来又退下去"）
        "burst_cooldown_seconds": 2.4,   # 回落中不涨、也不连着爆（和回落时长一致 = 退回 0 才重新涨）
        "dev_cap": 100,                  # 溢出攒的开发度上限（叠在面板/配置值上）
        "sensitivity_cap": 5.0,          # 溢出攒的敏感度上限
        "prompt_zones": 3,               # 提示词里最多带几个正在涨的部位
    },

    # 射精方式：只有阴道内参与受孕，且只有它计入子宫容量
    "ejaculation": {
        "vagina_pleasure": 10.0,
        "anal_pleasure": 12.0,
        "throat_pleasure": 8.0,
        "outside_pleasure": 4.0,
        "volume_ml": 3.0,
        "uterus_capacity_ml": 20.0,
        "uterus_leak_per_hour": 0.4,
        # 子宫能短暂撑开一点：到 stretch_at 比例后再射就会撑，
        # 最多多装 stretch_ratio（0.35 = 多 35%）；量降回基础容量以内就自己缩回去（不靠计时）
        "uterus_stretch_at": 0.6,
        "uterus_stretch_ratio": 0.35,
        # 满了会溢：到 overflow_at（占总容量比例）再射就往外溢，可开关
        "uterus_overflow_enabled": True,
        "uterus_overflow_at": 0.95,
        "uterus_overflow_minutes": 15,
        # 活动结束后会渐渐漏出去：漏到 until（占容量 %）以下就停，剩下的交给吸收
        "uterus_after_leak_enabled": True,
        "uterus_after_leak_per_hour": 6.0,
        "uterus_after_leak_until": 20.0,
    },

    # 寸止：快感快到门槛时停下来，之后更渴、门槛暂时更高，最后到的时候更强烈
    # 小玩具：用一次涨快感（不判定受孕），会在身上留一段状态
    # 小玩具：用一次涨快感（不判定受孕），会在身上留一段状态
    "toys": {
        "enabled": True,
        "keyword_detect": True,
        "active_minutes": 10,
        "intensity_scale": 1.0,
        # 日常小场景：不进入亲密、只是用一下日常玩具时开的小窗口
        "daily_scene": True,        # 日常用玩具会开一个"日常小场景"
        "daily_minutes": 20,        # 多久没继续就散
        "sub_zone": True,           # 玩具也推高对应部位的子敏感度（日常/场景都算）
        "auto_orgasm": True,        # 玩具把快感推过门槛时自动记一次高潮
        "endurance_gain": 2.0,      # 用一次玩具额外攒多少高潮忍耐
        # 她主动用玩具
        "self_use_enabled": True,
        "self_use_chance": 20.0,    # 每次检查触发概率 %
        "self_use_check_minutes": 30,
        "self_use_cooldown_minutes": 120,
        "self_use_min_desire": 60.0,
        "self_use_min_wet": 50.0,
        "self_use_min_lewd": 30.0,
        "self_use_controller_chance": 30.0,  # 把控制器递给主人的概率 %
        "self_use_delay_seconds": 0,
        # 跳蛋
        "bullet_enabled": True,
        "bullet_pleasure": 8.0,
        "bullet_outside": True,   # 不在亲密场景时也能用
        # 振动棒
        "vibrator_enabled": True,
        "vibrator_pleasure": 12.0,
        "vibrator_outside": False,   # 不在亲密场景时也能用
        # 吸吮器
        "sucker_enabled": True,
        "sucker_pleasure": 10.0,
        "sucker_outside": False,   # 不在亲密场景时也能用
        # 按摩棒
        "wand_enabled": True,
        "wand_pleasure": 9.0,
        "wand_outside": True,   # 不在亲密场景时也能用
        # 肛塞
        "plug_enabled": True,
        "plug_pleasure": 7.0,
        "plug_outside": False,   # 不在亲密场景时也能用
        # 乳夹
        "clamp_enabled": True,
        "clamp_pleasure": 6.0,
        "clamp_outside": True,   # 不在亲密场景时也能用
        # 筋膜枪：一直可用；按部位分三档加成
        "massage_gun_enabled": True,
        "massage_gun_outside": True,
        "massage_gun_pleasure": 10.0,
        "mg_soft_attachment": 1.0,
        "mg_soft_intimacy": 1.0,
        "mg_soft_desire": 3.0,
        "mg_body_pleasure": 4.0,
        "mg_body_desire": 3.0,
        "mg_body_wet": 5.0,
        "mg_body_endurance": 2.0,
        "mg_hot_pleasure": 10.0,
        "mg_hot_desire": 6.0,
        "mg_hot_wet": 10.0,
        "mg_hot_endurance": 4.0,
    },

    "edge": {
        "enabled": True,
        "min_ratio": 0.55,            # 至少到门槛的 55% 才能算寸止
        "threshold_step": 8.0,        # 第一次寸止后门槛 +8
        "step_decay": 0.7,            # 每多一次，加成递减
        "max_bonus": 20.0,            # 门槛加成上限
        "window_minutes": 25,         # 多久没继续就消退
        "craving_gain": 18.0,         # 每次寸止渴求 +18
        "craving_decay_per_hour": 6.0,
        "craving_gain_bonus": 0.35,   # 渴求满时触碰收益 +35%
        "orgasm_bonus": 12.0,         # 寸止后高潮的额外快感（每次叠加）
        "orgasm_bonus_cap": 40.0,
        "auto_full_minutes": 10,      # 忍耐满后多久没高潮，自动算一次寸止
    },

    # 诱发排卵：不在排卵期，也可能被累积的高潮/快感"催"出来
    "ovulation": {
        "induced_enabled": True,
        "min_orgasms": 3,             # 本次会话高潮到 3 次
        "min_pleasure": 70.0,         # 或快感到 70
        "chance": 18.0,               # 满足条件后每次高潮掷一次
        "duration_hours": 24.0,
        "cooldown_hours": 72.0,
        "require_outside_fertile": True,  # 已经在排卵前期/排卵期就不触发
    },

    "menstrual": {
        "enabled": True,
        "flow_ml_per_hour": 4.0,
        "flow_jitter": 0.35,
        "capacity_ml": 60.0,
        "drain_ml_per_hour": 8.0,
        "pad_models": {"liner": 8.0, "regular": 20.0, "night": 35.0, "pants": 60.0},
        "pad_auto_choose": True,
        "pad_capacity_ml": 20.0,
        "change_at_percent": 80.0,
        "change_min_minutes": 30,
        "auto_pad": True,
        "pad_change_shame": 6.0,
        "pad_change_desire": 4.0,
        "pad_change_wet": 4.0,
        "pad_change_fish_desire": 3.0,
        "pad_mixed_shame": 8.0,
        "pad_mixed_desire": 6.0,
        "pad_mixed_fish_desire": 4.0,
        "pad_mixed_wet": 5.0,
        "pad_unbirth_shame": 8.0,
        "pad_unbirth_desire": 6.0,
        "pad_unbirth_wet": 6.0,
        "pad_unbirth_fish_desire": 4.0,
        "pad_shame_cap": 99.0,
        "pad_seen_chance": 35.0,
        "pad_seen_shame": 8.0,
        "pad_seen_fish_desire": 3.0,
        "pad_notice_chance": 100.0,
        "pad_warn_minutes": 2,
        "pad_change_minutes": 2,
    },

    "cycle": {
        # auto：优先读 private_companion 的周期，读不到就用插件自己的
        # pc  ：只读 PC；own：只用插件自己的
        "source": "auto",
        "prompts_enabled": True,
        "own_anchor_date": "",         # 留空 = 首次运行时按自然偏移落一个锚点
        "own_menstrual_days": 5,
        "own_follicular_days": 7,
        "own_pre_ovulation_days": 2,
        "own_ovulation_days": 2,
        "own_luteal_days": 9,
        "own_pms_days": 3,
    },

    "inject": {
        "enabled": True,
        "stable_system": True,         # 受孕状态写进 system prompt（日常提示词）
        "dynamic_tail": True,          # 快感/高潮/阶段挂在本轮用户消息末尾
        "show_pleasure": True,
        "show_probability_tier": True,
        "show_arousal_tone": True,     # 快感/高潮也影响她的语气和行为提示
        "tool_hint": True,
    },

    "tools": {
        "enabled": True,
        "touch": True,
        "edge": True,
        "toy": True,
        "expel": True,
        "contraception": True,
        "pleasure": True,
        "orgasm": True,
        "ejaculation": True,
        "status": True,
        "self_test": True,
    },

    # 淫乱度：场景/日常积累，久了会退；高了会自己推欲望和湿润
    # 欲望来源策略：每个功能自己选读哪条欲望
    "desire": {
        "night_raid": "max",
        "daily_scene": "mood",
        "wetness": "fish",
        "conception": "both",
    },

    "lewd": {
        "enabled": True,
        "max": 100.0,
        "scene_add": 8.0,
        "daily_add": 5.0,
        "tick_minutes": 20,
        "tick_min": 30.0,
        "cost_per_tick": 4.0,
        "desire_per_tick": 3.0,
        "wet_per_tick": 3.0,
        "decay_after_minutes": 120,
        "decay_per_hour": 4.0,
        "prompt_min": 15.0,           # 淫乱度低于这个值不注入提示词
        "level_at_2": 25.0,           # 到多少 % 算第 2 段
        "level_at_3": 50.0,           # 到多少 % 算第 3 段
        "level_at_4": 75.0,           # 到多少 % 算第 4 段
    },

    # 夜袭：她半夜自己摸过来；PC 熬夜时才会考虑
    "night_raid": {
        "enabled": True,
        "start_hour": 23,
        "end_hour": 4,
        "desire_min": 65.0,
        "very_high_desire": 85.0,
        "very_high_wet_min": 80.0,
        "very_high_bonus": 20.0,
        "wet_min": 65.0,
        "chance": 35.0,
        "pregnancy_chance": 5.0,
        "activity_window_minutes": 240,
        "after_ejac_minutes": 360,
        "after_ejac_factor": 0.2,
        "unfinished_minutes": 180,
        "unfinished_bonus": 20.0,
        "lead_minutes": 30,
        "wait_minutes": 10,
        "afterglow_minutes": 10,
        "after_scene_minutes": 30,
        "cooldown_hours": 6,
        "pc_keywords": ["熬夜", "失眠", "睡不着", "没睡", "通宵", "还醒着"],
        "lewd_late_per_point": 0.5,
        "lewd_late_max": 80.0,
        "pc_stay_up_enabled": True,
        "fish_stay_up_enabled": True,
        "fish_stay_up_bonus": 0.5,
        "energy_gain": 5,
    },

    "debug": False,
}

# 只读插件数据（不写）的联动开关
SOURCES_DEFAULTS = {
    "fish_heart_state": str(FISH_HEART_STATE),
    "fish_heart_config": str(FISH_HEART_CONFIG),
    "dark_state": str(LONGING_STATE),
    "dark_engine_state": str(LONGING_ENGINE_STATE),
    "desire_switch": str(DESIRE_SWITCH),
    "pc_db": str(PC_DB),
    # 暗涌状态文件超过这个分钟数就当引擎没在跑
    "dark_max_age_minutes": 15,
}
# 这些键也进 schema（放在 sources 组里）
DEFAULTS["sources"] = dict(SOURCES_DEFAULTS)


# ---------------------------------------------------------------- 读取

def cfg_raw(config, path: str, default=None):
    """按 a.b.c 取配置；读不到返回 default；None 也当读不到。"""
    node = config
    for part in path.split("."):
        if isinstance(node, Mapping):
            if part not in node:
                return default
            node = node[part]
        else:
            return default
    return default if node is None else node


def default_of(path: str):
    node = DEFAULTS
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class Settings:
    """把 AstrBot 传进来的 config（dict）包一层类型安全。"""

    def __init__(self, config=None):
        self.config = config if isinstance(config, Mapping) else {}

    # -- 基础 --

    def raw(self, path: str):
        return cfg_raw(self.config, path, default_of(path))

    def str(self, path: str) -> str:
        value = self.raw(path)
        return str(value).strip() if value is not None else ""

    def bool(self, path: str) -> bool:
        value = self.raw(path)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "是", "开")
        return bool(value)

    def float(self, path: str, lo: float | None = None, hi: float | None = None) -> float:
        try:
            value = float(self.raw(path))
        except (TypeError, ValueError):
            try:
                value = float(default_of(path) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
        if lo is not None:
            value = max(lo, value)
        if hi is not None:
            value = min(hi, value)
        return value

    def int(self, path: str, lo: int | None = None, hi: int | None = None) -> int:
        return int(round(self.float(path, lo, hi)))

    def list(self, path: str) -> list[str]:
        value = self.raw(path)
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
        return []

    # -- 组合 --

    def phase_probability(self) -> dict[str, float]:
        """各生理期阶段的受孕基准（百分比）。"""
        result = {}
        for phase in ("menstrual", "follicular", "pre_ovulation", "ovulation",
                      "luteal", "pms", "recovery", "unknown", "paused"):
            result[phase] = self.float(f"phase_probability.{phase}", 0.0, 100.0)
        return result

    def own_cycle_days(self) -> list[dict]:
        return [
            {"phase": "menstrual", "days": self.int("cycle.own_menstrual_days", 1, 30)},
            {"phase": "follicular", "days": self.int("cycle.own_follicular_days", 1, 30)},
            {"phase": "pre_ovulation", "days": self.int("cycle.own_pre_ovulation_days", 0, 30)},
            {"phase": "ovulation", "days": self.int("cycle.own_ovulation_days", 0, 30)},
            {"phase": "luteal", "days": self.int("cycle.own_luteal_days", 1, 40)},
            {"phase": "pms", "days": self.int("cycle.own_pms_days", 0, 30)},
        ]

    def summary(self) -> dict:
        """给 /受孕状态 用的一层摘要。"""
        return {
            "enabled": self.bool("enabled"),
            "owner_qq": self.str("owner_qq"),
            "gender_mode": self.str("gender_mode"),
            "adult_required": self.bool("adult_required"),
            "suppress_pc_cycle": self.bool("pregnancy.suppress_pc_cycle"),
            "pc_write": self.bool("pregnancy.pc_write_enabled"),
            "pc_role_name": self.str("pregnancy.pc_role_name"),
            "cycle_source": self.str("cycle.source"),
        }
