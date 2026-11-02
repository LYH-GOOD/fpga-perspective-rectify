"""Explicit AI-page selection; requests never run in the normal video loop."""
from pathlib import Path
import hashlib, time
import numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _check(context, deadline):
    context.check()
    if time.perf_counter() >= deadline:
        raise TimeoutError('AI selection session ended')
    if context.display.error is not None:
        raise context.display.error


def select_frame(context, raw, color_mode, frozen, deadline, camera=None,auto_recapture=False):
    """Return a verified seed, or (None,None) for an explicit new capture.

    Own and retire every Request before source replacement, handoff or return.
    Request/Inspection retain generation, token, sequence and source checks.
    A failed inference stays on the AI page. Manual is a separate user request.
    """
    from v98_ai_request import start_request
    from v75_ui import UIReturnRequested
    display = context.display
    inspection = display.inspection
    task = None
    started = None
    try:
        _check(context, deadline)
        if not inspection.begin_ai(raw, color_mode, context.generation, frozen.sequence):
            _check(context, deadline)
            raise RuntimeError('AI page was not accepted')
        checkpoint('AI_SELECTION_BEGIN', generation=context.generation,
                   sequence=frozen.sequence, source='frozen_current_camera_frame',
                   fixed_source=camera is None, manual_fallback='explicit_user_only')
        while True:
            _check(context, deadline)
            if task is not None:
                task.poll()
                inspection.ai_progress(context.generation,
                    'candidate' if task.done.is_set() else
                    str((task.progress or {}).get('stage') or task.service.state))
            action = inspection.take_action(context.generation)
            if action is not None:
                name, value = action
                if name == 'ai':
                    if task is not None:
                        task.close()
                        task = None
                    started = time.perf_counter()
                    try:
                        task = start_request(inspection, context.generation)
                        checkpoint('AI_REQUEST_DISPATCHED', generation=context.generation,
                                   sequence=frozen.sequence, request_id=task.receipt['request_id'],
                                   initial_service_state=task.service.state)
                    except Exception as exc:
                        inspection.ai_failed(context.generation, str(exc), 'runtime_error')
                elif name == 'refresh':
                    return None, None
                elif name in ('auto', 'manual'):
                    # UI dispatch creates the requested next ticket; never
                    # switch to a manual seed inside an AI-labelled session.
                    raise UIReturnRequested()
                elif name == 'confirm':
                    if task is not None:
                        task.close()
                        task = None
                    _check(context, deadline)
                    if camera is not None:
                        while not context.native_setup.done.is_set():
                            _check(context, deadline)
                            context.native_setup.done.wait(.10)
                        context.native_setup.result()
                        try:
                            from v100_ai_tracking import align_current
                            current, quad = align_current(context, camera, frozen, value)
                        except (ValueError, TimeoutError) as exc:
                            _check(context, deadline)
                            if auto_recapture:
                                checkpoint('AI_AUTOMATIC_RECAPTURE',generation=context.generation,
                                    reason=str(exc),policy='bounded fresh-source retry, at most two per entry')
                                return None,None
                            inspection.ai_alignment_failed(context.generation, str(exc))
                            continue
                        frozen.release()
                    else:
                        current, quad = frozen, value
                    checkpoint('AI_SEED_ACCEPTED', generation=context.generation,
                               sequence=current.sequence, corner_source='ai',
                               total_click_request_ms=(time.perf_counter()-started)*1000.
                                   if started is not None else None,
                               includes_cold_start=True, current_alignment=camera is not None,
                               hardware_proof_still_required=True)
                    return current, quad
            with display.condition:
                display.condition.wait(.10)
    finally:
        if task is not None:
            task.close()


def select_live(context, camera, deadline):
    from v79_acquire import OwnedFrame
    warming = True
    warm_begin = time.perf_counter()
    observed = 0
    previous_sequence=None
    recaptures=0
    while True:
        _check(context, deadline)
        try:
            frame = camera.take(.15)
        except TimeoutError:
            continue
        try:
            sequence=int(frame.sequence)
            if sequence!=previous_sequence:observed+=1;previous_sequence=sequence
            # A slow FIRST delivery must not bypass all startup observations.
            if warming and observed<12:continue
            if warming:checkpoint('AI_CAPTURE_SETTLED',generation=context.generation,
                distinct_frames=observed,selected_sequence=sequence,elapsed_s=time.perf_counter()-warm_begin,
                policy='minimum distinct frames; video content is not a global stillness test')
            warming = False
            raw = np.array(frame.image, copy=True, order='C')
            raw.setflags(write=False)
            frozen = OwnedFrame(raw, float(frame.ready), int(frame.sequence),
                                float(frame.timestamp), int(frame.flags))
        finally:
            frame.release()
        selected = None
        try:
            selected, quad = select_frame(context, raw, camera.color_mode,
                                          frozen, deadline, camera,auto_recapture=recaptures<2)
            if selected is not None:
                return selected, quad
            recaptures+=1
        finally:
            if selected is not frozen:
                frozen.release()
