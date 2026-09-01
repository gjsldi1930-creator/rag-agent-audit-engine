"""
[Audit Engine] 법적/규정 보관 기간(Retention) 계산 엔진
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
행위 유형(action)별 법정 보관 기한과 만료 예정일을 산출한다 (기존 step03과 동일 로직, 독립 재구현).
"""

from datetime import datetime, timedelta, timezone

from .schema import AuditEvent

DEFAULT_POLICY = {
    "retention_days": 365,
    "category": "일반 감사 로그 (1년)",
    "legal_basis": "일반 보안 정책",
}


class AuditRetentionEngine:
    """보관 정책 설정 기반 보관 기간 계산 엔진"""

    def __init__(self, policy_config: dict = None):
        self.policy_config = policy_config or {}

    def calculate_retention(self, event: AuditEvent) -> dict:
        """이벤트의 행위(action)에 따른 법정 보관 기한 및 만료 예정일 산출"""
        policies = self.policy_config.get("policies", {})
        default_policy = self.policy_config.get("default_policy", DEFAULT_POLICY)
        policy = policies.get(event.action, default_policy)

        ts_clean = event.timestamp.replace("Z", "+00:00")
        try:
            event_dt = datetime.fromisoformat(ts_clean)
        except ValueError:
            event_dt = datetime.now(timezone.utc)

        retention_days = policy["retention_days"]
        retention_until_dt = event_dt + timedelta(days=retention_days)

        return {
            "action": event.action,
            "actor": event.actor,
            "retention_days": retention_days,
            "retention_until": retention_until_dt.strftime("%Y-%m-%d"),
            "category": policy["category"],
            "legal_basis": policy["legal_basis"],
        }
