"""Opt-in offline subprocess guard: add this directory to PYTHONPATH for tests only."""
import ipaddress,json,os,socket
_log=os.environ.get('TRUSTFORK_OFFLINE_GUARD_LOG')
if _log:
 _connect=socket.socket.connect;_connect_ex=socket.socket.connect_ex;_lookup=socket.getaddrinfo
 def _local(host):
  if host in (None,'',b''):return True
  text=host.decode() if isinstance(host,bytes) else str(host)
  if text.rstrip('.').lower()=='localhost':return True
  try:address=ipaddress.ip_address(text.split('%',1)[0])
  except ValueError:return False
  return address.is_loopback or address.is_unspecified
 def _deny(operation,host):
  fd=os.open(_log,os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
  try:os.write(fd,(json.dumps({'operation':operation,'host':str(host),'blocked':True})+'\n').encode())
  finally:os.close(fd)
  raise RuntimeError('Offline external network forbidden: '+operation+' '+str(host))
 def _checked_connect(self,address):
  if self.family in (socket.AF_INET,socket.AF_INET6) and not _local(address[0]):_deny('connect',address[0])
  return _connect(self,address)
 def _checked_connect_ex(self,address):
  if self.family in (socket.AF_INET,socket.AF_INET6) and not _local(address[0]):_deny('connect_ex',address[0])
  return _connect_ex(self,address)
 def _checked_lookup(host,*args,**kwargs):
  if not _local(host):_deny('getaddrinfo',host)
  return _lookup(host,*args,**kwargs)
 socket.socket.connect=_checked_connect;socket.socket.connect_ex=_checked_connect_ex;socket.getaddrinfo=_checked_lookup
