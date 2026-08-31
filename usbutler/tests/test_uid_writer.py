"""Unit tests for ACR122U UID block construction and protocol selection."""

from app.models.identifier import UidRotationOutcome, UidRotationProtocol
from app.services.uid_writer import (
    ACR122UidWriter,
    UidWriteResult,
    UidWriterError,
    UidWriterNak,
    classify_writer_exception,
)


class DummyReader:
    def disconnect(self):
        pass

    def wait_for_card(self, timeout=2):
        return True


def test_block_patch_preserves_manufacturer_bytes_and_updates_bcc():
    block = bytes.fromhex("01020304040000112233445566778899")
    patched = ACR122UidWriter._patched_block(
        block, bytes.fromhex("01020304"), bytes.fromhex("A1B2C3D4")
    )
    assert patched[:4] == bytes.fromhex("A1B2C3D4")
    assert patched[4] == 0x04
    assert patched[5:] == block[5:]


def test_block_patch_rejects_card_swap():
    block = bytes.fromhex("01020304040000112233445566778899")
    try:
        ACR122UidWriter._patched_block(
            block, bytes.fromhex("FFFFFFFF"), bytes.fromhex("A1B2C3D4")
        )
    except UidWriterError as exc:
        assert "different card" in str(exc)
    else:
        raise AssertionError("card swap was not rejected")


def test_gen1a_acknowledgement_is_not_confirmation(monkeypatch):
    writer = ACR122UidWriter(DummyReader())
    monkeypatch.setattr(writer, "_try_gen1a", lambda source, target: True)
    result = writer.write_uid("01020304", "A1B2C3D4")
    assert result.protocol == UidRotationProtocol.GEN1A
    assert result.outcome == UidRotationOutcome.ACKNOWLEDGED
    assert "awaiting a later scan" in result.detail


def test_gen2_fallback(monkeypatch):
    writer = ACR122UidWriter(DummyReader())
    monkeypatch.setattr(writer, "_try_gen1a", lambda source, target: False)
    monkeypatch.setattr(writer, "_reconnect", lambda: True)
    monkeypatch.setattr(writer, "_write_gen2", lambda source, target: None)
    result = writer.write_uid("01020304", "A1B2C3D4")
    assert result.protocol == UidRotationProtocol.GEN2
    assert result.outcome == UidRotationOutcome.ACKNOWLEDGED


def test_unsupported_card_returns_auditable_result(monkeypatch):
    writer = ACR122UidWriter(DummyReader())
    monkeypatch.setattr(writer, "_try_gen1a", lambda source, target: False)
    monkeypatch.setattr(writer, "_reconnect", lambda: True)
    monkeypatch.setattr(
        writer,
        "_write_gen2",
        lambda source, target: (_ for _ in ()).throw(UidWriterError("read only")),
    )
    result = writer.write_uid("01020304", "A1B2C3D4")
    assert result.outcome == UidRotationOutcome.UNSUPPORTED
    assert "read only" in result.detail


def test_writer_failures_have_stable_audit_classifications():
    assert classify_writer_exception(UidWriterNak("NAK")) == UidRotationOutcome.NAK
    assert classify_writer_exception(TimeoutError()) == UidRotationOutcome.TIMEOUT
    assert (
        classify_writer_exception(RuntimeError("card disconnected"))
        == UidRotationOutcome.CONNECTION_LOSS
    )
    assert (
        classify_writer_exception(RuntimeError("Card was removed. (0x80100069)"))
        == UidRotationOutcome.CONNECTION_LOSS
    )
    assert (
        classify_writer_exception(RuntimeError("PC/SC transport failed"))
        == UidRotationOutcome.PCSC_ERROR
    )


def test_transient_write_failure_is_retried(monkeypatch):
    writer = ACR122UidWriter(DummyReader(), max_attempts=3, retry_delay_seconds=0)
    results = iter(
        (
            UidWriteResult(
                UidRotationProtocol.GEN1A,
                UidRotationOutcome.CONNECTION_LOSS,
                "card removed",
            ),
            UidWriteResult(
                UidRotationProtocol.GEN1A,
                UidRotationOutcome.ACKNOWLEDGED,
                "write acknowledged",
            ),
        )
    )
    reconnects = []
    monkeypatch.setattr(writer, "_write_uid_once", lambda source, target: next(results))
    monkeypatch.setattr(writer, "_reconnect", lambda: reconnects.append(True) or True)

    result = writer.write_uid("01020304", "A1B2C3D4")

    assert result.outcome == UidRotationOutcome.ACKNOWLEDGED
    assert reconnects == [True]
    assert "hardware attempt 2/3" in result.detail


def test_explicit_nak_is_not_retried(monkeypatch):
    writer = ACR122UidWriter(DummyReader(), max_attempts=3, retry_delay_seconds=0)
    calls = []
    monkeypatch.setattr(
        writer,
        "_write_uid_once",
        lambda source, target: calls.append(True)
        or UidWriteResult(
            UidRotationProtocol.GEN1A,
            UidRotationOutcome.NAK,
            "card returned NAK",
        ),
    )

    result = writer.write_uid("01020304", "A1B2C3D4")

    assert result.outcome == UidRotationOutcome.NAK
    assert calls == [True]


def test_gen1a_probe_uses_direct_seven_bit_wakeup_before_halt(monkeypatch):
    writer = ACR122UidWriter(DummyReader(), max_attempts=1)
    block = bytes.fromhex("01020304040000112233445566778899")
    frames = []

    monkeypatch.setattr(writer, "_set_raw_mode", lambda **kwargs: None)

    def communicate(payload):
        frames.append(payload)
        if payload == bytes((0x30, 0x00)):
            return block
        return bytes((0x0A,))

    monkeypatch.setattr(writer, "_communicate", communicate)
    monkeypatch.setattr(
        writer,
        "_reconnect",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected reconnect")),
    )

    assert writer._try_gen1a(bytes.fromhex("01020304"), bytes.fromhex("A1B2C3D4"))
    assert frames[:2] == [bytes((0x40,)), bytes((0x43,))]
    assert bytes((0x50, 0x00)) not in frames


def test_pcsc_card_removal_during_halt_still_reaches_gen2(monkeypatch):
    writer = ACR122UidWriter(DummyReader(), max_attempts=1)
    unlock_calls = []
    gen2_writes = []

    def unlock(halt_first):
        unlock_calls.append(halt_first)
        if halt_first:
            raise RuntimeError("Card was removed. (0x80100069)")
        return False

    monkeypatch.setattr(writer, "_unlock_gen1a", unlock)
    monkeypatch.setattr(writer, "_set_raw_mode", lambda **kwargs: None)
    monkeypatch.setattr(writer, "_reconnect", lambda: True)
    monkeypatch.setattr(
        writer, "_write_gen2", lambda source, target: gen2_writes.append(True)
    )

    result = writer.write_uid("01020304", "A1B2C3D4")

    assert unlock_calls == [False, True]
    assert gen2_writes == [True]
    assert result.protocol == UidRotationProtocol.GEN2
    assert result.outcome == UidRotationOutcome.ACKNOWLEDGED
