# Podcast and Blog RSS Feeds

A curated starter set for frontend, Node.js, developer communities, AI, and influential individual developers/researchers. Chinese sources are intentionally limited to three highly influential ones.

Custom imports can use either an array of feed objects or `{ "feeds": [...] }`; each item needs at least a `url` field. See `rss_feeds_template.json` for a minimal example.

| Source | Region | Topic | RSS |
|---|---|---|---|
| Syntax | US | Frontend, JavaScript, React, Web development | `https://feed.syntax.fm/rss` |
| JS Party | US | JavaScript, frontend ecosystem | `https://changelog.com/jsparty/feed` |
| ShopTalk Show | US | CSS, frontend, Web platform | `https://shoptalkshow.com/feed/podcast/` |
| The Changelog | US | Open source, developer tools, tech trends | `https://changelog.com/podcast/feed` |
| Software Engineering Daily | US | Software engineering, cloud, AI, infrastructure | `https://softwareengineeringdaily.com/feed/podcast/` |
| Software Engineering Radio | US | Software engineering practices | `https://feeds.feedburner.com/se-radio` |
| Practical AI | US | AI engineering, ML in practice | `https://changelog.com/practicalai/feed` |
| Latent Space | US | AI, LLMs, agents, AI engineering | `https://www.latent.space/feed` |
| Hard Fork | US | AI, tech companies, internet trends | `https://feeds.simplecast.com/l2i9YnTd` |
| Stack Overflow Blog | Global | Developer community, software culture | `https://stackoverflow.blog/feed/` |
| GitHub Blog | Global | Developer tools, open source, GitHub | `https://github.blog/feed/` |
| Vercel Blog | Global | Frontend, Web platform, deployment | `https://vercel.com/atom` |
| OpenAI News | US | AI research, products, safety | `https://openai.com/news/rss.xml` |
| Overreacted, Dan Abramov | US | React, JavaScript, software thinking | `https://overreacted.io/rss.xml` |
| Kent C. Dodds | US | React, testing, frontend engineering | `https://kentcdodds.com/blog/rss.xml` |
| Josh W. Comeau | Canada | CSS, React, UI craft | `https://www.joshwcomeau.com/rss.xml` |
| Jake Archibald | UK | Web platform, browser APIs, performance | `https://jakearchibald.com/posts.rss` |
| Jeremy Keith, Adactio | UK | Web standards, resilient frontend | `https://adactio.com/journal/rss` |
| Addy Osmani | UK/US | Performance, Chrome, AI tooling | `https://addyosmani.com/rss.xml` |
| Lea Verou | Europe | CSS, Web standards | `https://lea.verou.me/feed.xml` |
| David Walsh | US | JavaScript, frontend development | `https://davidwalsh.name/feed` |
| Simon Willison | UK | AI, LLMs, Python, web engineering | `https://simonwillison.net/atom/everything/` |
| swyx | Singapore/US | AI engineering, developer tools, DX | `https://www.swyx.io/rss.xml` |
| Lilian Weng | US | AI research, agents, LLMs | `https://lilianweng.github.io/posts/index.xml` |
| Sebastian Raschka | US/EU | Machine learning, LLMs | `https://magazine.sebastianraschka.com/feed` |
| Andrej Karpathy | US | AI, neural networks, software | `https://karpathy.bearblog.dev/feed/` |
| JSer.info | Japan | JavaScript community digest | `https://jser.info/rss/` |
| Takuto Wada | Japan | Testing, software design | `https://t-wada.hatenablog.jp/rss` |
| mizchi | Japan | Frontend, JavaScript, AI | `https://mizchi.dev/rss.xml` |
| uhyo | Japan | TypeScript, frontend | `https://blog.uhy.ooo/rss.xml` |
| NAVER D2 | Korea | Developer community, engineering | `https://d2.naver.com/d2.atom` |
| Kakao Tech | Korea | Engineering blog | `https://tech.kakao.com/feed/` |
| GeekNews Korea | Korea | Developer community news | `https://news.hada.io/rss/news` |
| Martin Fowler | UK | Software architecture, delivery | `https://martinfowler.com/feed.atom` |
| Baldur Bjarnason | Iceland | Web, software culture | `https://www.baldurbjarnason.com/index.xml` |
| Surma | Germany | Web platform, performance | `https://surma.dev/index.xml` |
| Sindre Sorhus | Norway | Open source, Node.js, tooling | `https://sindresorhus.com/rss.xml` |
| Manuel Matuzovic | Austria | HTML, CSS, accessibility | `https://www.matuzo.at/feed.xml` |
| Piccalilli | UK | CSS, design systems, frontend craft | `https://piccalil.li/feed.xml` |
| 阮一峰 | China | Weekly developer links | `https://www.ruanyifeng.com/blog/atom.xml` |
| CoolShell | China | Influential engineering essays | `https://coolshell.cn/feed` |
| 美团技术团队 | China | Engineering blog | `https://tech.meituan.com/feed/` |

## Candidates not included in the one-click preset

| Source | Reason | RSS |
|---|---|---|
| Robin Wieruch | Influential React author, but the feed produced intermittent SSL EOF errors from the app parser during testing. | `https://www.robinwieruch.de/index.xml` |
| Chip Huyen | Influential ML systems author, but the feed produced intermittent SSL EOF errors from the app parser during testing. | `https://huyenchip.com/feed.xml` |
