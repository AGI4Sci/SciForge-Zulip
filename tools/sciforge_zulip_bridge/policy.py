from dataclasses import dataclass

ROLE_ORDER: dict[str, int] = {
    "reviewer": 10,
    "scientist": 20,
    "pi": 30,
}


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str


class RolePolicy:
    def __init__(self, user_roles: dict[int, set[str]] | None = None) -> None:
        self.user_roles = user_roles or {}

    def authorize(self, *, user_id: int, required_role: str | None) -> AuthorizationDecision:
        if required_role is None:
            return AuthorizationDecision(allowed=True, reason="no role required")
        normalized_required_role = required_role.strip().lower()
        required_rank = ROLE_ORDER.get(normalized_required_role)
        if required_rank is None:
            return AuthorizationDecision(allowed=False, reason="unknown required role")
        actor_roles = self.user_roles.get(user_id, set())
        for role in actor_roles:
            rank = ROLE_ORDER.get(role.strip().lower())
            if rank is not None and rank >= required_rank:
                return AuthorizationDecision(allowed=True, reason=f"matched role {role}")
        return AuthorizationDecision(allowed=False, reason="actor lacks required role")

