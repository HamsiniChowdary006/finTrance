from schemas.models import CompanyProfile, CompanyType


def profile_company(name: str, *, signals: list[str] | None = None) -> CompanyProfile:
    """Return a conservative profile; exchange resolution is intentionally not guessed."""
    observed = signals or []
    joined = " ".join(observed).casefold()
    if "banking licence" in joined or "scheduled commercial bank" in joined:
        kind, confidence = CompanyType.BANK, 0.7
    elif "rbi-registered nbfc" in joined:
        kind, confidence = CompanyType.NBFC, 0.7
    else:
        kind, confidence = CompanyType.OTHER_FIN, 0.2
    return CompanyProfile(name=name, company_type=kind, confidence=confidence, signals=observed)
