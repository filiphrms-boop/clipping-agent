# Whop Content Rewards — operating notes

Research gathered 2026-10-02, before committing to the platform as a clip
source. Verify anything load-bearing against the campaign's own brief; the
terms change and the brief is the only enforceable document.

## The board

`https://contentrewards.com/discover/` is the real campaign board — **and it is
public, no login required.** All ~50 live campaigns and their briefs can be read
without a session, which means campaign discovery and scoring needs **no
credential automation**. Do not build login flows for this.

Whop's own Discover forum also carries a **"New Campaigns"** feed that
announces each campaign as it goes live.

## How a campaign pays

- A brand funds a pool, sets a rate per 1,000 verified views, and lists rules.
- **Minimum campaign budget is $1,000.** Most new campaigns use exactly that.
- Rates cluster around **$1–$1.50 per 1K** on the live board; advertised range
  is $0.20–$6.
- **A flat 10% platform fee** comes off the CPM payout before it reaches your
  balance.
- Settlement is ~**10 days after approval** (7 days of earning views + a 3-day
  hold), then 3–5 business days to withdraw.
- Per-post **maximum payout caps** matter more than the headline rate: a clip on
  a $2 CPM campaign capped at $25 stops earning at 12,500 views.
- A brand may reject **only** for failing a requirement *written* in the
  campaign requirements. Rules communicated any other way are unenforceable.
  There is **one appeal** per flagged submission — screenshot the brief and the
  post together as evidence.
- **Submit the post link within 30 minutes of posting.** Treat this as a hard
  deadline; the queue has to carry caption, link and media ready to go.

## The economics, without the hype

- **Gaming and streamer clips are the cheapest niche on the board**: streamers
  average ~$0.91–$1.76 per 1K, against ~$6 for finance and ~$9 for crypto.
- Advertised rates are not realised rates. The blended realised figure across
  tracked clippers is about **$0.39 per 1K views**, with average lifetime
  earnings per clipper around **$305**.
- Reference point: on a $0.30 CPM campaign, the top three clippers on the whole
  board earned $283, $214 and $104 — the best of them needed roughly
  **943,000 views** to clear $283.
- **The metric that matters is break-even, not virality.** At $1.25 per 1K, a
  clip that costs $0.33 to produce pays for itself at **264 views**. Optimise
  cost-per-clip and clips-per-hour; that is the only lever you control.

## The Tier-1 audience wall

Most campaigns require **30–50% of a clip's viewers to be in Tier-1 countries**
(US/UK/CA, sometimes AU/W. Europe), and it is checked *after* the fact —
platforms only expose audience-location data ~24h after posting. Clippers based
outside Tier-1 countries get shown to local viewers first, miss the threshold,
and are rejected or have payouts slashed once views land.

Consequences:

- **Filter the board for campaigns with no audience-location clause.** This is
  the highest-value thing an agent can do here — rejecting campaigns you cannot
  qualify for matters more than producing more clips.
- Non-US-market campaigns do exist on the board (French, Spanish, German).
- Gaming content aimed at US/UK audiences with English hooks and captions is one
  of the few niches where a new account can realistically draw Tier-1 viewers.
- Many clippers outside Tier-1 countries abandon per-view pools for **retainers**
  with podcasters and founders, where there is no pool to qualify for.

## Hard rules — these end accounts

- **Buying or generating views, likes, followers or engagement = permanent ban
  with all pending earnings forfeited.** Views from bots, scripts or macros are
  excluded from the count, and views obtained via prizes, payments or barters
  are excluded by the same clause.
- **Faking analytics to pass a Tier-1 rule violates the creator terms.** Be
  aware that sellers advertise exactly this ("customise audience location",
  "adjust views/likes/comments", VPN geo-spoofing). It is the ban.
- Every submission carries a **0–100 bot score**; over threshold freezes the
  payout for human review.
- **One account per person.** Multi-accounting to farm payouts bans every linked
  account.
- **Original content only** — clip only the footage the campaign provides. You
  must have rights to what you submit. Approved submissions grant the brand a
  perpetual, sublicensable licence to your cut.
- Social accounts must be **linked inside Whop**, or views cannot be tracked and
  submissions can never be credited.
- 18+.

## Payout eligibility

Whop pays out to **200+ countries in local currency** (Serbia and all its
neighbours are supported).

- Setup: Dashboard → Balances → *Set up Whop Payments* → select country → KYC
  (details, link bank, photo ID).
- The bank account must accept the currency of your registered country — Whop
  converts to local currency before sending.
- PayPal and Coinbase Commerce are direct alternatives.
- Minimum withdrawal $10 on some documentation, none on others; wire ~$23;
  crypto ~5% + $1. Check your own dashboard.

## Third-party IP — the GTA6 case study

Grand Theft Auto VI launches **19 November 2026**. As of Oct 2026 there is no
released gameplay to clip, and **no GTA6 campaign on the board** — the word
"GTA" appears exactly once, inside one music campaign's brief listing desired
edit styles.

Take-Two were in active enforcement over GTA6 leaks in August 2026: DMCA
takedowns against GitHub, **DMCA subpoenas against Microsoft and Discord** to
unmask leakers, and YouTube channel strikes. Rockstar's standing video policy
permits monetised gameplay but explicitly excludes **leaked or pre-release
material** and **reposting cinematics as-is**.

The general rule this illustrates: a campaign brief is your permission for *that
campaign's* footage. It cannot grant rights the brand does not own. Where a
third party owns the underlying IP, respect their content policy independently
of the brief.

## Platform risks specific to gaming clips

YouTube's gaming policy can age-restrict or demonetise violence against in-game
NPCs. For a Grand Theft Auto title that is not an edge case, and an
age-restricted clip is a clip whose views may not count toward a campaign.
Bias selections toward driving, stunts, systems, comedy and glitches.
