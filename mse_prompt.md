你是笔记本数据合并专家。merge_data.py 的 canonical_model_family 归一化不完整，导致以下 ZOL×PConline 兼容配置机型未合并。
已知根因：PConline 加'酷睿'前缀 ZOL 省略；屏幕规格后缀(/2.5K /240Hz /OLED)未剥离；大小写/空格差异(Redmi vs REDMI、Pro vs PRO、R9 vs 锐龙9)。
请精确列出需要新增的归一化规则（不要代码、不要 diff），按以下 JSON 格式输出：
{"rules": [{"type": "strip_prefix", "tokens": ["酷睿", "Intel", "英特尔"]}, {"type": "strip_suffix", "pattern": "/(\d+(\.\d+)?K|\d+Hz|OLED|\d+K屏)"}, {"type": "normalize_case", "detail": "统一小写、去空格连字符、Pro/PRO→pro"}], "reasoning": "...", "confidence": 0-1}
当前未合并的兼容重叠：
- ZOL: 荣耀MagicBook Pro 16 2025(Ultra5 225H/32GB/1TB) || PConline: 荣耀MagicBook Pro 16 2025(酷睿Ultra5 225H/32GB/1TB)
- ZOL: 联想拯救者Y9000P 2026(i9-14900HX/16GB/1TB/RTX5060) || PConline: 联想拯救者Y9000P 2026(酷睿i9-14900HX/16GB/1TB/RTX5060/2.5K/240Hz)
- ZOL: 华为MateBook Pro(32GB/1TB) || PConline: 华为MateBook Pro(32GB/1TB)
- ZOL: 惠普暗影精灵 乐享版(i7 14650HX/16GB/512GB/RTX4060) || PConline: 惠普暗影精灵 乐享版(酷睿i7-14650HX/16GB/512GB/RTX4060)
- ZOL: Redmi Book Pro 16 2025(Ultra5-225H/32GB/1TB/2.5K) || PConline: REDMI Book Pro 16 2025(Ultra 5 225H/32GB/1TB/2.5K屏)
- ZOL: 惠普HyperX 暗影精灵 Pro 15酷睿版 (Ultra7 255HX/16GB/1TB/RTX5060) || PConline: 惠普HyperX 暗影精灵PRO 15酷睿版(酷睿Ultra7 255HX/16GB/1TB/RTX5060/180Hz)
- ZOL: 惠普星Book Pro Air 14(Ultra 5 225H/16GB/512GB) || PConline: 惠普星Book Pro Air 14(酷睿Ultra5 225H/16GB/512GB/2.8K/120Hz)
- ZOL: 惠普星Book Pro Air 14(Ultra 7 255H/32GB/1TB) || PConline: 惠普星Book Pro Air 14(酷睿Ultra7 255H/32GB/1TB/2.8K/120Hz)
- ZOL: 联想拯救者R7000P 2025(锐龙9 8940HX/16GB/1TB/RTX5060) || PConline: 联想拯救者R7000P 2025(R9-8940HX/16GB/1TB/RTX5060/2.5K/240Hz)
- ZOL: 华硕灵耀14 2025(Ultra9 285H/32GB/1TB) || PConline: 华硕灵耀14 2025(酷睿Ultra9 285H/32GB/1TB/2.8K/120Hz/OLED)
- ZOL: 惠普暗影精灵11(i7 14650HX/RTX5060/16GB/1TB/黑色) || PConline: 惠普暗影精灵11(酷睿i7-14650HX/16GB/1TB/RTX5060/2.5K/240Hz)
- ZOL: 华硕天选6 Pro 锐龙版(锐龙9 9955HX/16GB/1TB/RTX5060) || PConline: 华硕天选6 Pro 锐龙版(R9-9955HX/16GB/1TB/RTX5060/2.5K/165Hz)
- ZOL: 华硕天选6 Pro 酷睿版(i7-14650HX/16GB/1TB/RTX5060) || PConline: 华硕天选6 Pro 酷睿版(酷睿i7-14650HX/16GB/1TB/RTX5060/2.5K/165Hz)
- ZOL: 华硕天选6 Pro 锐龙版(锐龙9 8940HX/16GB/1TB/RTX5060) || PConline: 华硕天选6 Pro 锐龙版(R9-8940HX/16GB/1TB/RTX5060/2.5K/165Hz)
- ZOL: 惠普HyperX 暗影精灵 Pro 16锐龙版 (R9 9955HX/16GB/1TB/RTX5060) || PConline: 惠普HyperX 暗影精灵PRO 16锐龙版(R9-9955HX/16GB/1TB/RTX5060/240Hz)
- ZOL: 荣耀MagicBook Art 14 2025(Ultra5 225H/32GB/1TB) || PConline: 荣耀MagicBook Art 14 2025(酷睿Ultra5 225H/32GB/1TB)
只输出上述 JSON 对象，不要其它内容。