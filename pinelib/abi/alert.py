from __future__ import annotations

from pinelib.events import AlertEvent, SourceSpan
from pinelib.runtime.session import RuntimeTransaction


def alert_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    message: str,
    frequency: str = "once_per_bar",
) -> AlertEvent:
    return tx.alert(
        kind="alert",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={"message": message, "frequency": frequency},
    )


def alertcondition_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    condition: bool,
    title: str,
    message: str,
) -> AlertEvent | None:
    if not condition:
        return None
    return tx.alert(
        kind="alertcondition",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={"title": title, "message": message},
    )
