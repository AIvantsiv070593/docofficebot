import pytest
from pathlib import Path

from src.services.download import _download_one


class _FakeBot:
    def __init__(self, fails: int = 2) -> None:
        self.fails = fails
        self.calls = 0

    async def download(self, file_id, destination, timeout=30):
        self.calls += 1
        if self.calls <= self.fails:
            raise TimeoutError()
        Path(destination).write_bytes(b"ok")


@pytest.mark.asyncio
async def test_download_retries_then_ok(tmp_path: Path):
    bot = _FakeBot(fails=2)
    dest = tmp_path / "a.jpg"
    await _download_one(bot, "fid", dest)  # type: ignore[arg-type]
    assert dest.read_bytes() == b"ok"
    assert bot.calls == 3


@pytest.mark.asyncio
async def test_download_gives_up(tmp_path: Path):
    bot = _FakeBot(fails=99)
    with pytest.raises(RuntimeError, match="TimeoutError"):
        await _download_one(bot, "fid", tmp_path / "a.jpg")  # type: ignore[arg-type]
