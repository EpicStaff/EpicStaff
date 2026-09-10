import zoneinfo
from datetime import datetime, timezone as _datetime_timezone

from loguru import logger
from rest_framework import serializers

from tables.exceptions import ScheduleTriggerValidationError
from tables.models.graph_models import ScheduleTriggerNode


class ScheduleTriggerInputParser:
    """Wire ↔ model translation for ScheduleTriggerNode.

    `parse` takes the user-supplied `schedule` dict (or None for clear) and
    returns a flat dict of model columns: validates the nested shape (via
    the DTO serializer in the serializer module — lazy-imported to avoid a
    cycle), normalises naive ISO strings to UTC, and applies the
    schedule-null reset. `render` does the reverse for outbound responses.

    Pure transformation/shape concerns — no state-level rules.
    Domain state validation belongs in ScheduleTriggerValidator.
    """

    _RESET_FIELDS: dict = {
        "is_active": False,
        "run_mode": None,
        "start_date_time": None,
        "every": None,
        "unit": None,
        "weekdays": None,
        "end_type": None,
        "end_date_time": None,
        "max_runs": None,
        "timezone": "UTC",
    }

    def parse_to_internal_value(
        self,
        raw_schedule,
        instance: ScheduleTriggerNode | None,
    ) -> dict:
        if raw_schedule is None:
            # Explicit null clears the schedule and forces deactivation.
            return dict(self._RESET_FIELDS)

        cfg = self._validate_shape(raw_schedule)

        attrs: dict = {}
        tz_name = cfg.get("timezone")
        if tz_name is None and instance is not None:
            effective_tz = instance.timezone or "UTC"
        else:
            effective_tz = tz_name or "UTC"
        if tz_name is not None:
            attrs["timezone"] = tz_name

        if "run_mode" in raw_schedule:
            new_run_mode = cfg.get("run_mode")
            attrs["run_mode"] = new_run_mode
            # When the user flips to run_mode="once" without re-stating
            # interval/end, the validator's compose-with-instance step would
            # otherwise see stale every/unit/weekdays/end_* and 400. Clearing
            # them here makes the change request self-consistent.
            if new_run_mode == ScheduleTriggerNode.RunMode.ONCE:
                if "interval" not in raw_schedule:
                    attrs["every"] = None
                    attrs["unit"] = None
                    attrs["weekdays"] = None
                if "end" not in raw_schedule:
                    attrs["end_type"] = ScheduleTriggerNode.EndType.NEVER
                    attrs["end_date_time"] = None
                    attrs["max_runs"] = None

        if "start_date_time" in raw_schedule:
            attrs["start_date_time"] = self._parse_dt(
                cfg.get("start_date_time"),
                effective_tz,
                ("schedule", "start_date_time"),
            )

        if "interval" in raw_schedule:
            interval = cfg.get("interval") or {}
            attrs["every"] = interval.get("every")
            attrs["unit"] = interval.get("unit")
            attrs["weekdays"] = interval.get("weekdays")

        if "end" in raw_schedule:
            end = cfg.get("end") or {}
            attrs["end_type"] = end.get("type")
            attrs["end_date_time"] = self._parse_dt(
                end.get("date_time"),
                effective_tz,
                ("schedule", "end", "date_time"),
            )
            attrs["max_runs"] = end.get("max_runs")

        return attrs

    @staticmethod
    def render_to_representation(instance: ScheduleTriggerNode) -> dict:
        """Render a node's flat columns back into the wire `schedule` block."""
        tz_name = instance.timezone or "UTC"
        interval = (
            None
            if instance.run_mode == ScheduleTriggerNode.RunMode.ONCE
            else {
                "every": instance.every,
                "unit": instance.unit,
                "weekdays": instance.weekdays or [],
            }
        )

        next_run = instance.next_run_date_time
        if (
            instance.is_active
            and next_run is not None
            and next_run < datetime.now(_datetime_timezone.utc)
        ):
            logger.warning(
                f"[ScheduleTriggerNode {instance.pk}] stored next_run_date_time "
                f"{next_run.isoformat()} is in the past while node is active; "
                f"returning None. Possible Manager outage or lost 'deactivate' signal."
            )
            next_run = None

        return {
            "run_mode": instance.run_mode,
            "timezone": tz_name,
            "start_date_time": ScheduleTriggerValidator.format_utc_to_local_naive_iso(
                instance.start_date_time, tz_name
            ),
            "next_run_date_time": ScheduleTriggerValidator.format_utc_to_local_naive_iso(
                next_run, tz_name
            ),
            "interval": interval,
            "end": {
                "type": instance.end_type,
                "date_time": ScheduleTriggerValidator.format_utc_to_local_naive_iso(
                    instance.end_date_time, tz_name
                ),
                "max_runs": instance.max_runs,
            },
        }

    @staticmethod
    def _validate_shape(raw_schedule) -> dict:
        # Lazy import: DTO lives in serializers; importing it eagerly would
        # form a cycle since the serializer imports this module.
        from tables.serializers.model_serializers.node_serializers.trigger_serializers import (
            _ScheduleConfigInputSerializer,
        )

        config = _ScheduleConfigInputSerializer(data=raw_schedule)
        try:
            config.is_valid(raise_exception=True)
        except serializers.ValidationError as exc:
            raise ScheduleTriggerValidationError({"schedule": exc.detail}) from exc
        return config.validated_data

    @staticmethod
    def _parse_dt(raw, tz_name: str, error_path: tuple[str, ...]):
        try:
            return ScheduleTriggerValidator.parse_naive_to_utc(raw, tz_name)
        except ValueError as exc:
            detail: dict = {}
            cursor = detail
            for key in error_path[:-1]:
                cursor[key] = {}
                cursor = cursor[key]
            cursor[error_path[-1]] = [str(exc)]
            raise ScheduleTriggerValidationError(detail) from exc


class ScheduleTriggerValidator:
    _WEEKDAYS_UNITS = {
        ScheduleTriggerNode.TimeUnit.DAYS,
        ScheduleTriggerNode.TimeUnit.WEEKS,
    }

    _SCHEDULE_FIELDS = (
        "is_active",
        "run_mode",
        "start_date_time",
        "every",
        "unit",
        "weekdays",
        "end_type",
        "end_date_time",
        "max_runs",
        "timezone",
    )

    @classmethod
    def compose_state(
        cls,
        instance: ScheduleTriggerNode | None,
        attrs: dict,
        initial_data: object,
    ) -> dict:
        """Project attrs over the existing instance to a complete schedule state.

        Validation reasons over the post-write snapshot, so missing fields fall
        back to the instance and `is_active` reflects the user's stated intent
        even when to_internal_value forced it to False (schedule cleared).
        """
        if instance is not None:
            state = {f: getattr(instance, f, None) for f in cls._SCHEDULE_FIELDS}
        else:
            state = {}
        state.update(attrs)

        initial = initial_data if isinstance(initial_data, dict) else {}
        if "is_active" in initial:
            state["is_active"] = bool(initial["is_active"])
        return state

    @staticmethod
    def parse_naive_to_utc(raw, tz_name: str | None) -> datetime | None:
        """Parse an ISO string in the given IANA tz into a UTC tz-aware datetime.

        Naive input is localized in `tz_name` (what the user typed on their wall
        clock). Aware input is respected as-is and converted to UTC. Returns None
        for empty input; raises ValueError on unparseable input or unknown tz.
        """
        if raw in (None, ""):
            return None
        if isinstance(raw, datetime):
            parsed = raw
        else:
            try:
                parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"Invalid ISO 8601 datetime: {raw!r}.") from exc

        if parsed.tzinfo is None:
            try:
                tz = zoneinfo.ZoneInfo(tz_name or "UTC")
            except zoneinfo.ZoneInfoNotFoundError as exc:
                raise ValueError(f"Unknown IANA timezone: {tz_name!r}.") from exc
            parsed = parsed.replace(tzinfo=tz)

        return parsed.astimezone(_datetime_timezone.utc)

    @staticmethod
    def format_utc_to_local_naive_iso(
        dt: datetime | None, tz_name: str | None
    ) -> str | None:
        """Render a UTC datetime as a naive ISO string in the given IANA tz.

        Falls back to UTC if `tz_name` is missing or unknown so a stored node is
        always renderable even if its tz later becomes invalid.
        """
        if dt is None:
            return None
        try:
            tz = zoneinfo.ZoneInfo(tz_name or "UTC")
        except zoneinfo.ZoneInfoNotFoundError:
            tz = zoneinfo.ZoneInfo("UTC")
        return dt.astimezone(tz).replace(tzinfo=None).isoformat()

    def validate(self, attrs: dict) -> None:
        self._validate_timezone(attrs)
        self._validate_run_mode_once(attrs)
        self._validate_run_mode_repeat(attrs)
        self._validate_end_type(attrs)
        self._validate_weekdays(attrs)
        self._validate_active_state(attrs)

    @staticmethod
    def _validate_active_state(attrs: dict) -> None:
        if not attrs.get("is_active"):
            return
        if not (
            attrs.get("run_mode")
            and attrs.get("start_date_time")
            and attrs.get("end_type")
        ):
            raise ScheduleTriggerValidationError(
                {"is_active": "Cannot activate: schedule is not fully configured."}
            )

    @staticmethod
    def _validate_timezone(attrs: dict) -> None:
        tz_name = attrs.get("timezone")
        if not tz_name:
            return
        try:
            zoneinfo.ZoneInfo(tz_name)
        except zoneinfo.ZoneInfoNotFoundError:
            raise ScheduleTriggerValidationError(
                {"timezone": f"Unknown IANA timezone: {tz_name!r}."}
            )

    @staticmethod
    def _validate_run_mode_once(attrs: dict) -> None:
        if attrs.get("run_mode") != ScheduleTriggerNode.RunMode.ONCE:
            return
        if (
            attrs.get("every") is not None
            or attrs.get("unit") is not None
            or attrs.get("weekdays")
        ):
            raise ScheduleTriggerValidationError(
                {
                    "every": 'Fields every/unit/weekdays are not used for run_mode="once".'
                }
            )
        if attrs.get("end_type") != ScheduleTriggerNode.EndType.NEVER:
            raise ScheduleTriggerValidationError(
                {"end_type": 'run_mode="once" implies end_type="never".'}
            )

    @staticmethod
    def _validate_run_mode_repeat(attrs: dict) -> None:
        if attrs.get("run_mode") != ScheduleTriggerNode.RunMode.REPEAT:
            return
        every = attrs.get("every")
        if every is None or every < 1:
            raise ScheduleTriggerValidationError(
                {"every": 'Must be >= 1 for run_mode="repeat".'}
            )
        if attrs.get("unit") is None:
            raise ScheduleTriggerValidationError(
                {"unit": 'Required for run_mode="repeat".'}
            )

    def _validate_end_type(self, attrs: dict) -> None:
        end_type = attrs.get("end_type")
        if end_type == ScheduleTriggerNode.EndType.NEVER:
            self._validate_end_never(attrs)
        elif end_type == ScheduleTriggerNode.EndType.AFTER_N_RUNS:
            self._validate_end_after_n_runs(attrs)
        elif end_type == ScheduleTriggerNode.EndType.ON_DATE:
            self._validate_end_on_date(attrs)

    @staticmethod
    def _validate_end_never(attrs: dict) -> None:
        if attrs.get("end_date_time") is not None or attrs.get("max_runs") is not None:
            raise ScheduleTriggerValidationError(
                {
                    "end_type": 'end_date_time and max_runs must be empty for end_type="never".'
                }
            )

    @staticmethod
    def _validate_end_after_n_runs(attrs: dict) -> None:
        max_runs = attrs.get("max_runs")
        if max_runs is None or max_runs < 1:
            raise ScheduleTriggerValidationError(
                {"max_runs": 'Required and must be >= 1 for end_type="after_n_runs".'}
            )

    @staticmethod
    def _validate_end_on_date(attrs: dict) -> None:
        end_dt = attrs.get("end_date_time")
        if not end_dt:
            raise ScheduleTriggerValidationError(
                {"end_date_time": 'Required for end_type="on_date".'}
            )
        start_dt = attrs.get("start_date_time")
        if start_dt and end_dt <= start_dt:
            raise ScheduleTriggerValidationError(
                {"end_date_time": "Must be later than start_date_time."}
            )

    def _validate_weekdays(self, attrs: dict) -> None:
        weekdays = attrs.get("weekdays") or []
        if not weekdays:
            return
        if not set(weekdays).issubset(ScheduleTriggerNode.ALLOWED_WEEKDAYS):
            raise ScheduleTriggerValidationError(
                {
                    "weekdays": f'Allowed values: {", ".join(sorted(ScheduleTriggerNode.ALLOWED_WEEKDAYS))}.'
                }
            )
        unit = attrs.get("unit")
        if unit is not None and unit not in self._WEEKDAYS_UNITS:
            raise ScheduleTriggerValidationError(
                {"weekdays": 'Only supported with unit="days" or unit="weeks".'}
            )
