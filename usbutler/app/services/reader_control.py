import threading


class ReaderControl:
    """Coordinates exclusive access to the NFC reader between services."""

    _owner: str = "door"
    _shared_lock = threading.Lock()

    def __init__(self, default_owner: str = "door") -> None:
        self.default_owner = default_owner

    def get_owner(self) -> str:
        with type(self)._shared_lock:
            return type(self)._owner or self.default_owner

    def set_owner(self, owner: str) -> str:
        with type(self)._shared_lock:
            type(self)._owner = owner
            return owner

    def reset_to_default(self) -> str:
        return self.set_owner(self.default_owner)


_reader_control_instance = ReaderControl()


def get_reader_control() -> ReaderControl:
    return _reader_control_instance


__all__ = ["ReaderControl", "get_reader_control"]
