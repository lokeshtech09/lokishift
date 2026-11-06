"""Prompts for tailoring: rewrite a DOCX resume toward a JD without making it longer."""

TAILOR_PROMPT = """You are an expert technical resume writer. Tailor the candidate's resume so it
reads as a strong, direct match for the job below and passes an ATS keyword
screen. Work in ONE pass: there is no review step and nobody will answer
questions, so make every decision yourself.

The resume is a Word document shown as numbered paragraphs. Your text is
written straight back into the original document, so formatting (fonts,
bullets, spacing) is preserved automatically.

TARGET ROLE: {job_title}
DOMAIN: {domain}

JOB DESCRIPTION (benefits and company boilerplate already removed):
<<<
{job_description}
>>>

WHAT THE JD PRIORITISES (most important first):
{priorities}

KEY SKILLS (each one MUST appear in the bullets of ROLE 1, ROLE 2 or ROLE 3):
{key_skills}

ATS TERMS THE RESUME IS MISSING (weighted by importance, most important first):
{missing_terms}

{requests_block}
RESUME PARAGRAPHS
Format: [index] (style | ROLE n | current chars, max chars) text
LOCKED paragraphs (title/company/date lines, headings, contact) cannot change.
ROLE 1 is the most recent client, ROLE 2 the one before, and so on.
{paragraphs}
{instructions_block}
THE LENGTH RULE (most important)
The tailored resume must be the SAME LENGTH as the original: the same number
of bullets and no more text. Every rewrite must stay within its "max chars".
To fit new terms, replace weaker words, drop filler and merge ideas; do not
just append.

WHAT TO DO
1. Summary / profile paragraph: rewrite it for the target role, leading with
   the JD's key skills and the domain. Same length.
2. Skills lines: put the key skills first and work in the missing JD skills
   and tools on the matching line (languages with languages, cloud with
   cloud). Keep any bold lead-in such as "Languages:" exactly. You may drop
   listed skills that have nothing to do with this JD to make room.
3. Experience bullets of ROLE 1, ROLE 2 and ROLE 3: rewrite the existing bullets
   so that EVERY key skill appears in at least one of them, spread across the
   three roles, using the JD's own terms where they fit the work the bullet
   describes. Most recent role first.
4. Swaps (optional, at most one per role, ROLE 1 to ROLE 3 only): if a JD
   responsibility cannot be worked into any existing bullet, replace the
   role's least relevant bullet with a new one. Give "remove": the index of
   the bullet to delete, "after": the same index (the new bullet takes its
   place) or another bullet in the SAME role to place it after, and "text": the
   new bullet, no longer than the removed bullet. The new bullet must read like the role's other bullets:
   concrete work (what was built, with what, for what).
5. Use as many of the ATS TERMS as fit naturally across the whole resume; the
   goal is that at least 95% of them (by weight) appear.
6. CANDIDATE'S REQUESTS (if listed above) come first, are not optional, and
   override steps 1 to 5 and the one-swap-per-role limit:
   - "add": exactly that many new bullets about the skill in each named role,
     as swaps with "request": the request number. Each replaces a different
     one of that role's least relevant bullets ("after" = the same index), so
     the bullet count stays the same. Each must name the skill and describe
     concrete work that fits that role.
   - "rewrite": rewrite exactly that many EXISTING bullets of each named role
     so each one mentions the skill; give these edits "request": the request
     number.
   - "remove": list the bullets to delete in "removals" with "request": the
     request number.

NEVER CHANGE
- The candidate's name, contact details, company names, job titles, dates,
  locations, education, certifications, or section headings.
- Do not invent metrics: no new percentages, dollar amounts, user counts or
  other numbers that are not already in the resume.
- Do not put a technology in a role whose dates end before that technology
  existed (for example generative-AI frameworks before 2023).

STYLE
- Plain, specific verbs (built, designed, automated, migrated, developed,
  integrated, optimized). One idea per bullet.
- Never use these words: {avoid_words}. No hype ("passionate",
  "results-driven", "proven track record"). No first-person pronouns.
- Match each role's tense (past for past roles). One paragraph per item, no
  newlines.
- Only include paragraphs you actually change.

Return JSON exactly in this shape:
{{
  "summary": "two sentences on what you changed and why",
  "edits": [
    {{"index": paragraph index, "new_text": "full replacement text", "keywords": ["JD terms surfaced"]}}
  ],
  "swaps": [
    {{"remove": index of the weakest bullet, "after": index of a bullet in the same role, "text": "the new bullet", "keywords": ["JD terms covered"], "request": request number or null}}
  ],
  "removals": [
    {{"index": paragraph index of a bullet to delete, "request": request number}}
  ]
}}
(Edits may also carry "request": request number when they fulfil a "rewrite" request.)"""


REPAIR_PROMPT = """You are an expert technical resume writer finishing a tailored resume.
It is not done yet: {problems}

TARGET ROLE: {job_title}

STILL MISSING (work these in; most important first):
{missing_terms}

KEY SKILLS NOT YET IN THE BULLETS OF ROLE 1 TO 3 (each must appear in one of them):
{missing_key_skills}

CANDIDATE'S REQUESTS STILL NOT DONE (these come first):
{open_requests}

CURRENT RESUME PARAGRAPHS
Format: [index] (style | ROLE n | current chars, max chars) text
LOCKED paragraphs cannot change. ROLE 1 is the most recent client.
{paragraphs}

RULES
- Rewrite only the paragraphs you need. Each one must stay within its "max
  chars": replace weaker words and filler instead of appending. The resume as a
  whole must not get longer.
- Put KEY SKILLS into bullets of ROLE 1, ROLE 2 or ROLE 3, where they fit the
  work the bullet describes. Put other missing terms in the summary, a skills
  line or any bullet where they fit.
- Keep every JD term that is already present. Keep bold lead-ins such as
  "Languages:" exactly.
- Do every open candidate request. "add": new bullets as swaps: "remove" =
  one of the role's least relevant original bullets, "after" = the same index
  (the new bullet takes its place), "text" = the new bullet, which must mention
  the skill by name, "request" = the request number. "rewrite": edits of
  existing bullets in that role that mention the skill, with "request".
  "remove": "removals" with the bullet index and "request".
- Never change names, contact details, companies, titles, dates or headings.
  No new numbers or metrics. Never use: {avoid_words}.

Return JSON exactly in this shape:
{{
  "edits": [
    {{"index": paragraph index, "new_text": "full replacement text", "keywords": ["terms added"]}}
  ],
  "swaps": [
    {{"remove": index, "after": same index, "text": "the new bullet", "keywords": ["skill"], "request": request number}}
  ],
  "removals": [
    {{"index": paragraph index, "request": request number}}
  ]
}}"""


REQUESTS_PROMPT = """Read the candidate's instructions for tailoring their resume and list every
explicit request about the BULLET POINTS of particular roles (clients).

THE CANDIDATE'S ROLES (ROLE 1 is the most recent client):
{roles}

THE CANDIDATE'S INSTRUCTIONS:
<<<
{instructions}
>>>

Each request has an "action":
- "add": new bullets about a skill or topic ("add 5 points on Kafka in Delta
  Bank", "need 3 bullets for Snowflake in client 2", "replace 4 points with
  Azure work in client 1"). Each new bullet replaces one of that role's weakest
  bullets, so "add" and "replace with" are the same thing.
- "rewrite": change EXISTING bullets so they mention a skill or topic ("modify
  all points in client 2 to mention Azure", "change 3 bullets in Orion to focus
  on data quality").
- "remove": delete bullets ("remove the Excel points from Old Mutual", "drop 2
  points from client 4"). "skill" is the topic of the bullets to remove, or ""
  if any bullets will do.

Rules
- "count" is the number of bullets PER ROLE. "3 points on Kafka in Delta Bank
  and Orion" means 3 in each. If they clearly say "in total" or "across", split
  the total as evenly as possible, most recent role first, and give each role
  its own request. Use "all" for "all points", "every bullet", "whole role".
  There is no upper limit: copy the number the candidate gave.
- No number given means 2 for "add" and "rewrite", and "all" for "remove"
  with a topic ("remove the Excel points").
- Roles may be named by company or client name ("Delta Bank"), by position
  ("client 2", "second client", "most recent", "last two clients", "first 3
  clients", "all clients"), or by job title. Map them to ROLE numbers from the
  list above. "Last/latest/current/recent client" means ROLE 1. No role given
  means ROLE 1.
- Instructions that are not about bullets of a role (the summary, the skills
  section, the tone) are not requests here; leave them out.
- If there are no such requests, return an empty list.

Return JSON exactly in this shape:
{{"requests": [{{"action": "add", "skill": "Kafka", "count": 3, "roles": [1, 2]}}]}}"""
