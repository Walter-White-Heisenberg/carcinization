"""Atomic writes within this independent workspace; no in-place truncation."""
from pathlib import Path
import os,uuid
from v2_validation import assert_output_path
ROOT=Path(__file__).resolve().parent.parent
FROZEN=ROOT/'reference'/'excluded_legacy_study'

def safe_write_bytes(path,data):
    path=assert_output_path(path,ROOT,FROZEN)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.parent/('write_'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        assert_output_path(path,ROOT,FROZEN)
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()
    return len(data)

def safe_write_text(path,text,encoding='utf-8'):
    safe_write_bytes(path,text.encode(encoding));return len(text)
