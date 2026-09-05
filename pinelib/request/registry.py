from __future__ import annotations

from dataclasses import dataclass

from pinelib.errors import (
    PL_REQUEST_CACHE,
    PL_REQUEST_IDENTITY,
    PL_REQUEST_REVISION,
    PL_RESOURCE_LIMIT,
    PineRuntimeError,
)
from pinelib.request.models import (
    DataFinality,
    RequestDataset,
    RequestKind,
    RequestQuery,
    ResultShape,
    SnapshotMode,
)
from pinelib.state.checkpoint import canonical_json, is_canonical_sha256, sha


@dataclass(frozen=True, slots=True)
class MergeCursor:
    operation: str
    dataset_key_hash: str
    chart_open_ms: int
    chart_close_ms: int
    selected_start: int
    selected_end: int

    def __post_init__(self) -> None:
        if self.operation not in {"security", "security_lower_tf"}:
            raise PineRuntimeError(
                "unknown request cursor operation", code=PL_REQUEST_CACHE
            )
        if not is_canonical_sha256(self.dataset_key_hash):
            raise PineRuntimeError(
                "cursor dataset identity is invalid", code=PL_REQUEST_IDENTITY
            )
        if (
            type(self.chart_open_ms) is not int
            or type(self.chart_close_ms) is not int
            or self.chart_close_ms <= self.chart_open_ms
        ):
            raise PineRuntimeError(
                "cursor chart boundaries are invalid", code=PL_REQUEST_CACHE
            )
        if (
            type(self.selected_start) is not int
            or type(self.selected_end) is not int
            or self.selected_start < -1
            or self.selected_end < -1
            or self.selected_end < self.selected_start
        ):
            raise PineRuntimeError("cursor indexes are invalid", code=PL_REQUEST_CACHE)

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "dataset_key_hash": self.dataset_key_hash,
            "chart_open_ms": self.chart_open_ms,
            "chart_close_ms": self.chart_close_ms,
            "selected_start": self.selected_start,
            "selected_end": self.selected_end,
        }

    @classmethod
    def from_dict(cls, data: object) -> MergeCursor:
        if not isinstance(data, dict) or set(data) != {
            "operation",
            "dataset_key_hash",
            "chart_open_ms",
            "chart_close_ms",
            "selected_start",
            "selected_end",
        }:
            raise PineRuntimeError(
                "request cursor schema mismatch", code=PL_REQUEST_CACHE
            )
        if (
            type(data["operation"]) is not str
            or type(data["dataset_key_hash"]) is not str
            or any(
                type(data[name]) is not int
                for name in (
                    "chart_open_ms",
                    "chart_close_ms",
                    "selected_start",
                    "selected_end",
                )
            )
        ):
            raise PineRuntimeError(
                "request cursor types are invalid", code=PL_REQUEST_CACHE
            )
        return cls(
            data["operation"],
            data["dataset_key_hash"],
            data["chart_open_ms"],
            data["chart_close_ms"],
            data["selected_start"],
            data["selected_end"],
        )


class RequestDatasetRegistry:
    """Transactional registry of immutable request datasets and merge cursors."""

    def __init__(
        self,
        *,
        max_datasets: int,
        max_bars: int,
        max_cache_bytes: int,
    ) -> None:
        if min(max_datasets, max_bars, max_cache_bytes) <= 0:
            raise PineRuntimeError(
                "request registry limits are invalid", code=PL_RESOURCE_LIMIT
            )
        self.max_datasets = max_datasets
        self.max_bars = max_bars
        self.max_cache_bytes = max_cache_bytes
        self._committed_datasets: dict[str, RequestDataset] = {}
        self._committed_discovery: dict[str, str] = {}
        self._committed_cursors: dict[str, MergeCursor] = {}
        self._working_datasets: dict[str, RequestDataset] = {}
        self._working_discovery: dict[str, str] = {}
        self._working_cursors: dict[str, MergeCursor] = {}
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def dataset_count(self) -> int:
        return len(self._committed_datasets)

    @property
    def discovery_count(self) -> int:
        return len(self._committed_discovery)

    @property
    def discovery_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._committed_discovery))

    @property
    def committed_datasets(self) -> tuple[RequestDataset, ...]:
        return tuple(
            sorted(
                self._committed_datasets.values(),
                key=lambda dataset: dataset.key.key_hash,
            )
        )

    @property
    def dataset_identity_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                dataset.key.query.discovery_identity(dataset.result_shape)
                for dataset in self._committed_datasets.values()
            )
        )

    def lookup_dataset_identity(self, discovery_id: str) -> RequestDataset | None:
        if not is_canonical_sha256(discovery_id):
            raise PineRuntimeError(
                "request discovery identity is invalid", code=PL_REQUEST_IDENTITY
            )
        matches = [
            dataset
            for dataset in self._committed_datasets.values()
            if dataset.key.query.discovery_identity(dataset.result_shape)
            == discovery_id
        ]
        if len(matches) > 1:
            raise PineRuntimeError(
                "request dataset identity is ambiguous", code=PL_REQUEST_IDENTITY
            )
        return matches[0] if matches else None

    @property
    def content_hash(self) -> str:
        return sha(self.to_json())

    @property
    def cache_bytes(self) -> int:
        return len(canonical_json(self.to_json()))

    def begin(self) -> None:
        if self._active:
            raise PineRuntimeError(
                "request registry transaction is already active", code=PL_REQUEST_CACHE
            )
        self._working_datasets = dict(self._committed_datasets)
        self._working_discovery = dict(self._committed_discovery)
        self._working_cursors = dict(self._committed_cursors)
        self._active = True

    def _require_active(self) -> None:
        if not self._active:
            raise PineRuntimeError(
                "request registry transaction is not active", code=PL_REQUEST_CACHE
            )

    def lookup(
        self, discovery_id: str, *, committed_only: bool = False
    ) -> RequestDataset | None:
        if not is_canonical_sha256(discovery_id):
            raise PineRuntimeError(
                "request discovery identity is invalid", code=PL_REQUEST_IDENTITY
            )
        mapping = (
            self._committed_discovery
            if committed_only or not self._active
            else self._working_discovery
        )
        datasets = (
            self._committed_datasets
            if committed_only or not self._active
            else self._working_datasets
        )
        key_hash = mapping.get(discovery_id)
        return None if key_hash is None else datasets.get(key_hash)

    def register(self, discovery_id: str, dataset: RequestDataset) -> RequestDataset:
        self._require_active()
        if not is_canonical_sha256(discovery_id):
            raise PineRuntimeError(
                "request discovery identity is invalid", code=PL_REQUEST_IDENTITY
            )
        expected_discovery = dataset.key.query.discovery_identity(dataset.result_shape)
        if discovery_id != expected_discovery:
            raise PineRuntimeError(
                "request discovery identity does not match dataset",
                code=PL_REQUEST_IDENTITY,
            )
        existing_key = self._working_discovery.get(discovery_id)
        if existing_key is not None:
            existing = self._working_datasets[existing_key]
            if (
                existing.key.key_hash != dataset.key.key_hash
                or existing.content_hash != dataset.content_hash
            ):
                raise PineRuntimeError(
                    "same request identity resolved to different immutable data",
                    code=PL_REQUEST_REVISION,
                )
            return existing
        existing_dataset = self._working_datasets.get(dataset.key.key_hash)
        if (
            existing_dataset is not None
            and existing_dataset.content_hash != dataset.content_hash
        ):
            raise PineRuntimeError(
                "request dataset key collision", code=PL_REQUEST_REVISION
            )
        if existing_dataset is None:
            if len(self._working_datasets) >= self.max_datasets:
                raise PineRuntimeError(
                    "request dataset limit exceeded", code=PL_RESOURCE_LIMIT
                )
            if len(dataset.evaluated_bars) > self.max_bars:
                raise PineRuntimeError(
                    "request bar limit exceeded", code=PL_RESOURCE_LIMIT
                )
            self._working_datasets[dataset.key.key_hash] = dataset
        self._working_discovery[discovery_id] = dataset.key.key_hash
        if len(canonical_json(self._working_json())) > self.max_cache_bytes:
            self._working_discovery.pop(discovery_id, None)
            if existing_dataset is None:
                self._working_datasets.pop(dataset.key.key_hash, None)
            raise PineRuntimeError(
                "request cache memory limit exceeded", code=PL_RESOURCE_LIMIT
            )
        return dataset

    def find_by_snapshot_hash(
        self,
        snapshot_hash: str,
        *,
        query: RequestQuery,
        result_shape: ResultShape,
        language_hash: str,
        policy_hash: str,
        parent_runtime_hash: str,
    ) -> RequestDataset | None:
        source = self._working_datasets if self._active else self._committed_datasets
        matches = []
        for dataset in source.values():
            child = dataset.child_context
            if (
                dataset.key.snapshot_hash == snapshot_hash
                and dataset.lineage_hash == query.lineage_hash
                and dataset.result_shape.content_hash == result_shape.content_hash
                and child is not None
                and child.language_hash == language_hash
                and child.policy_hash == policy_hash
                and child.instrument_id == query.instrument_id
                and child.timeframe == query.timeframe
                and child.parent_runtime_hash == parent_runtime_hash
            ):
                matches.append(dataset)
        if len(matches) > 1:
            raise PineRuntimeError(
                "append snapshot parent is ambiguous", code=PL_REQUEST_REVISION
            )
        return matches[0] if matches else None

    def validate_parent_identity(self, parent_runtime_hash: str) -> None:
        if not is_canonical_sha256(parent_runtime_hash):
            raise PineRuntimeError(
                "request parent runtime identity is invalid",
                code=PL_REQUEST_IDENTITY,
            )
        for dataset in self._committed_datasets.values():
            child = dataset.child_context
            if child is not None and child.parent_runtime_hash != parent_runtime_hash:
                raise PineRuntimeError(
                    "request dataset belongs to a different parent runtime",
                    code=PL_REQUEST_IDENTITY,
                )

    def validate_reachability(self) -> None:
        dataset_keys = set(self._committed_datasets)
        identity_ids = self.dataset_identity_ids
        if len(set(identity_ids)) != len(identity_ids):
            raise PineRuntimeError(
                "request dataset identities are ambiguous", code=PL_REQUEST_IDENTITY
            )

        reachable: set[str] = set()
        pending = list(self._committed_discovery.values())
        while pending:
            key_hash = pending.pop()
            if key_hash in reachable:
                continue
            dataset = self._committed_datasets.get(key_hash)
            if dataset is None:
                raise PineRuntimeError(
                    "request discovery references a missing dataset",
                    code=PL_REQUEST_IDENTITY,
                )
            reachable.add(key_hash)
            snapshot = dataset.snapshot
            if snapshot is None or snapshot.mode != SnapshotMode.APPEND:
                continue
            parent = self._append_parent(dataset)
            self._validate_append_edge(dataset, parent)
            pending.append(parent.key.key_hash)

        if reachable != dataset_keys:
            raise PineRuntimeError(
                "request registry contains unreachable datasets",
                code=PL_REQUEST_IDENTITY,
            )

    def _append_parent(self, dataset: RequestDataset) -> RequestDataset:
        snapshot = dataset.snapshot
        child = dataset.child_context
        assert snapshot is not None and child is not None
        candidates = []
        for candidate in self._committed_datasets.values():
            candidate_child = candidate.child_context
            if (
                candidate.key.snapshot_hash == snapshot.parent_snapshot_hash
                and candidate.lineage_hash == dataset.lineage_hash
                and candidate.result_shape.content_hash
                == dataset.result_shape.content_hash
                and candidate_child is not None
                and candidate_child.language_hash == child.language_hash
                and candidate_child.policy_hash == child.policy_hash
                and candidate_child.instrument_id == dataset.key.query.instrument_id
                and candidate_child.timeframe == dataset.key.query.timeframe
                and candidate_child.parent_runtime_hash == child.parent_runtime_hash
            ):
                candidates.append(candidate)
        if len(candidates) != 1:
            raise PineRuntimeError(
                "append request dataset parent is missing or ambiguous",
                code=PL_REQUEST_IDENTITY,
            )
        return candidates[0]

    def validate_evaluator_lineage(self, evaluators: dict[str, str]) -> None:
        for dataset in self._committed_datasets.values():
            snapshot = dataset.snapshot
            if snapshot is None or snapshot.mode != SnapshotMode.APPEND:
                continue
            parent = self._append_parent(dataset)
            child_identity = dataset.key.query.discovery_identity(dataset.result_shape)
            parent_identity = parent.key.query.discovery_identity(parent.result_shape)
            if evaluators[child_identity] != evaluators[parent_identity]:
                raise PineRuntimeError(
                    "append snapshot evaluator lineage mismatch",
                    code=PL_REQUEST_REVISION,
                )

    @staticmethod
    def _validate_append_edge(dataset: RequestDataset, parent: RequestDataset) -> None:
        snapshot = dataset.snapshot
        parent_snapshot = parent.snapshot
        if snapshot is None or parent_snapshot is None:
            raise PineRuntimeError(
                "append request dataset edge is incomplete",
                code=PL_REQUEST_IDENTITY,
            )
        if snapshot.revision <= parent_snapshot.revision:
            raise PineRuntimeError(
                "append snapshot revision did not strictly increase",
                code=PL_REQUEST_REVISION,
            )
        if any(bar.revision != snapshot.revision for bar in snapshot.bars):
            raise PineRuntimeError(
                "append bar revision does not match snapshot revision",
                code=PL_REQUEST_REVISION,
            )
        if any(bar.finality != DataFinality.FINAL for bar in snapshot.bars[:-1]):
            raise PineRuntimeError(
                "append snapshot contains a non-final interior bar",
                code=PL_REQUEST_REVISION,
            )
        if (
            parent.evaluated_bars
            and parent.evaluated_bars[-1].finality != DataFinality.FINAL
        ):
            raise PineRuntimeError(
                "append snapshot cannot extend an unresolved developing tail",
                code=PL_REQUEST_REVISION,
            )
        if (
            snapshot.bars
            and parent.evaluated_bars
            and snapshot.bars[0].open_time_ms < parent.evaluated_bars[-1].close_time_ms
        ):
            raise PineRuntimeError(
                "append snapshot overlaps parent history",
                code=PL_REQUEST_REVISION,
            )
        inherited_count = len(dataset.evaluated_bars) - len(snapshot.bars)
        inherited = dataset.evaluated_bars[:inherited_count]
        if canonical_json([bar.to_dict() for bar in inherited]) != canonical_json(
            [bar.to_dict() for bar in parent.evaluated_bars]
        ):
            raise PineRuntimeError(
                "append dataset parent history mismatch",
                code=PL_REQUEST_REVISION,
            )

    def cursor(self, discovery_id: str) -> MergeCursor | None:
        self._require_active()
        return self._working_cursors.get(discovery_id)

    def update_cursor(self, discovery_id: str, cursor: MergeCursor) -> None:
        self._require_active()
        dataset = self.lookup(discovery_id)
        if dataset is None or dataset.key.key_hash != cursor.dataset_key_hash:
            raise PineRuntimeError(
                "cursor does not belong to request dataset", code=PL_REQUEST_CACHE
            )
        self._working_cursors[discovery_id] = cursor

    def savepoint(
        self,
    ) -> tuple[dict[str, RequestDataset], dict[str, str], dict[str, MergeCursor]]:
        self._require_active()
        return (
            dict(self._working_datasets),
            dict(self._working_discovery),
            dict(self._working_cursors),
        )

    def restore_savepoint(
        self,
        savepoint: tuple[
            dict[str, RequestDataset], dict[str, str], dict[str, MergeCursor]
        ],
    ) -> None:
        self._require_active()
        datasets, discovery, cursors = savepoint
        self._working_datasets = dict(datasets)
        self._working_discovery = dict(discovery)
        self._working_cursors = dict(cursors)

    def commit(self) -> None:
        self._require_active()
        self._committed_datasets = dict(self._working_datasets)
        self._committed_discovery = dict(self._working_discovery)
        self._committed_cursors = dict(self._working_cursors)
        self._active = False

    def rollback(self) -> None:
        self._require_active()
        self._working_datasets = {}
        self._working_discovery = {}
        self._working_cursors = {}
        self._active = False

    def _working_json(self) -> dict[str, object]:
        return {
            "datasets": [
                dataset.to_dict()
                for dataset in sorted(
                    self._working_datasets.values(), key=lambda row: row.key.key_hash
                )
            ],
            "discovery": [
                {"discovery_id": discovery_id, "dataset_key_hash": key_hash}
                for discovery_id, key_hash in sorted(self._working_discovery.items())
            ],
            "cursors": [
                {"discovery_id": discovery_id, "cursor": cursor.to_dict()}
                for discovery_id, cursor in sorted(self._working_cursors.items())
            ],
        }

    @property
    def semantic_hash(self) -> str:
        # Datasets are admitted content-addressed immutable values. Cursors and
        # discovery are live state, not revision-count stand-ins.
        return sha(
            {
                "algorithm": "pinelib.request-registry.v1",
                "datasets": [
                    {
                        "key": key,
                        "content_hash": value.content_hash,
                        "child_state": value.child_state,
                    }
                    for key, value in sorted(self._committed_datasets.items())
                ],
                "discovery": dict(sorted(self._committed_discovery.items())),
                "cursors": {
                    key: value.to_dict()
                    for key, value in sorted(self._committed_cursors.items())
                },
            }
        )

    def to_json(self) -> dict[str, object]:
        return {
            "datasets": [
                dataset.to_dict()
                for dataset in sorted(
                    self._committed_datasets.values(), key=lambda row: row.key.key_hash
                )
            ],
            "discovery": [
                {"discovery_id": discovery_id, "dataset_key_hash": key_hash}
                for discovery_id, key_hash in sorted(self._committed_discovery.items())
            ],
            "cursors": [
                {"discovery_id": discovery_id, "cursor": cursor.to_dict()}
                for discovery_id, cursor in sorted(self._committed_cursors.items())
            ],
        }

    @classmethod
    def from_json(
        cls,
        data: object,
        *,
        max_datasets: int,
        max_bars: int,
        max_cache_bytes: int,
    ) -> RequestDatasetRegistry:
        if not isinstance(data, dict) or set(data) != {
            "datasets",
            "discovery",
            "cursors",
        }:
            raise PineRuntimeError(
                "request registry schema mismatch", code=PL_REQUEST_CACHE
            )
        if not all(
            isinstance(data[name], list)
            for name in ("datasets", "discovery", "cursors")
        ):
            raise PineRuntimeError(
                "request registry segments must be lists", code=PL_REQUEST_CACHE
            )
        registry = cls(
            max_datasets=max_datasets,
            max_bars=max_bars,
            max_cache_bytes=max_cache_bytes,
        )
        datasets: dict[str, RequestDataset] = {}
        for raw in data["datasets"]:
            dataset = RequestDataset.from_dict(raw)
            if dataset.key.key_hash in datasets:
                raise PineRuntimeError(
                    "duplicate request dataset key", code=PL_REQUEST_CACHE
                )
            datasets[dataset.key.key_hash] = dataset
        discovery: dict[str, str] = {}
        for raw in data["discovery"]:
            if not isinstance(raw, dict) or set(raw) != {
                "discovery_id",
                "dataset_key_hash",
            }:
                raise PineRuntimeError(
                    "request discovery row schema mismatch", code=PL_REQUEST_CACHE
                )
            if (
                type(raw["discovery_id"]) is not str
                or type(raw["dataset_key_hash"]) is not str
            ):
                raise PineRuntimeError(
                    "request discovery row types are invalid", code=PL_REQUEST_CACHE
                )
            discovery_id = raw["discovery_id"]
            key_hash = raw["dataset_key_hash"]
            discovery_dataset = datasets.get(key_hash)
            if (
                not is_canonical_sha256(discovery_id)
                or discovery_id in discovery
                or discovery_dataset is None
                or discovery_id
                != discovery_dataset.key.query.discovery_identity(
                    discovery_dataset.result_shape
                )
            ):
                raise PineRuntimeError(
                    "request discovery row is invalid", code=PL_REQUEST_CACHE
                )
            discovery[discovery_id] = key_hash
        cursors: dict[str, MergeCursor] = {}
        for raw in data["cursors"]:
            if not isinstance(raw, dict) or set(raw) != {"discovery_id", "cursor"}:
                raise PineRuntimeError(
                    "request cursor row schema mismatch", code=PL_REQUEST_CACHE
                )
            discovery_id = str(raw["discovery_id"])
            cursor = MergeCursor.from_dict(raw["cursor"])
            cursor_key_hash = discovery.get(discovery_id)
            cursor_dataset = datasets.get(cursor_key_hash or "")
            expected_operation = (
                "security"
                if cursor_dataset is not None
                and cursor_dataset.key.query.kind == RequestKind.SECURITY
                else "security_lower_tf"
            )
            empty = cursor.selected_start == cursor.selected_end == -1
            populated = (
                cursor.selected_start >= 0
                and cursor.selected_end >= cursor.selected_start
                and cursor_dataset is not None
                and cursor.selected_end < len(cursor_dataset.evaluated_bars)
            )
            if (
                type(raw["discovery_id"]) is not str
                or discovery_id in cursors
                or cursor_dataset is None
                or cursor_key_hash != cursor.dataset_key_hash
                or cursor.operation != expected_operation
                or not (empty or populated)
            ):
                raise PineRuntimeError(
                    "request cursor row is invalid", code=PL_REQUEST_CACHE
                )
            cursors[discovery_id] = cursor
        registry._committed_datasets = datasets
        registry._committed_discovery = discovery
        registry._committed_cursors = cursors
        registry.validate_reachability()
        if len(datasets) > max_datasets or any(
            len(item.evaluated_bars) > max_bars for item in datasets.values()
        ):
            raise PineRuntimeError(
                "restored request registry exceeds limits", code=PL_RESOURCE_LIMIT
            )
        if registry.cache_bytes > max_cache_bytes:
            raise PineRuntimeError(
                "restored request cache exceeds memory limit", code=PL_RESOURCE_LIMIT
            )
        return registry
