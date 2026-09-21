import json
import subprocess
from pathlib import Path

from app.common.errors import ApiError


def parse_ffprobe_payload(payload: str) -> tuple[int, int | None, int | None]:
    try:
        data = json.loads(payload)
        duration = round(float(data["format"]["duration"]))
        stream = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), {})
        if duration <= 0:
            raise ValueError
        return duration, stream.get("width"), stream.get("height")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ApiError("RESOURCE.VIDEO_METADATA_INVALID", "无法从真实媒体解析有效时长", 422) from exc


def probe_local_video(path_text: str) -> tuple[int, int | None, int | None]:
    path = Path(path_text).resolve()
    if not path.is_file():
        raise ApiError("RESOURCE.VIDEO_SOURCE_UNAVAILABLE", "视频文件不可读取，不能登记时长", 422)
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=True)
    except FileNotFoundError as exc:
        raise ApiError("RESOURCE.MEDIA_PROBE_UNAVAILABLE", "当前环境未安装 ffprobe，不能伪造视频时长", 503) from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ApiError("RESOURCE.VIDEO_PROBE_FAILED", "真实视频媒体解析失败", 422) from exc
    return parse_ffprobe_payload(result.stdout)
