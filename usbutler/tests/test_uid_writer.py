"""Unit tests for ACR122U UID block construction and protocol selection."""

from app.models.identifier import UidRotationOutcome, UidRotationProtocol
from app.services.uid_writer import (
    ACR122UidWriter,
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
        classify_writer_exception(RuntimeError("PC/SC transport failed"))
        == UidRotationOutcome.PCSC_ERROR
    )
