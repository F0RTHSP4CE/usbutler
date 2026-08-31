"""ACR122U access to one MIFARE Classic data block."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional, Protocol

from app.emv.nfc_reader import NFCReader
from app.services.mifare_rotation_service import canonical_uuid4


class MifareBlockError(RuntimeError):
    pass


@dataclass(frozen=True)
class MifareWriteResult:
    verified: bool
    attempts: int
    observed_uuid: Optional[str]
    detail: Optional[str] = None


class MifareBlockStore(Protocol):
    def read_uuid(self) -> Optional[str]: ...

    def write_and_verify(
        self, target_uuid: str, expected_uid: Optional[str] = None
    ) -> MifareWriteResult: ...


def validate_data_block(block_number: int) -> int:
    """Reject manufacturer and sector-trailer blocks for Classic 1K/4K."""
    if not 0 <= block_number <= 255:
        raise ValueError("MIFARE data block must be between 0 and 255")
    if block_number == 0:
        raise ValueError("MIFARE block 0 is the read-only manufacturer block")
    if block_number < 128:
        is_trailer = block_number % 4 == 3
    else:
        is_trailer = (block_number - 128) % 16 == 15
    if is_trailer:
        raise ValueError("MIFARE sector-trailer blocks cannot store rotating UUIDs")
    return block_number


class ACR122MifareBlockStore:
    """Read and update a UUID in a normal MIFARE Classic data block."""

    def __init__(
        self,
        reader: NFCReader,
        block_number: int = 4,
        key_a: str = "FFFFFFFFFFFF",
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.15,
    ):
        self.reader = reader
        self.block_number = validate_data_block(block_number)
        cleaned_key = key_a.replace(" ", "").upper()
        if len(cleaned_key) != 12 or any(
            character not in "0123456789ABCDEF" for character in cleaned_key
        ):
            raise ValueError("MIFARE_CLASSIC_KEY_A must be exactly 12 hex characters")
        if max_attempts < 1:
            raise ValueError("MIFARE write max attempts must be at least 1")
        if retry_delay_seconds < 0:
            raise ValueError("MIFARE write retry delay cannot be negative")
        self.key_a = bytes.fromhex(cleaned_key)
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds

    def read_uuid(self) -> Optional[str]:
        raw = self._read_block()
        if len(raw) != 16:
            raise MifareBlockError("MIFARE block read did not return 16 bytes")
        parsed = uuid.UUID(bytes=raw)
        return canonical_uuid4(str(parsed))

    def write_and_verify(
        self, target_uuid: str, expected_uid: Optional[str] = None
    ) -> MifareWriteResult:
        canonical = canonical_uuid4(target_uuid)
        if canonical is None:
            raise ValueError("MIFARE data credential must be a UUIDv4")
        payload = uuid.UUID(canonical).bytes
        last_detail: Optional[str] = None
        observed: Optional[str] = None

        for attempt in range(1, self.max_attempts + 1):
            write_error: Optional[BaseException] = None
            try:
                self._ensure_connected()
                self._assert_uid(expected_uid)
                self._write_block(payload)
            except Exception as exc:
                write_error = exc

            read_error: Optional[BaseException] = None
            try:
                self._ensure_connected()
                self._assert_uid(expected_uid)
                observed = self.read_uuid()
            except Exception as exc:
                observed = None
                read_error = exc

            if observed == canonical:
                detail = (
                    f"Verified target after write error: {write_error}"
                    if write_error
                    else None
                )
                return MifareWriteResult(True, attempt, observed, detail)

            details = []
            if write_error:
                details.append(f"write failed: {write_error}")
            if read_error:
                details.append(f"verification failed: {read_error}")
            elif observed is None:
                details.append("verification returned invalid or empty UUID data")
            else:
                details.append("verification returned a different UUID")
            last_detail = "; ".join(details)
            if attempt < self.max_attempts and self.retry_delay_seconds:
                time.sleep(self.retry_delay_seconds)

        return MifareWriteResult(
            False, self.max_attempts, observed, last_detail or "write was not verified"
        )

    def _read_block(self) -> bytes:
        self._ensure_connected()
        self._authenticate()
        return self._apdu([0xFF, 0xB0, 0x00, self.block_number, 0x10], "read block")

    def _write_block(self, payload: bytes) -> None:
        if len(payload) != 16:
            raise ValueError("MIFARE block writes require exactly 16 bytes")
        self._authenticate()
        self._apdu(
            [0xFF, 0xD6, 0x00, self.block_number, 0x10, *payload],
            "update block",
        )

    def _ensure_connected(self) -> None:
        if self.reader.is_connected():
            return
        if not self.reader.wait_for_card(timeout=1):
            raise MifareBlockError("Card could not be reselected")

    def _assert_uid(self, expected_uid: Optional[str]) -> None:
        if not expected_uid:
            return
        expected = expected_uid.replace(" ", "").replace(":", "").upper()
        response = self._apdu([0xFF, 0xCA, 0x00, 0x00, 0x00], "read UID")
        actual = response.hex().upper()
        if actual != expected:
            raise MifareBlockError("A different card was presented during UUID write")

    def _authenticate(self) -> None:
        self._apdu([0xFF, 0x82, 0x00, 0x00, 0x06, *self.key_a], "load Key A")
        self._apdu(
            [
                0xFF,
                0x86,
                0x00,
                0x00,
                0x05,
                0x01,
                0x00,
                self.block_number,
                0x60,
                0x00,
            ],
            "authenticate block",
        )

    def _apdu(self, command: list[int], operation: str) -> bytes:
        response, sw1, sw2 = self.reader.send_apdu(command)
        if (sw1, sw2) != (0x90, 0x00):
            raise MifareBlockError(
                f"MIFARE {operation} returned status {sw1:02X}{sw2:02X}"
            )
        return bytes(response)
