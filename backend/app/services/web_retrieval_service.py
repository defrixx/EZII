class WebRetrievalService:
    @classmethod
    def _is_allowed_redirect_domain(cls, requested: str, final_domain: str) -> bool:
        req = requested.strip().lower()
        final = final_domain.strip().lower()
        return final == req or final.endswith(f".{req}")
