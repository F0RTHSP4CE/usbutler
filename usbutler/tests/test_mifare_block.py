"""Unit tests for normal ACR122U MIFARE data-block access."""

import uuid

import pytest

from app.services.mifare_block import (
    ACR122MifareBlockStore,
    validate_data_block,
)


class ScriptedReader:
    def __init__(self, replies):
        self.replies = list(replies)
        self.commands = []

    def send_apdu(self, command):
        self.commands.append(command)
        return self.replies.pop(0)

    def is_connected(self):
        return True

    def wait_for_card(self, timeout=1):
        return True


def ok(data=()):
    return list(data), 0x90, 0x00


def read_sequence(raw):
    return [ok(), ok(), ok(raw)]


def write_sequence(update_status=(0x90, 0x00)):
    return [ok(), ok(), ([], *update_status)]


def test_read_uuid_uses_key_a_and_configured_data_block():
    value = uuid.UUID("12345678-1234-4abc-9234-1234567890ab")
    reader = ScriptedReader(read_sequence(value.bytes))
    store = ACR122MifareBlockStore(reader, block_number=4)

    assert store.read_uuid() == str(value)
    assert reader.commands == [
        [0xFF, 0x82, 0x00, 0x00, 0x06, *bytes.fromhex("FFFFFFFFFFFF")],
        [0xFF, 0x86, 0x00, 0x00, 0x05, 0x01, 0x00, 0x04, 0x60, 0x00],
        [0xFF, 0xB0, 0x00, 0x04, 0x10],
    ]


def test_read_rejects_non_v4_block_data():
    reader = ScriptedReader(read_sequence(bytes(16)))
    assert ACR122MifareBlockStore(reader).read_uuid() is None


@pytest.mark.parametrize("block", [0, 3, 7, 63, 143, 159])
def test_rejects_manufacturer_and_sector_trailer_blocks(block):
    with pytest.raises(ValueError):
        validate_data_block(block)


@pytest.mark.parametrize("block", [1, 2, 4, 62, 128, 142, 254])
def test_accepts_classic_data_blocks(block):
    assert validate_data_block(block) == block


def test_ack_with_stale_read_retries_and_verifies_same_target():
    target = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    stale = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    replies = (
        write_sequence()
        + read_sequence(stale.bytes)
        + write_sequence()
        + read_sequence(target.bytes)
    )
    reader = ScriptedReader(replies)
    store = ACR122MifareBlockStore(reader, max_attempts=2, retry_delay_seconds=0)

    result = store.write_and_verify(str(target))

    assert result.verified is True
    assert result.attempts == 2
    updates = [command for command in reader.commands if command[1] == 0xD6]
    assert len(updates) == 2
    assert updates[0][-16:] == list(target.bytes) == updates[1][-16:]


def test_failed_update_is_success_when_fresh_read_has_target():
    target = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    reader = ScriptedReader(
        write_sequence(update_status=(0x63, 0x00)) + read_sequence(target.bytes)
    )
    result = ACR122MifareBlockStore(
        reader, max_attempts=1, retry_delay_seconds=0
    ).write_and_verify(str(target))

    assert result.verified is True
    assert "write error" in result.detail


def test_unverified_write_returns_failure_after_bound():
    target = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    stale = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    reader = ScriptedReader(write_sequence() + read_sequence(stale.bytes))
    result = ACR122MifareBlockStore(
        reader, max_attempts=1, retry_delay_seconds=0
    ).write_and_verify(str(target))

    assert result.verified is False
    assert result.observed_uuid == str(stale)
    assert "different UUID" in result.detail


def test_write_rejects_card_swap_before_updating_data():
    target = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    reader = ScriptedReader([ok(bytes.fromhex("DEADBEEF"))] * 2)
    result = ACR122MifareBlockStore(
        reader, max_attempts=1, retry_delay_seconds=0
    ).write_and_verify(str(target), expected_uid="01020304")

    assert result.verified is False
    assert "different card" in result.detail
    assert not any(command[1] == 0xD6 for command in reader.commands)
