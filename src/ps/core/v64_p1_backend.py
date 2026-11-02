"""P1 immutable combined overlay, conservative plan and a single remap owner.

Original V31 spatial light/surface tables remain unused. A separate pointwise
PWL light stage is controlled once per frame by the existing owner.
"""
from pathlib import Path
from dataclasses import dataclass
from collections import OrderedDict
import hashlib,json,os,threading,time,xml.etree.ElementTree as ET,zlib
import cv2,numpy as np
from p11_contract import RELEASE_ID,verify_package,EXACT_PAIR_SHA256
from v64_io import guard,pack_yuyv,poll,parameters,arm,PlanWorkspace
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED=[]
_OWNER_SESSION=None

@dataclass(frozen=True)
class Tile:
    box:tuple
    crop:tuple
    regs:tuple
    proof:dict
    packet:bytes

def encode(h):
    h=np.asarray(h,np.float64);h=h/h[2,2]
    values=h.reshape(-1)[:8].copy()
    values[[0,1,3,4,6,7]]*=2048.
    values=np.rint(values*65536.)
    if not np.isfinite(values).all() or (np.abs(values)>2147483647).any():raise ValueError('P1 coefficient overflow')
    return tuple(map(int,values))

class ProofCache:
    """Bounded receipts keyed by the ACTUAL encoded hardware mapping/domain."""
    def __init__(self,capacity=128):
        self.capacity=int(capacity);self.items=OrderedDict();self.hits=0;self.misses=0
    def get(self,key):
        receipt=self.items.get(key)
        if receipt is None:self.misses+=1;return None
        self.items.move_to_end(key);self.hits+=1
        return dict(receipt,proof_cached=True,proof_s=0.,proof_thread_cpu_s=0.,
            receipt_coordinate_samples=receipt.get('checked_pixels'),checked_pixels=0,
            interval_blocks=0,subdivided_blocks=0,proof_nodes=0)
    def put(self,key,receipt):
        # Budget prefixes are not complete receipts, even when sampled values
        # looked safe. Conservative negative decisions may be repeated safely.
        if receipt.get('budget_inconclusive') or receipt.get('code')==-5:return
        self.items[key]=dict(receipt);self.items.move_to_end(key)
        while len(self.items)>self.capacity:self.items.popitem(last=False)
    def snapshot(self):return dict(entries=len(self.items),hits=self.hits,misses=self.misses,capacity=self.capacity)


def _partition_boxes(boxes,size,max_tiles=32):
    """Coverage is exact: bounded rectangles, disjoint interiors, full area."""
    ow,oh=map(int,size);boxes=tuple(tuple(map(int,b)) for b in boxes)
    if not boxes or len(boxes)>max_tiles:raise ValueError('Invalid P1 partition count')
    area=0
    for i,b in enumerate(boxes):
        if len(b)!=4:raise ValueError('P1 partition rectangle requires four bounds')
        x0,y0,x1,y1=b
        if not(0<=x0<x1<=ow and 0<=y0<y1<=oh and x1-x0>=2 and y1-y0>=2):raise ValueError('P1 partition rectangle out of bounds')
        area+=(x1-x0)*(y1-y0)
        for c in boxes[:i]:
            if max(x0,c[0])<min(x1,c[2]) and max(y0,c[1])<min(y1,c[3]):raise ValueError('P1 partition rectangles overlap')
    if area!=ow*oh:raise ValueError('P1 partition does not cover output')
    return boxes


def _merge_pairs(boxes):
    result=[]
    for i,a in enumerate(boxes):
        for j in range(i+1,len(boxes)):
            b=boxes[j]
            if a[0]==b[0] and a[2]==b[2] and (a[3]==b[1] or b[3]==a[1]):
                result.append((i,j,(a[0],min(a[1],b[1]),a[2],max(a[3],b[3]))))
            elif a[1]==b[1] and a[3]==b[3] and (a[2]==b[0] or b[2]==a[0]):
                result.append((i,j,(min(a[0],b[0]),a[1],max(a[2],b[2]),a[3])))
    return result


def _legacy_make_plan(q,shape,size,max_tiles=32,*,proof_cache=None,strategy='fast_safe',proof_cpu_budget_s=.012,
              partition_boxes=None,merge_probe=False,merge_cursor=0,workspace=None,_h_current=None,_proof_prior_cpu_s=0.):
    """Reuse leaf geometry only; every current H/crop/packet has a fresh proof.

    Bounded low-frequency merging can reduce tile count without retrying the
    expensive full-output proof on each moving corner measurement.
    """
    if strategy not in ('fast_safe','exact_reference'):raise ValueError('Unknown P1 plan strategy')
    if not .002<=float(proof_cpu_budget_s)<=.03:raise ValueError('Proof CPU budget must be2..30ms')
    ih,iw=map(int,shape[:2]);ow,oh=map(int,size)
    q=np.asarray(q,np.float32)
    if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Invalid current quad')
    if not 2<=ow<=4095 or not 2<=oh<=4095:raise ValueError('P1 output dimensions invalid')
    ws=workspace if workspace is not None else PlanWorkspace()
    h=(cv2.getPerspectiveTransform(ws.destination(size),q).astype(np.float64) if _h_current is None
        else np.asarray(_h_current,np.float64).copy())
    if not np.isfinite(h).all() or abs(h[2,2])<1e-12:raise ValueError('Invalid P1 homography')
    h/=h[2,2];tiles=[];failures=[];proof_s=0.;proof_cpu_s=0.;visited=0
    proof_cache_hits=0;proof_budget_splits=0;proof_samples=0;interval_blocks=0
    mapping_s=0.;mapping_cpu_s=0.;merge_attempts=0;merge_accepted=0
    reused=partition_boxes is not None and strategy=='fast_safe'
    boxes=_partition_boxes(partition_boxes,size,max_tiles) if reused else ((0,0,ow,oh),)
    def candidate(box,probe=False):
        nonlocal proof_s,proof_cpu_s,visited,proof_cache_hits,proof_budget_splits,proof_samples,interval_blocks,mapping_s,mapping_cpu_s
        t=time.perf_counter();c=time.thread_time();mapping,reason=ws.map_tile(h,box,(iw,ih))
        mapping_s+=time.perf_counter()-t;mapping_cpu_s+=time.thread_time()-c
        if mapping is None:return None,reason
        crop,regs,packet=mapping;cx,cy,cw,ch=crop;tw,th=box[2]-box[0],box[3]-box[1]
        key=(6601,0x10007,int(__import__('p11_contract').LINE_BUF_ROWS),strategy,regs,cw,ch,tw,th)
        proof=proof_cache.get(key) if proof_cache is not None else None
        if proof is not None:proof_cache_hits+=1
        else:
            remaining=float(proof_cpu_budget_s)-proof_cpu_s-float(_proof_prior_cpu_s)
            #   ⚠️ 2026-10-25：这个门槛原来是 192（旧 ROWS）。硬件现在是 384，
            #      用 192 会把「其实装得下」的 tile 也判成"预算不够"→ 多余地切块/放弃。
            if strategy=='fast_safe' and ch>int(__import__('p11_contract').LINE_BUF_ROWS) and remaining<.0005:
                proof_budget_splits+=1;visited+=1
                return None,dict(code=-5,reason='bounded_plan_proof_CPU_budget_exhausted',safe_fallback='split_to_whole_source_crop_retention')
            proof=guard(regs,(cw,ch),(tw,th),strategy=strategy,
                cpu_budget_s=max(.0005,min(.001 if probe else .008,remaining)),block_pixels=128,workspace=ws)
            if proof_cache is not None:proof_cache.put(key,proof)
        proof_s+=proof['proof_s'];proof_cpu_s+=proof.get('proof_thread_cpu_s',0.);visited+=1
        proof_samples+=int(proof.get('checked_pixels') or 0);interval_blocks+=int(proof.get('interval_blocks') or 0)
        proof_budget_splits+=int(proof.get('budget_inconclusive',False))
        if not proof['valid']:return None,proof
        return Tile(tuple(box),crop,regs,proof,packet),None
    def split(box,depth=0):
        tile,reason=candidate(box)
        if tile is not None:tiles.append(tile);return
        if len(tiles)>=max_tiles or depth>=12:raise ValueError('P1 tile proof budget exceeded: '+str(reason))
        x0,y0,x1,y1=box;w,hh=x1-x0,y1-y0
        if min(w,hh)<4:raise ValueError('P1 cannot prove this raster direction: '+str(reason))
        # Keep the established split decision: smaller worst source y span.
        choices=[]
        for axis in ('x','y'):
            mid=(x0+x1)//2 if axis=='x' else (y0+y1)//2
            children=[(x0,y0,mid,y1),(mid,y0,x1,y1)] if axis=='x' else [(x0,y0,x1,mid),(x0,mid,x1,y1)]
            spans=[]
            for b in children:
                xy=np.array([[b[0],b[1]],[b[2]-1,b[1]],[b[2]-1,b[3]-1],[b[0],b[3]-1]],np.float64)
                d=xy@h[2,:2]+h[2,2];yy=(xy@h[1,:2]+h[1,2])/d;spans.append(float(np.ptp(yy)))
            choices.append((max(spans),axis,children))
        _,axis,children=min(choices,key=lambda v:v[0]);failures.append(dict(box=box,axis=axis,reason=reason))
        for b in children:split(b,depth+1)
    merged=None;excluded=()
    if reused and merge_probe and len(boxes)>1:
        pairs=_merge_pairs(boxes)
        if pairs:
            i,j,merged_box=pairs[int(merge_cursor)%len(pairs)];merge_attempts=1
            merged,merge_reason=candidate(merged_box,probe=True)
            if merged is not None:excluded=(i,j);merge_accepted=1
    for i,box in enumerate(boxes):
        if i not in excluded:split(box)
    if merged is not None:tiles.append(merged)
    tiles.sort(key=lambda tile:(tile.box[1],tile.box[0]))
    _partition_boxes((tile.box for tile in tiles),size,max_tiles)
    return tuple(tiles),dict(tile_count=len(tiles),proof_s=proof_s,proof_thread_cpu_s=proof_cpu_s,
        proof_attempts=visited,split_events=failures,proof_cache_hits=proof_cache_hits,
        proof_cache=proof_cache.snapshot() if proof_cache is not None else None,
        proof_budget_splits=proof_budget_splits,proof_coordinate_samples=proof_samples,
        interval_blocks=interval_blocks,proof_strategy=strategy,proof_cpu_budget_s=float(proof_cpu_budget_s),
        planner='reused_partition_fresh_native_mapping_and_proof',full_pixel_scan_enabled=strategy=='exact_reference',
        partition_reused=reused,partition_input_tiles=len(boxes),partition_boxes=[t.box for t in tiles],
        merge_probe_attempts=merge_attempts,merge_probe_accepted=merge_accepted,merge_probe_cpu_budget_s=.001,
        mapping_native_s=mapping_s,mapping_native_thread_cpu_s=mapping_cpu_s,
        proof_methods=[t.proof['method'] for t in tiles],h_out2in=h.tolist(),
        mapping='planar_p1_fixed_q16',input_bytes=sum(t.crop[2]*t.crop[3]*4 for t in tiles))


def make_plan(q,shape,size,max_tiles=32,*,proof_cache=None,strategy='fast_safe',proof_cpu_budget_s=.012,
              partition_boxes=None,merge_probe=False,merge_cursor=0,workspace=None):
    """Batch ordinary geometry, retaining the exact legacy split/merge fallback.

    Row certificates always describe actual encoded packets. Native cache keys
    contain all ten words and fixed ABI/version/192-row context, never rounded H.
    """
    args=dict(proof_cache=proof_cache,strategy=strategy,proof_cpu_budget_s=proof_cpu_budget_s,
        partition_boxes=partition_boxes,merge_probe=merge_probe,merge_cursor=merge_cursor,workspace=workspace)
    if strategy!='fast_safe' or merge_probe:
        tiles,detail=_legacy_make_plan(q,shape,size,max_tiles,**args)
        detail.update(native_geometry_used=False,native_geometry_fallback='reference_or_merge_probe',native_geometry_calls=0)
        return tiles,detail
    if not .002<=float(proof_cpu_budget_s)<=.03:raise ValueError('Proof CPU budget must be2..30ms')
    ih,iw=map(int,shape[:2]);ow,oh=map(int,size);q=np.asarray(q,np.float32)
    if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Invalid current quad')
    if not 2<=ow<=4095 or not 2<=oh<=4095:raise ValueError('P1 output dimensions invalid')
    ws=workspace if workspace is not None else PlanWorkspace();args['workspace']=ws
    boxes=_partition_boxes(partition_boxes,size,max_tiles) if partition_boxes is not None else ((0,0,ow,oh),)
    if len(boxes)>ws.batch.capacity:
        tiles,detail=_legacy_make_plan(q,shape,size,max_tiles,**args)
        detail.update(native_geometry_used=False,native_geometry_fallback='batch_capacity',native_geometry_calls=0)
        return tiles,detail
    batch=ws.batch.run(q,(iw,ih),size,boxes,proof_cpu_budget_s)
    if batch is None:
        tiles,detail=_legacy_make_plan(q,shape,size,max_tiles,**args)
        status=ws.batch.last_status
        detail.update(native_geometry_used=False,native_geometry_fallback=status.get('reason'),
            native_geometry_s=status.get('wall_s',0.),native_geometry_thread_cpu_s=status.get('thread_cpu_s',0.),
            native_geometry_calls=int(status.get('available',False)))
        return tiles,detail
    h,mapping,packets,results,status=batch
    start=time.perf_counter();used=time.thread_time();tiles=[];proofs=[];failures=[]
    for i,box in enumerate(boxes):
        meta=results[i];mapping_code=int(meta[0])
        if mapping_code:
            failures.append(dict(box=box,mapping_code=mapping_code));continue
        m=mapping[i];crop=tuple(map(int,m[:4]));regs=tuple(map(int,m[4:]));code=int(meta[1]);cached=bool(meta[2])
        t=ws.batch.times[16+i*4:20+i*4]
        proof=dict(valid=code==0,code=code,peak_rows=int(meta[3]) if code==0 else None,
            checked_pixels=int(meta[4]),interval_blocks=int(meta[5]),subdivided_blocks=int(meta[6]),
            failure_at=[int(meta[7]),int(meta[8])] if code else None,proof_nodes=int(meta[9]),
            method='whole_source_crop_retention_and_operand_bounds' if meta[10]==0 else 'bounded_fixed_point_interval_lifetime',
            proof_s=float(t[2]),proof_thread_cpu_s=float(t[3]),complete_domain_verified=code==0,
            budget_inconclusive=code==-5,proof_strategy=strategy,proof_cached=cached,
            cpu_budget_s=float(proof_cpu_budget_s),interval_block_pixels=128,exact_reference_fallback=False,
            proof_cache_backend='native_exact_ten_word_LRU',receipt_coordinate_samples=int(meta[11]) if cached else None)
        key=(6601,0x10007,int(__import__('p11_contract').LINE_BUF_ROWS),strategy,regs,crop[2],crop[3],box[2]-box[0],box[3]-box[1])
        proofs.append((key,proof))
        if proof['valid']:
            # Small immutable payload only. No mutable native workspace view is
            # published to the MMIO owner or asynchronous display.
            tiles.append(Tile(tuple(box),crop,regs,proof,packets[i].tobytes()))
        else:failures.append(dict(box=box,proof=proof))
    decode_s=time.perf_counter()-start;decode_cpu=time.thread_time()-used
    common=dict(native_geometry_used=True,native_geometry_s=status['wall_s'],
        native_geometry_thread_cpu_s=status['thread_cpu_s'],native_geometry_calls=1,
        h_native_s=status['h_s'],h_native_thread_cpu_s=status['h_thread_cpu_s'],
        geometry_result_decode_s=decode_s,geometry_result_decode_thread_cpu_s=decode_cpu,
        native_plan_cache=dict(ws.batch.last_cache),native_initial_proof_s=status['proof_s'],
        native_initial_proof_thread_cpu_s=status['proof_thread_cpu_s'])
    if failures:
        # Seed only complete actual-domain receipts. Failed CPU prefixes are
        # deliberately not cacheable. Legacy split decisions remain unchanged.
        if proof_cache is not None:
            for key,proof in proofs:proof_cache.put(key,proof)
        tiles,detail=_legacy_make_plan(q,shape,size,max_tiles,**args,_h_current=h,
            _proof_prior_cpu_s=status['proof_thread_cpu_s'])
        detail.update(common,native_geometry_fallback='existing_split_after_unproved_batch',
            native_batch_failures=failures,native_H_reused=True)
        # The old stage totals include all computation performed by this call.
        detail['proof_s']+=status['proof_s'];detail['proof_thread_cpu_s']+=status['proof_thread_cpu_s']
        detail['mapping_native_s']+=status['mapping_s'];detail['mapping_native_thread_cpu_s']+=status['mapping_thread_cpu_s']
        detail['proof_attempts']+=len(boxes);detail['proof_cache_hits']+=status['proof_cache_hits']
        detail['proof_coordinate_samples']+=sum(p['checked_pixels'] for _,p in proofs)
        detail['interval_blocks']+=sum(p['interval_blocks'] for _,p in proofs)
        detail['proof_budget_splits']+=sum(p['budget_inconclusive'] for _,p in proofs)
        return tiles,detail
    tiles.sort(key=lambda tile:(tile.box[1],tile.box[0]));_partition_boxes((t.box for t in tiles),size,max_tiles)
    detail=dict(tile_count=len(tiles),proof_s=status['proof_s'],proof_thread_cpu_s=status['proof_thread_cpu_s'],
        proof_attempts=len(boxes),split_events=[],proof_cache_hits=status['proof_cache_hits'],
        proof_cache=proof_cache.snapshot() if proof_cache is not None else None,
        proof_budget_splits=0,proof_coordinate_samples=sum(p['checked_pixels'] for _,p in proofs),
        interval_blocks=sum(p['interval_blocks'] for _,p in proofs),proof_strategy=strategy,proof_cpu_budget_s=float(proof_cpu_budget_s),
        planner='native_current_H_mapping_packet_and_rowproof',full_pixel_scan_enabled=False,
        partition_reused=partition_boxes is not None,partition_input_tiles=len(boxes),partition_boxes=[t.box for t in tiles],
        merge_probe_attempts=0,merge_probe_accepted=0,merge_probe_cpu_budget_s=.001,
        mapping_native_s=status['mapping_s'],mapping_native_thread_cpu_s=status['mapping_thread_cpu_s'],
        proof_methods=[t.proof['method'] for t in tiles],h_out2in=h.tolist(),mapping='planar_p1_fixed_q16',
        input_bytes=sum(t.crop[2]*t.crop[3]*4 for t in tiles),native_geometry_fallback=None)
    detail.update(common);return tuple(tiles),detail

def inspect_pair(bitfile):
    path=Path(bitfile).resolve();verify_package(str(path))
    info=json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf-8-sig'))
    if info.get('format')!='p1-light-pair-v1' or info.get('remap_version')!=0x00010005:raise ValueError('Specified PL sharp pair receipt mismatch')
    for p,stem in ((path,'bit'),(path.with_suffix('.hwh'),'hwh')):
        data=p.read_bytes()
        if (hashlib.sha256(data).hexdigest()!=EXACT_PAIR_SHA256[p.name] or
            info[stem+'_sha256']!=EXACT_PAIR_SHA256[p.name] or
            '%08x'%(zlib.crc32(data)&0xffffffff)!=info[stem+'_crc32']):raise ValueError('Specified P1 hardware pair mismatch')
    if info.get('input_contract')!=dict(format='BGRX32',bytes_per_pixel=4,PL_YUYV=False,color_conversion='existing_native_CPU'):
        raise ValueError('Selected remap1.5 requires BGRX32 native CPU input contract')
    tree=ET.parse(path.with_suffix('.hwh'));mods={m.get('FULLNAME'):m for m in tree.findall('.//MODULE')}
    remap=mods.get('/remap')
    if remap is None:raise ValueError('Missing P1 remap metadata')
    params={p.get('NAME'):p.get('VALUE') for p in remap.findall('./PARAMETERS/PARAMETER')}
    #   ⚠️ 2026-10-25：行缓存改成 MAX_W=512 / ROWS=384（用宽度换深度）。
    #      hwh 里的参数必须和这里一致 —— 不一致说明装错了 bit。
    #   ⚠️ 硬件参数从 p11_contract 取（别再写字面量 —— 已经漏过两次）。
    from p11_contract import LINE_BUF_W,LINE_BUF_ROWS
    for key,val in (('DW',32),('MAX_W',int(LINE_BUF_W)),('NCH',3),('PIX_W',24),('ROWS',int(LINE_BUF_ROWS)),('NORM_SCALE',2048)):
        if int(params.get(key,-1))!=val:raise ValueError('P1 parameter mismatch '+key)
    dma=mods.get('/axi_dma_0')
    if dma is None:raise ValueError('Missing remap DMA metadata')
    dp={p.get('NAME'):p.get('VALUE') for p in dma.findall('./PARAMETERS/PARAMETER')}
    if int(dp.get('C_INCLUDE_SG',-1))!=0 or int(dp.get('C_SG_LENGTH_WIDTH',-1))!=23:raise ValueError('P1 simple DMA/length metadata mismatch')
    ps=next((m for m in mods.values() if m.get('INSTANCE')=='ps7'),None)
    if ps is None:raise ValueError('Missing PS clock metadata')
    p={x.get('NAME'):x.get('VALUE') for x in ps.findall('./PARAMETERS/PARAMETER')}
    if p.get('PCW_FCLK0_PERIPHERAL_CLKSRC')!='IO PLL':raise ValueError('Unexpected P1 FCLK0 source')
    hz=float(p['PCW_IO_IO_PLL_FREQMHZ'])*1e6/(int(p['PCW_FCLK0_PERIPHERAL_DIVISOR0'])*int(p['PCW_FCLK0_PERIPHERAL_DIVISOR1']))
    if abs(hz-float(p['PCW_CLK0_FREQ']))>1000:raise ValueError('P1 HWH clock tree mismatch')
    display=mods.get('/video/axi_vdma_disp')
    if display is None:raise ValueError('Specified P1 HDMI VDMA hierarchy missing')
    vp={x.get('NAME'):x.get('VALUE') for x in display.findall('./PARAMETERS/PARAMETER')}
    for key,val in (('C_INCLUDE_MM2S',1),('C_INCLUDE_S2MM',0),('C_M_AXIS_MM2S_TDATA_WIDTH',32),('C_NUM_FSTORES',4)):
        if int(vp.get(key,-1))!=val:raise ValueError('Specified P1 HDMI VDMA mismatch '+key)
    for ip in ('/video/hdmi_out/pixel_unpack','/video/hdmi_out/color_convert','/video/hdmi_out/frontend/vtc_out','/video/hdmi_out/frontend/axi_dynclk'):
        if ip not in mods:raise ValueError('Specified P1 HDMI pipeline missing '+ip)
    from v120_sharp import inspect_sharp_metadata
    inspect_sharp_metadata(mods)
    from v122_light import inspect_light_metadata
    inspect_light_metadata(mods)
    checkpoint('P1_PAIR_ADMITTED',source_pair='PWL light27 matched bit + HWH',
        bitfile=str(path),sha256=dict(EXACT_PAIR_SHA256),hdmi_vdma='video/axi_vdma_disp',fclk0_hz=hz,
        hardware_substitution_allowed=False,hardware_modified=True,bit_rebuilt=True)
    return path,info,hz

class P1Backend:
    def __init__(self,bitfile='system.bit',input_shape=(480,640),output_size=(362,512),timeout_s=3.):
        global _OWNER_SESSION
        if _OWNER_SESSION is not None:raise RuntimeError('Previous P1 session must be closed before download')
        path,manifest,hz=inspect_pair(bitfile)
        from pynq import Overlay,MMIO,allocate,Clocks
        # Register official drivers before constructing the overlay hierarchy.
        import pynq.lib.video,pynq.lib.dma
        self.overlay=Overlay(str(path),ignore_version=True);self.path=path;self.manifest=manifest
        from v64_hdmi_display import validate_overlay
        validate_overlay(self.overlay,manifest)
        if abs(float(Clocks.fclk0_mhz)*1e6-hz)>5000:raise RuntimeError('Actual FCLK0 differs from selected P1 HWH')
        self.mmio=MMIO(0x40000000,0x40)
        dma_info=self.overlay.ip_dict['axi_dma_0']
        # Do not instantiate overlay.axi_dma_0: its PYNQ channel constructor
        # starts the channels immediately. This adapter exclusively owns MMIO.
        self.dma=MMIO(int(dma_info['phys_addr']),int(dma_info['addr_range']))
        self.owner=threading.get_ident();self.timeout_s=float(timeout_s);self.active=False;self.failed=False;self.closed=False
        self.ticket=0;self.buffers=[];self.packed={};self.input_shape=tuple(input_shape)
        self.output_slots=None;self.completed_output=None
        self.input_packer=None;self.active_input_slot=None
        #   ⭐ C2：None = 还没决定；True/False = PL 侧做 YUV→RGB / PS 侧做
        self.input_yuyv=None;self.pl_color_mode=0;self.last_release_s=0.
        self.output_capacity=int(output_size[0])*int(output_size[1]);self.dma_snapshot=np.zeros(4,np.uint32)
        self.parameter_snapshot=np.zeros(2,np.uint32)
        _OWNER_SESSION=self
        try:
            for _ in range(2):self.buffers.append(allocate(shape=(int(input_shape[0])*int(input_shape[1])*4,),dtype=np.uint8))
            self.tile_buffer=allocate(shape=(self.output_capacity*4,),dtype=np.uint8);self.buffers.append(self.tile_buffer)
            from v90_transaction import OutputSlots
            self.output_slots=OutputSlots(allocate,self.output_capacity)
            self._start_fresh()
            from v120_sharp import SharpControl,SharpDriver
            self.sharp_control=SharpControl(path.parent)
            self.sharp=SharpDriver(self.overlay,MMIO,self.sharp_control)
            from v122_light import LightControl,LightDriver
            self.light_control=LightControl(path.parent)
            self.light=LightDriver(self.overlay,MMIO,self.light_control)
        except BaseException:
            self.close();raise
        checkpoint('P1_BACKEND_READY',durable=True,version=int(self.mmio.read(0x30)),fclk0_hz=hz,
            rows=int(__import__('p11_contract').LINE_BUF_ROWS),max_width=int(__import__('p11_contract').LINE_BUF_W),input_format='YUYV_or_BGRX',internal_line_format='RGB565',
            cma_bytes=sum(b.nbytes for b in self.buffers)+sum(b.nbytes for b in self.output_slots.buffers),ack='ten_register_readback_plus_software_ticket',
            board_hardware_tested=manifest.get('board_hardware_tested',False))
    def _assert_owner(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('P1 device access must stay on owner thread')
        if self.failed or self.closed:raise RuntimeError('P1 session failed/closed; restart board after active DMA error')
    def _start_fresh(self):
        d=self.dma;tx,rx=d.read(4),d.read(0x34)
        if not(tx&1 and rx&1) or (tx|rx)&0x70:raise RuntimeError('Fresh overlay DMA is not halted/clean')
        d.write(0,4);end=time.perf_counter()+self.timeout_s
        while d.read(0)&4:
            if time.perf_counter()>end:raise TimeoutError('Fresh P1 DMA reset timed out')
            time.sleep(.0002)
        d.write(0x30,1);d.write(0,1)
        while (d.read(4)|d.read(0x34))&1:
            if time.perf_counter()>end:raise TimeoutError('Fresh P1 DMA start timed out')
            time.sleep(.0002)
        # This adapter owns the simple DMA directly; PYNQ transfer/wait is never called.
        self.dma_array=d.array
    def _configure(self,tile,size):
        before=parameters(self.mmio.array,tile.packet,self.parameter_snapshot)
        self.ticket+=1;return self.ticket,before
    def _input_format(self):
        # This exact supplied pair is remap1.5. Its CTRL is write-only and
        # has no YUYV/colour mode latch. Use the existing native BGRX32 packer;
        # never probe unsupported format bits or reinterpret raw YUYV as RGB.
        if self.input_yuyv is None:
            from v31_pixels import color_mode
            self.input_yuyv=False;self.pl_color_mode=int(color_mode())&3
            checkpoint('P1_INPUT_FORMAT',durable=True,yuyv=False,color_mode=self.pl_color_mode,
                requested=os.environ.get('P11_YUYV_INPUT','1')!='0',
                reason='paired_remap_1p5_BGRX32_only',input_format='BGRX32',bytes_per_pixel=4,
                color_conversion='existing_native_CPU',board_FPS_verified=False)
        return self.input_yuyv
    def _copy_input_batch(self,job,slot):
        #   ⭐ C2：只做 strided memcpy，**不做 YUV→RGB**（那步挪进 PL 了）。
        #   目的地是 CMA（可缓存），源是相机 mmap 的 YUYV 行；crop 的 left/width
        #   都已按偶数对齐（v8_geometry.make_tile 保证），所以每行 4 字节对齐。
        #   ⚠️ 一次 numpy 赋值 = 一次 C 层 strided copy，没有 Python 逐像素循环。
        from v91_native import PackedInput
        from v31_pixels import require_yuyv
        dest=self.buffers[slot];image=require_yuyv(job.lease.image)
        #   ⚠️ 与写进 PL 的 color_mode 必须一致，否则 PL 用错系数 ⇒ 颜色偏但不报错
        if int(job.color_mode)!=int(self.pl_color_mode):
            raise RuntimeError('YUYV color_mode %d != PL %d'%(int(job.color_mode),int(self.pl_color_mode)))
        from v64_io import copy_yuyv_rows
        offsets=[];offset=0;begin=time.perf_counter();native=0.
        for tile in job.tiles:
            x,y,w,h=map(int,tile.crop)
            if (x&1) or (w&1):raise RuntimeError('YUYV crop must be even-aligned: %r'%((x,w),))
            n=w*h*2
            if offset+n>dest.nbytes:return None
            #   ⚠️ 必须用 C++ 的每行 memcpy（ctypes）。
            #      numpy 三维赋值在**桌面 x86 上并不慢**（122 KB 0.003 ms），
            #      所以早先"numpy 退化成逐 2 字节"的解释是【错的】，已撤。
            #      板上真正贵的是 ctypes 调用的 GIL/调度抖动（见 C1）。
            t=time.perf_counter();copy_yuyv_rows(image,(x,y,w,h),dest,offset);native+=time.perf_counter()-t
            offsets.append(offset);offset+=n
        return PackedInput(job,offsets,dict(input_pack_batch=True,input_pack_yuyv=True,input_bpp=2,
            input_pack_tiles=len(job.tiles),input_pack_bytes=offset,
            input_pack_converted_pixels=offset//2,input_pack_kernel_calls=len(job.tiles),
            input_pack_native_s=native,input_pack_wrapper_s=time.perf_counter()-begin-native,
            input_pack_pl_copy=True))
    def _pack_input_batch(self,job,slot):
        self._assert_owner()
        if slot not in (0,1) or (self.active and slot==self.active_input_slot):
            raise RuntimeError('Cannot pack an active P1 input buffer')
        if self._input_format():
            batch=self._copy_input_batch(job,slot)
            if batch is None:raise RuntimeError('YUYV input copy rejected a tile')
            job.release_source()
            return batch
        if self.input_packer is None:
            from v91_native import InputPackWorkspace
            self.input_packer=InputPackWorkspace()
        batch=self.input_packer.pack(job,self.buffers[slot])
        if batch is not None:job.release_source()  # All crops now own independent CMA bytes.
        return batch
    def prefill(self,job,slot):
        """Only the owner copies into idle CMA; never change current DMA buffer."""
        self._assert_owner()
        if job is None or job.state=='LOST' or not job.tiles:return 0.
        key=(job.index,slot)
        if key in self.packed:return 0.
        begin=time.perf_counter();batch=self._pack_input_batch(job,slot)
        if batch is not None:
            self.packed[key]=batch
            return time.perf_counter()-begin
        pack_yuyv(job.lease.image,job.tiles[0].crop,job.color_mode,self.buffers[slot])
        # DMA sees a CMA copy; no camera MMAP address is programmed.
        self.packed[key]=job.tiles[0]
        # A multi-tile job still needs its leased source for subsequent crops.
        if len(job.tiles)==1:job.release_source()
        return time.perf_counter()-begin
    def execute(self,job,lookahead=None):
        self._assert_owner()
        if job.state=='LOST':raise ValueError('LOST frame cannot be submitted')
        ow,oh=job.size
        if ow*oh>self.output_capacity:raise ValueError('Output exceeds persistent capacity')
        if not job.tiles:raise ValueError('Current P1 frame has no proved tiles')
        # Whole-width strips have contiguous output rows. RX addresses must be
        # four-byte aligned: the immutable DMA has no data-realignment engine.
        row_end=0;direct_rows=True
        for tile in job.tiles:
            x0,y0,x1,y1=tile.box
            if x0!=0 or x1!=ow or y0!=row_end or y1<=y0 or y1>oh:direct_rows=False;break
            row_end=y1
        direct_rows=direct_rows and row_end==oh
        _t0=time.perf_counter()          # ⭐ 诊断：release/acquire 原先落在 owner_s 之外
        if self.completed_output is not None:self.completed_output.release();self.completed_output=None
        self.completed_output=self.output_slots.acquire(ow,oh)
        _out_reset_s=time.perf_counter()-_t0
        result=self.completed_output.array
        receive_buffer=self.output_slots.buffers[self.completed_output.index] if direct_rows else self.tile_buffer
        timing=dict(control_s=0.,input_copy_s=0.,cache_sync_s=0.,dma_wait_s=0.,tile_assembly_s=0.,
            owner_release_s=0.,owner_prep_s=0.,owner_sharp_prep_s=0.,owner_arm_s=0.,owner_sharp_done_s=0.,
            lookahead_service_s=0.,lookahead_prefills=0,tiles=len(job.tiles),
            direct_row_receive=bool(direct_rows),receive_layout='full_width_row_offsets' if direct_rows else 'tile_then_host_assembly',
            tile_assembly_bytes=0,output_cache_batches=0,output_slot=self.completed_output.index,
            completed_output_reference=True,owner_out_reset_s=_out_reset_s,
            prev_release_source_s=float(getattr(self,'last_release_s',0.)),
            #   ⭐ 2026-10-25：查 tile 数到底被什么卡住 —— 是行缓存的 ROWS 还是别的。
            #      peak_rows = 该 tile 需要的最大源行跨度（证明里算出来的），
            #      ROWS=192 是硬件上限，两者一比就知道"加深行缓存能不能少切块"。
            tile_boxes=[list(map(int,t.box)) for t in job.tiles],
            tile_crops=[list(map(int,t.crop)) for t in job.tiles],
            tile_peak_rows=int(max((t.proof.get('peak_rows') or 0) for t in job.tiles)),
            tile_crop_w=int(max(int(t.crop[2]) for t in job.tiles)),
            tile_crop_h=int(max(int(t.crop[3]) for t in job.tiles)))
        began=time.perf_counter();cpu=time.thread_time();slot=job.index%2
        try:
            timing['sharp_receipt']=self.sharp.begin_frame(job.tiles)
            if hasattr(self,'light'):timing['light_receipt']=self.light.begin_frame(job.tiles)
            from v91_native import PackedInput
            #   ⚠️ 2026-10-31：预取深度改 2 后命中率从 14% 升到 ~92%，LOST 帧不会走 execute，
            #      它的预取条目就永远没人 pop ⇒ 字典会无限长。这里顺手清掉过期的（正常 ≤2 项）。
            if self.packed:
                for stale in [k for k in self.packed if k[0]<job.index]:self.packed.pop(stale,None)
            packed_first=self.packed.pop((job.index,slot),None)
            batch=packed_first if isinstance(packed_first,PackedInput) else None
            if batch is not None and not batch.matches(job):raise RuntimeError('Stale P1 input batch does not belong to this frame')
            pack_begin=time.perf_counter()
            if packed_first is None:batch=self._pack_input_batch(job,slot)
            timing['input_copy_s']+=time.perf_counter()-pack_begin
            timing.update(input_pack_batch=batch is not None,input_pack_prefilled=isinstance(packed_first,PackedInput))
            if batch is not None:timing.update(batch.detail)
            #   ⭐ 2026-10-24 诊断：owner_s 里有 13.4 ms 说不清（run 83），先把它拆成
            #      前置 / 循环 / 收尾 三段，循环内部再用已有的子计时往下减。
            #      ⚠️ 纯计时，不改任何行为。
            timing['owner_setup_s']=time.perf_counter()-began
            loop_begin=time.perf_counter()
            for number,tile in enumerate(job.tiles):
                t=time.perf_counter();packed=packed_first if number==0 else None
                if batch is None and packed is not tile:pack_yuyv(job.lease.image,tile.crop,job.color_mode,self.buffers[slot])
                timing['input_copy_s']+=time.perf_counter()-t
                t=time.perf_counter()
                if len(job.tiles)==1:job.release_source()
                timing['owner_release_s']+=time.perf_counter()-t
                if self.active:raise RuntimeError('Cannot reconfigure active remap')
                t=time.perf_counter();ticket,before=self._configure(tile,job.size);timing['control_s']+=time.perf_counter()-t
                t_prep=time.perf_counter()
                #   ⚠️ n_in 的 bpp 必须跟着【实际送进 DMA 的格式】走：
                #      BGRX32=4、YUYV=2。写错会让 DMA 多搬/少搬一半的字节，
                #      现象是"图错位但核不报错"，很难查。
                #   ⚠️ 行缓存 MAX_W=640（2026-10-25 由 1024 降下来换 ROWS=320）。
                #      crop 宽度超 640 会让行缓存地址**静默回绕**（错图但不报错），
                #      所以在这里硬挡一道 —— 规划器那边改漏了也炸得出来。
                from p11_contract import LINE_BUF_W as _LBW
                if int(tile.crop[2])>_LBW:
                    raise RuntimeError('P1 crop width %d exceeds line buffer MAX_W=%d'%(int(tile.crop[2]),_LBW))
                n_in=tile.crop[2]*tile.crop[3]*(4 if batch is None else int(batch.bpp))
                tw,th=tile.box[2]-tile.box[0],tile.box[3]-tile.box[1];n_out=tw*th*4
                if not tile.proof.get('valid') or not tile.proof.get('complete_domain_verified') or n_in>=(1<<23) or n_out>=(1<<23):raise RuntimeError('Unproved P1 tile')
                receive_offset=tile.box[1]*ow*4 if direct_rows else 0
                if receive_offset<0 or receive_offset+n_out>receive_buffer.nbytes or receive_offset%4:
                    raise RuntimeError('P1 receive span exceeds aligned CMA capacity')
                receive_address=int(receive_buffer.physical_address)+receive_offset
                if receive_address+n_out>(1<<32):raise RuntimeError('P1 receive span exceeds 32-bit address space')
                input_offset=0 if batch is None else int(batch.offsets[number])
                if input_offset<0 or input_offset%4 or input_offset+n_in>self.buffers[slot].nbytes:
                    raise RuntimeError('P1 input batch span exceeds aligned CMA capacity')
                input_address=int(self.buffers[slot].physical_address)+input_offset
                if input_address+n_in>(1<<32):raise RuntimeError('P1 input span exceeds 32-bit address space')
                timing['owner_prep_s']+=time.perf_counter()-t_prep
                t=time.perf_counter()
                if batch is None or number==0:self.buffers[slot].flush()
                # The CPU never touches output storage between strip transfers.
                # Flush once before the first strip, invalidate after the last.
                if not direct_rows or number==0:receive_buffer.flush()
                timing['cache_sync_s']+=time.perf_counter()-t
                expected=(before+1)&65535
                # Set active before the first physical submission; failure pins all CMA.
                self.active=True
                self.active_input_slot=slot
                d=self.dma
                t=time.perf_counter();self.sharp.prepare_tile(tile);timing['owner_sharp_prep_s']+=time.perf_counter()-t
                t=time.perf_counter();arm(self.dma_array,receive_address,input_address,n_out,n_in);timing['owner_arm_s']+=time.perf_counter()-t
                t=time.perf_counter();deadline=t+self.timeout_s;prefilled=False;stop_requested=False
                while True:
                    try:rc,snapshot=poll(self.dma_array,self.mmio.array,expected,.002,self.dma_snapshot)
                    except KeyboardInterrupt:
                        # Drain the current physical transfer before allowing a
                        # normal user stop to release CMA or change the overlay.
                        stop_requested=True;continue
                    if rc<0:raise RuntimeError('P1 DMA error '+str(snapshot))
                    if rc==1:break
                    if time.perf_counter()>=deadline:raise TimeoutError('P1 DMA/frame timeout '+str(snapshot))
                    # Completion gets checked before any next-frame CPU prefill.
                    if not stop_requested and not prefilled and number==len(job.tiles)-1 and lookahead is not None:
                        next_job=lookahead()
                        if next_job is not None and next_job.index==job.index+1:
                            spent=self.prefill(next_job,1-slot);timing['lookahead_service_s']+=spent
                            timing['lookahead_prefills']+=int(spent>0);prefilled=True
                timing['dma_wait_s']+=time.perf_counter()-t-timing['lookahead_service_s']
                t=time.perf_counter()
                if int(d.read(0x58))!=n_out:raise RuntimeError('P1 receive byte count differs from this tile')
                self.sharp.completed_tile()
                timing['owner_sharp_done_s']+=time.perf_counter()-t
                self.active=False
                self.active_input_slot=None
                t=time.perf_counter()
                if not direct_rows or number==len(job.tiles)-1:
                    receive_buffer.invalidate();timing['output_cache_batches']+=1
                timing['cache_sync_s']+=time.perf_counter()-t
                t=time.perf_counter();x0,y0,x1,y1=tile.box
                if direct_rows:
                    # This completed slot is immutable until both the P1 owner
                    # and HDMI reader release their explicit references.
                    pass
                else:
                    np.copyto(result[y0:y1,x0:x1],self.tile_buffer[:n_out].reshape(th,tw,4))
                    timing['tile_assembly_bytes']+=n_out
                timing['tile_assembly_s']+=time.perf_counter()-t
                timing['ticket']=ticket;timing['frame_count']=expected;timing['parameter_readbacks']=10*len(job.tiles)
                timing['parameter_readback_verified']=True
                if stop_requested:timing['stop_requested']=True
            if hasattr(self,'light'):self.light.completed_frame()
            timing['owner_loop_s']=time.perf_counter()-loop_begin
            timing['owner_tail_s']=time.perf_counter()-began-timing['owner_setup_s']-timing['owner_loop_s']
            #   循环内部「已计时项」之和 —— 与 owner_loop_s 的差就是没被覆盖的部分
            timing['owner_loop_accounted_s']=(timing['input_copy_s']+timing['control_s']+
                timing['cache_sync_s']+timing['dma_wait_s']+timing['tile_assembly_s']+
                timing['owner_release_s']+timing['owner_prep_s']+timing['owner_sharp_prep_s']+
                timing['owner_arm_s']+timing['owner_sharp_done_s'])
            timing.update(owner_s=time.perf_counter()-began,owner_thread_cpu_s=time.thread_time()-cpu)
            return result,timing
        except BaseException as exc:
            self.failed=True
            if self not in _RETAINED:_RETAINED.append(self)
            checkpoint('P1_OWNER_FAILED',durable=True,active=self.active,error=repr(exc),ticket=self.ticket,
                dma_state=[int(self.dma.read(o)) for o in (4,0x34)],frame_count=int(self.mmio.read(0x34)),buffers_retained=True)
            raise
        finally:
            #   ⭐ 诊断：归还相机 buffer 可能才是"看不见的等待" —— 计时并挂到实例上，
            #      下一帧的 timing 里会带出来（一帧延迟，统计用没问题）。
            _t_rel=time.perf_counter()
            job.release_source()
            self.last_release_s=time.perf_counter()-_t_rel
    def output_reference(self,image):
        # Only completed output may cross to HDMI; no DMA ownership transfers.
        self._assert_owner()
        if image is None:return None
        if self.active or self.completed_output is None:raise RuntimeError('Output not completed')
        return self.completed_output
    def close(self):
        global _OWNER_SESSION
        if self.closed:return
        if self.active or self.failed:
            if self not in _RETAINED:_RETAINED.append(self)
            raise RuntimeError('Failed/active P1 DMA: CMA and overlay retained; reboot board')
        self._assert_owner()
        # Even an idle DMA must be halted before its overlay may be replaced.
        self.dma.write(0,0);self.dma.write(0x30,0);deadline=time.perf_counter()+self.timeout_s
        while not(self.dma.read(4)&1 and self.dma.read(0x34)&1):
            if time.perf_counter()>=deadline:
                self.failed=True;_RETAINED.append(self)
                raise TimeoutError('P1 DMA did not halt; CMA/overlay retained')
            time.sleep(.0002)
        if hasattr(self,'light'):self.light.close()
        elif hasattr(self,'light_control'):self.light_control.close()
        if hasattr(self,'sharp'):self.sharp.close()
        elif hasattr(self,'sharp_control'):self.sharp_control.close()
        if self.completed_output is not None:self.completed_output.release();self.completed_output=None
        if self.output_slots is not None:
            try:self.output_slots.close()
            except BaseException:
                self.failed=True
                if self not in _RETAINED:_RETAINED.append(self)
                raise
        if self.input_packer is not None:self.input_packer.close();self.input_packer=None
        for buf in self.buffers:buf.freebuffer()
        self.buffers.clear();self.packed.clear();self.closed=True
        if _OWNER_SESSION is self:_OWNER_SESSION=None
