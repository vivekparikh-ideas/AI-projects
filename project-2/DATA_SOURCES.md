# Gap Finder: data sources and licenses

The register of every data source and service Gap Finder uses or has considered. It records what each license allows and what we checked. Reasons for decisions live in `decisions.md`, and the files we hold live in `data/raw/MANIFEST.json`. The full audit with sources is the "Gap Finder Data Audit" artifact (https://claude.ai/artifact/6Sgpm4y9bNapofS3uW1CEt).

This is a technical compliance record, not legal advice. Re-check every source before the v2 commercial release.

**Status key:** ✅ in use · ⏳ planned, not yet ingested · ⏸ deferred · 🔁 fallback · ⛔ excluded

| Source | Status | License | v1 | v2 | Last checked |
|---|---|---|---|---|---|
| Learning Commons Knowledge Graph v1.15.0 | ✅ | CC BY 4.0 (Coherence Map edges CC0) | Yes | Yes, after per-state review | 2026-10-14 |
| IM K–12 Math, first edition | ⏳ | CC BY 4.0 | Yes | Yes | 2026-10-14 |
| Common Core math standards text | ⏳ | NGA/CCSSO public license | Yes | Commercial license needed | 2026-10-14 |
| Common Core math Progressions (2023) | ⏸ deferred | CC BY 4.0 | Yes | Yes | 2026-10-14 |
| 1EdTech CASE Network 2 | 🔁 | State terms per framework | Yes | Yes, with supplier fee | 2026-10-14 |
| IM v.360 lessons and problems | ⛔ | CC BY-NC 4.0 | — | No | 2026-10-14 |
| Eureka Math / EngageNY | ⛔ | CC BY-NC-SA | — | No | 2026-10-14 |
| Common Standards Project | ⛔ | No terms found | — | — | 2026-10-14 |
| achievethecore.org (site copy) | ⛔ | Varies per item | — | — | 2026-10-14 |
| OpenAI API | ✅ | Commercial API terms | Yes | Yes | 2026-10-14 |
| Neo4j AuraDB Free | ✅ | Service terms | Yes | Re-check for production | 2026-10-14 |
| Pinecone Starter | ✅ | Service terms | Yes | Re-check for production | 2026-10-14 |

---

## Learning Commons Knowledge Graph ✅
- **Provider:** Learning Commons (Chan Zuckerberg Initiative)
- **Version / files:** v1.15.0, `nodes.jsonl` and `relationships.jsonl` (see MANIFEST.json for checksums). Math-only copy: `data/interim/learning_commons_v1.15.0_math/`.
- **Download:** `https://cdn.learningcommons.org/knowledge-graph/v1.15.0/exports/{nodes,relationships}.jsonl`. No key is needed for open datasets. The REST API needs a key and is in early access, so breaking changes are possible.
- **License:** "Knowledge Graph is provided by Learning Commons under the CC BY-4.0 license." The datasets we use:

  | Dataset | Upstream provider | License | Required attribution |
  |---|---|---|---|
  | US academic standards | State education agencies via 1EdTech / Common Good Learning Tools | Varies by state | Use each row's `attributionStatement` verbatim |
  | Standards crosswalks (state → Common Core) | Learning Commons | Varies by state | Use each row's `attributionStatement` verbatim |
  | Math learning components | Achievement Network | CC BY 4.0 | "Math learning components are provided under CC BY 4.0 from Achievement Network." |
  | Eedi Misconceptions Graph v1.0 | Eedi Ltd. | CC BY 4.0 | "'Eedi Misconceptions Graph v1.0' (c) 2026 Eedi Ltd. is licensed under CC BY 4.0" |
  | Math Coherence Map | Student Achievement Partners | CC0 | Not required. Courtesy credit: "Learning progressions are provided under CC0 from Student Achievement Partners." |
  | IM v.360 scope and sequence (outline only) | Illustrative Mathematics | CC BY 4.0 | "Scope and sequence of the Illustrative Mathematics 360 curriculum are provided under CC BY 4.0" |

- **Terms:** use for "exploratory, research, and other uses permitted under their respective licenses." There are no extra commercial or AI restrictions beyond each dataset's license.
- **Open questions:**
  - Review the state standards rows state by state before v2, and set `v2_allowed` for each state.
  - The Eedi misconceptions link only to Eedi's own constructs. A mapping to US standards still needs building.
- **Links:** [license](https://docs.learningcommons.org/knowledge-graph/resources/license) · [terms](https://docs.learningcommons.org/knowledge-graph/resources/terms-of-use) · [local files](https://docs.learningcommons.org/knowledge-graph/using-knowledge-graph/local-files)

## IM K–12 Math, first edition ⏳
- **Provider:** Illustrative Mathematics. The 6–8 edition was published by Open Up Resources (© 2017–2019), and the K–5 first edition is © 2021.
- **License:** CC BY 4.0 (IM Terms of Use §7.1).
- **Required attribution (exact):** "Based on IM® K–12 Math authored by Illustrative Mathematics and licensed under CC BY 4.0." Also link to the license and indicate whether changes were made.
- **Restrictions:**
  - The IM® name and logo aren't covered by the license (§3, §7.3). Never use them as branding or imply endorsement, and don't name anything "Illustrative Math".
  - No framing of IM pages (§8.3).
  - No bots that put excessive load on IM's servers or get around access controls (§9).
- **Host (checked 2026-10-14):** `im.kendallhunt.com`, which IM itself operates under the IM Central Terms (effective 2026-05-21). Pages: `/K5/teachers/grade-N/unit-N/lesson-N/lesson.html` and `/MS/teachers/{grade}/{unit}/{lesson}/index.html` and `.../practice.html`. IM's old `curriculum.illustrativemathematics.org` now redirects here. `robots.txt` has no directives.
- **License on the pages (verified):**
  - 6–8: "copyright 2017-2019 by Open Up Resources", with adaptations "copyright 2019 by Illustrative Mathematics", both CC BY 4.0.
  - K–5: "© 2021 Illustrative Mathematics®. Licensed under the Creative Commons Attribution 4.0 license."
  - Both are the first edition, and neither is NC.
- **What's public without login:**
  - lesson text, activities and student-facing problems
  - 6–8 practice problems
  - lesson summaries and syntheses (which contain some worked answers)
  - **standards for each activity** (Addressing / Building On / Building Towards), which gives first-edition lessons their own standards alignment
- **What's behind a free teacher login** ("Teachers with a valid work email address"): practice-problem solutions, student responses and cool-downs. **No answer keys are publicly available.**
- **Format:** HTML, with math in LaTeX. Sampled 6–8 practice problems are mostly text-only. K–5 problems depend more on images.
- **Rules that apply:** decision #10 (first edition, exact attribution, no IM® branding) and IM Terms §9 (no excessive load, no getting around access controls). Logging in to bulk-collect answer keys is **not permitted** under our decisions without IM's written permission.
- **Open questions:**
  - how to get answer keys: decided in decisions.md #16 (computed by us, checked by a person; no login)
  - what share of problems can be checked automatically
  - Some third-party copies (for example ASSISTments) carry NC-SA terms, so don't use them.
- **Links:** [IM Terms of Use](https://www.illustrativemathematics.org/terms-of-use) · [IM trademark policy](https://www.illustrativemathematics.org/im-trademark-usage-policy/)

## Common Core math standards text ⏳
- **Provider:** NGA Center and CCSSO.
- **License:** the public license is "limited, non-exclusive, royalty-free … for purposes that support the Common Core State Standards Initiative." The examples inside the standards are excluded. A separate royalty-free commercial license is available. It prohibits revising or recasting the standards where the meaning changes, and covers only the version current when you sign.
- **Required notice (exact):** "© Copyright 2010. National Governors Association Center for Best Practices and Council of Chief State School Officers. All rights reserved."
- **How we use it:** show the standards verbatim with the notice and without the examples. Label Gap Finder's plain-language descriptions as our own.
- **Before v2:** sign the commercial license.
- **Links:** [public license](http://www.thecorestandards.org/public-license/) · [commercial license](https://thecorestandards.org/commercial-license/)

## Common Core math Progressions (May 2023) ⏳
- **Provider:** Common Core Standards Writing Team, published by the Institute for Mathematics and Education, University of Arizona.
- **License:** CC BY 4.0, per the document's front matter.
- **Attribution:** "Common Core Standards Writing Team. Progressions for the Common Core State Standards for Mathematics. Tucson, AZ: Institute for Mathematics and Education, University of Arizona." Plus the license link.
- **Use:** source for "why this skill comes first" explanations.
- **Status:** ⏸ deferred (2026-10-14). The host site is down and the Wayback Machine copy is rate-limited. Until it can be downloaded, "why" explanations draw on the Learning Commons skill-component and Coherence Map descriptions. When it's available, save it to `data/raw/progressions_2023/` and add it to MANIFEST.json.
- **Link:** [2023 PDF (New Mexico PED copy)](https://webnew.ped.state.nm.us/wp-content/uploads/2025/04/Progressions-for-the-Common-Core-State-Standards-Math_05.23-version.pdf)

## 1EdTech CASE Network 2 🔁
- **Use:** fallback for state standards that Learning Commons doesn't cover.
- **Access:** browsing is free. API and download access need registration. It's free for non-commercial users, and edtech suppliers pay a nominal annual fee (budget for it in v2).
- **License:** each framework's state terms.
- **Link:** [CASE Network 2](https://www.1edtech.org/1edtech-article/1edtech-and-common-good-learning-tools-launch-major-upgrade-to-database-of-state)

## Excluded ⛔
- **IM v.360 lessons and problems:** CC BY-NC 4.0 (IM Terms §7.2). Commercial use needs IM's Restricted Use License. Only the CC BY outline (scope and sequence) from Learning Commons is used.
- **Eureka Math / EngageNY (Great Minds):** CC BY-NC-SA, according to a third-party notice. It's non-commercial and copyleft, so excluded in both phases.
- **Common Standards Project:** no API terms or sign of recent activity found. Replaced by Learning Commons, with CASE Network 2 as the fallback.
- **achievethecore.org copy of the Coherence Map:** the site's terms vary per item. Use the CC0 copy in Learning Commons instead, and don't scrape the site.

## Services ✅
- **OpenAI API** (generation, grading, `text-embedding-3-small`):
  - API inputs and outputs aren't used for training unless you opt in.
  - We own the outputs.
  - The terms bar using outputs to build competing models, which doesn't apply to Gap Finder.
  - Never send anything about a child.
  - [API data privacy](https://openai.com/api-data-privacy)
- **Neo4j AuraDB Free:**
  - Confirmed limit is 200k nodes and 400k relationships.
  - The instance pauses after 72 hours with no writes, so the keep-alive job must run a write query.
  - A paused instance is deleted after 30 days.
- **Pinecone Starter:** 2 GB storage, with monthly read and write unit caps.

## Re-check schedule
- **Before each new raw download:** confirm the license page hasn't changed, then update "Last checked".
- **Before the v2 commercial release:** re-verify every row, finish the per-state review of the standards rows, sign the Common Core commercial license, and confirm the Neo4j and Pinecone terms allow production use.
