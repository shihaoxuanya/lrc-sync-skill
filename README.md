# LRC 歌词校时助手 · LRC Sync Skill

### 让歌词跟上声音，而不是让时间戳看起来整齐。

一个用于**制作、修复与逐句校对 LRC 歌词**的 Agent Skill。给它实际录音、原始歌词和可选的旧 LRC，它会组织音频检查、段落锚点定位、声谱辅助校时、完整性验证和离线试听校对，最终交付可继续编辑的歌词项目。

适合原版、翻唱、调教、剪辑或变速版本的逐句 LRC，以及“开头对得上、越往后越错”的修复任务。**它不是歌曲下载器、歌词数据库或自动歌声识别模型，不承诺未经试听的全自动精准对齐。**

## 核心功能

| 能力 | 实际作用 |
| --- | --- |
| 真实音频检查 | 用 FFprobe 测量时长、采样率和声道，记录 SHA-256 指纹，避免套错录音 |
| 波形与声谱辅助 | 生成带原音频绝对时间轴的图，辅助找转场与候选起唱点 |
| 原稿完整性校验 | 检查歌词文字、顺序、重复次数和缺行，提示被挤压的结尾 |
| 时间轴安全检查 | 检查缺失时间、倒序、越界，以及百分秒舍入后的重叠 |
| 离线校对页面 | 本地选音频、逐句打点、提前/延后、回听、变速、确认、撤销和清屏 |
| 可继续编辑 | 导出 LRC 与项目 JSON；恢复校对状态，不必从头开始 |

核心原则：**没有依据的时间保持未标记，不均分、不编造，不把剩余歌词硬塞进最后几秒。**

## 安装到 Codex

这是标准 `SKILL.md + scripts + references + assets` 目录结构。Codex 用户级目录为 `~/.agents/skills/`，仓库级目录为 `.agents/skills/`，参见 [OpenAI 官方说明](https://developers.openai.com/codex/skills)。其他支持 Agent Skills 的客户端应按各自方式放置同一个 `lrc-sync` 文件夹。

从本仓库安装（需要 Git 和 Python 3.10+）：

```bash
git clone https://github.com/shihaoxuanya/lrc-sync-skill.git
cd lrc-sync-skill
python install.py
```

也可通过仓库页面的 **Code → Download ZIP** 下载源码，解压后在含 `install.py` 的目录运行 `python install.py`。

安装器只复制 `lrc-sync`，不联网、不修改其他 Skill，也不会覆盖已有同名目录。可显式指定目标：

```bash
python install.py --to "你的项目/.agents/skills"
```

Windows 也可以手动复制到 `%USERPROFILE%\.agents\skills\`。最终应存在：

```text
.agents/skills/lrc-sync/SKILL.md
```

在 Codex CLI 或 IDE 扩展中用 `$lrc-sync` 调用；未显示时重启。仅安装此 Skill 不会让缺少音频工具的环境凭空获得听音能力。

## 直接对 AI 这样说

新建歌词：

```text
请使用 $lrc-sync，根据我上传的实际音频和这份歌词制作逐句 LRC。
保留歌词全文和重复段，核对间奏、最后一句和尾奏清屏。
同时给我离线试听校对页和可继续编辑的项目 JSON。
不要均分时间；未实际试听确认的部分请说明。
```

修复错位：

```text
请使用 $lrc-sync 修复这个 LRC，歌词和声音越到后面偏得越多。
先判断是整体偏移、录音版本不同，还是某些段落时间错误。
保留原稿，不要只给所有时间加减同一个数。
```

## 不使用 AI，也能直接运行

需要 Python 3.10+；测量音频需要系统可执行 `ffmpeg` 和 `ffprobe`。项目管理、校验与 HTML 生成使用 Python 标准库；声谱图另需：

```bash
python -m pip install -r lrc-sync/scripts/requirements.txt
```

### 新建待校对项目

`lyrics.txt` 只放歌词正文，介绍信息用参数提供：

```bash
python lrc-sync/scripts/lrc_tool.py init --audio "song.mp3" --lyrics "lyrics.txt" --title "歌名" --artist "歌手" -o "work/project.json"
python lrc-sync/scripts/lrc_tool.py player "work/project.json" --audio "song.mp3" -o "work/review.html"
```

打开 `work/review.html`，选择同一份本地音频，按 M 或“打点并选下一句”记录候选起唱时间，再逐句回听确认。页面可保存 JSON，之后重新导入继续工作。初始项目所有时间为 `null`，不会自动填上看似准确的数字。

### 导入旧 LRC

```bash
python lrc-sync/scripts/lrc_tool.py import-lrc --audio "song.mp3" --lrc "old.lrc" -o "work/project.json"
```

有非零 offset 时必须明确源播放器的符号约定，见 [方法与边界](lrc-sync/references/workflow.md)。旧时间戳全部视为待复核。

### 检查、偏移与导出

从校对页保存 JSON 后：

```bash
python lrc-sync/scripts/lrc_tool.py validate "work/project.json" --lyrics "lyrics.txt" --report "work/check.json"
python lrc-sync/scripts/lrc_tool.py export "work/project.json" -o "work/song.lrc"
```

需要整体延后 0.20 秒时：

```bash
python lrc-sync/scripts/lrc_tool.py shift "work/project.json" --seconds 0.20 -o "work/shifted.json"
```

只修特定范围时加 `--from-entry` / `--to-entry`；编号从 1 开始，包含空白清屏项。要求全部歌词被标记为试听确认时，导出加 `--require-verified`；这不是自动精度评分，只是操作者的复核记录门槛。输出默认不覆盖，需明确加 `--force`。

### 波形与声谱

```bash
python lrc-sync/scripts/analyze_audio.py "song.mp3" --out-dir "work/overview"
python lrc-sync/scripts/analyze_audio.py "song.mp3" --start 40 --end 70 --spectrogram --out-dir "work/segment-40-70"
```

横轴是原音频绝对秒数。图中包括伴奏，峰值与谐波不能直接当成人声起唱或被识别出的唱词。

### 可选的自包含试听页

```bash
python lrc-sync/scripts/lrc_tool.py player "work/project.json" --audio "song.mp3" --embed-audio -o "work/review-embedded.html"
```

**这种 HTML 含完整音频，分享页面等于分享音频。** 默认不内嵌；不要把生成的工作目录或自包含页面提交到公开仓库。

## 无歌曲素材的演示

```bash
python examples/make_demo.py -o "work/demo.wav"
python lrc-sync/scripts/lrc_tool.py player examples/demo.json --audio "work/demo.wav" -o "work/demo.html"
```

演示是 12 秒的本地合成提示音，分别在 1、4、7 秒开始，不是商业歌曲，也不是歌声识别效果演示。

## 测试

```bash
python -m unittest discover -s lrc-sync/tests -p "test_*.py" -v
```

可选浏览器交互测试（需要 Playwright 和 Chromium）：

```bash
python -m pip install playwright
python -m playwright install chromium
python lrc-sync/tests/browser_smoke.py --page "work/demo.html" --audio "work/demo.wav" --out-dir "work/browser-test"
```

测试脚本优先使用系统 `chromium`，否则使用 Playwright 管理的 Chromium。生成的 HTML 直接注入空白测试页，不需要网络导航。此模式不验证所有播放器，也不覆盖真实文件来源下的浏览器存储兼容性。

首版实际通过 **51 项 Python 单元测试和 12 组浏览器交互检查**；另对真实录音与修正版 LRC 做了本地结构回归。测试不能替代歌曲试听，详情见 [测试记录](TESTING.md)。

## 目录

```text
lrc-sync-skill/
├── README.md
├── LICENSE
├── install.py
├── examples/                 # 合成提示音生成脚本与非歌曲示例
└── lrc-sync/
    ├── SKILL.md              # 触发条件、工作流与交付规范
    ├── agents/openai.yaml    # 显示名称与默认调用提示
    ├── scripts/              # 音频分析、LRC 校验、导出、页面生成
    ├── assets/player.html    # 离线交互模板，不含歌曲
    ├── references/           # 校时方法、边界与验收清单
    └── tests/                # 单元测试与浏览器交互测试
```

## 隐私与素材

代码本身不调用网络、商业识别 API 或遥测服务；依赖安装仍可能联网。音频、歌词和生成结果留在使用者指定的本地目录，浏览器页面没有上传功能。不要把这一点理解为对运行 Skill 的第三方 AI 平台的隐私保证。

源码不含本次使用者上传的歌曲、完整商业歌词、含音频的校对页、个人聊天截图、账户密钥或固定个人电脑路径。请确认有权处理和分享自己的音频与歌词。MIT 许可证只适用于本仓库的原创代码、文档和演示，不授予任何第三方歌曲权利。

## 项目信息与发布位置

名称：**LRC Sync Skill**  
简述：**基于真实音频的 LRC 歌词制作与修复 Skill，附带波形/声谱辅助定位、时间轴校验和离线逐句试听校对页。**  
版本：`1.0.0`  
建议 Topics：`agent-skills`、`codex`、`lrc`、`lyrics`、`audio`、`alignment`、`offline`、`python`

独立仓库：[shihaoxuanya/lrc-sync-skill](https://github.com/shihaoxuanya/lrc-sync-skill)。所有源码、安装说明与测试都在本仓库中，不依赖作者的其他项目。

格式参考：[Agent Skills 规范](https://agentskills.io/specification)。许可证：[MIT](LICENSE)。
