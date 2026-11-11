"""Package-build guards with a fake compiler, never a production artifact."""
import hashlib,json,os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SHA='b'*40;TARGET=os.uname().machine+'-unknown-linux-gnu'
with tempfile.TemporaryDirectory(prefix='qbo-build-contract-')as temporary:
 root=Path(temporary);app=root/'app';deploy=app/'deploy';deploy.mkdir(parents=True);script=deploy/'build-release.sh';script.write_text((ROOT/'deploy/build-release.sh').read_text());fake=root/'fake';fake.mkdir()
 def command(name,text):path=fake/name;path.write_text(text);path.chmod(0o755)
 command('git',f'''#!/usr/bin/python3
import os,sys
args=sys.argv
if args[-1]=='--show-toplevel':print({str(root)!r})
elif 'status'in args:print(' M source'if os.environ.get('CASE')=='dirty'else'',end='')
elif args[-1]=='origin/main'and os.environ.get('CASE')=='unpublished':print('c'*40)
else:print({SHA!r})
''')
 command('cargo',f'''#!/usr/bin/python3
import os,sys
from pathlib import Path
a=sys.argv[1:];target=a[a.index('--target')+1];directory=Path(a[a.index('--target-dir')+1]);assert target=={TARGET!r};assert '--locked'in a and '--release'in a;assert os.environ['QBO_BUILD_COMMIT']=={SHA!r};assert os.environ['QBO_BUILD_TARGET']==target
path=directory/target/'release/qbo-mcp-keepalive';path.parent.mkdir(parents=True,exist_ok=True)
message='wrong help'if os.environ.get('CASE')=='bad-help'else'qbo-mcp-keepalive: configuration via QBO_KEEPALIVE_CONFIG; no work performed\\nsource='+os.environ['QBO_BUILD_COMMIT']+'\\ntarget='+target
path.write_text('#!/usr/bin/python3\\nimport sys\\nassert sys.argv[1:] == ["--help"]\\nprint('+repr(message)+')\\n');path.chmod(0o755)
''')
 for case in ['success','dirty','unpublished','bad-help','existing']:
  output=root/case
  if case=='existing':output.mkdir();(output/'keep').write_text('untouched')
  result=subprocess.run(['bash',str(script),str(output)],env={**os.environ,'PATH':str(fake)+':'+os.environ['PATH'],'CASE':case,'CARGO_BUILD_TARGET':'wasm32-unknown-unknown'},capture_output=True,text=True,timeout=15)
  if case=='success':
   assert result.returncode==0,result.stderr;assert(output/'source-commit').read_text().strip()==SHA;assert(output/'build-target').read_text().strip()==TARGET
   for line in(output/'manifest.sha256').read_text().splitlines():
    digest,name=line.split();assert hashlib.sha256((output/name).read_bytes()).hexdigest()==digest
  else:
   assert result.returncode!=0,(case,result.stdout)
   if case=='existing':assert(output/'keep').read_text()=='untouched'
   else:assert not output.exists()
  assert not list(root.glob('.qbo-package.*'))
 print('Five package-build guard scenarios passed with fake compiler and explicit native target')
