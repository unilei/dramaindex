# 短剧平台分销/affiliate 渠道调研（2026-09-16）

目标：找出 RS Boost 之外、**无需邀请码**的分销渠道作为收入通道。

结论：**没有。** RS Boost（走官方邮件申请）是唯一可用的通道，且我已走的是正确路径。

---

## 逐平台核实结果

| 平台 | 运营方 | 有无推广者分销 | 证据 |
|---|---|---|---|
| ReelShort | NewLeaf Publishing | **有** — RS Boost (`cps.reelshort.com`) | 需邀请码；见下方「官方路径」 |
| DramaBox | STORYMATRIX PTE. LTD. | **无** | `/business` 只面向**版权方**：`distribution@`（有剧要发行）、`adaptation@`（编剧/字幕）、`production@`（自制剧）、`partnerships@`（IP/品牌）。无推广者入口。`/terms` 全文 0 处提到 affiliate/commission/referral |
| GoodShort | NewReading PTE. LTD. | **无** | `/business` 只面向**内容供应方**：`contact@goodshort.com`、`copyright@goodnovel.com`（卖电子书/有声书/短剧给它）。`term-of-use` 全文无 affiliate 条款（仅出现在免责声明的"affiliates"泛指） |
| ShortMax | SHORTTV LIMITED | **无** | 全站没有 business/partner/affiliate 页面；只有客服邮箱 `shorttv.service@shorttv.live` |
| NetShort | NETSTORY PTE. LTD. | **无** | `cps.netshort.com` 存在但只返回 6 字节 `hello`（阿里云 OSS 占位文件，非可用系统）。主站无任何推广入口 |
| DramaWave / JoyReels / FlickReels | SKYWORK / UREELS / FARSUN | 未发现 | JoyReels 所有路径返回**完全相同**内容（SPA catch-all），无真实页面 |
| 各母公司域名 | — | 无 | `cps/affiliate/partner` 子域扫描 shorttv.live、storymatrix.com、skywork.ai、netstory.com、ureels.com、farsun.com 全部无响应 |

**为什么其他平台不做推广者分销**：RS Boost 这类系统的核心是「用户充值 CPS + 归因」，需要平台自己建归因、结算、风控、提现体系，成本很高。ReelShort 做了，其余多数没做。

---

## 两个「看起来像机会」的陷阱

### ❌ DramaCPS (dramacps.com) — 不是可用渠道

首页宣称：一站接入 ReelShort/DramaBox/GoodShort + 14 个平台、45%–65% CPS、NET7 周结。

但实测：

- `/`、`/signup`、`/register`、`/login`、`/apply`、`/contact`、`/terms` **全部返回字节完全相同的内容**（md5 均为 `124100d7…`）→ 是 catch-all，**根本没有注册页**
- 全站 **0 个 `<form>`、0 个邮箱地址、0 个可点击外链**（整页仅 6.2KB）
- 域名 **2026-03-16 才注册**（约 6 个月），注册商 Dynadot，Cloudflare NS

即一个只有宣传文案、没有任何功能或联系方式的页面。**不要把它当作渠道**，更不要向它提交任何信息。

### ❌ DramaPartner 的「免费邀请码」— 会让你永久被抽成

dramapartner.com 提供「免费 RS Boost 邀请码」，但**它自己的披露页写着**：

> "The publisher may receive a benefit when a reader uses an invitation code supplied by this site."

而 RS Boost 的邀请码 **`不可解绑`（Cannot be unbound）**。也就是说：用它的码注册 = 把它设为你**永久的上级分销商**，你未来所有收益都要分它一份，且无法解除。

它页面上的说明（不卖码、不索要密码、不承诺收入）看着规范，但商业实质就是**用免费码换取永久下线**。

**结论：不要用任何第三方提供的邀请码。**

---

## ✅ 官方路径（已验证，且已执行）

RS Boost 注册页在「Creator Safelist / 报白」区块内置了这条文案：

```
"没有邀请码？请联系平台商务"
"Don't have a Referral Code? Please contact by email: "
```

该邮箱由 JS bundle 在运行时注入。我在
`/_next/static/chunks/app/%5Blocale%5D/layout-*.js` 中解析出实际地址为：

```
rsboostsupport@crazymaplestudio.com
```

**这正是 2026-09-16 01:02 已经发信过去的地址。**

也就是说：没有邀请码时的**官方指定做法就是发邮件给官方商务**，而不是找第三方要码。已经走对了，无需再补发。

---

## 结算窗口的澄清

RS Boost 门户里同时存在**两个**提现窗口文案：

- `每月25-31日提现上月结算收益`
- `每月12-20日提现上月结算收益`

推测对应不同账号等级/类型（DramaPartner 的页面写的是 12–20 日）。无论哪个，**都是「提现上个月的收益」** —— 本月产生的收入最快也要到下月才能提。这条结论不变。

第三方引用的佣金率（20–30% / 35–50% / 45–65%）互相矛盾且都非官方。DramaPartner 自己的说法也印证了这点：「比率可能变动，不要依赖旧教程里的百分比」。**真实比率只有登录后才能看到。**

---

## 对收入目标的含义

1. **没有旁路可走** —— 除 RS Boost 外不存在第二个可立即开通的短剧分销通道
2. **不该用第三方邀请码** —— 会永久被抽成，且不可解绑
3. **官方路径已在走** —— 等 `rsboostsupport@` 回复即可，不要再发第二封
4. **时间约束不变** —— 结算周期决定本月收入最快下月到账，30 天内产生现金在结构上不成立
