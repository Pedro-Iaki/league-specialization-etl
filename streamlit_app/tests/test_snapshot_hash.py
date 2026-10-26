from app_core.snapshot_hash import sha256_file


def test_text_file_hash_is_independent_of_line_endings(tmp_path):
    lf_file = tmp_path / "lf.json"
    crlf_file = tmp_path / "crlf.json"
    lf_file.write_bytes(b'{"value": 1}\n')
    crlf_file.write_bytes(b'{"value": 1}\r\n')

    assert sha256_file(lf_file, normalize_newlines=True) == sha256_file(crlf_file, normalize_newlines=True)
    assert sha256_file(lf_file) != sha256_file(crlf_file)
