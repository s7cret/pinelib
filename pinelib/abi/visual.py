from __future__ import annotations

from pinelib.events import SourceSpan, VisualEvent
from pinelib.reference import ReferenceHandle
from pinelib.runtime.session import RuntimeTransaction


def plot_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    series: object,
    title: str = "",
    color: object = None,
    linewidth: int = 1,
    style: str = "line",
    offset: int = 0,
    display: str = "all",
) -> VisualEvent:
    return tx.visual(
        kind="plot",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={
            "series": series,
            "title": title,
            "color": color,
            "linewidth": linewidth,
            "style": style,
            "offset": offset,
            "display": display,
        },
    )


def plotshape_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    series: object,
    title: str = "",
    style: str = "shape",
    location: str = "abovebar",
    color: object = None,
    text: str = "",
) -> VisualEvent:
    return tx.visual(
        kind="plotshape",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={
            "series": series,
            "title": title,
            "style": style,
            "location": location,
            "color": color,
            "text": text,
        },
    )


def plotchar_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    series: object,
    title: str = "",
    character: str = "*",
    location: str = "abovebar",
    color: object = None,
) -> VisualEvent:
    return tx.visual(
        kind="plotchar",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={
            "series": series,
            "title": title,
            "character": character,
            "location": location,
            "color": color,
        },
    )


def bgcolor_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    color: object,
    offset: int = 0,
    editable: bool = True,
    show_last: int | None = None,
    title: str = "",
) -> VisualEvent:
    return tx.visual(
        kind="bgcolor",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={
            "color": color,
            "offset": offset,
            "editable": editable,
            "show_last": show_last,
            "title": title,
        },
    )


def barcolor_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    color: object,
    offset: int = 0,
    editable: bool = True,
    show_last: int | None = None,
    title: str = "",
) -> VisualEvent:
    return tx.visual(
        kind="barcolor",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={
            "color": color,
            "offset": offset,
            "editable": editable,
            "show_last": show_last,
            "title": title,
        },
    )


def hline_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    price: object,
    title: str = "",
    color: object = None,
    linestyle: str = "solid",
    linewidth: int = 1,
) -> VisualEvent:
    return tx.visual(
        kind="hline",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={
            "price": price,
            "title": title,
            "color": color,
            "linestyle": linestyle,
            "linewidth": linewidth,
        },
    )


def fill_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    first_id: str,
    second_id: str,
    color: object = None,
    title: str = "",
    show_last: int | None = None,
    fillgaps: bool = True,
) -> VisualEvent:
    return tx.visual(
        kind="fill",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={
            "first_id": first_id,
            "second_id": second_id,
            "color": color,
            "title": title,
            "show_last": show_last,
            "fillgaps": fillgaps,
        },
    )


def line_new_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    object_id: str,
    x1: object,
    y1: object,
    x2: object,
    y2: object,
    xloc: str = "bar_index",
    extend: str = "none",
    color: object = None,
    style: str = "solid",
    width: int = 1,
) -> ReferenceHandle:
    handle = tx.references.create(
        object_id,
        "visual",
        "line",
        {
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "xloc": xloc,
            "extend": extend,
            "color": color,
            "style": style,
            "width": width,
        },
    )
    tx.visual(
        kind="line.new",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={"object": handle, "state": tx.references.read_payload(handle)},
    )
    return handle


def line_set_xy1_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    handle: ReferenceHandle,
    x: object,
    y: object,
) -> VisualEvent:
    payload = tx.references.read_payload(handle)
    assert isinstance(payload, dict)
    payload.update(x1=x, y1=y)
    tx.references.mutate_payload(handle, payload)
    return tx.visual(
        kind="line.set_xy1",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={"object": handle, "x": x, "y": y},
    )


def line_set_xy2_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    handle: ReferenceHandle,
    x: object,
    y: object,
) -> VisualEvent:
    payload = tx.references.read_payload(handle)
    assert isinstance(payload, dict)
    payload.update(x2=x, y2=y)
    tx.references.mutate_payload(handle, payload)
    return tx.visual(
        kind="line.set_xy2",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={"object": handle, "x": x, "y": y},
    )


def line_delete_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    handle: ReferenceHandle,
) -> VisualEvent:
    return tx.visual(
        kind="line.delete",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={"object": handle},
    )


def label_new_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    object_id: str,
    x: object,
    y: object,
    text: str = "",
    xloc: str = "bar_index",
    yloc: str = "price",
    color: object = None,
    style: str = "label",
    textcolor: object = None,
    size: str = "normal",
) -> ReferenceHandle:
    handle = tx.references.create(
        object_id,
        "visual",
        "label",
        {
            "x": x,
            "y": y,
            "text": text,
            "xloc": xloc,
            "yloc": yloc,
            "color": color,
            "style": style,
            "textcolor": textcolor,
            "size": size,
        },
    )
    tx.visual(
        kind="label.new",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={"object": handle, "state": tx.references.read_payload(handle)},
    )
    return handle


def label_set_text_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    handle: ReferenceHandle,
    text: str,
) -> VisualEvent:
    payload = tx.references.read_payload(handle)
    assert isinstance(payload, dict)
    payload["text"] = text
    tx.references.mutate_payload(handle, payload)
    return tx.visual(
        kind="label.set_text",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={"object": handle, "text": text},
    )


def label_delete_v1(
    tx: RuntimeTransaction,
    call_site_id: str,
    source_span: SourceSpan,
    handle: ReferenceHandle,
) -> VisualEvent:
    return tx.visual(
        kind="label.delete",
        call_site_id=call_site_id,
        source_span=source_span,
        payload={"object": handle},
    )
