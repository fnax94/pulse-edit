"""Resolve subprocess worker — runs in python_shim/python.exe outside PyInstaller.

Reads JSON commands from stdin, executes Resolve API calls, writes JSON responses to stdout.
Stays alive for the lifetime of the parent PulseEdit process.
"""

import sys
import os
import json


def _setup_resolve():
    """Setup paths and connect to Resolve. Returns (resolve, error_string).

    Belt-and-suspenders: configure PYTHONHOME + HKCU registry pointing at this very
    interpreter, in case the subprocess was launched without the parent's env. Without
    these, fusionscript.dll silently fails init when a conflicting Python is registered.
    """
    # Add Resolve scripting modules to path
    module_paths = [
        os.path.join(os.environ.get("PROGRAMDATA", ""), "Blackmagic Design",
                     "DaVinci Resolve", "Support", "Developer", "Scripting", "Modules"),
    ]
    for mp in module_paths:
        if os.path.isdir(mp) and mp not in sys.path:
            sys.path.insert(0, mp)

    # Force PYTHONHOME to this interpreter's prefix
    own_prefix = sys.prefix
    os.environ["PYTHONHOME"] = own_prefix

    # Force HKCU registry to point at this interpreter — overwrites any conflicting Python install
    try:
        import winreg
        own_exe = sys.executable
        for ver in ("3.10", "3.11", "3.12", "3.13"):
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                      fr"Software\Python\PythonCore\{ver}\InstallPath") as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, own_prefix + os.sep)
                    winreg.SetValueEx(key, "ExecutablePath", 0, winreg.REG_SZ, own_exe)
                    winreg.SetValueEx(key, "WindowedExecutablePath", 0, winreg.REG_SZ, own_exe)
            except OSError:
                pass
    except ImportError:
        pass

    # Set Resolve env vars
    lib_path = os.environ.get("RESOLVE_SCRIPT_LIB", "")
    if not lib_path:
        default = os.path.join(os.environ.get("PROGRAMFILES", ""),
                               "Blackmagic Design", "DaVinci Resolve", "fusionscript.dll")
        if os.path.exists(default):
            os.environ["RESOLVE_SCRIPT_LIB"] = default

    resolve_dir = os.path.join(os.environ.get("PROGRAMFILES", ""),
                               "Blackmagic Design", "DaVinci Resolve")
    if os.path.isdir(resolve_dir):
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(resolve_dir)
            except OSError:
                pass
        os.environ["PATH"] = resolve_dir + os.pathsep + os.environ.get("PATH", "")

    # Add own interpreter dir to DLL search so python3.dll is found locally
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(own_prefix)
        except OSError:
            pass

    try:
        import DaVinciResolveScript as dvr
        resolve = dvr.scriptapp("Resolve")
        if resolve:
            return resolve, None
        return None, "scriptapp returned None"
    except Exception as e:
        return None, str(e)


# Global state
_resolve = None
_project = None
_timeline = None
_media_pool = None
_folders = {}
_clips_cache = {}


def _get_timeline():
    global _project, _timeline, _media_pool
    if not _resolve:
        return None
    _project = _resolve.GetProjectManager().GetCurrentProject()
    if not _project:
        return None
    _media_pool = _project.GetMediaPool()
    _timeline = _project.GetCurrentTimeline()
    return _timeline


def _handle(cmd, args):
    global _resolve, _project, _timeline, _media_pool, _folders, _clips_cache

    if cmd == "connect":
        _resolve, err = _setup_resolve()
        if not _resolve:
            return {"ok": False, "error": err}
        tl = _get_timeline()
        result = {"ok": True, "resolve": True}
        if _project:
            result["project"] = _project.GetName()
        if tl:
            result["timeline"] = tl.GetName()
            result["fps"] = tl.GetSetting("timelineFrameRate")
        return result

    if not _resolve:
        return {"ok": False, "error": "not connected"}

    if cmd == "refresh":
        tl = _get_timeline()
        result = {"ok": True}
        if _project:
            result["project"] = _project.GetName()
        if tl:
            result["timeline"] = tl.GetName()
            result["fps"] = tl.GetSetting("timelineFrameRate")
        return result

    if cmd == "get_audio_tracks":
        if not _timeline:
            return {"ok": True, "tracks": {}}
        tracks = {}
        for t_idx in range(1, _timeline.GetTrackCount("audio") + 1):
            items = _timeline.GetItemListInTrack("audio", t_idx)
            if items and len(items) > 0:
                name = ""
                for item in items:
                    mp = item.GetMediaPoolItem()
                    if mp:
                        name = mp.GetClipProperty("Clip Name") or ""
                        break
                label = f"Track {t_idx}: {name} ({len(items)} clip)"
                tracks[label] = t_idx
        return {"ok": True, "tracks": tracks}

    if cmd == "get_video_tracks":
        if not _timeline:
            return {"ok": True, "tracks": {}}
        tracks = {}
        count = _timeline.GetTrackCount("video")
        for t_idx in range(1, count + 1):
            name = _timeline.GetTrackName("video", t_idx)
            items = _timeline.GetItemListInTrack("video", t_idx)
            n_items = len(items) if items else 0
            label = f"V{t_idx}: {name} ({n_items} clip)" if name else f"V{t_idx} ({n_items} clip)"
            tracks[label] = t_idx
        return {"ok": True, "tracks": tracks}

    if cmd == "find_audio_file":
        track_idx = args.get("track_idx")
        if not _timeline:
            return {"ok": True, "path": None}
        items = _timeline.GetItemListInTrack("audio", track_idx)
        if not items:
            return {"ok": True, "path": None}
        for item in items:
            mp = item.GetMediaPoolItem()
            if mp:
                fp = mp.GetClipProperty("File Path")
                if fp and os.path.exists(fp):
                    return {"ok": True, "path": fp}
        return {"ok": True, "path": None}

    if cmd == "get_media_pool_folders":
        if not _resolve:
            return {"ok": True, "folders": []}
        project = _resolve.GetProjectManager().GetCurrentProject()
        if not project:
            return {"ok": True, "folders": []}
        mp = project.GetMediaPool()
        root = mp.GetRootFolder()
        _folders = {"Root": root}
        _collect_folders(root, "", _folders)
        return {"ok": True, "folders": list(_folders.keys())}

    if cmd == "scan_clips_in_folder":
        folder_name = args.get("folder")
        folder = _folders.get(folder_name)
        if not folder:
            return {"ok": True, "total": 0, "matched": 0}
        clips = folder.GetClipList()
        if not clips:
            return {"ok": True, "total": 0, "matched": 0}
        audio_exts = {".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a", ".aif", ".aiff"}
        total = 0
        for clip in clips:
            fp = clip.GetClipProperty("File Path") or ""
            if not fp or not os.path.exists(fp):
                continue
            frames_str = clip.GetClipProperty("Frames")
            if not frames_str:
                continue
            try:
                frames = int(frames_str)
            except (ValueError, TypeError):
                continue
            if frames <= 0:
                continue
            ext = os.path.splitext(fp)[1].lower()
            if ext in audio_exts:
                continue
            total += 1
        return {"ok": True, "total": total, "matched": total}

    if cmd == "get_clips_from_folder":
        folder_name = args.get("folder")
        fps = args.get("fps")
        folder = _folders.get(folder_name)
        if not folder:
            return {"ok": True, "clips": []}
        clips = folder.GetClipList()
        if not clips:
            return {"ok": True, "clips": []}
        audio_exts = {".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a", ".aif", ".aiff"}
        result = []
        _clips_cache = {}
        for i, clip in enumerate(clips):
            fp = clip.GetClipProperty("File Path") or ""
            if not fp or not os.path.exists(fp):
                continue
            frames_str = clip.GetClipProperty("Frames")
            if not frames_str:
                continue
            try:
                frames = int(frames_str)
            except (ValueError, TypeError):
                continue
            if frames <= 0:
                continue
            ext = os.path.splitext(fp)[1].lower()
            if ext in audio_exts:
                continue
            fps_str = clip.GetClipProperty("FPS") or "24"
            try:
                clip_fps = float(fps_str)
            except (ValueError, TypeError):
                clip_fps = 24.0
            clip_id = f"clip_{i}"
            _clips_cache[clip_id] = clip
            result.append({
                "id": clip_id,
                "name": clip.GetClipProperty("Clip Name") or clip.GetClipProperty("File Name") or "",
                "file_path": fp,
                "frames": frames,
                "fps": clip_fps,
            })
        return {"ok": True, "clips": result}

    if cmd == "clear_timeline_markers":
        if not _timeline:
            return {"ok": True, "removed": 0}
        markers = _timeline.GetMarkers()
        if not markers:
            return {"ok": True, "removed": 0}
        removed = 0
        for frame_id in list(markers.keys()):
            if _timeline.DeleteMarkerAtFrame(frame_id):
                removed += 1
        return {"ok": True, "removed": removed}

    if cmd == "add_marker":
        frame = args["frame"]
        color = args.get("color", "Yellow")
        name = args.get("name", "")
        note = args.get("note", "")
        if _timeline:
            _timeline.AddMarker(frame, color, name, note, 1)
        return {"ok": True}

    if cmd == "clear_video_track":
        track_idx = args["track_idx"]
        if not _timeline:
            return {"ok": True, "removed": 0}
        items = _timeline.GetItemListInTrack("video", track_idx)
        if items and len(items) > 0:
            _timeline.DeleteClips(items)
            return {"ok": True, "removed": len(items)}
        return {"ok": True, "removed": 0}

    if cmd == "place_clips":
        entries = args["entries"]
        track_idx = args["track_idx"]
        marker_frames = args.get("marker_frames", [])
        fps = args["fps"]
        if not _timeline or not _media_pool:
            return {"ok": True, "placed": 0}

        import math
        tl_start = 0
        try:
            tl_start = int(_timeline.GetStartFrame())
        except Exception:
            pass

        sorted_markers = sorted(marker_frames)
        if sorted_markers and sorted_markers[0] > 0:
            sorted_markers.insert(0, 0)

        placed_count = 0
        for i, entry in enumerate(entries):
            clip_id = entry["clip_id"]
            mpi = _clips_cache.get(clip_id)
            if not mpi:
                continue
            start_f = entry["startFrame"]
            end_f = entry["endFrame"]
            clip_fps = entry.get("clip_fps", fps)

            target_marker_idx = i + 1
            if i > 0 and target_marker_idx < len(sorted_markers):
                target_end_abs = sorted_markers[target_marker_idx] + tl_start
                try:
                    items_on_track = _timeline.GetItemListInTrack("video", track_idx)
                    if items_on_track and len(items_on_track) > 0:
                        last_item = items_on_track[-1]
                        actual_pos = int(last_item.GetEnd())
                        needed_tl = target_end_abs - actual_pos
                        if needed_tl > 0:
                            fps_ratio = clip_fps / fps
                            same_fps = abs(fps_ratio - 1.0) < 0.01
                            if same_fps:
                                new_segment = needed_tl
                            else:
                                exact_src = needed_tl * fps_ratio
                                src_lo = max(1, math.floor(exact_src))
                                src_hi = max(1, math.ceil(exact_src))
                                tl_lo = int(src_lo * fps / clip_fps)
                                tl_hi = int(src_hi * fps / clip_fps)
                                if abs(tl_lo - needed_tl) <= abs(tl_hi - needed_tl):
                                    new_segment = src_lo
                                else:
                                    new_segment = src_hi
                            end_f = start_f + new_segment
                except Exception:
                    pass

            result = _media_pool.AppendToTimeline([{
                "mediaPoolItem": mpi,
                "startFrame": start_f,
                "endFrame": end_f,
                "mediaType": 1,
                "trackIndex": track_idx,
            }])
            if result:
                placed_count += 1

        # Return placed items info for zoom/effects
        final_items = _timeline.GetItemListInTrack("video", track_idx)
        placed_ids = []
        if final_items:
            for idx, item in enumerate(final_items):
                item_id = f"tl_item_{idx}"
                _clips_cache[item_id] = item
                placed_ids.append({
                    "id": item_id,
                    "start": int(item.GetStart()),
                    "end": int(item.GetEnd()),
                })
        return {"ok": True, "placed": placed_count, "items": placed_ids}

    if cmd == "apply_zoom":
        item_id = args["item_id"]
        item = _clips_cache.get(item_id)
        if not item:
            return {"ok": False, "error": "item not found"}
        zoom_value = args.get("zoom_value", 1.05)
        try:
            item.SetProperty("ZoomX", zoom_value)
            item.SetProperty("ZoomY", zoom_value)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if cmd == "get_timeline_start_frame":
        if not _timeline:
            return {"ok": True, "frame": 0}
        try:
            return {"ok": True, "frame": int(_timeline.GetStartFrame())}
        except Exception:
            return {"ok": True, "frame": 0}

    return {"ok": False, "error": f"unknown command: {cmd}"}


def _collect_folders(folder, prefix, result):
    subs = folder.GetSubFolderList()
    if not subs:
        return
    for sub in subs:
        name = sub.GetName()
        path = f"{prefix}/{name}" if prefix else name
        result[path] = sub
        _collect_folders(sub, path, result)


def main():
    # Signal ready
    sys.stdout.write(json.dumps({"ready": True}) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            cmd = msg.get("cmd", "")
            args = msg.get("args", {})
            response = _handle(cmd, args)
        except Exception as e:
            response = {"ok": False, "error": str(e)}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
