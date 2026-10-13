"""Deterministic ORIGINAL adapter-only zipapp; no external GPL source embedded."""
from pathlib import Path
import hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]
def package():
    folder=ROOT/'build/actors';folder.mkdir(parents=True,exist_ok=True);path=folder/'musesfish-timed-v1.pyz'
    files={str(p.relative_to(ROOT)):p.read_bytes() for p in sorted((ROOT/'jieqi').glob('*.py'))}
    files['adapters/__init__.py']=b''
    files['adapters/musesfish_worker.py']=(ROOT/'adapters/musesfish_worker.py').read_bytes()
    files['__main__.py']=(ROOT/'tools/musesfish_timed_worker.py').read_bytes()
    temp=path.with_suffix('.tmp')
    with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,raw in sorted(files.items()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            z.writestr(info,raw)
    temp.replace(path)
    record=dict(schema='jieqi-musesfish-timed-package-v1',path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        contents_sha256={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()})
    (folder/'musesfish-timed-v1.json').write_text(json.dumps(record,indent=2)+'\n');return record
if __name__=='__main__':print(json.dumps(package()))
