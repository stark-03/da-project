import pytest

from app.services.storage import DocumentStorage, StorageError


def test_save_read_delete_roundtrip(tmp_path):
    storage = DocumentStorage(tmp_path)
    name = storage.save(b"data", "png")
    assert name.endswith(".png") and len(name) == 36
    assert storage.read(name) == b"data"
    assert storage.delete(name) is True
    assert storage.delete(name) is False


def test_random_names_are_unique(tmp_path):
    storage = DocumentStorage(tmp_path)
    assert storage.save(b"a", "png") != storage.save(b"a", "png")


@pytest.mark.parametrize("bad", ["../secret.png", "..", "a/b.png", "/etc/passwd", ".hidden", ""])
def test_path_traversal_rejected(tmp_path, bad):
    with pytest.raises(StorageError):
        DocumentStorage(tmp_path).read(bad)


def test_missing_file_raises(tmp_path):
    with pytest.raises(StorageError):
        DocumentStorage(tmp_path).read("0" * 32 + ".png")
