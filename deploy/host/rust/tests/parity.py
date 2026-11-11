"""Executed pinned watchdog oracle, fake SSE/HTTP/TLS only; no provider access."""
import datetime,hashlib,http.server,importlib.util,json,os,queue,re,socket,ssl,statistics,subprocess,tempfile,threading,time,urllib.request
from pathlib import Path
os.environ["NO_PROXY"]="*";os.environ["no_proxy"]="*"
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT.parent/'bin/keepalive.py'
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()=='c3d00adfba5b2311c5dd39ed608c19cd31dff7c8be06a12325fb556d4bc6dc46'
spec=importlib.util.spec_from_file_location('oracle',SOURCE);ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref);ref.CALL_TIMEOUT=.5
PROFILE='release'if os.environ.get('QBO_TEST_RELEASE')=='1'else'debug'
subprocess.run(['cargo','test','--offline','--manifest-path',str(ROOT/'Cargo.toml'),'--test','driver','--no-run']+(['--release']if PROFILE=='release'else[]),check=True)
DRIVER=max((p for p in(ROOT/f'target/{PROFILE}/deps').glob('driver-*')if p.is_file()and os.access(p,os.X_OK)),key=lambda p:p.stat().st_mtime_ns)
class Server(http.server.ThreadingHTTPServer):
 daemon_threads=True
 def handle_error(self,request,client_address):
  # A client intentionally closes rejected redirects/TLS streams.
  if not isinstance(os.sys.exception(),(BrokenPipeError,ConnectionResetError)):super().handle_error(request,client_address)
class Handler(http.server.BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def log_message(self,*args):pass
 def answer(self,status,body=b'',headers=()):
  self.send_response(status);self.send_header('Content-Length',str(len(body)))
  for key,value in headers:self.send_header(key,value)
  self.end_headers();self.wfile.write(body)
 def do_GET(self):
  if self.path in getattr(self.server,'redirects',{}):
   self.server.requests.append(('GET',self.path));status,target=self.server.redirects[self.path];self.answer(status,headers=[('Location',target)]);return
  if self.path in ['/final','/end']:self.server.requests.append(('GET',self.path));self.answer(self.server.final_status,b'ok');return
  if self.path!='/sse':
   assert self.headers.get('Authorization')is None
   self.server.requests.append(('GET',self.path));self.answer(self.server.status);return
  if self.server.case=='get-fail':self.answer(503);return
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();events=queue.Queue();self.server.events=events
  endpoint='/fixture/message?session=synthetic-secret'
  if self.server.case=='absolute':endpoint='https://unused.test'+endpoint
  initial=('data: '+endpoint if self.server.case=='implicit'else'event: endpoint\ndata: '+endpoint)+'\n\n'
  self.wfile.write(initial.encode());self.wfile.flush()
  try:
   while True:
    value=events.get(timeout=2)
    if value is None:return
    time.sleep(.025)
    self.wfile.write(('event: message\ndata: ignored\ndata: '+json.dumps(value)+'\n\n').encode());self.wfile.flush()
  except (OSError,queue.Empty):pass
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));self.server.requests.append(('POST',self.path,body,self.client_address[1]))
  if self.path in getattr(self.server,'redirects',{}):
   status,target=self.server.redirects[self.path];self.answer(status,headers=[('Location',target)]);return
  if self.path=='/slack':self.answer(self.server.status,self.server.slack_body);return
  if self.server.case=='post-fail':self.answer(403);return
  self.answer(202)
  if 'id'not in body:return
  if self.server.case=='timeout'and body['id']==2:return
  if body['id']==1:reply={'jsonrpc':'2.0','id':1,'error':{'code':-1}}if self.server.case=='init-error'else{'jsonrpc':'2.0','id':1,'result':{}}
  else:
   text=json.dumps({'CompanyName':'Other company'if self.server.case=='wrong'else'Synthetic company'})
   if self.server.case=='bad-json':text='not json'
   if self.server.case=='tool-error':text='synthetic failure'
   reply={'jsonrpc':'2.0','id':2,'result':{'content':[{'type':'text','text':text}],'isError':self.server.case=='tool-error'}}
  if self.server.case=='rpc-error'and body['id']==2:reply={'id':2,'error':{'code':-32000,'message':'Synthetic é failure'}}
  self.server.events.put(reply)
def normalize(result):
 result=list(result);result[1]=re.sub(r', \d+\.\ds\)',', <elapsed>s)',result[1]);return result
with tempfile.TemporaryDirectory(prefix='qbo-parity-')as temporary:
 root=Path(temporary)
 def rust(value):
  value.setdefault('timeout',.5);(root/'input').write_text(json.dumps(value));subprocess.run([str(DRIVER),'--exact','fixture_driver'],env={**os.environ,'FIXTURE_INPUT':str(root/'input'),'FIXTURE_OUTPUT':str(root/'output')},stdout=subprocess.DEVNULL,check=True,timeout=8);return json.loads((root/'output').read_text())
 replies=[]
 for value in [None,True,False,[],{},"'quotes\"",'\x00\x1f\x7f','\u0085\u00a0','\u200b\u2028\u2029','\ue000','\U000f0000','é😀','\u0378']:
  replies.append({'result':{'content':[{'text':json.dumps({'CompanyName':value})}]}})
  replies.append({'error':{'code':-1,'message':value}})
 class FixtureSession:
  def __init__(self,*a,**k):pass
  def post(self,payload):pass
  def wait(self,id,timeout):return self.reply if id==2 else{}
  def close(self):pass
 original_session=ref.SseSession;ref.SseSession=FixtureSession
 try:
  expected=[]
  for reply in replies:
   FixtureSession.reply=reply;expected.append(ref.check_company({'slug':'fixture','port':1,'expect':'Synthetic company'}))
 finally:ref.SseSession=original_session
 actual=rust({'op':'diagnostics','replies':replies})['result'];assert [list(v)for v in expected]==actual,(expected,actual)
 server=Server(('127.0.0.1',0),Handler);server.status=401;server.requests=[];server.slack_body=b'ok';threading.Thread(target=server.serve_forever,daemon=True).start();timings={'python':[],'rust':[]};count=len(replies)
 try:
  for case in ['good','absolute','implicit','wrong','bad-json','tool-error','rpc-error','init-error','get-fail','post-fail','timeout']:
   records=[];results=[]
   for backend in ['python','rust']:
    server.case=case;server.requests=[];start=time.perf_counter()
    if backend=='python':result=ref.check_company({'slug':'fixture','port':server.server_port,'expect':'Synthetic company'});elapsed=(time.perf_counter()-start)*1000
    else:reply=rust({'op':'company','port':server.server_port});result=reply['result'];elapsed=reply['elapsed_ms']
    records.append(list(server.requests));results.append(normalize(result))
    if case in ['good','absolute','implicit']:timings[backend].append(elapsed)
    if hasattr(server,'events'):server.events.put(None)
   assert results[0]==results[1],(case,results)
   assert [r[:3]for r in records[0]]==[r[:3]for r in records[1]],(case,records)
   if len(records[1])==3:assert len({r[3]for r in records[1]})==1,('Rust POST connection not reused',records[1])
   count+=1
  for ok in [False,True]:
   for heartbeat in [False,True]:
    expected=(f'*QuickBooks MCP keep-alive FAILED* (2026-11-11)\nsynthetic report\nRe-authorize: see Systems registry entry “QuickBooks Online MCP”.'if not ok else'f'if heartbeat else None)
    if expected=='f':expected='QuickBooks MCP keep-alive: all companies OK (2026-11-11)\nsynthetic report'
    assert rust({'op':'notification','ok':ok,'heartbeat':heartbeat})['result']==expected;count+=1
  for label,case,weekday,force in [('quiet','good',None,False),('forced','good',None,True),('weekly','good',datetime.date.today().weekday(),False),('other-day','good',(datetime.date.today().weekday()+1)%7,False),('failure','wrong',None,False)]:
   settings=root/'config.json';settings.write_text(json.dumps({'targets':[{'slug':'fixture','port':server.server_port,'expect':'Synthetic company'}],'heartbeat_weekday':weekday}))
   outputs=[];posts=[]
   for command in [[os.sys.executable,str(SOURCE)],[str(ROOT/f'target/{PROFILE}/qbo-mcp-keepalive')]]:
    server.case=case;server.status=200;server.requests=[]
    result=subprocess.run(command,env={**os.environ,'QBO_KEEPALIVE_CONFIG':str(settings),'QBO_KEEPALIVE_TIMEOUT':'.5','QBO_KEEPALIVE_HEARTBEAT':'1'if force else'0','SLACK_WEBHOOK_URL':f'http://127.0.0.1:{server.server_port}/slack'},capture_output=True,text=True,timeout=10)
    clean=lambda text:re.sub(r', \d+\.\ds\)',', <elapsed>s)',text)
    outputs.append((result.returncode,clean(result.stdout)))
    posts.append([clean(r[2]['text'])for r in server.requests if r[0]=='POST'and r[1]=='/slack'])
    if hasattr(server,'events'):server.events.put(None)
   assert outputs[0]==outputs[1],(label,outputs);assert posts[0]==posts[1],(label,posts)
   assert len(posts[0])==int(force or label in ['weekly','failure']);count+=1
  subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(root/'key'),'-out',str(root/'cert'),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
  tls=Server(('127.0.0.1',0),Handler);context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(root/'cert',root/'key');tls.socket=context.wrap_socket(tls.socket,server_side=True);tls.requests=[];tls.case='gate';tls.slack_body=b'ok';threading.Thread(target=tls.serve_forever,daemon=True).start()
  original=ref.urllib.request.urlopen;trusted=ssl.create_default_context(cafile=str(root/'cert'));ref.urllib.request.urlopen=lambda *a,**kw:original(*a,context=trusted,**kw)
  try:
   for status in [200,202,301,304,401,403,404,503]:
    tls.status=status;host=f'localhost:{tls.server_port}';want=ref.check_gate(host,'fixture');got=rust({'op':'gate','host':host,'certificate':str(root/'cert')})['result'];assert list(want)==got,(status,want,got);count+=1
   for status in [301,302,303,307,308]:
    tls.redirects={'/fixture/healthz':(status,'/final')};tls.final_status=401;host=f'localhost:{tls.server_port}'
    want=ref.check_gate(host,'fixture');got=rust({'op':'gate','host':host,'certificate':str(root/'cert')})['result'];assert list(want)==got,(status,want,got);count+=1
    tls.redirects={'/slack':(status,'/final')};tls.final_status=200;webhook=f'https://localhost:{tls.server_port}/slack';os.environ['SLACK_WEBHOOK_URL']=webhook;records=[];errors=[]
    for backend in ['python','rust']:
     tls.requests=[]
     if backend=='python':
      try:ref.slack('synthetic message');error=None
      except Exception as exception:error=str(exception)
     else:error=rust({'op':'slack','webhook':webhook,'certificate':str(root/'cert')})['result']
     records.append([(r[0],r[1])for r in tls.requests]);errors.append(error)
    assert records[0]==records[1],(status,records)
    assert records[0]==([('POST','/slack'),('GET','/final')]if status in [301,302,303]else[('POST','/slack')]),(status,records)
    assert all(error is None for error in errors)if status in [301,302,303]else all(error and str(status)in error for error in errors)
    count+=1
   tls.redirects={}
   tls.status=401
   for host,certificate in [(f'localhost:{tls.server_port}',None),(f'127.0.0.1:{tls.server_port}',str(root/'cert'))]:
    got=rust({'op':'gate','host':host,'certificate':certificate})['result'];assert got[0]is False and 'unreachable'in got[1];assert host not in got[1];count+=1
   for body in [b'ok',b' ok\n',b'not okay']:
    tls.status=200;tls.slack_body=body;webhook=f'https://localhost:{tls.server_port}/slack';os.environ['SLACK_WEBHOOK_URL']=webhook
    try:ref.slack('synthetic message');want=None
    except RuntimeError as error:want=str(error)
    got=rust({'op':'slack','webhook':webhook,'certificate':str(root/'cert')})['result'];assert want==got,(want,got);count+=1
  finally:ref.urllib.request.urlopen=original;os.environ.pop('SLACK_WEBHOOK_URL',None);tls.shutdown();tls.server_close()
 finally:server.shutdown();server.server_close()
 print(json.dumps({'parity_cases':count,'handshake_ms':timings,'median_ms':{k:statistics.median(v)for k,v in timings.items()}},indent=2))
