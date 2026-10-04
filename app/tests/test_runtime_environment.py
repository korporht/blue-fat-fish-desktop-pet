"""Fresh-process coverage of inherited DLL paths, TLS pairing and audio initialization."""
import os
from pathlib import Path
import sys,subprocess,json,unittest
APP=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name=='nt','Windows native DLL loading regression')
class RuntimeTests(unittest.TestCase):
    def test_fresh_qt_tls_and_audio_load_this_python_ssl_pair_before_foreign_path(self):
        # The external tool PATH remains inherited, just as in a desktop launch.
        # Use a fresh process: a previously loaded DLL could hide the first-use bug.
        script=r'''
import ctypes,hashlib,json,os,sys
ctypes.windll.kernel32.SetErrorMode(0x0001|0x8000)
from runtime_environment import prepare_runtime
prepare_runtime()
before=os.environ['PATH'];prepare_runtime();assert os.environ['PATH']==before
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QSslSocket
from PySide6.QtMultimedia import QMediaDevices
app=QApplication([])
version=QSslSocket.sslLibraryVersionString()
devices=QMediaDevices.audioOutputs()
k=ctypes.windll.kernel32
k.GetModuleHandleW.argtypes=[ctypes.c_wchar_p];k.GetModuleHandleW.restype=ctypes.c_void_p
k.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint]
loaded={}
for name in ('libssl-3-x64.dll','libcrypto-3-x64.dll'):
    handle=k.GetModuleHandleW(name)
    if handle:
        buffer=ctypes.create_unicode_buffer(32768)
        k.GetModuleFileNameW(handle,buffer,len(buffer));loaded[name]=buffer.value
print(json.dumps({'base':sys.base_prefix,'libraries':loaded,'tls':version,'outputs':len(devices)}))
'''
        env=dict(os.environ,QT_QPA_PLATFORM='offscreen')
        # Parent tests may already have prepared PATH. Put any conflicting
        # external OpenSSL directory first again to exercise the real trigger.
        foreign=[path for path in env.get('PATH','').split(os.pathsep)
                 if path and (Path(path)/'libssl-3-x64.dll').is_file()
                 and Path(path).resolve()!= (Path(sys.base_prefix)/'DLLs').resolve()]
        env['PATH']=os.pathsep.join(foreign+[env.get('PATH','')])
        result=subprocess.run([sys.executable,'-c',script],cwd=APP,env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout.strip())
        self.assertTrue(data['tls'])
        # These names are used by the affected CPython 3.11 Windows build.
        if (Path(data['base'])/'DLLs/libssl-3-x64.dll').is_file():
            self.assertEqual(len(data['libraries']),2)
            for path in data['libraries'].values():
                self.assertEqual(Path(path).resolve().parent,(Path(data['base'])/'DLLs').resolve())

if __name__=='__main__':unittest.main()
