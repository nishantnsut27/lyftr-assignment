from app.errors import InvalidFailureSimulation

ALLOWED_FAILURE_STATUSES = {429, 500, 502, 503}


def parse_failure_simulation(header: str | None, key_count: int) -> dict[str, int]:
    if header is None:
        return {}

    failures: dict[str, int] = {}
    known_keys = {f"key_{index}" for index in range(1, key_count + 1)} | {"*"}
    for entry in header.split(","):
        key_id, separator, status_text = entry.strip().partition("=")
        key_id, status_text = key_id.strip(), status_text.strip()
        if (
            not separator
            or key_id not in known_keys
            or status_text not in {str(status) for status in ALLOWED_FAILURE_STATUSES}
            or key_id in failures
        ):
            raise InvalidFailureSimulation
        failures[key_id] = int(status_text)
    return failures
