"""Best-effort UID writer for ACR122U and 4-byte magic MIFARE Classic cards."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from app.emv.nfc_reader import NFCReader
from app.models.identifier import UidRotationOutcome, UidRotationProtocol

logger = logging.getLogger(__name__)


class UidWriterError(RuntimeError):
    pass


class UidWriterNak(UidWriterError):
    """The card explicitly declined a raw MIFARE command."""


@dataclass(frozen=True)
class UidWriteResult:
    protocol: UidRotationProtocol
    outcome: UidRotationOutcome
    detail: Optional[str] = None


class UidWriter(Protocol):
    """Hardware-independent writer contract used by the door path."""

    def write_uid(self, source_uid: str, target_uid: str) -> UidWriteResult: ...


def classify_writer_exception(
    exc: BaseException,
    fallback: UidRotationOutcome = UidRotationOutcome.FAILED,
) -> UidRotationOutcome:
    """Map driver-specific failures to stable audit outcomes."""
    detail = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timeout" in detail or "timed out" in detail:
        return UidRotationOutcome.TIMEOUT
    if isinstance(exc, UidWriterNak) or "nak" in detail or "not acknowledged" in detail:
        return UidRotationOutcome.NAK
    if any(
        marker in detail
        for marker in (
            "connection lost",
            "connection loss",
            "disconnected",
            "not connected",
            "card was removed",
            "card removed",
            "0x80100069",
            "different card",
            "could not be reselected",
            "no card",
        )
    ):
        return UidRotationOutcome.CONNECTION_LOSS
    if any(
        marker in detail
        for marker in ("pc/sc", "pcsc", "scard", "apdu transmission failed")
    ):
        return UidRotationOutcome.PCSC_ERROR
    return fallback


class ACR122UidWriter:
    """Writes block 0 on Gen1A and Gen2/CUID 4-byte magic cards."""

    _TX_MODE = 0x6302
    _RX_MODE = 0x6303
    _BIT_FRAMING = 0x633D

    _RETRYABLE_OUTCOMES = {
        UidRotationOutcome.TIMEOUT,
        UidRotationOutcome.PCSC_ERROR,
        UidRotationOutcome.CONNECTION_LOSS,
        UidRotationOutcome.FAILED,
    }

    def __init__(
        self,
        reader: NFCReader,
        key_a: str = "FFFFFFFFFFFF",
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.15,
    ):
        self.reader = reader
        cleaned_key = key_a.replace(" ", "").upper()
        if len(cleaned_key) != 12 or any(
            char not in "0123456789ABCDEF" for char in cleaned_key
        ):
            raise ValueError("MIFARE_CLASSIC_KEY_A must be exactly 12 hex characters")
        self.key_a = bytes.fromhex(cleaned_key)
        if max_attempts < 1:
            raise ValueError("UID write max_attempts must be at least 1")
        if retry_delay_seconds < 0:
            raise ValueError("UID write retry delay cannot be negative")
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds

    def write_uid(self, source_uid: str, target_uid: str) -> UidWriteResult:
        source = self._uid_bytes(source_uid)
        target = self._uid_bytes(target_uid)

        result: Optional[UidWriteResult] = None
        for attempt_number in range(1, self.max_attempts + 1):
            if attempt_number > 1:
                try:
                    if not self._reconnect():
                        raise UidWriterError("Card could not be reselected for retry")
                except Exception as exc:
                    result = UidWriteResult(
                        UidRotationProtocol.UNKNOWN,
                        classify_writer_exception(exc),
                        str(exc),
                    )
                else:
                    result = self._write_uid_once(source, target)
            else:
                result = self._write_uid_once(source, target)

            result = self._with_attempt_detail(result, attempt_number)
            if (
                result.outcome == UidRotationOutcome.ACKNOWLEDGED
                or result.outcome not in self._RETRYABLE_OUTCOMES
                or attempt_number == self.max_attempts
            ):
                return result

            logger.warning(
                "UID write attempt %s/%s failed (%s/%s); retrying",
                attempt_number,
                self.max_attempts,
                result.protocol.value,
                result.outcome.value,
            )
            if self.retry_delay_seconds:
                time.sleep(self.retry_delay_seconds)

        # The loop is guaranteed to run at least once.
        assert result is not None
        return result

    def _write_uid_once(self, source: bytes, target: bytes) -> UidWriteResult:
        """Run one complete Gen1A probe followed by Gen2/CUID fallback."""

        try:
            gen1a = self._try_gen1a(source, target)
            if gen1a:
                return UidWriteResult(
                    UidRotationProtocol.GEN1A,
                    UidRotationOutcome.ACKNOWLEDGED,
                    "Card acknowledged Gen1A block-0 write; awaiting a later scan",
                )
        except Exception as exc:
            return UidWriteResult(
                UidRotationProtocol.GEN1A,
                classify_writer_exception(exc),
                f"Gen1A write failed after unlock: {exc}",
            )

        try:
            if not self._reconnect():
                raise UidWriterError("Card could not be reselected after Gen1A probe")
            self._write_gen2(source, target)
            return UidWriteResult(
                UidRotationProtocol.GEN2,
                UidRotationOutcome.ACKNOWLEDGED,
                "Card acknowledged Gen2 block-0 write; awaiting a later scan",
            )
        except Exception as exc:
            return UidWriteResult(
                UidRotationProtocol.GEN2,
                classify_writer_exception(exc, UidRotationOutcome.UNSUPPORTED),
                f"Neither Gen1A nor Gen2/CUID write was accepted: {exc}",
            )

    def _with_attempt_detail(
        self, result: UidWriteResult, attempt_number: int
    ) -> UidWriteResult:
        detail = result.detail or "UID write completed"
        return UidWriteResult(
            result.protocol,
            result.outcome,
            f"{detail}; hardware attempt {attempt_number}/{self.max_attempts}",
        )

    @staticmethod
    def _uid_bytes(value: str) -> bytes:
        cleaned = value.replace(" ", "").replace(":", "").upper()
        if len(cleaned) != 8 or any(
            character not in "0123456789ABCDEF" for character in cleaned
        ):
            raise ValueError("UID rotation requires a 4-byte hexadecimal UID")
        return bytes.fromhex(cleaned)

    @staticmethod
    def _patched_block(block: bytes, source: bytes, target: bytes) -> bytes:
        if len(block) != 16:
            raise UidWriterError("Block 0 read did not return 16 bytes")
        if block[:4] != source:
            raise UidWriterError("Card UID changed or a different card was presented")
        patched = bytearray(block)
        patched[:4] = target
        patched[4] = target[0] ^ target[1] ^ target[2] ^ target[3]
        return bytes(patched)

    def _try_gen1a(self, source: bytes, target: bytes) -> bool:
        """Return False only when the card does not acknowledge the Gen1A unlock."""
        unlocked = False
        try:
            # Flipper's current Gen1A poller begins with the 7-bit 0x40 wake-up.
            # This is also friendlier to ACR122U/PCSC, which can report a card as
            # removed immediately after HALT. If direct wake-up is declined, try
            # the conventional HALT + wake-up sequence after reselecting.
            for halt_first in (False, True):
                try:
                    unlocked = self._unlock_gen1a(halt_first=halt_first)
                except UidWriterError:
                    unlocked = False
                except Exception:
                    # ACR122U/PCSC may invalidate its card handle as soon as the
                    # fallback HALT is sent. Treat that as a failed Gen1A probe
                    # so the reconnecting Gen2 path still gets a chance.
                    if not halt_first:
                        raise
                    unlocked = False
                if unlocked:
                    break
                if not halt_first and not self._reconnect():
                    return False
            if not unlocked:
                return False

            self._set_raw_mode(crc=True, tx_last_bits=0)
            block = self._communicate(bytes((0x30, 0x00)))
            if len(block) < 16:
                raise UidWriterError("Gen1A block-0 read failed")
            patched = self._patched_block(block[:16], source, target)

            if not self._is_ack(self._communicate(bytes((0xA0, 0x00)))):
                raise UidWriterNak("Gen1A write command was not acknowledged")
            if not self._is_ack(self._communicate(patched)):
                raise UidWriterNak("Gen1A block data was not acknowledged")
            return True
        except UidWriterError:
            if unlocked:
                raise
            return False
        finally:
            try:
                self._set_raw_mode(crc=True, tx_last_bits=0)
            except Exception:
                pass

    def _unlock_gen1a(self, halt_first: bool) -> bool:
        self._set_raw_mode(crc=True, tx_last_bits=0)
        if halt_first:
            try:
                self._communicate(bytes((0x50, 0x00)))  # HALT has no response
            except UidWriterError:
                pass

        self._set_raw_mode(crc=False, tx_last_bits=7)
        if not self._is_ack(self._communicate(bytes((0x40,)))):
            return False

        self._set_raw_mode(crc=False, tx_last_bits=0)
        return self._is_ack(self._communicate(bytes((0x43,))))

    def _write_gen2(self, source: bytes, target: bytes) -> None:
        self._apdu([0xFF, 0x82, 0x00, 0x00, 0x06, *self.key_a])
        self._apdu([0xFF, 0x86, 0x00, 0x00, 0x05, 0x01, 0x00, 0x00, 0x60, 0x00])
        block = self._apdu([0xFF, 0xB0, 0x00, 0x00, 0x10])
        patched = self._patched_block(block, source, target)
        self._apdu([0xFF, 0xD6, 0x00, 0x00, 0x10, *patched])

    def _set_raw_mode(self, crc: bool, tx_last_bits: int) -> None:
        crc_bit = 0x80 if crc else 0x00
        payload = bytes(
            (
                0xD4,
                0x08,  # PN532 WriteRegister
                self._TX_MODE >> 8,
                self._TX_MODE & 0xFF,
                crc_bit,
                self._RX_MODE >> 8,
                self._RX_MODE & 0xFF,
                crc_bit,
                self._BIT_FRAMING >> 8,
                self._BIT_FRAMING & 0xFF,
                tx_last_bits & 0x07,
            )
        )
        reply = self._direct(payload)
        if len(reply) < 2 or reply[:2] != bytes((0xD5, 0x09)):
            raise UidWriterError("PN532 register configuration failed")

    def _communicate(self, payload: bytes) -> bytes:
        reply = self._direct(bytes((0xD4, 0x42)) + payload)
        if len(reply) < 3 or reply[:2] != bytes((0xD5, 0x43)):
            raise UidWriterError("Invalid PN532 InCommunicateThru response")
        if reply[2] != 0:
            raise UidWriterError(f"PN532 communication status 0x{reply[2]:02X}")
        return reply[3:]

    def _direct(self, payload: bytes) -> bytes:
        response, sw1, sw2 = self.reader.send_apdu(
            [0xFF, 0x00, 0x00, 0x00, len(payload), *payload]
        )
        if sw1 == 0x61:
            response, sw1, sw2 = self.reader.send_apdu([0xFF, 0xC0, 0x00, 0x00, sw2])
        if (sw1, sw2) != (0x90, 0x00):
            raise UidWriterError(f"ACR122U direct transmit returned {sw1:02X}{sw2:02X}")
        return bytes(response)

    def _apdu(self, command: list[int]) -> bytes:
        response, sw1, sw2 = self.reader.send_apdu(command)
        if (sw1, sw2) != (0x90, 0x00):
            raise UidWriterError(f"Card APDU returned {sw1:02X}{sw2:02X}")
        return bytes(response)

    def _reconnect(self) -> bool:
        self.reader.disconnect()
        return self.reader.wait_for_card(timeout=2)

    @staticmethod
    def _is_ack(response: bytes) -> bool:
        return bool(response) and response[0] & 0x0F == 0x0A
