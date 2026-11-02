"""Release-independent CPU helper cache; no device, frame or model data."""
from pathlib import Path
import ctypes,hashlib,json,os,platform,shutil,struct,threading,time
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LOCK=threading.RLock()
# Filled by the release assembler using reviewed baseline loader bytes.
LEGACY_LOADER_SHA256 = {'tracker': ['3b344449de4da614f3b55898f4296a4ffd675e8d22d7c1064164085bc79e20c0', 'df64ea52980a42620aad7759d95ce1ab1e6b603515acda00ef247d09ec3f350e', 'f40711f9ae073c06c7b177831f5ce4c316ef877cee0fc616ab9e3044d38ec199', 'f2578e5250515d7063940679b1f9e3f5bfb310c54b5b7c6eb503097c5a0f8bd8', '522dff375efb56848524a07d45a724bc1a18dd3072592c213072a6487ce02dbf'], 'io': ['9e19f967f922647c305ec5e8572008fb878e78ef952491d5e5e774c4f9d4c2c0', '12f4566a4639bab9b6eb985b5846561c057c33fe20d81e4bd88919f7c0671d17'], 'capture': ['982f5f783d310534c4b605758b721a3c01023e08ee0698a8ee16d2a75d87ad36', 'b88ef3d7516ec72727c680c56e255eb08276f5ddde52ebab5a4eb313f524e29e', '6343d8277577dc5b5893cdc1937991632460d1b6761e5f30d061c1a61532060e']}  # REVIEWED_V74_CACHE_LOADER
_FAMILIES={'tracker':('v31_native.py','p11_v31_abi',3107),
    'io':('v64_io.py','p11_v64_abi',6601),'capture':('v31_camera.py','p11_camera_abi',3102),
    'transaction':('v91_native.py','p11_v91_abi',9101)}


def shared_root():
    configured=os.environ.get('P11_NATIVE_CACHE_ROOT')
    return Path(configured).expanduser().resolve()/'v2' if configured else Path.home()/'.cache'/'p11_native'/'v2'


def _hash(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec(target,source,family,flags):
    source=Path(source);target=Path(target)
    if family not in _FAMILIES:raise ValueError('Unknown CPU cache family')
    item=dict(schema=1,family=family,source_sha256=_hash(source),architecture=platform.machine(),
        target_name=target.name,compiler_flags=list(flags),abi=_FAMILIES[family][2])
    key=hashlib.sha256(json.dumps(item,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return item,key


def _probe(path,family):
    with path.open('rb') as stream:header=stream.read(20)
    machine={'armv7l':40,'aarch64':183,'x86_64':62}.get(platform.machine())
    if len(header)<20 or header[:4]!=b'\x7fELF' or header[5]!=1:
        raise ValueError('Cache artifact is not a supported little-endian ELF')
    if machine is not None and struct.unpack_from('<H',header,18)[0]!=machine:
        raise ValueError('Cache ELF architecture mismatch')
    if not 1024<=path.stat().st_size<=64*1024*1024:raise ValueError('Cache ELF size outside bounds')
    lib=ctypes.CDLL(str(path.resolve()))
    function=getattr(lib,_FAMILIES[family][1]);function.argtypes=[];function.restype=ctypes.c_int
    if function()!=_FAMILIES[family][2]:raise ValueError('CPU helper ABI mismatch')


def _copy_atomic(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name(target.name+'.'+str(os.getpid())+'.'+str(threading.get_ident())+'.'+str(time.time_ns())+'.tmp')
    try:
        shutil.copyfile(source,temporary)
        if _hash(source)!=_hash(temporary):raise ValueError('CPU cache copy hash mismatch')
        os.replace(str(temporary),str(target))
    finally:
        if temporary.exists():temporary.unlink()


def _write_receipt(path,value):
    temporary=path.with_name(path.name+'.'+str(os.getpid())+'.'+str(time.time_ns())+'.tmp')
    try:
        temporary.write_text(json.dumps(value,sort_keys=True)+'\n',encoding='utf-8')
        os.replace(str(temporary),str(path))
    finally:
        if temporary.exists():temporary.unlink()


def restore(target,source,family,flags,cancel=None,source_alias=None):
    """Import a known recipe and full source match; reject bad cache, then build normally."""
    from v79_setup import check_cancel
    if source_alias not in (None,'v31_native.cpp'):raise ValueError('Unsupported historical cache source alias')
    source_leaf=source_alias or Path(source).name
    target=Path(target);source=Path(source);begin=time.perf_counter()
    if platform.system()!='Linux':return False
    item,key=_spec(target,source,family,flags);root=target.parent.resolve()
    shared=shared_root();artifact=shared/(key+'.so');receipt=shared/(key+'.json')
    with _LOCK:
        check_cancel(cancel)
        from v84_prebuilt import check_local,remember_local,restore_pack
        if target.is_file():
            if check_local(target,item):
                try:_probe(target,family)
                except (OSError,ValueError,AttributeError,TypeError) as exc:
                    checkpoint('CPU_NATIVE_LOCAL_REJECTED',family=family,exception=str(exc))
                else:
                    checkpoint('CPU_NATIVE_LOCAL_VERIFIED',family=family,path=str(target),
                        source_sha256=item['source_sha256'],artifact_sha256=_hash(target),abi=item['abi'])
                    return False
            # Preserve unregistered/corrupt bytes for inspection, never load them.
            quarantine=target.with_name(target.name+'.unverified.'+str(time.time_ns()))
            os.replace(str(target),str(quarantine))
            checkpoint('CPU_NATIVE_LOCAL_QUARANTINED',family=family,path=str(quarantine),
                reason='missing or mismatched source/recipe/environment/binary receipt')
        if restore_pack(target,item,cancel):return True
        if artifact.is_file() and receipt.is_file():
            try:
                meta=json.loads(receipt.read_text(encoding='utf-8'))
                from v84_prebuilt import environment
                if (meta.get('spec')!=item or meta.get('environment')!=environment()
                    or meta.get('artifact_sha256')!=_hash(artifact)):raise ValueError('Cache receipt/environment mismatch')
                _probe(artifact,family);check_cancel(cancel);_copy_atomic(artifact,target);remember_local(target,item)
                checkpoint('CPU_NATIVE_CACHE_HIT',family=family,source='shared',path=str(target),elapsed_s=time.perf_counter()-begin)
                return True
            except (OSError,ValueError,AttributeError,TypeError) as exc:
                checkpoint('CPU_NATIVE_CACHE_REJECTED',family=family,source='shared',exception=str(exc))
        try:
            siblings=sorted((p for p in root.parent.iterdir() if p.name.startswith('p11_rgb_v') and p.is_dir()),
                key=lambda p:p.stat().st_mtime,reverse=True)[:128]
        except OSError:siblings=[]
        loader=_FAMILIES[family][0];allowed=set(LEGACY_LOADER_SHA256.get(family,()))
        for folder in siblings:
            check_cancel(cancel)
            if folder.resolve()==root or folder.resolve().parent!=root.parent:continue
            candidate=folder/target.name
            if not candidate.is_file():continue
            try:
                # Portable receipt binds actual source, recipe, environment and
                # binary SHA; also covers the independent V74 helper in V87+.
                if check_local(candidate,item):
                    _probe(candidate,family);check_cancel(cancel);_copy_atomic(candidate,target);remember_local(target,item)
                    checkpoint('CPU_NATIVE_CACHE_HIT',family=family,source='verified_previous_receipt',
                        previous_folder=folder.name,path=str(target),elapsed_s=time.perf_counter()-begin)
                    return True
                if not allowed or _hash(folder/loader) not in allowed:continue
                if _hash(folder/source_leaf)!=item['source_sha256']:continue
                manifest=json.loads((folder/'release_manifest.json').read_text(encoding='utf-8'))
                if manifest.get('sha256',{}).get(source_leaf)!=item['source_sha256']:continue
                # Probe only the declared ABI. No camera/VDMA/MMIO call is made.
                _probe(candidate,family);check_cancel(cancel);_copy_atomic(candidate,target);remember_local(target,item)
                checkpoint('CPU_NATIVE_CACHE_HIT',family=family,source='reviewed_previous_release',
                    previous_folder=folder.name,path=str(target),elapsed_s=time.perf_counter()-begin)
                return True
            except (OSError,ValueError,AttributeError,TypeError) as exc:
                checkpoint('CPU_NATIVE_CACHE_REJECTED',family=family,source=folder.name,exception=str(exc))
        checkpoint('CPU_NATIVE_CACHE_MISS',family=family,elapsed_s=time.perf_counter()-begin,
            exact_source_and_recipe_required=True)
        return False


def remember(target,source,family,flags):
    """Best-effort atomic persistence after the caller has bound/checked its ABI."""
    target=Path(target);source=Path(source)
    if platform.system()!='Linux' or not target.is_file():return
    try:
        item,key=_spec(target,source,family,flags)
        from v84_prebuilt import remember_local
        remember_local(target,item)
        shared=shared_root()
        artifact=shared/(key+'.so');receipt=shared/(key+'.json');digest=_hash(target)
        with _LOCK:
            if artifact.is_file() and receipt.is_file():
                try:
                    meta=json.loads(receipt.read_text(encoding='utf-8'))
                    from v84_prebuilt import environment
                    if meta.get('spec')==item and meta.get('environment')==environment() and meta.get('artifact_sha256')==digest and _hash(artifact)==digest:return
                except (OSError,ValueError,TypeError):pass
            _copy_atomic(target,artifact)
            from v84_prebuilt import environment
            _write_receipt(receipt,dict(spec=item,environment=environment(),artifact_sha256=digest,created_by_release=RELEASE_ID))
        checkpoint('CPU_NATIVE_CACHE_STORED',family=family,path=str(artifact),bytes=target.stat().st_size)
    except (OSError,ValueError,TypeError) as exc:
        checkpoint('CPU_NATIVE_CACHE_STORE_SKIPPED',family=family,exception=str(exc),local_library_retained=True)
