"""A keyring in a file, for a connector started as its own process on a system with no keyring: `test_preview_outlives`
names it in PYTHON_KEYRING_BACKEND. Only tests load it; Windows does not, as sign-in records there are in a file."""

import json
import os
from pathlib import Path

from keyring.backend import KeyringBackend


class FileBackend(KeyringBackend):
    priority = 1

    @staticmethod
    def _file() -> Path:
        return Path(os.environ["LOCALAPPDATA"]) / "test-keyring.json"

    def _read(self) -> dict:
        return json.loads(self._file().read_text()) if self._file().exists() else {}

    def get_password(self, service, user):
        return self._read().get(f"{service}/{user}")

    def set_password(self, service, user, password):
        self._file().parent.mkdir(parents=True, exist_ok=True)
        self._file().write_text(json.dumps({**self._read(), f"{service}/{user}": password}))

    def delete_password(self, service, user):
        records = self._read()
        records.pop(f"{service}/{user}", None)
        self._file().write_text(json.dumps(records))
