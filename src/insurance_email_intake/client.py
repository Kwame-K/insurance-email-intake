from collections.abc import Mapping
from typing import Any, Protocol

import httpx2

from insurance_email_intake.errors import UnderwritingUnavailableError


class UnderwritingPort(Protocol):
    def extract_and_underwrite(
        self,
        payload: Mapping[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]: ...


class HTTPUnderwritingClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    def extract_and_underwrite(
        self,
        payload: Mapping[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        try:
            with httpx2.Client(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            ) as client:
                response = client.post(
                    "/extract-and-underwrite",
                    json=dict(payload),
                    headers={"X-Correlation-ID": correlation_id},
                )
                response.raise_for_status()
            data = response.json()
        except (httpx2.HTTPError, ValueError) as error:
            raise UnderwritingUnavailableError(str(error)) from error

        if not isinstance(data, dict):
            raise UnderwritingUnavailableError("Unexpected response shape.")
        return data
