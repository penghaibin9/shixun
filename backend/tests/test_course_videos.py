from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.teaching.catalog import curriculum_rows


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "backend" / "app" / "resources" / "content" / "course-videos-v1.json"
VIDEO_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "course-videos-v1"


def media_probe() -> str | None:
    override = os.getenv("YUEKE_FFPROBE")
    if override and Path(override).is_file():
        return override
    return shutil.which("ffprobe")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_course_video_policy_matches_the_authoritative_curriculum():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    authority = curriculum_rows(policy["courseId"])
    assert policy["version"] == "1.0.0"
    assert len(authority["lessons"]) == 49
    assert sum(row["lesson_type"] == "THEORY" for row in authority["lessons"]) == 37
    assert sum(row["lesson_type"] == "LAB" for row in authority["lessons"]) == 12
    assert policy["durationPolicy"] == {
        "theoryTargetSeconds": 2400,
        "theoryMinimumSeconds": 2100,
        "theoryMaximumSeconds": 2700,
        "labMinimumSeconds": 600,
    }
    assert policy["reviewPolicy"] == {
        "authorCannotReview": True,
        "ffprobeRequired": True,
        "databaseApprovalRequired": True,
        "productionAcceptanceRequiresHumanSampling": True,
    }


def test_formal_course_videos_have_real_media_transcripts_subtitles_and_hashes():
    probe = media_probe()
    if not probe:
        pytest.skip("需要 ffprobe（媒体探测工具）复核正式视频")

    index = json.loads((VIDEO_DIR / "index.json").read_text(encoding="utf-8"))
    authority = curriculum_rows(index["course_id"])
    expected = {
        row["lesson_id"]: (row["lesson_code"], row["lesson_type"], row["title"])
        for row in authority["lessons"]
    }
    assert index["schema_version"] == "1.0"
    assert index["content_version"] == "1.0.0"
    assert index["complete"] is True
    assert index["video_count"] == 49
    assert index["theory_count"] == 37
    assert index["lab_count"] == 12
    assert len(index["videos"]) == 49
    assert {item["lesson_id"] for item in index["videos"]} == set(expected)

    total_duration = 0
    for item in index["videos"]:
        lesson_code, lesson_kind, title = expected[item["lesson_id"]]
        assert (item["lesson_code"], item["lesson_kind"], item["title"]) == (lesson_code, lesson_kind, title)
        video_path = VIDEO_DIR / item["filename"]
        transcript_path = VIDEO_DIR / item["transcript_filename"]
        caption_path = VIDEO_DIR / item["caption_filename"]
        assert video_path.stat().st_size == item["size_bytes"]
        assert sha256(video_path) == item["sha256"]
        assert sha256(transcript_path) == item["transcript_sha256"]
        assert sha256(caption_path) == item["caption_sha256"]
        transcript = transcript_path.read_text(encoding="utf-8")
        caption = caption_path.read_text(encoding="utf-8")
        assert lesson_code in transcript or lesson_kind == "LAB"
        assert title in transcript
        assert "。。" not in transcript
        assert "-->" in caption and len(caption) > 1000
        assert item["automated_media_check"] == "PASS"
        assert item["human_sampling"] == "PENDING"

        completed = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration,size:stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        media = json.loads(completed.stdout)
        streams = {stream["codec_type"]: stream for stream in media["streams"]}
        actual_duration = round(float(media["format"]["duration"]))
        assert abs(actual_duration - item["duration_seconds"]) <= 1
        assert int(media["format"]["size"]) == item["size_bytes"]
        assert streams["video"]["codec_name"] == "h264"
        assert (streams["video"]["width"], streams["video"]["height"]) == (1280, 720)
        assert streams["audio"]["codec_name"] == "aac"
        assert streams["subtitle"]["codec_name"] == "mov_text"
        if lesson_kind == "THEORY":
            assert 2100 <= actual_duration <= 2700
        else:
            assert actual_duration >= 600
        total_duration += actual_duration

    assert index["duration_total_seconds"] == total_duration
