#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import subprocess
import logging
import re
from pathlib import Path
import ffmpeg_utils

logger = logging.getLogger(__name__)

def list_subtitle_tracks(video_file):
    """비디오 파일에서 모든 자막 트랙 목록을 가져옵니다.
    
    Returns:
        list: 자막 트랙 정보의 리스트 (각 항목은 dict 형태)
            [
                {
                    'index': 0,            # 트랙 인덱스
                    'stream_index': 2,     # 스트림 인덱스
                    'language': 'eng',     # 언어 코드
                    'codec': 'subrip',     # 코덱
                    'title': 'English',    # 제목 (있는 경우)
                }
            ]
    """
    # 방법 1: ffprobe로 시도 (상세 정보)
    try:
        return _get_subtitle_tracks_with_ffprobe(video_file)
    except Exception as e:
        logger.warning(f"ffprobe로 자막 트랙 정보 가져오기 실패: {e} - 대체 방법 시도")
    
    # 방법 2: ffmpeg -i로 시도 (제한된 정보)
    try:
        return _get_subtitle_tracks_with_ffmpeg(video_file)
    except Exception as e:
        logger.warning(f"ffmpeg로 자막 트랙 정보 가져오기 실패: {e}")
    
    # 방법 3: 최소한으로라도 첫 번째 자막 트랙이 있다고 가정
    logger.warning("모든 방법이 실패했습니다. 기본 자막 트랙을 가정합니다.")
    return [{'index': 0, 'stream_index': 0, 'language': 'und', 'codec': 'unknown', 'title': 'Auto-detected subtitle'}]


def _get_subtitle_tracks_with_ffprobe(video_file):
    """ffprobe를 사용하여 자막 트랙 정보를 가져옵니다."""
    # ffmpeg_utils의 무결성 검사 실행
    if not ffmpeg_utils.check_ffmpeg_integrity():
        logger.error("ffprobe 무결성 검사에 실패했습니다.")
        raise RuntimeError("ffprobe 실행 파일 무결성 검사 실패")
    
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "s",
            video_file
        ]
        
        logger.debug(f"ffprobe 명령어 실행: {' '.join(cmd)}")
        
        # 새로운 ffmpeg_utils 함수 사용
        success, output = ffmpeg_utils.run_ffprobe_command(cmd, timeout=30)
        
        if not success:
            logger.error(f"ffprobe 명령 실패: {output}")
            raise RuntimeError(f"ffprobe 명령 실패: {output}")
            
        if not output.strip():
            logger.warning("ffprobe가 빈 출력을 반환했습니다")
            return []
            
        video_info = json.loads(output)
        
        subtitle_tracks = []
        for i, stream in enumerate(video_info.get("streams", [])):
            if stream.get("codec_type") == "subtitle":
                track = {
                    'index': i,  # 자막 트랙의 순서 인덱스
                    'stream_index': stream.get("index"),  # 실제 스트림 인덱스
                    'language': stream.get("tags", {}).get("language", "und"),
                    'codec': stream.get("codec_name", "unknown"),
                    'title': stream.get("tags", {}).get("title", "")
                }
                subtitle_tracks.append(track)
        
        logger.info(f"ffprobe를 사용하여 {len(subtitle_tracks)}개의 자막 트랙 발견")
        return subtitle_tracks
    
    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 오류: {e}")
        raise
    except Exception as e:
        logger.error(f"자막 트랙 정보 가져오기 중 오류 발생: {type(e).__name__} - {e}")
        raise


def _get_subtitle_tracks_with_ffmpeg(video_file):
    """ffmpeg -i 명령을 사용하여 자막 트랙 정보를 가져옵니다."""
    # ffmpeg_utils의 무결성 검사 실행
    if not ffmpeg_utils.check_ffmpeg_integrity():
        logger.error("ffmpeg 무결성 검사에 실패했습니다.")
        raise RuntimeError("ffmpeg 실행 파일 무결성 검사 실패")
    
    try:
        # ffmpeg -i 명령은 오류 출력에 스트림 정보를 남김
        cmd = [
            "ffmpeg",
            "-i", video_file
        ]
        
        logger.debug(f"ffmpeg 명령어 실행: {' '.join(cmd)}")
        
        # 의도적으로 에러를 받아오기 위한 호출 (새로운 ffmpeg_utils 함수 사용)
        success, stderr = ffmpeg_utils.run_ffmpeg_command(cmd, timeout=30)
        
        # 출력에서 자막 스트림 정보 추출 (ffmpeg는 항상 이 명령에 대해 실패하므로 success는 무시)
        output = stderr
        subtitle_tracks = []
        
        # "Stream #0:N(LANG): Subtitle: CODEC" 패턴 검색
        subtitle_pattern = re.compile(r'Stream\s+#\d+:(\d+)(?:\((\w+)\))?\s*:\s*Subtitle:\s*(\w+)')
        matches = subtitle_pattern.findall(output)
        
        for i, match in enumerate(matches):
            stream_index, lang, codec = match
            stream_index = int(stream_index)
            
            if not lang:
                lang = "und"
                
            track = {
                'index': i,
                'stream_index': stream_index,
                'language': lang,
                'codec': codec,
                'title': ''
            }
            subtitle_tracks.append(track)
        
        logger.info(f"ffmpeg -i를 사용하여 {len(subtitle_tracks)}개의 자막 트랙 발견")
        return subtitle_tracks
        
    except Exception as e:
        logger.error(f"ffmpeg로 자막 트랙 정보 가져오기 중 오류 발생: {type(e).__name__} - {e}")
        raise

def find_best_subtitle_track(tracks, preferred_languages=None):
    """가장 적합한 자막 트랙을 찾습니다.
    
    Args:
        tracks (list): 자막 트랙 목록
        preferred_languages (list, optional): 선호하는 언어 코드 목록. 예: ['eng', 'en', 'kor']
    
    Returns:
        dict: 선택된 자막 트랙 정보 또는 None
    """
    if not tracks:
        return None
    
    # 기본 선호 언어 설정
    if preferred_languages is None:
        preferred_languages = ['eng', 'en']  # 기본적으로 영어 선호
    
    # 선호하는 언어에 맞는 트랙 찾기
    for lang in preferred_languages:
        for track in tracks:
            if track['language'].lower() == lang.lower():
                logger.info(f"선호하는 언어({lang})의 자막 트랙을 찾았습니다: {track}")
                return track
    
    # 선호 언어가 없으면, 'English' 또는 영어 관련 단어가 제목에 있는 트랙 찾기
    for track in tracks:
        title = track.get('title', '').lower()
        if 'english' in title or ' eng' in title or title.endswith('eng') or title.startswith('eng'):
            logger.info(f"영어 제목의 자막 트랙을 찾았습니다: {track}")
            return track
    
    # 그 외의 경우 첫 번째 트랙 사용
    logger.info(f"선호하는 언어의 자막이 없어 첫 번째 트랙을 사용합니다: {tracks[0]}")
    return tracks[0]

def extract_subtitle(video_file, output_srt, track_index=None, preferred_languages=None):
    """비디오 파일에서 자막을 추출합니다.
    
    Args:
        video_file (str): 비디오 파일 경로
        output_srt (str): 출력 SRT 파일 경로
        track_index (int, optional): 추출할 자막 트랙 인덱스. None이면 자동 선택
        preferred_languages (list, optional): 선호하는 언어 코드 목록
    
    Returns:
        bool: 성공 여부
    """
    # 방법 1: 지정된 트랙이나 자동 선택한 트랙 사용
    if track_index is not None or extract_subtitle_auto(video_file, output_srt, track_index, preferred_languages):
        return True
    
    # 방법 2: 첫 번째 자막 트랙 사용 (단순 방식)
    if extract_subtitle_simple(video_file, output_srt):
        return True
    
    # 방법 3: FFmpeg의 모든 미디어 스트림 중 첫 번째 자막 트랙 강제 시도
    if extract_subtitle_force(video_file, output_srt):
        return True
    
    logger.error(f"모든 자막 추출 방법이 실패했습니다: {os.path.basename(video_file)}")
    return False


def extract_subtitle_auto(video_file, output_srt, track_index=None, preferred_languages=None):
    """트랙 자동 선택 또는 지정된 트랙으로 자막을 추출합니다."""
    # ffmpeg 무결성 검사
    if not ffmpeg_utils.check_ffmpeg_integrity():
        logger.error("ffmpeg 무결성 검사에 실패했습니다.")
        return False
    
    try:
        # 트랙 인덱스가 지정되지 않은 경우, 자막 트랙 목록을 가져와서 선택
        if track_index is None:
            tracks = list_subtitle_tracks(video_file)
            if not tracks:
                logger.error(f"'{os.path.basename(video_file)}'에서 자막 트랙을 찾을 수 없습니다.")
                return False
            
            selected_track = find_best_subtitle_track(tracks, preferred_languages)
            if not selected_track:
                logger.error(f"'{os.path.basename(video_file)}'에서 적합한 자막 트랙을 찾을 수 없습니다.")
                return False
            
            track_index = selected_track['index']
            logger.info(f"자막 트랙 #{track_index} ({selected_track.get('language', 'unknown')}) 추출 중...")
        
        # ffmpeg 명령 실행
        cmd = [
            "ffmpeg", 
            "-y",  # 기존 파일 덮어쓰기
            "-i", video_file,
            "-map", f"0:s:{track_index}",  # 선택한 자막 트랙
            "-c:s", "srt",  # SRT 형식으로 변환
            output_srt
        ]
        
        logger.debug(f"추출 명령어: {' '.join(cmd)}")
        
        # 새로운 ffmpeg_utils 함수 사용
        success, output = ffmpeg_utils.run_ffmpeg_command(cmd, timeout=120)
        
        # 출력 파일 확인
        if success and os.path.exists(output_srt) and os.path.getsize(output_srt) > 0:
            logger.info(f"자막 추출 성공: {os.path.basename(output_srt)}")
            return True
        else:
            logger.warning(f"자막 파일이 생성되지 않았거나 비어있습니다: {output_srt}")
            if not success:
                logger.warning(f"ffmpeg 오류: {output}")
            return False
        
    except Exception as e:
        logger.error(f"자막 추출 중 오류 발생: {type(e).__name__} - {e}")
        return False


def extract_subtitle_simple(video_file, output_srt):
    """단순하게 첫 번째 자막 트랙만 추출합니다 (main.py 방식)."""
    # ffmpeg 무결성 검사
    if not ffmpeg_utils.check_ffmpeg_integrity():
        logger.error("ffmpeg 무결성 검사에 실패했습니다.")
        return False
    
    try:
        # 가장 단순한 방식: 첫 번째 자막 트랙 추출 시도
        cmd = [
            "ffmpeg", 
            "-y",  # 기존 파일 덮어쓰기
            "-i", video_file,
            "-map", "0:s:0",  # 첫 번째 자막 트랙
            "-c:s", "srt",  # SRT 형식으로 변환
            output_srt
        ]
        
        logger.info(f"단순 방식으로 자막 추출 시도: {os.path.basename(video_file)}")
        logger.debug(f"추출 명령어: {' '.join(cmd)}")
        
        # 새로운 ffmpeg_utils 함수 사용
        success, output = ffmpeg_utils.run_ffmpeg_command(cmd, timeout=120)
        
        # 출력 파일 확인
        if success and os.path.exists(output_srt) and os.path.getsize(output_srt) > 0:
            logger.info(f"단순 방식으로 자막 추출 성공: {os.path.basename(output_srt)}")
            return True
        else:
            logger.warning(f"단순 방식으로 자막 파일이 생성되지 않았거나 비어있습니다: {output_srt}")
            if not success:
                logger.warning(f"ffmpeg 오류: {output}")
            return False
            
    except Exception as e:
        logger.warning(f"단순 방식 자막 추출 중 오류: {type(e).__name__} - {e}")
        return False


def extract_subtitle_force(video_file, output_srt):
    """모든 자막 추출 방법이 실패한 경우 강제로 시도합니다."""
    # ffmpeg 무결성 검사
    if not ffmpeg_utils.check_ffmpeg_integrity():
        logger.error("ffmpeg 무결성 검사에 실패했습니다.")
        return False
    
    try:
        # 모든 스트림 정보 획득
        cmd_info = [
            "ffmpeg",
            "-i", video_file
        ]
        
        logger.info(f"강제 추출 위한 스트림 정보 획득 중: {os.path.basename(video_file)}")
        
        # 새로운 ffmpeg_utils 함수 사용
        success, stderr = ffmpeg_utils.run_ffmpeg_command(cmd_info, timeout=30)
        
        # 스트림 인덱스 추출 (stderr에 출력됨)
        output = stderr
        streams = []
        
        # 모든 스트림 찾기
        stream_pattern = re.compile(r'Stream\s+#\d+:(\d+)')
        streams = stream_pattern.findall(output)
        
        if not streams:
            logger.warning("스트림 정보를 찾을 수 없습니다.")
            return False
            
        # 각 스트림을 자막으로 가정하고 시도
        for stream_idx in streams:
            try:
                logger.info(f"스트림 #{stream_idx}를 자막으로 추출 시도")
                
                cmd = [
                    "ffmpeg", 
                    "-y",
                    "-i", video_file,
                    "-map", f"0:{stream_idx}",
                    "-c:s", "srt",
                    output_srt
                ]
                
                # 새로운 ffmpeg_utils 함수 사용
                success, _ = ffmpeg_utils.run_ffmpeg_command(cmd, timeout=60)
                
                # 유효한 자막인지 확인
                if success and os.path.exists(output_srt) and os.path.getsize(output_srt) > 0:
                    # 최소한의 SRT 형식 검증
                    with open(output_srt, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read(200)  # 처음 200바이트만 읽음
                        if re.search(r'\d+\s+\d{2}:\d{2}:\d{2},\d{3}', content):
                            logger.info(f"스트림 #{stream_idx}에서 자막 추출 성공")
                            return True
                    
                    # SRT 형식이 아니라면 파일 삭제
                    if os.path.exists(output_srt):
                        os.remove(output_srt)
                    
            except Exception as e:
                logger.debug(f"스트림 #{stream_idx} 추출 실패: {e}")
                continue
                
        logger.warning("어떤 스트림에서도 자막을 추출할 수 없습니다.")
        return False
        
    except Exception as e:
        logger.warning(f"강제 자막 추출 중 오류: {type(e).__name__} - {e}")
        return False

def extract_all_subtitles(video_file, output_dir=None, preferred_format='srt'):
    """비디오 파일에서 모든 자막 트랙을 추출합니다.
    
    Args:
        video_file (str): 비디오 파일 경로
        output_dir (str, optional): 출력 디렉토리. None이면 비디오 파일과 같은 위치
        preferred_format (str, optional): 선호하는 자막 형식 (기본: 'srt')
    
    Returns:
        list: 추출된 자막 파일 경로 목록
    """
    # 출력 디렉토리 설정
    if output_dir is None:
        output_dir = os.path.dirname(video_file)
    
    # 디렉토리가 없으면 생성
    os.makedirs(output_dir, exist_ok=True)
    
    # 자막 트랙 목록 가져오기
    tracks = list_subtitle_tracks(video_file)
    if not tracks:
        logger.error(f"'{os.path.basename(video_file)}'에서 자막 트랙을 찾을 수 없습니다.")
        return []
    
    extracted_files = []
    video_basename = os.path.splitext(os.path.basename(video_file))[0]
    
    # 모든 트랙 추출
    for track in tracks:
        track_index = track['index']
        language = track.get('language', 'und')
        title = track.get('title', '')
        
        # 파일명 생성 (비디오이름_언어_타이틀.확장자)
        filename = f"{video_basename}_{language}"
        if title:
            # 파일명에 사용할 수 없는 문자 제거
            clean_title = re.sub(r'[\\/*?:"<>|]', '', title)
            filename += f"_{clean_title}"
        
        output_file = os.path.join(output_dir, f"{filename}.{preferred_format}")
        
        if extract_subtitle(video_file, output_file, track_index):
            extracted_files.append(output_file)
    
    return extracted_files

def verify_subtitle_file(srt_file):
    """SRT 파일이 유효한지 확인합니다.
    
    Args:
        srt_file (str): SRT 파일 경로
    
    Returns:
        tuple: (유효성 여부, 줄 수)
    """
    try:
        with open(srt_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 최소한의 유효한 SRT 구조 확인
        lines = content.strip().split('\n')
        line_count = len(lines)
        
        # 최소 4줄 이상인지 확인 (인덱스, 시간, 내용, 빈줄)
        if line_count < 4:
            return False, line_count
        
        # 첫 번째 줄이 숫자(인덱스)인지 확인
        if not lines[0].strip().isdigit():
            return False, line_count
        
        # 두 번째 줄이 시간 형식인지 확인 (HH:MM:SS,mmm --> HH:MM:SS,mmm)
        time_pattern = r'\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}'
        if not re.match(time_pattern, lines[1].strip()):
            return False, line_count
        
        return True, line_count
    
    except Exception as e:
        logger.error(f"자막 파일 확인 중 오류 발생: {e}")
        return False, 0

# 테스트
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # 비디오 파일 경로 (테스트용)
    video_file = "example.mkv"
    
    if os.path.exists(video_file):
        # 자막 트랙 목록 출력
        tracks = list_subtitle_tracks(video_file)
        print(f"자막 트랙 수: {len(tracks)}")
        for track in tracks:
            print(f"트랙 #{track['index']}: 언어={track['language']}, 코덱={track['codec']}, 제목={track['title']}")
        
        # 자막 추출 테스트
        output_srt = "example_extracted.srt"
        if extract_subtitle(video_file, output_srt):
            print(f"자막 추출 성공: {output_srt}")
        else:
            print("자막 추출 실패")
    else:
        print(f"테스트할 비디오 파일을 찾을 수 없습니다: {video_file}")
        print("이 스크립트를 테스트하려면 현재 디렉토리에 example.mkv 파일을 배치하세요.") 