# Newsletter design notes: making the issue an easy scroll

Date: 2026-06-11. Research and decisions for the visual format of the
weekly issue, destination Substack. The redesigned sample applying all
of this is issues/2026-06-10/draft-issue-redesigned.md.

## What Substack can and cannot do

The whole design has to survive a paste into the Substack editor, so it
is built from elements Substack actually supports.

Supported and used here: headings, bold, italics, bullet and numbered
lists, dividers, blockquotes, pull quotes, buttons (Subscribe and
Share, inserted in the editor), images, footnotes, emoji.

Not supported: tables. There is no native table element. The accepted
workaround is Datawrapper, a free tool whose tables and charts embed
interactively by pasting a URL into the editor; screenshots of tables
are discouraged (unreadable to screen readers, invisible to search).
Sources: nsokolsky.substack.com/p/how-to-insert-a-table-in-substack,
automato.substack.com/p/how-to-add-powerful-tables-and-graphs,
reallygoodbusinessideas.com/p/how-to-add-tables-to-substack.

## Design principles adopted

1. Two layers: a skim layer and a read layer. The top of the issue is
   an "at a glance" numbered index, one line per company with stage,
   amount, sector, and a hiring badge. The reader who only has thirty
   seconds gets the whole week there. Cards with detail follow for the
   reader who scrolls on. (Newsletter Operator: table of contents and
   section headers are the highest-value skim aids.)
2. Emoji as a fixed signal system, not decoration. Same emoji, same
   meaning, every week: 🟢 hiring now, ⚪ no live roles found, 🔒 job
   board unverifiable, 🎓 a role a recent grad could apply for. Legend
   printed once under the index. One brand emoji (📡) opens every
   subject line for inbox recognition (the Morning Brew ☕ trick, via
   Newsletter Operator and beehiiv's header guide).
3. A consistent card grammar. Every company card has the same shape:
   numbered H2 with badges, a bold strapline (stage, amount, one-line
   pitch), a two-sentence description, a one-line "why it matters",
   then exactly four labelled rows: founders, team, hiring, evidence.
   Eyes learn where to look; skimming gets faster every issue.
4. Section headers short and in caps, with dividers between cards.
   Single column, around 600px effective width; that is what email
   renders well everywhere (Newsletter Operator).
5. One image, reused weekly: a masthead banner at 1100 x 220 px (the
   Substack email banner size). Built once in Canva, numbers swapped
   each week. Per-post social preview is 1456 x 1048 px. (Really Good
   Business Ideas, Substack visuals guide; Substack support docs on
   image dimensions.) Do not hotlink company logos; rights are murky
   and broken images look worse than none.
6. Pull quote for the standout deal, right after the index. It is the
   one Substack flourish that reads like a newspaper front page.
7. Read time in the header line. Keeps the promise of a short scroll
   explicit.
8. Charts, when wanted, via Datawrapper embeds (stage breakdown, raise
   totals over time). Interactive in the post, no screenshots.

## Where the real newspaper styling lives

Substack is deliberately constrained. The GitHub Pages archive
(docs/issues/*.html) is fully ours, so the proper newspaper treatment
(masthead, column rules, small caps, dense front page) belongs there,
not in the email. Layout inspiration worth keeping:

- github.com/rotemweiss57/gpt-newspaper (agent pipeline with a
  dedicated layout/design step)
- github.com/j6k4m8/goosepaper (print-style daily, single column on
  narrow screens, multi-column on wide)
- github.com/emeliesidesio/newspaper-layout (responsive CSS newspaper
  layout exercise)

## Pictures, legally (added 2026-06-11 after layout approval)

The order of preference for images in an issue, safest first:

1. Make our own. The masthead banner and any stats cards come from
   Canva; charts come from Datawrapper fed with our own docs/data
   exports. Zero rights risk, and they carry the brand.
2. Company press kits. Many startups publish a press or brand assets
   page exactly so journalists can reuse logos and product shots, and
   funding announcements are usually distributed with images intended
   for coverage. Use those for featured companies, credit them
   ("image: company press kit"), and note the source URL in the brief.
   If a company has no press assets, it gets no image; the card layout
   already works without one.
3. Free-licence stock for the occasional hero image: Unsplash, Pexels,
   Pixabay. Their licences allow commercial use without attribution,
   though crediting the photographer is good practice. Avoid photos of
   identifiable people or trademarks in ways that could imply
   endorsement.
4. Wikimedia Commons for London imagery. Check the licence on each
   image; CC BY and CC BY-SA require naming the author and licence in
   the caption.

What we never do: lift photos from news outlets (wire and agency
photos are licensed to the outlet, not to us; UK fair dealing for
reporting current events explicitly excludes photographs, s.30(2)
CDPA 1988), grab images from search results, hotlink images from
company sites, or commit third-party images to this public repo.
Third-party images are added by the human at edit time, directly in
Substack, where the press-kit permission or licence covers the use.

Image selection stays a human editing step. The pipeline does not
fetch or attach images; judging whether a press kit covers a use is
exactly the kind of call rule 5 keeps with the human.

## Sources

- newsletteroperator.com/p/newsletter-design (structure, headers, TOC,
  brand emoji, 600px, boxes and dividers)
- reallygoodbusinessideas.com/p/substack-visuals (asset types, exact
  dimensions, Canva workflow)
- reallygoodbusinessideas.com/p/how-to-add-tables-to-substack and
  automato.substack.com/p/how-to-add-powerful-tables-and-graphs
  (Datawrapper as the table answer)
- nsokolsky.substack.com/p/how-to-insert-a-table-in-substack (no
  native tables, workaround comparison)
- blog.beehiiv.com/p/newsletter-headers (header and section title
  craft)
- on.substack.com/p/posting-consistently-formats-style (official notes
  on formats and templates)
- letters.byburk.net/p/the-best-substack-formatting-tips-2025
  (paywalled; headline advice matches the above)
