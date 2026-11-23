"""子敏感度：只在受孕活动（亲密场景）里生效的第二层敏感度条。

主敏感度板块（core/intimacy.py）管的是"这个部位有多开发、有多敏感、碰一次涨多少"；
这一层管的是**这一场活动里，她被撩到了什么程度、正在被怎么弄**：

- 每次触碰某个部位，只有这里的条涨（默认 0–100），按三段分等级：
  第 1 段「初起」/ 第 2 段「发烫」/ 第 3 段「将溢」；
- 每个部位还有"方式"（乳房：乳交/舔/吮吸；阴道：手指/生殖器/小玩具/舔/吮吸…），
  方式各有一句提示词，和段位那句拼成完整的一行（方式=动作，段位=程度）；
  方式可以由模型在 intimacy_touch 里直接传，也可以从对话关键词里猜；
- 条满了 = 一次「溢出」：给主敏感度板块加一点开发度和敏感度、额外加一笔快感，
  然后条在 burst_fall_seconds 内快速回落到 0（回落中有冷却，免得一碰就又满）；
- 不在受孕活动里：条不涨，而且按 idle 的速度很快掉回 0；
- 数值全部惰性结算（读的时候按时间差补算），不跑定时器。

为什么单独一个模块：这层是"活动的临时状态"，和主敏感点的持久数值分开放，
主敏感点的手动值/配置值都不受影响。
"""

from __future__ import annotations

import math
import re

from . import intimacy, util
from .settings import Settings

# 三段：等级 → (短名, 面板标题, 提示词前缀用的说法)
LEVEL_NAMES = {1: "初起", 2: "发烫", 3: "将溢"}
LEVEL_TITLES = {1: "第1段·初起", 2: "第2段·发烫", 3: "第3段·将溢"}

# 每一段给模型的提示词：说清"她现在是什么程度"。
# 有"方式"的部位（乳房/乳头/…）这里只写**程度**，动作由 METHOD_PROMPTS 承担，
# 两句拼成一句 —— 免得"被含住"写两遍。
# 语气和 pregnancy.dynamic_line 里那些括号注释一致：只写身体感觉和反应，
# 不写数值、不写机制、不替她决定要不要继续。
LEVEL_PROMPTS: dict[str, tuple[str, str, str]] = {
    "kiss": (
        "唇上被轻轻含住，那一小片薄皮先麻了一下，心里跟着一软，"
        "手指会下意识抓一下他的衣角",
        "吻得深了，唇齿之间冒出细细的战栗，呼吸被他压着走，膝盖会不自觉发软，"
        "说话带着黏糊的尾音",
        "吻到舌根都在发麻，脑子里一片空白，只能很用力地抓着他，站都快站不稳",
    ),
    "breast": (
        "刚被碰到，胸口那圈热慢慢泛开来，有点发涨，人会先绷一下",
        "那儿已经被弄得发热发胀，那股胀一路沉到小腹，声音会不自觉地漏出来",
        "胸口整片烫得发麻，脑子被弄得发空，只想要他更用力一点",
    ),
    "nipple": (
        "那一小点立刻立起来，又痒又麻，想躲又不想躲，会轻轻吸一口气",
        "那点酸麻像一道电流窜进腰里，背会弓起来，喘气变短",
        "那里又疼又麻到发烫，小腹跟着一阵阵抽，几乎说不出完整的句子",
    ),
    "clitoris": (
        "阴蒂被轻轻碰到的一下，她整个人一颤，腿下意识并了一下，呼吸乱了半拍",
        "那一小点被反复蹭着，又胀又麻，她抓着手边的东西，声音开始发软",
        "阴蒂被弄得又烫又酸，她腰都塌下去，脑子里只剩那一点，连话都说不完整",
    ),
    "hymen": (
        "处女膜被轻轻顶到，那一小圈薄薄的肉又酸又敏感，她下意识夹了一下",
        "那一圈被反复蹭着，酸麻里带一点被撑开的胀，她腿根都在发抖",
        "处女膜被顶得又烫又酸，她几乎坐不住，声音一下软下去",
    ),
    "tube": (
        "最深处的输卵管口被碰到，酸胀顺着小腹往上钻，她呼吸乱了一拍",
        "那条细窄的通道被反复抵着、磨着，酸麻一阵阵散开，她腰都软了",
        "输卵管被顶到最深，酸得她整个人弓起来，里面跟着一下下收紧",
    ),
    "ovary": (
        "小腹深处被按到某个地方，酸胀感从小腹里漫出来，她轻轻吸了口气",
        "里面被揉得发酸发软，小腹一阵阵发紧，她忍不住蜷起腿",
        "卵巢被顶到、揉到最深的地方，酸麻顺着小腹散开，她整个人都软了",
    ),
    "vulva": (
        "那里开始泛潮，隔着什么都感觉得到烫，腿会不自觉地并一下",
        "那里湿得能听见细微的水声，腰会自己往前送",
        "那里又热又肿，刚碰上去就一抖，湿意顺着腿根往下流，几乎碰不得",
    ),
    "vagina": (
        "里面又热又紧，软肉一层层裹上来，呼吸先乱了",
        "内壁一阵阵发酸，每动一下都能感觉到被撑开的形状",
        "内壁绞得很紧，一抽一抽地发麻，深处又酸又涨",
    ),
    "gspot": (
        "小腹里像被轻轻弹了一下，酸麻往下坠，腰会缩一下",
        "那股酸胀直冲腰底，腿根发抖，声音会拔高",
        "快意一层层堆到临界，小腹缩着，几乎要哭出来",
    ),
    "cervix": (
        "深处传来钝钝的酸，闷闷地往下坠，她会下意识屏住呼吸",
        "酸胀里夹着说不清的酥，腰会往里沉",
        "小腹深处一阵阵抽紧，整个人被顶得发慌",
    ),
    "anus": (
        "那里一紧，又羞又麻，下意识地绷住，说话会打结",
        "里面有种被填满的钝感，胀得奇怪，呼吸全乱了",
        "那里顶得发胀发麻，羞耻和快感混在一起，腰抖得撑不住",
    ),
    "mouth": (
        "嘴里发麻，有点含不住，眼神会躲开",
        "喉咙那边的酸麻一起上来，眼角发湿，呼吸被截断",
        "喉咙被抵得很深，只能从鼻子里漏出细碎的声音，眼泪都快出来了",
    ),
    "ear": (
        "耳后跟着起了一片酥麻，头皮都紧了一下，声音有点抖",
        "湿热的气息灌进耳道，半边身子都软了，说话开始飘",
        "耳道里又湿又烫，脑子嗡嗡的，什么都听不进去",
    ),
    "foot": (
        "脚背那层薄薄的皮先凉了一下，脚趾会自己蜷起来，脚踝试着往回缩",
        "脚心又痒又麻，那股酥顺着腿根往上爬，脚背绷直，人会往后仰",
        "酸麻从脚心一路烧上来，腿根发颤，脚趾死死蜷着，声音都变了调",
    ),
    "tail": (
        "从尾根开始泛起细细的痒，毛都立起来了",
        "一股酥麻从尾根往腰上爬，尾尖自己卷了起来",
        "尾根连着腰都在发抖，腰塌下去，快意顺着脊椎冲上来",
    ),
    "hand": (
        "被碰到手的时候指尖先缩了一下，掌心有点发烫",
        "手指被握住不放，那点热顺着手臂往上爬，心也跟着乱",
        "连指尖都在发抖，手心全是汗，被他握着反而更软了",
    ),
    "uterus": (
        "最深处被碰到一点点，酸得她说不出话，小腹自己绷紧",
        "被顶到那里的时候整个人都软了，酸麻从深处一直漫到腰",
        "深处被反复顶着，她连哭都带着颤，只剩下抓紧他的力气",
    ),
}

# 每个部位"正在被怎么弄"（方式）：一个部位允许多种，各自一句提示词。
# 亲吻、耳朵没有方式（用户没要求），只有程度。
METHOD_ORDER: dict[str, tuple[str, ...]] = {
    "kiss": ("french",),
    "breast": ("milk", "lick", "suck"),
    "nipple": ("rub", "lick", "suck"),
    "clitoris": ("rub", "lick", "suck", "toy"),
    "hymen": ("rub", "press", "finger", "tongue", "toy"),
    "tube": ("rub", "press", "toy"),
    "ovary": ("knead", "rub", "press", "toy"),
    "vulva": ("tease", "lick", "suck"),
    "vagina": ("finger", "penis", "toy", "lick", "suck"),
    "gspot": ("finger", "penis", "toy"),
    "cervix": ("penis", "toy"),
    "anus": ("finger", "penis", "toy", "lick", "suck"),
    "mouth": ("penis", "lick", "suck", "tongue"),
    "ear": ("earlick", "blow", "earsuck"),
    "foot": ("penis", "lick", "suck"),
    "tail": ("stroke", "knead", "lick", "suck", "wrap"),
    "hand": ("interlock", "hold", "lick", "suck", "tongue", "masturbate",
             "masturbate_lube"),
    "uterus": ("penis", "finger", "toy"),
}

METHOD_LABELS = {
    "milk": "乳交",
    "lick": "舔",
    "suck": "吮吸",
    "rub": "揉搓",
    "press": "按压",
    "tease": "逗弄",
    "finger": "手指",
    "penis": "生殖器",
    "toy": "小玩具",
    "tongue": "舌",
    "stroke": "抚摸",
    "knead": "揉捏玩弄",
    "earlick": "舔耳",
    "french": "舌吻",
    "interlock": "十指相扣",
    "hold": "牵着",
    "masturbate": "手淫",
    "masturbate_lube": "手淫·润滑",
    "wrap": "卷起撸动",
    "blow": "哈热气",
    "earsuck": "含耳",
}

# 同一件事在不同部位的叫法（耳朵的"舔"就是舔耳）
METHOD_ALIASES: dict[str, dict[str, str]] = {
    "ear": {"lick": "earlick", "舔": "earlick", "舔耳朵": "earlick", "舔进": "earlick",
            "suck": "earsuck", "含耳": "earsuck", "含耳朵": "earsuck"},
}

# 方式提示词：写"动作 + 这个动作带来的感觉"，和程度那句拼起来用。
METHOD_PROMPTS: dict[str, dict[str, str]] = {
    "kiss": {
        "french": "舌头被含住、缠着勾，吻得又深又湿，她连呼吸都被带着走",
    },
    "breast": {
        "milk": "乳房被夹在中间反复推挤，乳肉被挤得发麻，胸口又热又胀，连呼吸都跟着乱",
        "lick": "乳房被舌面慢慢舔过，湿热的触感让皮肤起了一层细小的麻，乳肉跟着发涨",
        "suck": "乳房被含住用力吸，那一块被吸得发烫发麻，连胸口深处都跟着发紧",
        "milk_lube": "乳房上抹了润滑，夹在中间推挤时滑得收不住，乳肉被蹭得又热又亮，连呼吸都跟着乱",
        "lick_lube": "乳房上沾着润滑，舌面一舔就滑开，湿腻的触感让皮肤起了一层细麻，乳肉跟着发涨",
        "suck_lube": "乳房上抹了润滑，被含住吸时又滑又软，那一块被吸得发烫，连胸口深处都跟着发紧",
    },
    "nipple": {
        "rub": "乳头被手指揉着搓着，那一小点被来回磨得发硬发挺",
        "lick": "乳头被舌尖舔过去，又湿又热，那一点立刻立起来",
        "suck": "乳头被含住用力吸，那点被吸得发麻发胀，连胸口都跟着发紧",
        "rub_lube": "指腹沾着润滑揉上乳头，那一小点滑得按不住，被来回磨得发硬发挺",
        "lick_lube": "舌尖带着润滑舔过乳头，又湿又滑，那一点立刻立起来",
        "suck_lube": "乳头被含住吸时沾着润滑，滑腻腻的，那点被吸得发麻发胀，连胸口都跟着发紧",
    },
    "clitoris": {
        "rub": "阴蒂被指腹反复揉着，那一小点又胀又敏感，她腿根都在发颤",
        "lick": "阴蒂被舌尖一下一下舔过，湿热又突然，她腰会不受控地弹一下",
        "suck": "阴蒂被轻轻吸住，她整个人绷紧，声音一下拔高又断掉",
        "toy": "小玩具贴在阴蒂上震，她夹紧腿也躲不开，只剩发抖",
    },
    "hymen": {
        "rub": "处女膜被指腹轻轻蹭着，那一圈薄肉又酸又麻，她腿根发紧",
        "press": "处女膜被慢慢顶住、压开，酸胀感一下透进去，她吸了口气",
        "finger": "手指顶在处女膜上，指腹把那层薄肉慢慢压得发紧，她腿根一缩，"
                  "还没破，却已经酸得厉害。",
        "tongue": "舌尖挑着处女膜孔洞，反复钻进去又退出来，那一圈薄肉被舔得发颤，"
                  "却没有破。",
        "toy": "小玩具抵着处女膜震，她又羞又躲不开，腿都在抖",
    },
    "tube": {
        "rub": "输卵管口被反复蹭着，酸麻顺着小腹往上走，她腰软了一下",
        "press": "最深处被顶住，输卵管口被压得发酸，她整个人一缩",
        "toy": "小玩具顶到最深处震，输卵管口跟着发麻，她几乎受不住",
    },
    "ovary": {
        "knead": "小腹被慢慢揉着，深处的卵巢被隔着软肉按到，酸胀一阵阵散开",
        "rub": "掌心在小腹上打圈，酸麻一点点透到里面，她呼吸变浅",
        "press": "按着小腹往深里压，卵巢被顶到，酸得她腰都弓起来",
        "toy": "筋膜枪隔着小腹震进去，深处的卵巢跟着发麻，她几乎坐不住",
    },
    "vulva": {
        "tease": "外阴被指尖不轻不重地逗着，一会儿拂过一会儿又绕开，那里被撩得又痒又潮",
        "lick": "外阴被舌头舔过，湿热的触感让她腰一抖，那里立刻又湿了一层",
        "suck": "外阴被含住吸，那点被吸得发麻发胀，酸意直往小腹里钻",
    },
    "vagina": {
        "finger": "阴道被手指一下下抽插着，内壁被撑开又缩回，水声黏糊糊地响",
        "penis": "阴道被顶开又填满，里面又热又紧，被撑得满满当当",
        "toy": "阴道里被小玩具塞着、震着，不一样的硬度和震动一直往深处钻",
        "lick": "阴道口被舌头舔过，又软又热，湿意顺着腿根往下流",
        "suck": "那里被含住轻轻吸，那股吸力往里收，内壁跟着一下下发紧",
    },
    "gspot": {
        "finger": "G点被手指按住反复揉压，酸胀直冲腰底，腿根发抖",
        "penis": "G点被生殖器一下下顶到，酸麻里带着被撞开的钝感",
        "toy": "G点被小玩具顶着磨，震动一下下打在那一点上，酸得发慌",
    },
    "cervix": {
        "penis": "子宫颈被生殖器顶到，深处传来又钝又酸的撞击感",
        "toy": "子宫颈被小玩具顶住磨蹭，深的那点酸涨得让人发软",
    },
    "anus": {
        "finger": "后面被手指慢慢抽插着，肛口被撑开又收拢，胀得发慌",
        "penis": "后面被生殖器顶进来，撑得又满又胀，钝钝的酸一直往里走",
        "toy": "后面被小玩具塞着震，那种又胀又麻的震动一直往里钻",
        "lick": "后面被舌头舔过，又湿又热，羞耻感比快感先上来",
        "suck": "那里被含住吸，吸力把肛口一点点往里收，酸麻得几乎坐不住",
    },
    "mouth": {
        "penis": "嘴里被生殖器抵着，只能半张着唇含住，喉咙被顶得发紧",
        "lick": "用舌头舔过去，那里又热又硬，只能仰着头去够",
        "suck": "嘴里被含住用力吸，腮帮子发酸，喉咙里挤出细碎的声音",
        "tongue": "舌面贴着磨过去，又湿又黏，唇齿之间全是气息",
    },
    "ear": {
        "blow": "对着耳朵哈热气的时候她缩了一下脖子，耳根一下红透",
        "earsuck": "耳垂被含进嘴里轻轻吮住，她整个人一缩，耳朵热得发烫",
        "earlick": "舌头探进耳道口轻轻打着转，湿热的触感一下下舔过最里面那圈软肉，"
                   "痒麻得她直想缩脖子",
    },
    "foot": {
        "penis": "脚被夹在腿间来回磨，脚心被顶得发烫发麻",
        "lick": "脚背被舌头舔过，又凉又湿，脚趾会一下下蜷紧",
        "suck": "脚趾被含住吸，那种湿热把酥麻一路吸上腿根",
        "penis_lube": "阴茎上抹了润滑，贴着脚心来回磨时又热又滑，脚趾被顶得蜷紧，腿根一阵阵发软",
        "lick_lube": "脚背沾着润滑被舌头舔过，湿滑的触感让她脚趾一下下蜷紧",
        "suck_lube": "脚趾上沾着润滑被含住吸，又滑又痒，麻意一路吸上腿根",
    },
    "hand": {
        "interlock": "十指扣紧的时候她手指会用力回握，掌心贴在一起，连心跳都像传过去",
        "hold": "被他牵着，她手指会轻轻蹭他的指节，嘴上不说，手却没松开",
        "lick": "被舔手心的时候她猛地缩了一下，又慢慢把手摊开，痒得笑出来",
        "suck": "手指被含住吮，她脸一下红到耳根，连话都说不利索",
        "tongue": "她的手指被主人含在嘴里，舌尖绕着指尖舔弄、轻轻勾着；她痒得缩了一下，又慢慢把手摊开",
        "masturbate": "她主动伸手握住，掌心慢慢收紧，节奏由她自己试探着来，时不时抬眼看他，腰也跟着自己的动作轻轻往前送",
        "masturbate_lube": "她主动伸手握住，掌心被润滑液弄得又滑又热，节奏由她自己试探着来；"
                           "滑腻的水声让她耳根发红，手指却越收越紧",
    },
    "uterus": {
        "penis": "最深处被整个填满，那圈软肉被撑开又缩紧，酸胀感一波波往腰上涌",
        "finger": "指尖探到最深的地方，那里又软又敏感，被碰一下就抖",
        "toy": "玩具顶到最里面，硬邦邦地抵着，震动一直往宫腔里钻",
    },
    "tail": {
        "wrap": "尾巴自己卷上去缠住，一下一下地撸，她连尾巴尖都在抖",
        "stroke": "尾巴被顺着毛的方向一路抚摸下去，那层细软的绒毛全被摸得发烫，尾根自己往上抬",
        "knead": "尾巴被又揉又捏地玩着，尾根被攥在掌心里搓，整条尾巴被玩得又麻又胀",
        "lick": "尾巴被舌头从尾根一路舔上去，湿热的触感让整条尾巴都炸了毛",
        "suck": "尾尖被含住吸，那股麻顺着尾根一路窜回腰里",
        "stroke_lube": "尾巴上沾了润滑，被顺着毛抚摸时又滑又腻，尾根发麻，尾尖自己卷起来",
        "knead_lube": "尾巴上抹了润滑，被揉捏玩弄时滑得抓不住，酸麻从尾根往腰上爬",
        "lick_lube": "尾巴上沾着润滑被舌头舔过，湿滑的触感让整条尾巴都炸了毛",
        "suck_lube": "尾巴上抹了润滑被含住吸，又滑又软，麻意顺着尾根一路窜回腰里",
        "wrap_lube": "阴茎上抹了润滑，尾巴缠上去卷紧时又滑又热，尾根跟着发烫",
    },
}

# 关键词：从对话里猜"正在用哪种方式"（只在这个部位允许的方式里找，越长越优先）。
# 猜不出就留空 —— 由模型自己用 intimacy_touch 的 method 参数补上。
METHOD_KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "kiss": {
        "french": ("舌吻", "深吻", "法式吻", "舌头伸进", "缠着舌头", "舌头缠", "湿吻"),
    },
    "hymen": {
        "rub": ("处女膜", "膜", "蹭", "磨"),
        "press": ("顶住", "压开", "顶", "压"),
        "toy": ("玩具", "震动", "跳蛋"),
    },
    "tube": {
        "rub": ("输卵管", "蹭", "磨"),
        "press": ("顶到", "最里面", "顶住", "压"),
        "toy": ("玩具", "震动", "跳蛋"),
    },
    "ovary": {
        "knead": ("卵巢", "小腹", "揉", "按"),
        "rub": ("揉", "搓", "小腹"),
        "press": ("按", "压", "顶"),
        "toy": ("玩具", "筋膜枪", "震动"),
    },
    "breast": {
        "milk": ("乳交", "夹在乳", "夹在胸", "乳沟", "双乳夹", "乳房夹", "胸夹"),
        "lick": ("舔胸", "舔乳", "舌头", "舌面", "舔"),
        "suck": ("吸乳", "吮", "吸", "含住", "含在"),
    },
    "nipple": {
        "rub": ("揉搓", "揉", "搓", "捏", "捻"),
        "lick": ("舔", "舌头", "舌面"),
        "suck": ("吮", "吸", "含住", "含在"),
    },
    "vulva": {
        "tease": ("逗弄", "逗", "撩", "拂", "磨", "蹭", "撩拨"),
        "lick": ("舔", "舌头", "舌面"),
        "suck": ("吮", "吸", "含住", "含在"),
    },
    "vagina": {
        "finger": ("手指", "指尖", "指腹", "指节"),
        "penis": ("肉棒", "鸡巴", "阴茎", "龟头", "生殖器", "插进", "顶进", "抽插"),
        "toy": ("跳蛋", "振动棒", "玩具", "按摩棒", "吸吮器"),
        "lick": ("舔", "舌头", "舌面"),
        "suck": ("吮", "吸", "含住"),
    },
    "gspot": {
        "finger": ("手指", "指尖", "指腹", "指节"),
        "penis": ("肉棒", "鸡巴", "阴茎", "龟头", "生殖器", "顶到", "磨到"),
        "toy": ("跳蛋", "振动棒", "玩具", "按摩棒"),
    },
    "cervix": {
        "penis": ("肉棒", "鸡巴", "阴茎", "龟头", "生殖器", "顶到", "顶开"),
        "toy": ("跳蛋", "振动棒", "玩具", "按摩棒"),
    },
    "anus": {
        "finger": ("手指", "指尖", "指腹", "指节"),
        "penis": ("肉棒", "鸡巴", "阴茎", "龟头", "生殖器", "插进", "顶进"),
        "toy": ("跳蛋", "振动棒", "玩具", "肛塞", "按摩棒", "吸吮器"),
        "lick": ("舔", "舌头", "舌面"),
        "suck": ("吮", "吸", "含住"),
    },
    "mouth": {
        "penis": ("肉棒", "鸡巴", "阴茎", "龟头", "生殖器", "含进", "吞"),
        "lick": ("舔", "舌头", "舌面"),
        "suck": ("吮", "吸", "含住", "吸吮"),
        "tongue": ("舌吻", "舌头", "舌面", "舔舐"),
    },
    "ear": {
        "earlick": ("舔耳", "舔耳朵", "舔进", "舔舐", "舌头", "舌尖", "舌面", "舔"),
    },
    "foot": {
        "penis": ("足交", "夹着", "腿间", "生殖器", "肉棒", "龟头"),
        "lick": ("舔", "舌头", "舌面"),
        "suck": ("吮", "吸", "含住", "含进"),
    },
    "hand": {
        "interlock": ("十指相扣", "十指扣", "扣紧", "扣住", "十指交扣"),
        "hold": ("牵手", "牵着", "握住手", "拉着手", "握着手"),
        "lick": ("舔手", "舔手心", "舔手指", "舔指"),
        "suck": ("吮手指", "吸手指", "含手指", "含住手指", "吮指"),
        "tongue": ("含住舌头", "吸舌头", "舔舌头", "舌吻"),
        "masturbate": ("手淫", "帮他撸", "撸动", "套弄", "用手弄", "握着弄"),
    },
    "uterus": {
        "penis": ("插进子宫", "顶进子宫", "操进子宫", "子宫里", "宫腔", "插到最里面"),
        "finger": ("手指", "指尖", "指腹"),
        "toy": ("跳蛋", "振动棒", "玩具", "按摩棒"),
    },
    "tail": {
        "wrap": ("卷起", "卷住", "缠住", "尾巴卷", "尾巴缠"),
        "stroke": ("抚摸", "顺着", "拂", "摸尾巴", "摸上去", "撸", "蹭"),
        "knead": ("揉捏", "揉", "捏", "搓", "玩弄", "把玩", "攥", "捻"),
        "lick": ("舔", "舌头", "舌面"),
        "suck": ("吮", "吸", "含住", "吸吮"),
    },
}

IDLE_PROMPT = "还没被碰到，那里只是安静地热着"

# 面板里自定义的提示词存 state["sub_prompts"][部位] = ["第1段", "第2段", "第3段"]，
# 空字符串 = 这一段用回内置默认。长度只做防呆（面板上也是一次几百字的长句）。
PROMPT_MAX = 400


def level_of(charge: float, max_charge: float = 100.0) -> int:
    """把进度换成段位：1–3，0 表示还没涨。三段等分。"""
    value = util.safe_float(charge, 0.0)
    cap = max(1.0, util.safe_float(max_charge, 100.0))
    if value <= 0:
        return 0
    segment = cap / 3.0
    return max(1, min(3, int(math.ceil(value / segment - 1e-9))))


def level_name(level: int) -> str:
    return LEVEL_NAMES.get(int(level), "")


def level_title(level: int) -> str:
    return LEVEL_TITLES.get(int(level), "还没被碰到")


def prompt_for(zone: str, level: int) -> str:
    """某个部位在第 N 段的**内置默认**提示词（0 段给"还没被碰到"）。"""
    row = LEVEL_PROMPTS.get(zone) or ()
    index = int(level) - 1
    if 0 <= index < len(row):
        return row[index]
    return IDLE_PROMPT


# ---------------------------------------------------------------- 提示词自定义

def _prompt_box(state: dict) -> dict:
    box = state.get("sub_prompts")
    if not isinstance(box, dict):
        box = {}
        state["sub_prompts"] = box
    return box


def _zone_prompts(state: dict, zone: str) -> dict:
    """取某个部位的自定义结构（只读，不落盘）。

    结构：{"stages": [s1, s2, s3], "methods": {method: text}}；
    老版本存的是裸 list（只有三段），这里兼容读成 stages。
    """
    raw = _prompt_box(state).get(zone)
    stages = [""] * 3
    methods: dict[str, str] = {}
    if isinstance(raw, (list, tuple)):
        for index, text in enumerate(list(raw)[:3]):
            stages[index] = str(text or "").strip()
    elif isinstance(raw, dict):
        for index, text in enumerate(list(raw.get("stages") or [])[:3]):
            stages[index] = str(text or "").strip()
        for key, text in (raw.get("methods") or {}).items():
            value = str(text or "").strip()
            if value:
                methods[str(key)] = value
    return {"stages": stages, "methods": methods}


def _write_zone_prompts(state: dict, zone: str, value: dict) -> None:
    """写回；三段和方式都空了就把这个部位整个删掉（保持 state 干净）。"""
    box = _prompt_box(state)
    if any(value.get("stages") or []) or value.get("methods"):
        box[zone] = value
    else:
        box.pop(zone, None)


def _same_as_default(text: str, default: str) -> bool:
    """这段文字其实和内置默认一模一样（换行/空格差异不算改）。"""
    return " ".join(str(text or "").split()) == " ".join(str(default or "").split())


def prompt_override(state: dict | None, zone: str, level: int) -> str:
    """面板改过的那一段程度提示词；没改过（或改成了和默认一样）返回空字符串。"""
    if not isinstance(state, dict) or int(level) <= 0:
        return ""
    index = int(level) - 1
    stages = _zone_prompts(state, zone)["stages"]
    text = stages[index] if 0 <= index < len(stages) else ""
    if not text:
        return ""
    # 老版本"保存三段"会把没改的段也存成覆盖；和默认一样就当没改
    return "" if _same_as_default(text, prompt_for(zone, level)) else text


def prompt_of(state: dict | None, zone: str, level: int) -> str:
    """生效的程度提示词：面板改过就用改过的，否则用内置默认。"""
    return prompt_override(state, zone, level) or prompt_for(zone, level)


def method_override(state: dict | None, zone: str, method: str) -> str:
    """面板改过的那一句方式提示词；没改过（或和默认一样）返回空字符串。"""
    if not isinstance(state, dict) or not method:
        return ""
    text = _zone_prompts(state, zone)["methods"].get(method, "")
    if not text:
        return ""
    return "" if _same_as_default(text, method_prompt_for(zone, method)) else text


def method_prompt_for(zone: str, method: str) -> str:
    """内置的方式提示词（未知方式给空）。"""
    return (METHOD_PROMPTS.get(zone) or {}).get(method, "")


def method_prompt_of(state: dict | None, zone: str, method: str) -> str:
    """生效的方式提示词：面板改过就用改过的，否则用内置默认。"""
    if not method:
        return ""
    return method_override(state, zone, method) or method_prompt_for(zone, method)


def line_of(state: dict | None, zone: str, level: int, method: str = "") -> str:
    """面板和提示词注入共用的一句：方式（动作）+ 程度（到哪一步）。"""
    stage = prompt_of(state, zone, level)
    key = method
    if zone == "hand" and method == "masturbate":
        try:
            row = (state or {}).get("lube") or {}
            now = util.now_ts()
            if (util.safe_float(row.get("hand_until"), 0.0) > now
                    or util.safe_float(row.get("penis_until"), 0.0) > now):
                key = "masturbate_lube"
        except Exception:
            pass
    body = method_prompt_of(state, zone, key) if key else ""
    if key and zone in ("breast", "nipple", "foot", "tail"):
        try:
            row = (state or {}).get("lube") or {}
            now = util.now_ts()
            hand = util.safe_float(row.get("hand_until"), 0.0) > now
            penis = util.safe_float(row.get("penis_until"), 0.0) > now
            direct = util.safe_float(row.get(f"{zone}_until"), 0.0) > now
            if zone == "breast":
                lubed = hand or direct or (penis and key == "milk")
            elif zone == "nipple":
                lubed = hand or direct
            else:
                lubed = hand or penis or direct
            if lubed:
                body = method_prompt_of(state, zone, f"{key}_lube") or body
        except Exception:
            pass
    if body and int(level) > 0:
        return f"{body}。{stage}"
    return body or stage


def methods_of(zone: str) -> tuple[str, ...]:
    return METHOD_ORDER.get(zone, ())


def method_label(method: str) -> str:
    return METHOD_LABELS.get(method, "")


# ---------------------------------------------------------------- 方式关键词（可改）

# 一个方式最多存多少个词、单个词多长（防呆；面板上是一行逗号分隔）
KEYWORD_COUNT_MAX = 40
KEYWORD_MAX = 24


def method_keywords_for(zone: str, method: str) -> list[str]:
    """内置的方式关键词（默认值）。"""
    return list((METHOD_KEYWORDS.get(zone) or {}).get(method, ()))


def _keyword_box(state: dict) -> dict:
    box = state.get("sub_keywords")
    if not isinstance(box, dict):
        box = {}
        state["sub_keywords"] = box
    return box


def method_keywords_override(state: dict | None, zone: str, method: str):
    """面板改过的关键词；没改过返回 None（注意：改成空列表也算改过）。"""
    if not isinstance(state, dict) or not method:
        return None
    row = _keyword_box(state).get(zone)
    if not isinstance(row, dict):
        return None
    value = row.get(method)
    if isinstance(value, list):
        return [str(item) for item in value]
    return None


def method_keywords_of(state: dict | None, zone: str, method: str) -> list[str]:
    """生效的关键词：面板改过就用改过的，否则用内置。"""
    override = method_keywords_override(state, zone, method)
    return override if override is not None else method_keywords_for(zone, method)


def parse_keywords(value) -> list[str]:
    """把"抚摸, 顺着、拂 / 撸"这类输入切成词表（去重、限长、限量）。"""
    if isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
    else:
        text = str(value or "")
        for mark in ("，", "、", "；", ";", "|", "／", "/"):
            text = text.replace(mark, ",")
        items = re.split(r"[,\s]+", text)
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        word = str(item).strip()
        if not word or word in seen:
            continue
        seen.add(word)
        out.append(word[:KEYWORD_MAX])
        if len(out) >= KEYWORD_COUNT_MAX:
            break
    return out


def set_method_keywords(state: dict, zone: str, method: str, value) -> list[str]:
    """存某个方式的关键词（可以是字符串或列表）；空列表 = 这个方式不做自动判断。"""
    key = normalize_method(zone, method)
    if not key:
        return []
    box = _keyword_box(state)
    row = box.get(zone)
    if not isinstance(row, dict):
        row = {}
        box[zone] = row
    row[key] = parse_keywords(value)
    return row[key]


def reset_method_keywords(state: dict, zone: str | None = None,
                          method: str | None = None) -> int:
    """恢复默认关键词：可以只清一个方式（method）、一个部位（zone）、或者全部。"""
    box = _keyword_box(state)
    if not zone:
        count = sum(len(row) for row in box.values() if isinstance(row, dict))
        box.clear()
        return count
    row = box.get(zone)
    if not isinstance(row, dict):
        return 0
    if method:
        key = normalize_method(zone, method) or method
        cleared = 1 if row.pop(key, None) is not None else 0
    else:
        cleared = len(row)
        row.clear()
    if not row:
        box.pop(zone, None)
    return cleared


def normalize_method(zone: str, value) -> str:
    """把"乳交 / 舔 / suck"这类输入归一成这个部位允许的方式；不在列表里返回空。"""
    allowed = methods_of(zone)
    if not allowed:
        return ""
    key = str(value or "").strip().lower()
    if key in allowed:
        return key
    alias = (METHOD_ALIASES.get(zone) or {}).get(key)
    if alias and alias in allowed:
        return alias
    for method in allowed:
        if key == METHOD_LABELS.get(method, "").lower():
            return method
    return ""


def detect_method(text: str, zone: str, state: dict | None = None) -> str:
    """从一句话里猜这个部位正在被怎么弄：只在这个部位允许的方式里找，
    命中的关键词越长越优先；同级看命中次数。猜不出返回空（让模型自己传 method）。

    state 传进来时会用面板改过的关键词（`sub_keywords`）。
    """
    allowed = methods_of(zone)
    body = (text or "").lower()
    if not allowed or not body:
        return ""
    best, best_score = "", (0, 0)
    for method in allowed:
        score = (0, 0)
        for word in method_keywords_of(state, zone, method):
            token = str(word).lower()
            if token and token in body:
                count = body.count(token)
                score = (max(score[0], len(token)), max(score[1], count))
        if score > best_score:
            best, best_score = method, score
    return best


def _stage_value(zone: str, level: int, text: str) -> str:
    """要存的值：空、或和内置默认一样，就存空（等于"用默认"，不算自定义）。"""
    value = str(text or "").strip()[:PROMPT_MAX]
    if not value or _same_as_default(value, prompt_for(zone, level)):
        return ""
    return value


def set_prompt(state: dict, zone: str, level: int, text: str) -> str:
    """存一段自定义程度提示词（空字符串 = 恢复默认）。返回生效的文本。"""
    level = max(1, min(3, int(level)))
    value = _zone_prompts(state, zone)
    value["stages"][level - 1] = _stage_value(zone, level, text)
    _write_zone_prompts(state, zone, value)
    return prompt_of(state, zone, level)


def set_prompts(state: dict, zone: str, texts) -> list[str]:
    """一次改一个部位的三段程度提示词；返回三段生效值。

    只把"真的改过"的段存成覆盖：和内置默认一样的段存空，
    这样面板上"改过几段"才是准的。
    """
    values = list(texts or [])[:3]
    while len(values) < 3:
        values.append("")
    entry = _zone_prompts(state, zone)
    for index, text in enumerate(values):
        entry["stages"][index] = _stage_value(zone, index + 1, text)
    _write_zone_prompts(state, zone, entry)
    return [prompt_of(state, zone, level) for level in (1, 2, 3)]


def set_method_prompt(state: dict, zone: str, method: str, text: str) -> str:
    """存某个方式的自定义提示词（空字符串 = 恢复默认）。返回生效的文本。"""
    key = normalize_method(zone, method)
    if not key:
        return ""
    entry = _zone_prompts(state, zone)
    value = str(text or "").strip()[:PROMPT_MAX]
    if value and _same_as_default(value, method_prompt_for(zone, key)):
        value = ""
    if value:
        entry["methods"][key] = value
    else:
        entry["methods"].pop(key, None)
    _write_zone_prompts(state, zone, entry)
    return method_prompt_of(state, zone, key)


def reset_prompts(state: dict, zone: str | None = None, *,
                  level: int | None = None, method: str | None = None) -> int:
    """恢复默认：可以只清某一段（level）、只清某个方式（method），
    某个部位整份（zone），或者全部（都不传）。返回清掉了几处。"""
    box = _prompt_box(state)
    if not zone:
        count = len(box)
        box.clear()
        return count
    if zone not in box:
        return 0
    if level is not None:
        entry = _zone_prompts(state, zone)
        index = max(1, min(3, int(level))) - 1
        changed = 1 if entry["stages"][index] else 0
        entry["stages"][index] = ""
        _write_zone_prompts(state, zone, entry)
        return changed
    if method:
        entry = _zone_prompts(state, zone)
        key = normalize_method(zone, method)
        changed = 1 if key and entry["methods"].pop(key, None) else 0
        _write_zone_prompts(state, zone, entry)
        return changed
    box.pop(zone, None)
    return 1


def prompts_payload(state: dict) -> dict:
    """设置页要的整份提示词表：每个部位的三段（程度）+ 各方式（动作）。"""
    zones = []
    custom_total = 0
    for zone in intimacy.ZONE_ORDER:
        stages = []
        stage_custom = 0
        for level in (1, 2, 3):
            default = prompt_for(zone, level)
            override = prompt_override(state, zone, level)
            if override:
                stage_custom += 1
            stages.append({
                "level": level,
                "title": level_title(level),
                "name": level_name(level),
                "default": default,
                "value": override or default,
                "custom": bool(override),
            })
        methods = []
        method_custom = 0
        keyword_custom = 0
        for method in methods_of(zone):
            default = method_prompt_for(zone, method)
            override = method_override(state, zone, method)
            if override:
                method_custom += 1
            keywords = method_keywords_of(state, zone, method)
            keywords_custom = method_keywords_override(state, zone, method) is not None
            if keywords_custom:
                keyword_custom += 1
            methods.append({
                "key": method,
                "label": method_label(method),
                "default": default,
                "value": override or default,
                "custom": bool(override),
                "keywords": keywords,
                "keywords_text": "、".join(keywords),
                "keywords_default_text": "、".join(method_keywords_for(zone, method)),
                "keywords_custom": keywords_custom,
            })
        custom_total += stage_custom + method_custom
        zones.append({
            "key": zone,
            "label": intimacy.ZONE_LABELS.get(zone, zone),
            "stages": stages,
            "methods": methods,
            "stage_custom": stage_custom,
            "method_custom": method_custom,
            "keyword_custom": keyword_custom,
            "custom_count": stage_custom + method_custom,
        })
    return {"zones": zones, "custom_total": custom_total,
            "keyword_custom_total": sum(row.get("keyword_custom", 0) for row in zones),
            "max_len": PROMPT_MAX}


# ---------------------------------------------------------------- 数值

def _row(state: dict, zone: str) -> dict:
    """取/建某个部位的子敏感度记录（只补字段，不动主敏感点）。"""
    rows = state.get("sub_zones")
    if not isinstance(rows, dict):
        rows = {}
        state["sub_zones"] = rows
    row = rows.get(zone)
    if not isinstance(row, dict):
        row = {}
        rows[zone] = row
    row.setdefault("charge", 0.0)
    row.setdefault("at", 0.0)          # 上次结算时间
    row.setdefault("last_at", 0.0)     # 上次涨的时间
    row.setdefault("burst_at", 0.0)    # 上次溢出的时间
    row.setdefault("bursts", 0)        # 累计溢出次数
    row.setdefault("total", 0.0)       # 累计涨过的进度
    row.setdefault("method", "")       # 最近一次"正在被怎么弄"
    row.setdefault("methods", {})      # 各方式用过几次
    return row


def _max_charge(settings: Settings) -> float:
    return settings.float("sub_zones.max", 10.0, 1000.0)


def _fall_seconds(settings: Settings) -> float:
    return settings.float("sub_zones.burst_fall_seconds", 0.3, 60.0)


def _cooldown_seconds(settings: Settings) -> float:
    """溢出后多久能重新涨：至少等到回落结束。"""
    span = settings.float("sub_zones.burst_cooldown_seconds", 0.0, 120.0)
    return max(span, _fall_seconds(settings))


def settle(state: dict, settings: Settings, zone: str,
           now: float | None = None, *, in_scene: bool = False) -> dict:
    """把这段时间的变化补算上去（溢出后几秒内回落，平时按分钟慢慢掉）。

    溢出后的回落用"按时间算的曲线"而不是"按次递减"：
    不管中间被读了几次，t 秒后条一定落在 cap × (1 - t/fall) 上，
    回落时间一到就正好归零，不会卡在中间某个值上。
    """
    now = now or util.now_ts()
    row = _row(state, zone)
    cap = _max_charge(settings)
    stored_at = util.safe_float(row.get("at"), 0.0)
    at = stored_at or now
    charge = util.clamp(util.safe_float(row.get("charge"), 0.0), 0.0, cap)

    if now > at:
        seconds = now - at
        key = ("sub_zones.scene_decay_per_minute" if in_scene
               else "sub_zones.idle_decay_per_minute")
        rate = settings.float(key, 0.0, 600.0) / 60.0
        charge = max(0.0, charge - rate * seconds)
        # 只有"往后走"才更新结算时间：万一被传了更早的 now（时钟回拨/测试），
        # 不能把 at 往回拨，否则下一次结算会按多出来的时间把条一次掉光。
        row["at"] = now
    elif not stored_at:
        row["at"] = now

    burst_at = util.safe_float(row.get("burst_at"), 0.0)
    if burst_at:
        elapsed = max(0.0, now - burst_at)
        fall = _fall_seconds(settings)
        if elapsed < fall:
            charge = min(charge, cap * (1.0 - elapsed / fall))
        elif util.safe_float(row.get("last_at"), 0.0) <= burst_at + fall:
            # 回落结束、还没被重新碰过：停在 0
            charge = 0.0

    row["charge"] = round(util.clamp(charge, 0.0, cap), 3)
    return row


def charge_of(state: dict, settings: Settings, zone: str,
              now: float | None = None, *, in_scene: bool = False) -> float:
    return round(util.safe_float(settle(state, settings, zone, now,
                                        in_scene=in_scene).get("charge"), 0.0), 1)


def _falling(row: dict, settings: Settings, now: float) -> bool:
    burst_at = util.safe_float(row.get("burst_at"), 0.0)
    return bool(burst_at) and (now - burst_at) < _fall_seconds(settings)


def _cooling(row: dict, settings: Settings, now: float) -> float:
    """溢出后还剩几秒不能涨（0 = 现在可以涨）。"""
    burst_at = util.safe_float(row.get("burst_at"), 0.0)
    if not burst_at:
        return 0.0
    left = burst_at + _cooldown_seconds(settings) - now
    return round(max(0.0, left), 1)


def touch_gain(settings: Settings, sensitivity: float = 1.0, times: int = 1) -> float:
    """一次触碰涨多少进度：默认 34 × (0.8 + 0.35 × 敏感度)。

    亲吻（敏感 ×0.70）一次约 +35.6，乳头（×1.20）约 +41.9，尾巴（×1.80）约 +49.3：
    也就是说活动里碰两三下就满，不卡进度。
    """
    base = settings.float("sub_zones.gain", 0.0, 100.0)
    scale = settings.float("sub_zones.sensitivity_scale", 0.0, 2.0)
    sens = util.clamp(util.safe_float(sensitivity, 1.0), 0.0, 5.0)
    factor = max(0.2, min(2.5, 0.8 + scale * sens))
    count = max(1, min(20, int(times or 1)))
    return round(max(0.0, base * factor * count), 2)


# ---------------------------------------------------------------- 溢出

def burst(state: dict, settings: Settings, zone: str,
          now: float | None = None) -> dict:
    """条满了：给主敏感点加开发度/敏感度、额外补一笔快感，然后开始回落。"""
    from . import body, state as state_mod

    now = now or util.now_ts()
    row = _row(state, zone)
    cap = _max_charge(settings)
    dev = settings.int("sub_zones.burst_dev", 0, 60)
    sens = settings.float("sub_zones.burst_sensitivity", 0.0, 3.0)
    extra = settings.float("sub_zones.burst_pleasure", 0.0, 300.0)

    bonus = intimacy.add_zone_bonus(state, settings, zone, dev=dev, sens=sens)

    pleasure_gain = 0.0
    value = util.safe_float(state.get("pleasure"), 0.0)
    if extra > 0:
        mult = (state_mod.edge_gain_multiplier(state, settings, now)
                * body.pleasure_scale(settings, state))
        pleasure_gain = round(extra * max(0.0, mult), 2)
        value = state_mod.add_pleasure(state, settings, pleasure_gain, now=now)

    row["bursts"] = util.safe_int(row.get("bursts"), 0) + 1
    row["burst_at"] = now
    row["at"] = now
    row["charge"] = cap
    return {
        "zone": zone,
        "label": intimacy.ZONE_LABELS.get(zone, zone),
        "dev": bonus["dev"],
        "dev_gain": bonus["dev_gain"],
        "sensitivity": bonus["sensitivity"],
        "sensitivity_gain": bonus["sensitivity_gain"],
        "pleasure": pleasure_gain,
        "value": round(value, 2),
        "count": row["bursts"],
        "fall_seconds": round(_fall_seconds(settings), 1),
    }


# ---------------------------------------------------------------- 触碰

def _raise(state: dict, settings: Settings, zone: str, amount: float, *,
           now: float, in_scene: bool, method: str = "") -> dict:
    """给条加一段进度（加了就检查是不是满了）；返回统一结构。

    method 是这个部位"正在被怎么弄"（乳交/舔/吮吸…）：显式传了就用新的，
    没传就沿用这个部位上一次的方式（这样提示词不会来回跳）。
    """
    row = settle(state, settings, zone, now, in_scene=in_scene)
    cap = _max_charge(settings)
    before = util.safe_float(row.get("charge"), 0.0)
    current = str(row.get("method") or "")
    if current and not normalize_method(zone, current):
        current = ""
    info = {
        "zone": zone,
        "label": intimacy.ZONE_LABELS.get(zone, zone),
        "charge": round(before, 1),
        "max": cap,
        "gain": 0.0,
        "level": level_of(before, cap),
        "level_title": level_title(level_of(before, cap)),
        "method": current,
        "method_label": method_label(current),
        "burst": None,
        "blocked": "",
        "cooldown": _cooling(row, settings, now),
    }
    if not settings.bool("sub_zones.enabled"):
        info["blocked"] = "子敏感度关着"
        return info
    if settings.bool("sub_zones.scene_only") and not in_scene:
        info["blocked"] = "不在受孕活动里"
        return info
    if info["cooldown"] > 0:
        info["blocked"] = f"溢出后缓冲还没过，还剩 {info['cooldown']:.1f} 秒"
        return info

    explicit = normalize_method(zone, method)
    if explicit:
        row["method"] = explicit
        counts = row.get("methods")
        if not isinstance(counts, dict):
            counts = {}
            row["methods"] = counts
        counts[explicit] = util.safe_int(counts.get(explicit), 0) + 1
        current = explicit
    info["method"] = current
    info["method_label"] = method_label(current)

    gain = max(0.0, util.safe_float(amount, 0.0))
    charge = min(cap, before + gain)
    row["charge"] = round(charge, 3)
    row["at"] = now
    row["last_at"] = now
    row["total"] = round(util.safe_float(row.get("total"), 0.0) + gain, 2)

    info["gain"] = round(charge - before, 2)
    info["charge"] = round(charge, 1)
    info["level"] = level_of(charge, cap)
    info["level_title"] = level_title(info["level"])
    if charge >= cap - 1e-9:
        info["burst"] = burst(state, settings, zone, now)
        info["charge"] = round(cap, 1)
        info["level"] = 3
        info["level_title"] = level_title(3)
    return info


def apply_touch(state: dict, settings: Settings, zone: str, *,
                times: int = 1, now: float | None = None,
                in_scene: bool = False, sensitivity: float = 1.0,
                method: str = "") -> dict:
    """碰一次（或几次）这个部位，只涨子敏感度的条；满了自动溢出。

    method 可以写 key（lick）也可以写中文（舔）；不在这个部位的方式列表里就忽略。
    返回：charge / level / method / gain / burst（None 表示没满）；
    blocked 非空表示这次没涨（关着 / 不在活动里 / 回落冷却中）。
    """
    now = now or util.now_ts()
    count = max(1, min(20, int(times or 1)))
    return _raise(state, settings, zone, touch_gain(settings, sensitivity, count),
                  now=now, in_scene=in_scene, method=method)


def add(state: dict, settings: Settings, zone: str, amount: float, *,
        now: float | None = None, in_scene: bool = False,
        method: str = "") -> dict:
    """直接加一段进度（面板手动/测试用），满了同样溢出。"""
    now = now or util.now_ts()
    return _raise(state, settings, zone, amount, now=now, in_scene=in_scene,
                  method=method)


def fill(state: dict, settings: Settings, zone: str, *,
         now: float | None = None, in_scene: bool = False,
         method: str = "") -> dict:
    """把条直接填满并溢出一次（面板"满"按钮 / 测试段位提示词用）。"""
    now = now or util.now_ts()
    _row(state, zone)["at"] = now
    return _raise(state, settings, zone, _max_charge(settings),
                  now=now, in_scene=in_scene, method=method)


# ---------------------------------------------------------------- 面板 / 提示词

def rows_payload(settings: Settings, state: dict, *,
                 in_scene: bool = False, now: float | None = None) -> list[dict]:
    """面板用：每个启用部位一行（进度、段位、提示词、溢出次数）。"""
    now = now or util.now_ts()
    cap = _max_charge(settings)
    rows = []
    for zone in intimacy.ZONE_ORDER:
        if not intimacy.zone_enabled_effective(state, settings, zone):
            continue
        row = settle(state, settings, zone, now, in_scene=in_scene)
        charge = util.clamp(util.safe_float(row.get("charge"), 0.0), 0.0, cap)
        level = level_of(charge, cap)
        sens = intimacy.zone_sensitivity_effective(state, settings, zone)
        method = str(row.get("method") or "")
        if method and not normalize_method(zone, method):
            method = ""
        rows.append({
            "key": zone,
            "label": intimacy.ZONE_LABELS.get(zone, zone),
            "charge": round(charge, 1),
            "max": cap,
            "percent": round(charge / cap * 100, 1) if cap else 0.0,
            "level": level,
            "level_name": level_name(level),
            "level_title": level_title(level),
            "method": method,
            "method_label": method_label(method),
            "methods": [{"key": item, "label": method_label(item)}
                        for item in methods_of(zone)],
            "prompt": line_of(state, zone, level, method),
            "level_prompts": [line_of(state, zone, item, method) for item in (1, 2, 3)],
            "level_titles": [level_title(1), level_title(2), level_title(3)],
            "idle_prompt": IDLE_PROMPT,
            "prompt_custom": bool(prompt_override(state, zone, level)
                                  or method_override(state, zone, method)) if level else False,
            "bursts": util.safe_int(row.get("bursts"), 0),
            "burst_at": util.safe_float(row.get("burst_at"), 0.0),
            "last_at": util.safe_float(row.get("last_at"), 0.0),
            "falling": _falling(row, settings, now),
            "cooldown": _cooling(row, settings, now),
            "gain": touch_gain(settings, sens),
        })
    return rows


def payload(settings: Settings, state: dict, *,
            in_scene: bool = False, now: float | None = None) -> dict:
    now = now or util.now_ts()
    rows = rows_payload(settings, state, in_scene=in_scene, now=now) \
        if settings.bool("sub_zones.enabled") else []
    active = bool(in_scene) or not settings.bool("sub_zones.scene_only")
    return {
        "enabled": bool(settings.bool("sub_zones.enabled")),
        "scene_only": bool(settings.bool("sub_zones.scene_only")),
        "active": active,
        "scene": bool(in_scene),
        "rows": rows,
        "max": _max_charge(settings),
        "burst_dev": settings.int("sub_zones.burst_dev", 0, 60),
        "burst_sensitivity": round(settings.float("sub_zones.burst_sensitivity", 0.0, 3.0), 3),
        "burst_pleasure": round(settings.float("sub_zones.burst_pleasure", 0.0, 300.0), 2),
        "fall_seconds": round(_fall_seconds(settings), 1),
        "cooldown_seconds": round(_cooldown_seconds(settings), 1),
        "idle_decay": round(settings.float("sub_zones.idle_decay_per_minute", 0.0, 600.0), 1),
        "prompt_zones": settings.int("sub_zones.prompt_zones", 1, 20),
        "total_bursts": sum(row["bursts"] for row in rows),
    }


def prompt_block(settings: Settings, state: dict, *,
                 in_scene: bool, daily_zones=None, now: float | None = None,
                 limit: int | None = None) -> str:
    """给模型的子敏感度提示：只带正在涨的几个部位（按进度取前几个）。

    - 亲密场景里：所有涨起来的部位；
    - 日常小场景里（自己用玩具那种）：**只带这次真的碰到的部位**，标题也不一样；
    - 两边都不是：一个字都不注入（`sub_zones.scene_only`），
      免得日常聊天时模型凭空写她的身体反应。
    """
    if not settings.bool("sub_zones.enabled"):
        return ""
    zones = [str(zone) for zone in (daily_zones or []) if zone]
    activity = bool(in_scene or zones)
    if not activity and settings.bool("sub_zones.scene_only"):
        return ""
    now = now or util.now_ts()
    limit = limit or settings.int("sub_zones.prompt_zones", 1, 20)
    rows = [row for row in rows_payload(settings, state, in_scene=activity, now=now)
            if row["charge"] > 0]
    if not in_scene and zones:
        rows = [row for row in rows if row["key"] in zones]
    if not rows:
        return ""
    rows.sort(key=lambda item: (item["level"], item["charge"]), reverse=True)
    picked = rows[:max(1, limit)]
    lines = ["【子敏感度·活动进行中】" if in_scene else "【子敏感度·日常小场景】"]
    for row in picked:
        how = f"{row['method_label']} · " if row["method_label"] else ""
        lines.append(f"- {row['label']}（{how}{row['level_title']}，{row['percent']:.0f}%）："
                     f"{row['prompt']}。")
    if in_scene:
        lines.append("（这些是这一场里正被她累积起来的感觉：按对应部位、对应方式写她的反应和"
                     "语气，别报数值、别说机制；条快满时反应会突然变尖，满了会一下子冲上来、"
                     "然后很快退下去。）")
    else:
        lines.append("（这是日常里她自己用玩具那一小段：只写这些部位现在的感觉和反应，"
                     "别写成正式亲密、也别写受孕判定；要往下走成真正的亲密，"
                     "让他碰她/进入，那时会自然转成活动场景。）")
    return "\n".join(lines)


def reset(state: dict, zone: str | None = None) -> int:
    """清空某个/全部部位的进度（不动溢出累计和主敏感点）。"""
    rows = state.get("sub_zones")
    if not isinstance(rows, dict):
        return 0
    keys = [zone] if zone else list(rows.keys())
    cleared = 0
    for key in keys:
        row = rows.get(key)
        if not isinstance(row, dict):
            continue
        if util.safe_float(row.get("charge"), 0.0) or row.get("burst_at"):
            cleared += 1
        row["charge"] = 0.0
        row["burst_at"] = 0.0
        row["at"] = util.now_ts()
    return cleared


def describe(state: dict, settings: Settings, *, in_scene: bool,
             now: float | None = None) -> str:
    """给 /受孕状态 用的一行摘要。"""
    if not settings.bool("sub_zones.enabled"):
        return "子敏感度：关着"
    if not in_scene and settings.bool("sub_zones.scene_only"):
        return "子敏感度：不在受孕活动里（条不涨，会很快回落到 0）"
    rows = [row for row in rows_payload(settings, state, in_scene=in_scene, now=now)
            if row["charge"] > 0]
    if not rows:
        return ("子敏感度：都没涨起来（活动里碰一下涨 "
                f"{touch_gain(settings, 1.0):.0f} 左右，2–3 下就满）")
    rows.sort(key=lambda item: item["charge"], reverse=True)
    body = "｜".join(
        f"{row['label']} {row['method_label'] + ' ' if row['method_label'] else ''}"
        f"{row['level_title']} {row['percent']:.0f}%" for row in rows)
    return f"子敏感度：{body}"
