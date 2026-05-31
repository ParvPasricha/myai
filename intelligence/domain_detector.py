"""
Domain Detector — Phase 10.

Classifies text into a work domain using keyword scoring.
Fast, zero-LLM-call, runs synchronously.

Domains: code, physics, maths, business, editing, personal, general
"""
import re

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "code": [
        "function", "class", "algorithm", "api", "database", "python",
        "javascript", "typescript", "swift", "fastapi", "async", "await",
        "import", "bug", "error", "debug", "test", "deploy", "endpoint",
        "request", "response", "array", "dict", "loop", "variable",
        "compile", "runtime", "module", "git", "docker", "server",
        "frontend", "backend", "route", "middleware", "schema", "query",
    ],
    "physics": [
        "force", "energy", "momentum", "quantum", "relativity", "wave",
        "particle", "field", "gravity", "mass", "velocity", "acceleration",
        "entropy", "thermodynamics", "electric", "magnetic", "photon",
        "electron", "nucleus", "orbit", "spin", "optics", "laser",
    ],
    "maths": [
        "integral", "derivative", "matrix", "proof", "theorem", "equation",
        "calculus", "vector", "eigenvalue", "probability", "statistics",
        "polynomial", "limit", "series", "topology", "algebra", "geometry",
        "differential", "gradient", "divergence", "fourier", "laplace",
    ],
    "business": [
        "revenue", "market", "strategy", "customer", "product", "growth",
        "startup", "investor", "profit", "loss", "marketing", "sales",
        "funnel", "conversion", "kpi", "metric", "roi", "b2b", "b2c",
        "saas", "pricing", "competition", "equity", "valuation", "pitch",
    ],
    "editing": [
        "write", "edit", "draft", "sentence", "paragraph", "grammar",
        "style", "essay", "article", "blog", "tone", "voice", "audience",
        "clarity", "rewrite", "proofread", "summarize", "outline",
        "narrative", "publish", "content", "copy",
    ],
    "personal": [
        "habit", "goal", "feeling", "health", "exercise", "sleep", "mood",
        "motivation", "productivity", "focus", "anxiety", "stress",
        "relationship", "schedule", "routine", "mindset", "discipline",
        "journal", "reminder", "today", "tomorrow",
    ],
}

# Exemplar sentences for each domain (used for tie-breaking or calibration)
DOMAIN_EXEMPLARS: dict[str, str] = {
    "code": "Write a Python function that queries a REST API and parses JSON.",
    "physics": "Calculate the force on a particle in a magnetic field at relativistic speed.",
    "maths": "Prove that the integral of a Gaussian distribution over all reals equals one.",
    "business": "What is our customer acquisition cost and how does it affect runway?",
    "editing": "Rewrite this paragraph to improve clarity and reduce passive voice.",
    "personal": "I want to build a habit of waking up early and exercising every morning.",
}


def detect(text: str) -> str:
    """Return the most likely domain for the given text."""
    scores = _score(text)
    if max(scores.values()) == 0:
        return "general"
    return max(scores, key=lambda d: scores[d])


def detect_from_messages(messages: list[dict]) -> str:
    """Detect domain from a list of {role, content} dicts."""
    combined = " ".join(
        m.get("content", "") for m in messages if m.get("role") == "user"
    )
    return detect(combined)


def domain_weights(text: str) -> dict[str, float]:
    """Return normalised domain scores (0.0–1.0)."""
    scores = _score(text)
    total = sum(scores.values()) or 1.0
    return {d: round(s / total, 3) for d, s in scores.items()}


def _score(text: str) -> dict[str, int]:
    text_lower = text.lower()
    scores: dict[str, int] = {domain: 0 for domain in DOMAIN_KEYWORDS}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if " " in kw:
                scores[domain] += text_lower.count(kw)
            else:
                scores[domain] += len(
                    re.findall(r"\b" + re.escape(kw) + r"\b", text_lower)
                )
    return scores
