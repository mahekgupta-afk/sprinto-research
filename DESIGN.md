# Design brief: Swiss editorial

**Direction.** White paper, black ink, one red accent, strict 12-column grid, grotesk type (Helvetica Neue with system fallbacks, self-hosted by definition: no font files are fetched, so the CSP stays `default-src 'self'`). **Light theme**: used at a desk in daylight offices while reviewing a list; print-like contrast suits long reading. **Motion: calm**: sections fade up once, bars grow once, nothing loops.
**Craft bar.** Linear's changelog restraint, the Financial Times's chart labelling, Experimental Jetset's grid discipline.

**Rules applied.**
- Red is reserved for meaning: the 60-point qualify line, overturned verdicts, things that need the user. It is never decoration.
- One idea per section: a claim headline on the left four columns, the evidence drawn on the right eight.
- Charts are drawn to scale from the data (bar length = value / axis maximum; score ranges on a fixed 0 to 100 axis; reviewer scores on 0 to 10). Every number names what it is and what it is compared to.
- No cards-everywhere: hairline rules, tables and ledgers; a card appears only on the pipeline board where cards are the thing.
- Accessibility: ink 18.9:1, muted text 8.9:1 and the red 5.9:1 on white; visible 3px focus ring; drawer traps focus, Esc closes, focus returns; `prefers-reduced-motion` removes all transitions; checked at 1440x900 and 390 wide with no sideways scroll.
- Security: scraped text is rendered with `textContent` only; `style-src 'self'` means zero inline style attributes.
- Avoided: purple gradients, neon on black, emoji icons, identical rounded cards, eyebrow labels above every heading, cream + serif + terracotta.
