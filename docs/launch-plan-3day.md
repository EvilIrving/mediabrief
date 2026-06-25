# MediaBrief 三天冲刺发布计划（新号版）

> 前提:你的 HN、Reddit 账号都是 **karma=1 的全新号、从没用过**。这份计划是按这个硬约束写的,
> 不是通用模板。每个平台的规则都查过(文末有来源),不是拍脑袋。

---

## 先看懂这条铁律(决定了为什么这么排)

新号在不同平台的"生死"完全不同:

| 平台 | 新号能不能冷发? | 原因 |
|------|----------------|------|
| **Hacker News（Show HN）** | ✅ 能,但有风险 | 没有 karma 门槛。但绿号容易被 spam 过滤器静默吞掉(shadowban),发完**必须自查**(见下)。且 Show HN **只收能玩的东西(仓库/app),不收博客**。 |
| **掘金** | ✅ 能 | 国内开发者平台,新号可直接发文章,无 karma 墙。 |
| **即刻** | ✅ 能 | 新号可发,适合碎片+demo。 |
| **Product Hunt** | ⚠️ 能但弱 | 零活跃新号会被算法降权;官方建议提前 30 天养号 + 建 upcoming 页。冷发拿不到好名次,但可"自荐(self-hunt)"拿个反链。 |
| **Reddit** | ❌ 不能 | karma=1 会被 AutoMod **静默过滤**,r/selfhosted、r/SideProject 都有 karma 门槛。冷发=帖子直接进垃圾桶,你还看不出来。**这三天只能养号,不能发项目。** |
| **V2EX** | ❌ 不能 | 新号发「分享创造」会撞"需注册满 360~1014 天"的墙。这次直接放弃。 |

**结论**:这三天的主力是 **HN + 掘金 + 即刻**,Product Hunt 作为可选补充,Reddit 全程只养号。

---

## 发车前必须先做的两件事(D-day 前一晚,或更早)

### 1. 录 demo(没有它,所有渠道转化率减半)
- 30 秒以内,无声也行:粘链接 → 进度条 → 摘要秒出 → 翻历史。
- 存成 `docs/img/demo.gif`(GitHub README 内联用 GIF 比 mp4 稳)+ 一份 mp4(PH/即刻用)。
- 这是唯一我替不了你的事,但它是 ROI 最高的一步。

### 2. Reddit 养号(从今天就开始,越早越好)
三天冲刺期间,你**每天花 15 分钟**在这些 sub 里**真诚评论**(回答别人问题、夸别人项目),目标攒到 ~30+ comment karma:
- r/selfhosted、r/LocalLLaMA、r/opensource、r/SideProject
- 规则:**10% 自我推广**——每 1 个推广,配 9 个纯参与。这三天先纯参与,一个广告都别发。
- 等这波冲刺过后(下下周),账号有了 karma,再去 r/SideProject、r/selfhosted 发项目就发得出去了。

---

## DAY 1（周二)— 中文圈起步 + HN 蓄势

中文平台对新号最友好,先在这里拿到第一波真实 star 和反馈,也给自己练手。

### 平台 A:掘金(主)
- **发什么**:那篇随笔《我花了两周,把一行链接做成了一个能发给别人的软件》(`docs/blog/zh-building-ai-transcriber-story.md`)。
- **怎么发**:
  - 标签选「人工智能」「Python」「开源」。
  - 文章末尾的 GitHub 链接保留(掘金允许)。
  - 配图:把 demo GIF 放进文章开头第一屏。
- **为什么是它而不是工程复盘**:你删掉的那篇技术文太硬。这篇随笔门槛低、有故事,掘金「创造/随笔」类也吃得开。**如果反响好,Day 3 我再帮你补一篇纯技术复盘**(字幕优先链路、Whisper 抗幻觉那些),技术圈更买账。

### 平台 B:即刻(辅,全天滚动发 2-3 条)
即刻适合短、真、带图。**不要发链接墙**,发"造物心情 + 一个具体的坑",评论区再放链接。
- **第 1 条(配 demo GIF)**:
  > 折腾两周,做了个东西:粘个视频/播客链接进去,它自动抓字幕、没字幕就转录,再用大模型整理成干净文字稿和摘要。本来想着三步就完事,结果每一步都在收拾我。开源的,放评论区了。
- **第 2 条(讲那个连字符 bug,故事性最强)**:
  > 这两周最气的 bug:明明视频有字幕,工具却老说"找字幕失败"。查到最后是一个字符——该写下划线写成了横杠,Python 把它当成减法,语法合法、不报错,只在运行时悄悄崩,还正好被我自己的容错逻辑接住了。你以为写的是健壮,其实是在帮 bug 打掩护。
- **第 3 条(求反馈,引导互动)**:
  > 如果你也常和长视频/播客打交道,想问问你们一般怎么"消化"它们?我做的这个工具放 GitHub 了,想听点真实意见(轻喷)。

### 平台 C:Hacker News —— 今天只做准备,不发
- 注册/登录,把个人资料填上(about 写一句真人介绍 + 网站),**绿号有资料比裸号更不容易被判 spam**。
- 今天先在 HN 上**真诚评论几条**别人的帖,让账号有点活动痕迹。
- 明天(周三)再发 Show HN。

---

## DAY 2（周三)— Hacker News Show HN(主战场)

这是新号唯一能打的英文大盘,全天的重心。

### 发布时机
- **美西时间(PT)早上 ~7-9 点**发(对应北京时间晚上 22-24 点)。这是 HN 流量爬升、新帖最容易被看到的窗口。工作日(周二到周四)最佳。

### 标题(必须以 `Show HN:` 开头,不许吹)
直接用这条(已按 HN 规则:具体、不夸张、说清是什么):
```
Show HN: Self-hosted tool that turns videos/podcasts into clean transcripts and AI summaries
```
> 备选:`Show HN: Paste a video link, get a clean transcript and summary (subtitle-first, Whisper fallback)`

### URL 填什么
- **填 GitHub 仓库**:`https://github.com/EvilIrving/ai-transcribe`
- ⚠️ **不要填博客**——Show HN 明确不收 blog/阅读材料,只收"能玩的东西"。仓库符合。

### 发完立刻贴一条"作者评论"(maker comment,英文,200-300 词)
这条会被你自己顶在最上面,定整个讨论的调子。直接用:
```
Author here. I built this because I listen to a lot of podcasts and watch long
technical talks, and I didn't want to "watch the whole thing" — I wanted to know
what was said, keep it, and search it later. Existing tools were either paid,
sent my content to someone else's server, or gave me an unformatted wall of text.

So: paste a link (YouTube, Bilibili, 30+ platforms via yt-dlp) or drop a local
file. It grabs existing subtitles when they exist (fast path, no audio download),
falls back to Faster-Whisper transcription when they don't, then cleans it up and
summarizes with an LLM. The summary streams in first while the full transcript
keeps optimizing in the background. RSS automation is built in for podcasts.

Two design choices I'd call out: (1) the backend is stateless — your API key,
base URL and model live only in your browser, the server never stores them, which
let me package it as a double-click desktop app without an account system; (2)
it's bring-your-own-model — any OpenAI-compatible endpoint (OpenAI, OpenRouter,
a local LLM, whatever).

It's free and open source (MIT). Honest about the rough edges: it's three weeks
old, and getting it to run on a "blank" machine (no GitHub access, no system
ffmpeg) was harder than building the features. Happy to answer anything, and I'd
genuinely like feedback on where it breaks.
```

### 发完 30 分钟内 —— 自查有没有被 shadowban(新号最大的坑)
1. **退出登录**,或用无痕窗口打开你的帖子链接。看得到 = 正常;看不到 = 被吞了。
2. 或访问 `https://news.ycombinator.com/newest`,找你刚发的帖,如果显示 `[dead]` 就是被过滤了。
3. **如果被吞**:发邮件给 `hn@ycombinator.com`,礼貌说明"我是新用户,发了个 Show HN 介绍自己开源的项目,似乎被 spam 过滤了,能否帮看一下",通常很快会放出来。
4. **绝对不要**让朋友集中点赞(vote ring)——HN 反作弊很狠,会直接惩罚帖子。可以让朋友看、真心觉得好再自然点。

### 全天守评论区
- 每条评论都认真回,尤其技术问题。HN 排名极看"作者活跃度 + 讨论质量"。
- 有人提 bug/质疑,**先谢再答**,别防御。这是新号建立信誉最快的方式。

---

## DAY 3（周四)— 放大 + 补刀

### 平台 A:Product Hunt(可选,拿反链 + 一点流量)
- 用**个人号**(PH 禁公司号),把资料填完整(头像、bio、链接)。
- **自荐(self-hunt)**,2026 年完全正常、无惩罚。
- **tagline**(60 字符内):
  ```
  Paste a link, get a clean transcript and AI summary. Self-hosted.
  ```
- **第一条 maker comment**:把 Day 2 那条 HN 作者评论改短到 150 词复用即可。
- 素材:demo 视频 + 三张截图(home/rss/history)。
- ⚠️ **预期管理**:零养号冷发,拿不到 Product of the Day,但能拿个 dofollow 反链 + 少量开发者流量,值得顺手做。**别为它熬夜拉票**,重心仍在 HN 余热。

### 平台 B:掘金技术复盘(如果 Day 1 那篇反响好)
- 我帮你补一篇**纯技术**的:字幕优先两段式抓取、Whisper 抗幻觉调参、"取消要杀干净"那套进程组方案。
- 这篇技术圈更买账,和 Day 1 的随笔形成"故事 + 干货"组合拳。

### 平台 C:复盘 + Reddit 继续养号
- 看哪个渠道带来的 star 最多(GitHub Insights → Traffic → Referrers),**把有效的那个再投一轮**。
- Reddit 继续评论攒 karma。等 karma 够了(下下周),发 r/SideProject(最宽容)和 r/selfhosted(精准)——到时我再给你写那两个 sub 的专属帖子(它们口味和 HN 不一样,要更"自部署/隐私"角度)。

---

## 三天能到 1K 吗?——说实话

不骗你:从 2 star 三天冲 1K,需要 **HN 上首页前 10** 或 **PH 当日前三**级别的爆发,可遇不可求,**没法保证**。这套打法更现实的预期是:
- 大概率把你从两位数推到 **三位数**;
- 1K 看 HN 那一发的运气——所以 HN 标题、首评、demo 必须打磨到位,这是唯一能放大运气的地方。
- 真正的 1K 往往不是冲出来的,是这波拿到几百 star + 真实用户后,**靠口碑和后续常规流量**(SEO、目录反链、持续发版)慢慢爬上去的。

冲完这三天,我们再排"常规流量"的长线(目录提交、持续内容、发版节奏)。

---

## 来源(平台规则查证)
- [Hacker News — Show HN 官方规则](https://news.ycombinator.com/showhn.html)
- [Reddit 自我推广 / 新号 karma 门槛(综合)](https://postiz.com/blog/reddit-karma-requirements)
- [r/SideProject 发帖与新号要求](https://www.mediafa.st/marketing-on-rsideproject)
- [V2EX 新账号发帖注册天数限制(社区反馈)](https://www.v2ex.com/t/1144293)
- [Product Hunt 发布最佳时间与新号准备](https://www.producthunt.com/p/producthunt/the-best-day-to-launch-on-product-hunt)
