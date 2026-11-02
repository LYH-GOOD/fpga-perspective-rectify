"""Verified CPU-only artifacts, portable receipts and optional board export."""
from pathlib import Path
import ctypes, hashlib, json, os, platform, struct, sys, time, zipfile
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ENV=None


def environment():
    global _ENV
    if _ENV is None:
        import cv2
        _ENV=dict(system=platform.system(),architecture=platform.machine(),
            pointer_bits=struct.calcsize('P')*8,byteorder=sys.byteorder,
            libc=list(platform.libc_ver()),opencv_version=cv2.__version__)
    return dict(_ENV)


def _hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    path=Path(path)
    if path.stat().st_size>1024*1024:raise ValueError('CPU artifact receipt too large')
    return json.loads(path.read_text(encoding='utf-8'))


def _receipt(target):return Path(target).parent/'.native_receipts'/(Path(target).name+'.json')


def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+str(os.getpid())+'.'+str(time.time_ns())+'.tmp')
    try:
        temporary.write_text(json.dumps(value,sort_keys=True)+'\n',encoding='utf-8')
        os.replace(str(temporary),str(path))
    finally:
        if temporary.exists():temporary.unlink()


def check_local(target,spec):
    """A newly distributed local artifact needs a full source/recipe/hash receipt."""
    target=Path(target)
    try:
        meta=_read(_receipt(target))
        return (meta.get('schema')==1 and meta.get('spec')==spec
            and meta.get('environment')==environment()
            and meta.get('artifact_sha256')==_hash(target))
    except (OSError,ValueError,TypeError):return False


def remember_local(target,spec):
    """Called only after the original loader has checked and bound its ABI."""
    meta=dict(schema=1,spec=spec,environment=environment(),artifact_sha256=_hash(target),
        created_by_release=RELEASE_ID,abi_checked=True)
    try:_write(_receipt(target),meta)
    except OSError as exc:checkpoint('CPU_NATIVE_LOCAL_RECEIPT_FAILED',family=spec['family'],exception=str(exc))
    return meta


def restore_pack(target,spec,cancel=None):
    """Only import declared same-environment binaries; no device operation."""
    from v79_setup import check_cancel
    from v80_cache import _probe,_copy_atomic
    target=Path(target);folder=target.parent/'native_prebuilt';manifest=folder/'manifest.json'
    if not manifest.is_file():return False
    try:
        pack=_read(manifest)
        if pack.get('schema')!=1 or pack.get('environment')!=environment():
            raise ValueError('Prebuilt environment mismatch')
        entries=pack.get('artifacts',[])
        if not isinstance(entries,list) or len(entries)>12:raise ValueError('Invalid prebuilt inventory')
        selected=next((x for x in entries if x.get('spec')==spec),None)
        if selected is None:return False
        name=spec['target_name']
        if Path(name).name!=name or name in ('.','..'):raise ValueError('Invalid CPU artifact basename')
        artifact=folder/name
        if artifact.resolve().parent!=folder.resolve():raise ValueError('CPU artifact escapes prebuilt directory')
        check_cancel(cancel)
        if selected.get('artifact_sha256')!=_hash(artifact):raise ValueError('Prebuilt binary SHA256 mismatch')
        _probe(artifact,spec['family']);check_cancel(cancel);_copy_atomic(artifact,target)
        remember_local(target,spec)
        checkpoint('CPU_PREBUILT_LOADED',family=spec['family'],path=str(target),
            source_sha256=spec['source_sha256'],artifact_sha256=selected['artifact_sha256'],
            abi=spec['abi'],compiler_invoked=False,hardware_access=False)
        return True
    except (OSError,ValueError,TypeError,AttributeError) as exc:
        checkpoint('CPU_PREBUILT_REJECTED',family=spec['family'],exception=str(exc),fallback='verified shared or reviewed sibling cache')
        return False


def export_native_bundle(output=None):
    """Board-side preparation/export only. Does not open camera or download PL."""
    from p11_contract import verify_package
    root=Path(__file__).resolve().parent
    verify_package(str(root/'system.bit'))
    from v64_io import prepare_io
    from v31_native import prepare_native
    from v87_v74_native import prepare_native as prepare_v74
    from v31_camera import _library
    from v91_native import prepare_transactions
    from v80_cache import _probe
    io=prepare_io();tracker=prepare_native(required=True);v74=prepare_v74(required=True);capture=_library()
    transactions=prepare_transactions(required=True)
    artifacts=[];paths=[]
    for family,path in (('io',io._name),('tracker',tracker['path']),('tracker',v74['path']),('capture',capture._name),
                        ('transaction',transactions._name)):
        path=Path(path).resolve()
        if path.parent!=root:raise ValueError('CPU library was not loaded from this release')
        meta=_read(_receipt(path));spec=meta.get('spec',{})
        if spec.get('family')!=family or not check_local(path,spec):raise ValueError('CPU library export receipt mismatch')
        _probe(path,family);paths.append(path)
        artifacts.append(dict(spec=spec,artifact_sha256=_hash(path)))
    manifest=dict(schema=1,environment=environment(),artifacts=artifacts,created_by_release=RELEASE_ID,
        purpose='CPU-only helpers; no hardware/model/frame data')
    output=Path(output).expanduser().resolve() if output is not None else root/('p11_native_bundle_'+platform.machine()+'.zip')
    temporary=output.with_name(output.name+'.'+str(os.getpid())+'.tmp')
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('native_prebuilt/manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
            for path in paths:archive.write(path,'native_prebuilt/'+path.name)
        os.replace(str(temporary),str(output))
    finally:
        if temporary.exists():temporary.unlink()
    checkpoint('CPU_PREBUILT_EXPORTED',path=str(output),artifacts=len(paths),hardware_access=False)
    return str(output)


def export_ready_upload(output=None):
    """Repackage declared release files plus verified CPU artifacts on the board.

    Mutable run logs/captured images/caches are excluded. Notebook execution
    output is cleared. Includes IO, capture, motion, V74 detector and V91 addon.
    """
    bundle=Path(export_native_bundle());root=Path(__file__).resolve().parent
    manifest=_read(root/'release_manifest.json');payload={}
    for name in manifest['sha256']:
        if name in ('run-result.log','release_manifest.json','upload_inventory.json'):continue
        if Path(name).suffix.lower()=='.md':continue
        local=root/name
        if local.resolve().parent!=root or Path(name).name!=name:continue
        data=local.read_bytes()
        if name.endswith('.ipynb'):
            notebook=json.loads(data)
            for cell in notebook.get('cells',[]):
                if cell.get('cell_type')=='code':cell.update(outputs=[],execution_count=None)
            data=(json.dumps(notebook,ensure_ascii=False,indent=1)+'\n').encode('utf-8')
        payload[name]=data
    with zipfile.ZipFile(bundle) as archive:
        for info in archive.infolist():
            name=info.filename
            if (name.startswith('native_prebuilt/') and len(Path(name).parts)==2
                    and Path(name).suffix.lower()!='.md'
                    and not info.is_dir() and info.file_size<=64*1024*1024):payload[name]=archive.read(info)
    payload['run-result.log']=b''
    manifest.update(precompiled_libraries_included=True,precompiled_environment=environment(),
        precompiled_binary_verification='full source+recipe+environment+binary SHA256+ELF/ABI before import')
    manifest['sha256']={name:hashlib.sha256(data).hexdigest() for name,data in sorted(payload.items())}
    payload['release_manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    inventory=dict(release_id=RELEASE_ID,root_folder=root.name,files=[dict(name=name,bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest()) for name,data in sorted(payload.items())])
    payload['upload_inventory.json']=(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    output=Path(output).expanduser().resolve() if output is not None else root/(root.name+'_prebuilt_upload.zip')
    temporary=output.with_name(output.name+'.'+str(os.getpid())+'.tmp')
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in sorted(payload.items()):archive.writestr(root.name+'/'+name,data)
        os.replace(str(temporary),str(output))
    finally:
        if temporary.exists():temporary.unlink()
    checkpoint('CPU_PREBUILT_FULL_UPLOAD_EXPORTED',path=str(output),files=len(payload),
        hardware_access=False,run_log_included=False)
    return str(output)
