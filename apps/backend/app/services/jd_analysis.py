"""Deterministic job-description analysis for JD Studio.

Small models struggle to tell a hard requirement from a benefits paragraph in a
long JD. This module does that part in plain Python before any LLM call:

1. Split the JD into sections by their headings and weight each section
   (requirements > responsibilities > nice-to-have; benefits/EEO/about-us are
   dropped entirely).
2. Find skills with a curated tech vocabulary (with aliases such as
   ``k8s`` → ``kubernetes``), plus generic frequent terms as a fallback.
3. Score every term by where and how often it appears, so prompts and match
   scores focus on what the employer actually requires.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field

# canonical skill -> extra spellings. The canonical name is always matched too.
SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    # languages
    "python": (),
    "java": (),
    "javascript": ("js", "ecmascript"),
    "typescript": (),
    "go": ("golang",),
    "rust": (),
    "c++": ("cpp",),
    "c#": ("csharp", ".net c#"),
    "scala": (),
    "kotlin": (),
    "swift": (),
    "ruby": (),
    "php": (),
    "r": (),
    "sql": (),
    "bash": ("shell scripting", "shell"),
    "powershell": (),
    # data
    "postgresql": ("postgres",),
    "mysql": (),
    "mongodb": ("mongo",),
    "redis": (),
    "cassandra": (),
    "dynamodb": (),
    "elasticsearch": ("elastic search", "opensearch"),
    "snowflake": (),
    "bigquery": ("big query",),
    "redshift": (),
    "databricks": (),
    "spark": ("apache spark", "pyspark"),
    "hadoop": (),
    "hive": (),
    "kafka": ("apache kafka",),
    "flink": ("apache flink",),
    "airflow": ("apache airflow",),
    "dbt": (),
    "etl": ("elt", "etl/elt"),
    "data warehouse": ("data warehousing",),
    "data lake": ("lakehouse",),
    "data modeling": ("data modelling",),
    "data quality": (),
    "data pipelines": ("data pipeline",),
    "pandas": (),
    "numpy": (),
    "tableau": (),
    "power bi": ("powerbi",),
    "looker": (),
    # cloud / infra
    "aws": ("amazon web services",),
    "azure": ("microsoft azure",),
    "gcp": ("google cloud", "google cloud platform"),
    "ec2": (),
    "s3": (),
    "lambda": ("aws lambda",),
    "eks": (),
    "ecs": (),
    "cloudformation": (),
    "docker": ("containers", "containerization"),
    "kubernetes": ("k8s",),
    "helm": (),
    "terraform": (),
    "ansible": (),
    "puppet": (),
    "chef": (),
    "jenkins": (),
    "github actions": (),
    "gitlab ci": ("gitlab",),
    "argo cd": ("argocd",),
    "ci/cd": ("cicd", "ci cd", "continuous integration", "continuous delivery", "continuous deployment"),
    "linux": ("unix",),
    "nginx": (),
    "prometheus": (),
    "grafana": (),
    "datadog": (),
    "splunk": (),
    "elk": ("elk stack",),
    "observability": ("monitoring",),
    "infrastructure as code": ("iac",),
    "sre": ("site reliability",),
    "networking": ("tcp/ip", "dns"),
    "security": ("devsecops",),
    "microservices": ("microservice",),
    "serverless": (),
    "distributed systems": (),
    # web / apps
    "react": ("react.js", "reactjs"),
    "angular": (),
    "vue": ("vue.js", "vuejs"),
    "next.js": ("nextjs",),
    "node.js": ("nodejs",),
    "django": (),
    "flask": (),
    "fastapi": (),
    "spring": ("spring boot",),
    "rest api": ("rest apis", "restful", "rest-based", "rest services"),
    "graphql": (),
    "grpc": (),
    "html": (),
    "css": ("tailwind",),
    # ml / ai
    "machine learning": ("ml",),
    "deep learning": (),
    "llm": ("llms", "large language models", "genai", "generative ai"),
    "nlp": ("natural language processing",),
    "computer vision": (),
    "pytorch": (),
    "tensorflow": (),
    "scikit-learn": ("sklearn",),
    "mlops": (),
    "sagemaker": (),
    "rag": ("retrieval augmented generation",),
    # practice
    "agile": ("scrum", "kanban"),
    "git": (),
    "testing": ("unit testing", "tdd"),
    "system design": (),
    "api design": (),
}

# General practices rather than concrete tools. Useful for JD matching, but a
# rewrite mentioning them is not a new factual claim, so the truth guard skips
# them ("streaming pipelines" -> "data pipelines" is rephrasing, not invention).
CONCEPT_SKILLS: frozenset[str] = frozenset(
    {
        "data pipelines",
        "data quality",
        "data modeling",
        "data warehouse",
        "data lake",
        "etl",
        "observability",
        "security",
        "networking",
        "testing",
        "agile",
        "system design",
        "api design",
        "distributed systems",
        "microservices",
        "serverless",
        "infrastructure as code",
        "ci/cd",
    }
)

# Heading keyword -> section weight. Checked in order; first match wins.
_SECTION_RULES: tuple[tuple[str, float], ...] = (
    (r"benefit|perk|we offer|compensation|salary|pay range|equal opportunit|eeo|"
     r"accommodation|about (us|the company)|who we are|our (mission|values|culture)|"
     r"why join|life at", 0.0),
    (r"nice to have|preferred|bonus|plus|desired|good to have|nice-to-have", 1.0),
    (r"require|qualification|must|what you.?ll (need|bring)|you (have|bring)|"
     r"skills|experience|who you are|minimum|basic", 3.0),
    (r"responsib|what you.?ll do|the role|your role|day to day|duties|you will", 2.0),
)
_DEFAULT_WEIGHT = 1.5
_BOILERPLATE_LINE = re.compile(
    r"equal opportunity|without regard to|reasonable accommodation|e-verify|"
    r"visa sponsorship|401\(k\)|paid time off|health insurance",
    re.IGNORECASE,
)
_REQUIRED_CUE = re.compile(r"\b(required|must|minimum|strong|expert|proficien\w*|\d+\+? years)\b", re.I)
_OPTIONAL_CUE = re.compile(r"\b(preferred|nice to have|bonus|plus|familiarity|exposure)\b", re.I)
_YEARS = re.compile(r"(\d+)\+?\s*(?:-\s*\d+\s*)?years?", re.IGNORECASE)

_STOPWORDS = frozenset(
    """
    a about above across after again against all also am an and any are as at be
    because been before being below between both but by can could did do does doing
    down during each either etc few for from further had has have having he her here
    how i if in into is it its just least less like may me might more most must my
    no nor not now of off on once only or other our out over own per same she should
    so some such than that the their them then there these they this those through
    to too under until up upon us very via was we were what when where whether which
    while who whom why will with within without would you your ability able strong
    excellent good great preferred required requirements responsibilities role team
    teams work working experience years year plus including include includes using
    use used new skills skill knowledge understanding candidate candidates job
    position company opportunity looking seeking join help ensure build building
    develop developing support supporting provide well based related relevant
    equivalent degree bachelor bachelors master masters minimum one two three four
    five multiple various day days environment nice have bonus solutions solution
    across business customers customer products product closely cross functional
    data hands-on hands partner partners analysts own owning fast growing world
    impact high quality end best practices tools systems platform platforms
    """.split()
)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.\-/]*[a-z0-9+#]|[a-z0-9]")


def _alias_pattern(term: str) -> re.Pattern[str]:
    # Word boundaries that also work for terms like "c++", "c#", "ci/cd", ".net".
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9+#])", re.IGNORECASE)


_SKILL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    skill: [_alias_pattern(t) for t in (skill, *aliases)]
    for skill, aliases in SKILL_ALIASES.items()
}
# Single letters / very short aliases are too ambiguous in prose ("R", "go", "ts").
_CASE_SENSITIVE_SHORT = {"r": re.compile(r"(?<![A-Za-z])R(?![A-Za-z])"),
                         "go": re.compile(r"\bGo\b(?!\s+(?:to|through|live|beyond))")}


@dataclass
class JDAnalysis:
    """Result of analysing one JD."""

    cleaned_text: str
    weights: dict[str, float] = field(default_factory=dict)  # term -> importance
    must_have: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    years_required: int | None = None

    @property
    def ranked_terms(self) -> list[str]:
        return sorted(self.weights, key=lambda t: -self.weights[t])


def find_skills(text: str) -> set[str]:
    """Canonical skills mentioned in ``text`` (aliases resolved)."""
    found: set[str] = set()
    for skill, patterns in _SKILL_PATTERNS.items():
        special = _CASE_SENSITIVE_SHORT.get(skill)
        if special is not None:
            # The bare name is ambiguous; longer aliases ("golang") are not.
            if special.search(text) or any(p.search(text) for p in patterns[1:]):
                found.add(skill)
            continue
        if any(p.search(text) for p in patterns):
            found.add(skill)
    return found


def _is_heading(line: str) -> bool:
    stripped = line.strip().strip("*#").strip()
    if not stripped or len(stripped) > 70 or re.match(r"^([-•·*▪●◦]|\d+[.)])\s", stripped):
        return False
    if stripped.endswith(":"):
        return True
    if len(stripped.split()) > 7 or stripped.endswith("."):
        return False
    lower = stripped.lower()
    return stripped.isupper() or any(re.search(p, lower) for p, _ in _SECTION_RULES)


def _section_weight(heading: str) -> float:
    lower = heading.lower()
    for pattern, weight in _SECTION_RULES:
        if re.search(pattern, lower):
            return weight
    return _DEFAULT_WEIGHT


def _split_sections(jd: str) -> list[tuple[float, str]]:
    sections: list[tuple[float, list[str]]] = [(_DEFAULT_WEIGHT, [])]
    for line in jd.splitlines():
        if _is_heading(line):
            sections.append((_section_weight(line), []))
            continue
        sections[-1][1].append(line)
    return [(w, "\n".join(lines)) for w, lines in sections if any(l.strip() for l in lines)]


def _line_weight(line: str, section_weight: float) -> float:
    weight = section_weight
    if _REQUIRED_CUE.search(line):
        weight += 1.0
    if _OPTIONAL_CUE.search(line):
        weight = min(weight, 1.0)
    return weight


def analyze_jd(job_description: str, generic_limit: int = 15) -> JDAnalysis:
    """Weight JD skills by section and wording; strip boilerplate."""
    kept_lines: list[str] = []
    skill_scores: dict[str, float] = defaultdict(float)
    skill_max_line: dict[str, float] = defaultdict(float)
    generic_scores: dict[str, float] = defaultdict(float)

    for section_weight, body in _split_sections(job_description):
        if section_weight == 0.0:
            continue  # benefits / EEO / about-us: not requirements
        for line in body.splitlines():
            if not line.strip() or _BOILERPLATE_LINE.search(line):
                continue
            kept_lines.append(line)
            weight = _line_weight(line, section_weight)
            for skill in find_skills(line):
                skill_scores[skill] += weight
                skill_max_line[skill] = max(skill_max_line[skill], weight)
            for token in _TOKEN.findall(line.lower()):
                if token not in _STOPWORDS and len(token) > 2 and not token.isdigit():
                    generic_scores[token] += weight

    # Generic terms only add what the skill vocabulary missed (domain words,
    # uncommon tools). Tokens already covered by a skill or alias are skipped.
    covered = {
        word
        for s in skill_scores
        for phrase in (s, *SKILL_ALIASES.get(s, ()))
        for word in phrase.split()
    }
    generic = [
        (t, s) for t, s in sorted(generic_scores.items(), key=lambda kv: -kv[1])
        if t not in covered and s >= 2.0
    ][:generic_limit]

    weights = {s: round(v, 2) for s, v in skill_scores.items()}
    for term, score in generic:
        weights[term] = round(score * 0.5, 2)  # generic words matter less than skills

    must = sorted((s for s in skill_scores if skill_max_line[s] >= 3.0), key=lambda s: -weights[s])
    nice = sorted((s for s in skill_scores if skill_max_line[s] < 3.0), key=lambda s: -weights[s])
    years = [int(m.group(1)) for m in _YEARS.finditer("\n".join(kept_lines)) if int(m.group(1)) < 30]

    cleaned = "\n".join(kept_lines).strip() or job_description.strip()
    return JDAnalysis(
        cleaned_text=cleaned,
        weights=weights,
        must_have=must[:15],
        nice_to_have=nice[:10],
        years_required=max(years) if years else None,
    )


def term_in_text(term: str, text: str) -> bool:
    """Whether ``text`` mentions ``term`` (skills match any alias)."""
    if term in _SKILL_PATTERNS:
        return term in find_skills(text)
    return bool(_alias_pattern(term).search(text))


def weighted_match(analysis: JDAnalysis, text: str) -> dict[str, object]:
    """Importance-weighted coverage of the JD's terms by ``text`` (0–100)."""
    if not analysis.weights:
        return {"score": 0, "matched": [], "missing": []}
    resume_skills = find_skills(text)
    matched: list[str] = []
    missing: list[str] = []
    for term in analysis.ranked_terms:
        hit = term in resume_skills if term in _SKILL_PATTERNS else term_in_text(term, text)
        (matched if hit else missing).append(term)
    total = sum(analysis.weights.values())
    got = sum(analysis.weights[t] for t in matched)
    return {"score": round(100 * got / total) if total else 0, "matched": matched, "missing": missing}
