"""Disposable script harness. All service commands and deployment paths are fake."""
import hashlib,json,os,shutil,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];COMMIT='a'*40;TARGET=os.uname().machine+'-unknown-linux-gnu'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def executable(path,text):path.write_text(text);path.chmod(0o755)
with tempfile.TemporaryDirectory(prefix='qbo-release-contract-')as temporary:
 root=Path(temporary)
 def setup(name,mode='normal'):
  work=root/name;work.mkdir();scripts=work/'scripts';scripts.mkdir();fake=work/'fake';fake.mkdir();(work/'lock').mkdir()
  base=work/'srv/apps/quickbooks-mcp/keepalive-rust';fragment=work/'etc/systemd/system/qbo-mcp-keepalive.service';fragment.parent.mkdir(parents=True)
  python=work/'srv/apps/quickbooks-mcp/bin/keepalive.py';python.parent.mkdir(parents=True);shutil.copy2(ROOT.parent/'bin/keepalive.py',python);shutil.copy2(ROOT.parent/'qbo-mcp-keepalive.service',fragment)
  for source in(ROOT/'deploy').glob('*.sh'):
   text=source.read_text().replace('/srv/apps/quickbooks-mcp',str(work/'srv/apps/quickbooks-mcp')).replace('/etc/systemd/system',str(work/'etc/systemd/system')).replace('/run/lock',str(work/'lock')).replace('$EUID == 0 && ','')
   executable(scripts/source.name,text)
  old=f'/usr/bin/python3 {python}';dropin=Path(str(fragment)+'.d/20-rust-release.conf');state=work/'state';state.write_text(json.dumps({'loaded':old,'reloads':0,'idle_checks':0,'mode':mode,'old':old,'dropin':str(dropin),'fragment':str(fragment)}))
  executable(fake/'hostname','#!/bin/sh\necho arbitrum\n')
  executable(fake/'runuser','#!/bin/sh\nshift 3\nprintf "%s\\n" "$*" >> "$TEST_LOG"\nexec "$@"\n')
  executable(fake/'install','''#!/usr/bin/python3
import os,sys
args=sys.argv[1:];out=[];i=0
while i<len(args):
 if args[i]in['-o','-g']:i+=2
 else:out.append(args[i]);i+=1
os.execv('/usr/bin/install',['install',*out])
''')
  executable(fake/'stat','''#!/bin/sh
if [ "$1" = -c ] && [ "$2" = %u ]; then echo 0; else exec /usr/bin/stat "$@"; fi
''')
  executable(fake/'systemctl','''#!/usr/bin/python3
import json,os,signal,sys
from pathlib import Path
path=Path(os.environ['TEST_STATE']);s=json.loads(path.read_text());a=sys.argv[1:];code=0;out=''
with open(os.environ['TEST_LOG'],'a')as log:log.write('systemctl '+' '.join(a)+'\\n')
if a[0]=='show':
 prop=a[a.index('-p')+1]
 if prop=='ExecStart':
  command=s['loaded'];actual='/wrong'if s['mode']=='wrong-path'else command.split()[0];out='{ path='+actual+' ; argv[]='+command+' ; ignore_errors=no ; start_time=[volatile] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }'
 elif prop=='ActiveState':
  s['idle_checks']+=1;out='active'if s['mode']=='active'or(s['mode']=='race'and s['idle_checks']>=3)else'inactive'
 elif prop=='DynamicUser':out='no'if s['mode']=='identity'else'yes'
 elif prop=='FragmentPath':out=s['fragment']
 else:raise AssertionError(a)
elif a[0]=='is-enabled':out='masked-runtime'if s['mode']=='masked'else'static'
elif a==['daemon-reload']:
 s['reloads']+=1
 if s['mode']=='reload-once'and s['reloads']==1:code=1
 elif s['mode']=='reload-always':code=1
 elif s['mode']=='term'and s['reloads']==1:os.kill(os.getppid(),signal.SIGTERM);code=143
 else:
  dropin=Path(s['dropin']);s['loaded']=dropin.read_text().split('ExecStart=')[-1].strip()if dropin.exists()else s['old']
else:raise AssertionError('Forbidden service operation '+repr(a))
path.write_text(json.dumps(s));print(out);sys.exit(code)
''')
  package=work/'package';package.mkdir();executable(package/'qbo-mcp-keepalive',f'#!/bin/sh\n[ "$#" = 1 ] && [ "$1" = --help ] || exit 99\nprintf "qbo-mcp-keepalive: configuration via QBO_KEEPALIVE_CONFIG; no work performed\\nsource={COMMIT}\\ntarget={TARGET}\\n"\n')
  (package/'source-commit').write_text(COMMIT+'\n');(package/'build-target').write_text(TARGET+'\n');(package/'baseline-sha256').write_text(digest(python)+'\n')
  def manifest(): (package/'manifest.sha256').write_text(''.join(f'{digest(package/file)}  {file}\n'for file in ['qbo-mcp-keepalive','source-commit','build-target','baseline-sha256']))
  manifest();env={**os.environ,'PATH':str(fake)+':'+os.environ['PATH'],'TEST_STATE':str(state),'TEST_LOG':str(work/'commands')}
  return work,scripts,package,base,dropin,state,env,manifest
 def run(fixture,script,arg):
  work,scripts,package,base,dropin,state,env,_=fixture;result=subprocess.run(['bash',str(scripts/script),str(arg)],env=env,capture_output=True,text=True,timeout=15)
  assert not list(base.glob('releases/.stage-*')) if base.exists()else True
  if (work/'commands').exists():
   for line in(work/'commands').read_text().splitlines():assert line.startswith('systemctl ')or line.endswith(' --help'),line
  return result
 cases=0
 for mode in ['normal','active','masked','identity','wrong-path','reload-once','reload-always','term','race']:
  f=setup(mode,mode);work,scripts,package,base,dropin,state,env,_=f;result=run(f,'install-release.sh',package)
  if mode=='normal':
   assert result.returncode==0,result.stderr;assert dropin.is_file()and(base/'current').is_symlink();assert json.loads(state.read_text())['loaded']==str(base/'current/qbo-mcp-keepalive')
   result=run(f,'rollback-release.sh',COMMIT);assert result.returncode==0,result.stderr;assert not dropin.exists()and not(base/'current').exists();assert json.loads(state.read_text())['loaded']==json.loads(state.read_text())['old'];cases+=1
  else:
   assert result.returncode!=0,(mode,result.stdout)
   if mode!='race':assert not dropin.exists(),(mode,result.stderr)
  cases+=1
 for mutation in ['manifest-path','wrong-target','dangling-release','baseline-tamper','extra-file','writable-base']:
  f=setup(mutation);work,scripts,package,base,dropin,state,env,manifest=f
  if mutation=='manifest-path':(package/'manifest.sha256').write_text(('0'*64)+'  ../outside\n')
  elif mutation=='wrong-target':(package/'build-target').write_text('wrong-unknown-linux-gnu\n');manifest()
  elif mutation=='dangling-release':(base/'releases').mkdir(parents=True);(base/'releases'/COMMIT).symlink_to(work/'absent')
  elif mutation=='baseline-tamper':(work/'srv/apps/quickbooks-mcp/bin/keepalive.py').write_text('changed')
  elif mutation=='writable-base':base.mkdir(parents=True);base.chmod(0o777)
  else:(package/'unexpected').write_text('extra')
  result=run(f,'install-release.sh',package);assert result.returncode!=0;assert not dropin.exists();cases+=1
 for mode in ['reload-once','reload-always','term']:
  f=setup('rollback-'+mode);work,scripts,package,base,dropin,state,env,_=f;assert run(f,'install-release.sh',package).returncode==0
  value=json.loads(state.read_text());value.update(mode=mode,reloads=0);state.write_text(json.dumps(value));result=run(f,'rollback-release.sh',COMMIT);assert result.returncode!=0;assert dropin.exists()and(base/'current').is_symlink();assert json.loads(state.read_text())['loaded']==str(base/'current/qbo-mcp-keepalive');cases+=1
 print(f'{cases} isolated install/rollback safety scenarios passed; only help and fake systemctl metadata/reload invoked')
