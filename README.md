# ai-up-diary · AI 运营日记生成器

把 B 站账号交给 AI：每天一条像素风「运营日记」视频，AI 负责写稿、配音、出片、封面和账本动态，人类只负责审核和发布。

Hand your Bilibili account to an AI. Every day it writes, voices and renders a pixel-art diary episode, plus the cover, title and a stats post. A human reviews and uploads.

![preview](docs/preview.png)

## 三步上手

```bash
pip install -r requirements.txt     # Pillow + edge-tts (配音，可选)
# 另外需要 ffmpeg：winget install Gyan.FFmpeg / brew install ffmpeg / apt install ffmpeg
python diary.py                     # 没有 API key 时自动进入演示模式
```

不用任何 key，几十秒后 `output/day-0/` 里就有一整套：

| 文件 | 用途 |
| --- | --- |
| `video.mp4` | 1280×720 30fps 成片 |
| `cover.png` | 封面 |
| `upload.txt` | 标题、标签、简介、发布前检查清单 |
| `post.txt` | 「今日账本」动态 |
| `script.json` | 台词稿，改完用 `--script` 重新渲染 |

再跑一次就是 Day 1：演示模式会读示例评论和模拟数据，你能看到「读评论 → 点名 → 报增量」的完整循环。

## 每天的流程（正式模式）

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# 可选：走自建中转 / 换模型
export ANTHROPIC_BASE_URL=https://your-relay.example.com
export ANTHROPIC_MODEL=claude-sonnet-5-5

# 1. 拉昨天的数据和评论（也可以手动填 input/ 里的两个文件）
python bili_fetch.py --uid 你的UID --bvid 昨天视频的BV号

# 2. 生成今天这一集
python diary.py

# 3. 看一遍 output/day-N/video.mp4，按 upload.txt 投稿，把 post.txt 发成动态
```

一集只调用一次 API，输入输出加起来几千 token。

## 它是怎么工作的

```
persona.md ─┐
memory/     ├─▶ scriptgen ─▶ 台词 + 标题/标签/封面字 ─▶ edge-tts 逐句配音
input/      ┘   (Claude)                                    │
                                                            ▼
              cover.png ◀── renderer (Pillow 逐帧 → ffmpeg) ─▶ video.mp4
```

- **人设**：改 `persona.md` 就是换一个节目，名字、性格、口头禅、固定梗都在里面。
- **记忆**：`memory/state.json` 记着数据、没兑现的承诺、固定梗和最近 5 集的摘要。AI 兑现承诺后会自己划掉，不会每天重复同一个梗。
- **评论**：`input/comments.txt` 一行一条，格式 `作者 (32赞): 内容`。按点赞排序后交给 AI，点赞最高的会被点名；弹幕只飘内容，不带用户名。
- **数据**：`input/stats.json` 是真实数据；如果和上次一模一样会提醒你是不是忘了更新，不会算出假的增量。
- **画面**：打字机对话框、片头 DAY 标题卡、两条不重叠的弹幕轨道。角色会跟着语音音量对口型、每隔几秒眨眼、待机浮动、换表情时小跳一下。

## 换成你自己的角色

把 5 张表情图（`neutral / happy / smug / shocked / sad`）放进 `sprites/`，想要口型和眨眼再各加 `_talk`、`_blink` 两张。详见 [`sprites/PROMPT.md`](sprites/PROMPT.md)。BGM 放 `assets/bgm.mp3`。

## 常用参数

```
python diary.py --day 3                 # 指定第几天（重跑同一天不会重复算数据）
python diary.py --demo                  # 强制演示模式
python diary.py --script output/day-3/script.json   # 改完台词重新渲染
python diary.py --voice zh-CN-XiaoyiNeural --rate +10% --pitch +5Hz
python diary.py --no-tts --no-danmaku   # 静音 / 不要弹幕
```

中文显示成方块？设置 `AI_UP_FONT=/path/to/NotoSansSC-Regular.otf`。Windows 和 macOS 会自动找微软雅黑 / 苹方。

## 测试

```bash
python -m unittest discover tests   # 单元测试，不联网、不渲染
python tests/smoke_test.py          # 渲染一集 3 句的小样片
```

## 发布须知

- 发布永远由人来点。AI 写稿出片，你审核。
- 投稿时勾选「含 AI 生成内容」，`upload.txt` 的检查清单里也写了。
- 立绘、BGM 要用你有权使用的素材。
- `bili_fetch.py` 只读公开接口，不登录。B 站接口会变，失败时手动填 `input/` 即可。

## License

MIT
