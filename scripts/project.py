"""Portable local status storage for the public source checkout."""
from pathlib import Path
import argparse,json,os,uuid
ROOT=Path(__file__).resolve().parents[1]
def put(path,obj):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Output must stay inside this checkout')
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name('write_'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n','utf8')
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['status'])
    parser.parse_args();print((ROOT/'PROJECT_STATE.json').read_text('utf8'))
if __name__=='__main__':main()
