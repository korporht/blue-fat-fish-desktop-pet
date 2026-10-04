"""Import a local Fish key and create/bind a private cloned voice, without printing secrets."""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path
import urllib.request
import urllib.error
import uuid

BASE = Path(__file__).resolve().parents[1]
MODEL = 's2.1-pro-free'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def api(key, route, data=None, content_type=None):
    headers = {'Authorization':'Bearer '+key}
    if content_type: headers['Content-Type'] = content_type
    request = urllib.request.Request('https://api.fish.audio'+route, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'Fish Audio 请求失败（HTTP {error.code}），请检查密钥、权限和账户状态。') from None
    except urllib.error.URLError:
        raise RuntimeError('无法连接 Fish Audio，请检查网络。') from None


def multipart(fields, sample):
    boundary = 'fish-pet-'+uuid.uuid4().hex
    chunks = []
    for name, value in fields.items():
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode('utf-8'))
    suffix = sample.suffix.lower()
    mime = {'.wav':'audio/wav','.mp3':'audio/mpeg','.m4a':'audio/mp4','.opus':'audio/opus'}.get(suffix)
    if not mime: raise ValueError('参考音频支持 WAV、MP3、M4A、Opus。')
    raw = sample.read_bytes()
    if not raw or len(raw)>30*1024*1024: raise ValueError('参考音频为空或超过 30 MB。')
    chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="voices"; filename="reference{suffix}"\r\nContent-Type: {mime}\r\n\r\n').encode('ascii'))
    chunks.extend((raw,b'\r\n',f'--{boundary}--\r\n'.encode('ascii')))
    return b''.join(chunks), 'multipart/form-data; boundary='+boundary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--sample', type=Path)
    parser.add_argument('--transcript-file', type=Path)
    parser.add_argument('--reference-id')
    parser.add_argument('--data-dir', type=Path, default=BASE/'app/userdata')
    args = parser.parse_args()
    path = args.data_dir/'fish-tts.json'
    config = json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    if args.key_file:
        document = args.key_file.read_text(encoding='utf-8-sig').strip()
        match = re.search(r'\bsk-[A-Za-z0-9_-]+',document)
        key = match[0] if match else document.removeprefix('Bearer ').strip()
        if not key or any(c.isspace() for c in key): raise ValueError('密钥文档没有单个有效的 API key。')
        config['api_key'] = key
    if not config.get('api_key'): raise ValueError('先用 --key-file 导入密钥。')
    config.update(version=1,model=MODEL,enabled=True,volume=config.get('volume',.8))
    save(path,config)
    identity = args.reference_id or config.get('pending_reference_id','')
    if args.sample:
        digest = hashlib.sha256(args.sample.read_bytes()).hexdigest()
        if config.get('sample_sha256')==digest and (config.get('reference_id') or identity):
            identity = config.get('reference_id') or identity
        else:
            fields = {'type':'tts','title':'蓝色大肥鱼','train_mode':'fast','visibility':'private',
                      'enhance_audio_quality':'true','generate_sample':'false'}
            if args.transcript_file: fields['texts']=args.transcript_file.read_text(encoding='utf-8-sig').strip()
            payload, content_type = multipart(fields,args.sample)
            voice = api(config['api_key'],'/model',payload,content_type)
            identity = voice.get('_id') or voice.get('id')
            if not isinstance(identity,str) or not identity: raise RuntimeError('音色创建未返回 ID。')
            config.update(pending_reference_id=identity,sample_sha256=digest,voice_state=voice.get('state','created'))
            save(path,config)
            print('私有音色已创建，正在确认复刻状态。',flush=True)
    if not identity:
        print('本机密钥已导入，模型固定为 S2.1 Pro Free；等待参考音频或音色 ID。')
        return
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',identity): raise ValueError('音色 ID 格式不正确。')
    for attempt in range(24):
        voice = api(config['api_key'],'/model/'+identity)
        state = voice.get('state','created')
        config['voice_state'] = state
        save(path,config)
        if state=='trained':
            config['reference_id']=identity;config.pop('pending_reference_id',None)
            save(path,config)
            print('复刻音色已就绪并绑定；S2.1 Pro Free 流式朗读已配置。')
            return
        if state=='failed': raise RuntimeError('音色复刻失败，请检查音频质量。')
        print('音色仍在处理，稍后再次检查。',flush=True)
        time.sleep(3)
    raise RuntimeError('音色仍在处理，ID 已保留；稍后运行此脚本继续确认，不会重复创建。')


if __name__=='__main__':
    try: main()
    except (OSError,ValueError,RuntimeError) as error: raise SystemExit(str(error))
