"""Prompt for tailoring: rewrite a DOCX resume toward a JD in one pass."""

TAILOR_PROMPT = """You are an expert technical resume writer. Tailor the candidate's resume so it
reads as a strong, direct match for the job below. Work in ONE pass: there is
no review step and nobody will answer questions, so make every decision
yourself.

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

COVERAGE CHECK (computed from the resume text):
{coverage}

RESUME PARAGRAPHS (format: [index] (style) text). LOCKED paragraphs (usually
title/company/date lines) cannot change; use them to see which role each
bullet belongs to.
{paragraphs}
{instructions_block}
WHAT TO DO
1. Summary / profile paragraph: rewrite it for the target role, leading with
   the JD's must-have skills and the domain.
2. Skills / technical-skills lines: put the JD's must-have skills first and
   ADD the JD skills and tools the resume is missing to the matching line
   (languages with languages, cloud with cloud, and so on). Keep every skill
   already listed. Keep any bold lead-in such as "Languages:" exactly.
3. Experience bullets: rewrite bullets toward the JD's responsibilities, using
   the JD's own terms and tools where they fit the work the bullet describes.
4. Missing responsibilities: for every important JD responsibility or skill
   the resume does not cover, ADD new bullets under the most relevant roles,
   most recent roles first. Usually 2 to 4 new bullets per recent role, at
   most {max_additions} in total. Each new bullet must read like the role's
   existing bullets: concrete work (what was built, with what, for what),
   fitting that company's domain and the role's seniority.
   Use "after": the index of an existing EDITABLE bullet in that role; the new
   bullet is formatted like it and placed right after it.

NEVER CHANGE
- The candidate's name, contact details, company names, job titles, dates,
  locations, education, certifications, or section headings.
- Do not invent metrics: no new percentages, dollar amounts, user counts or
  other numbers that are not already in the resume.
- Do not put a technology in a role whose dates end before that technology
  existed (for example generative-AI frameworks before 2023).

STYLE
- Plain, specific verbs (built, designed, automated, migrated, developed,
  integrated, optimized). One idea per bullet, at most about 35 words.
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
  "additions": [
    {{"after": index of an editable bullet in the role, "text": "the new bullet", "keywords": ["JD terms covered"]}}
  ]
}}"""
