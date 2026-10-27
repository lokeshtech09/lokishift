"""Prompt for matching: rank the resume versions in a profile against a JD."""

RANK_BASES_PROMPT = """You are a senior technical recruiter screening one candidate who keeps several
versions of their resume. Decide which version is the best STARTING POINT for the
job below: the one whose real experience, skills and focus already fit the role
best, so it needs the fewest and smallest changes.

Judge substance (relevant experience, domain, seniority, required skills), not
wording or formatting. Every score must be justified by evidence in that resume.

JOB DESCRIPTION (benefits and company boilerplate already removed):
<<<
{job_description}
>>>

WHAT THE JD PRIORITISES (extracted from its sections, most important first):
{priorities}

Weight must-have skills far above nice-to-have ones. A version that covers the
must-haves beats one that only covers extras.

RESUME VERSIONS:
{resumes}

Return JSON exactly in this shape:
{{
  "company": "hiring company name from the JD, or empty string",
  "role": "job title from the JD, or empty string",
  "must_have_skills": ["up to 12 hard requirements from the JD"],
  "rankings": [
    {{
      "base_id": "id of the resume version, copied exactly",
      "score": 0-100 integer fit score,
      "strengths": ["up to 4 short phrases: what already matches"],
      "gaps": ["up to 4 short phrases: what the JD wants that this version lacks"],
      "reasoning": "one or two sentences"
    }}
  ],
  "recommended_base_id": "id of the best version"
}}

Include every resume version exactly once in "rankings", best first."""
