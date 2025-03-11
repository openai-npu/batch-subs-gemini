#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import platform
import subprocess
import logging
import shutil
import requests
import zipfile
import tarfile
import tempfile
import hashlib
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# FFmpeg 실행파일 기본 위치
FFMPEG_EXECUTABLES = {
    "darwin": ["ffmpeg", "ffprobe"],  # macOS
    "win32": ["ffmpeg.exe", "ffprobe.exe"],  # Windows
    "linux": ["ffmpeg", "ffprobe"]  # Linux
}

# FFmpeg 다운로드 URL (필요에 따라 업데이트)
FFMPEG_DOWNLOAD_URLS = {
    "darwin": "https://evermeet.cx/ffmpeg/getrelease/zip",  # macOS
    "win32": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",  # Windows
    "linux": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"  # Linux
}

# 내장 ffmpeg 경로 캐시
_ffmpeg_path_cache = None
_ffprobe_path_cache = None
_ffmpeg_verified = False

def get_ffmpeg_executable():
    """ffmpeg 실행 파일 경로를 가져옵니다."""
    global _ffmpeg_path_cache, _ffmpeg_verified
    
    # 이미 검증된 경로가 있으면 재사용
    if _ffmpeg_path_cache and _ffmpeg_verified:
        return _ffmpeg_path_cache
    
    try:
        # 기본 검색 경로
        paths_to_check = []
        
        # 1. 내장 ffmpeg 확인 (패키지된 앱일 경우)
        app_path = get_app_path()
        if app_path:
            bin_dir = os.path.join(app_path, "Contents", "Frameworks", "bin")
            if os.path.exists(bin_dir):
                paths_to_check.append(bin_dir)
        
        # 2. 스크립트와 동일한 디렉토리 확인
        script_dir = os.path.dirname(os.path.abspath(__file__))
        paths_to_check.append(script_dir)
        paths_to_check.append(os.path.join(script_dir, "bin"))
        
        # 3. 시스템 경로 확인
        system_paths = os.environ.get("PATH", "").split(os.pathsep)
        paths_to_check.extend(system_paths)
        
        # 운영체제별 실행 파일 이름
        system = platform.system().lower()
        if system == "darwin":
            executable_name = "ffmpeg"
        elif system == "windows":
            executable_name = "ffmpeg.exe"
        else:  # linux 등
            executable_name = "ffmpeg"
        
        # 모든 경로에서 ffmpeg 찾기
        ffmpeg_path = None
        for path in paths_to_check:
            candidate = os.path.join(path, executable_name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                logger.debug(f"ffmpeg 후보 찾음: {candidate}")
                if verify_ffmpeg(candidate):
                    ffmpeg_path = candidate
                    _ffmpeg_verified = True
                    break
                else:
                    logger.warning(f"ffmpeg 검증 실패: {candidate}")
        
        # ffmpeg을 찾을 수 없으면 다운로드 시도
        if not ffmpeg_path:
            logger.warning("사용 가능한 ffmpeg을 찾을 수 없습니다. 다운로드를 시도합니다.")
            ffmpeg_path = download_ffmpeg()
            if ffmpeg_path:
                _ffmpeg_verified = True
        
        _ffmpeg_path_cache = ffmpeg_path
        return ffmpeg_path
        
    except Exception as e:
        logger.error(f"ffmpeg 실행 파일 찾기 오류: {e}")
        return None

def get_ffprobe_executable():
    """ffprobe 실행 파일 경로를 가져옵니다."""
    global _ffprobe_path_cache, _ffmpeg_verified
    
    # 이미 검증된 경로가 있으면 재사용
    if _ffprobe_path_cache and _ffmpeg_verified:
        return _ffprobe_path_cache
    
    try:
        # ffmpeg 경로가 있으면 동일한 디렉토리에서 ffprobe 찾기
        ffmpeg_path = get_ffmpeg_executable()
        if ffmpeg_path:
            ffmpeg_dir = os.path.dirname(ffmpeg_path)
            
            # 운영체제별 실행 파일 이름
            system = platform.system().lower()
            if system == "darwin":
                executable_name = "ffprobe"
            elif system == "windows":
                executable_name = "ffprobe.exe"
            else:  # linux 등
                executable_name = "ffprobe"
            
            ffprobe_path = os.path.join(ffmpeg_dir, executable_name)
            if os.path.isfile(ffprobe_path) and os.access(ffprobe_path, os.X_OK):
                if verify_ffprobe(ffprobe_path):
                    _ffprobe_path_cache = ffprobe_path
                    return ffprobe_path
                else:
                    logger.warning(f"ffprobe 검증 실패: {ffprobe_path}")
        
        # ffprobe를 찾을 수 없으면 다운로드 시도 (ffmpeg와 함께 다운로드됨)
        if not _ffprobe_path_cache:
            logger.warning("사용 가능한 ffprobe를 찾을 수 없습니다. 다운로드를 시도합니다.")
            download_ffmpeg()  # ffmpeg와 함께 ffprobe도 다운로드됨
            
            # 다시 ffprobe 찾기 시도
            ffmpeg_path = get_ffmpeg_executable()
            if ffmpeg_path:
                ffmpeg_dir = os.path.dirname(ffmpeg_path)
                ffprobe_path = os.path.join(ffmpeg_dir, executable_name)
                if os.path.isfile(ffprobe_path) and os.access(ffprobe_path, os.X_OK):
                    if verify_ffprobe(ffprobe_path):
                        _ffprobe_path_cache = ffprobe_path
                        return ffprobe_path
        
        return _ffprobe_path_cache
        
    except Exception as e:
        logger.error(f"ffprobe 실행 파일 찾기 오류: {e}")
        return None

def verify_ffmpeg(ffmpeg_path):
    """ffmpeg 실행 파일의 무결성과 실행 가능성을 확인합니다."""
    if not os.path.exists(ffmpeg_path):
        return False
    
    try:
        # 간단한 ffmpeg 명령으로 실행 가능한지 테스트
        result = subprocess.run(
            [ffmpeg_path, "-version"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            timeout=5  # 5초 타임아웃
        )
        
        if result.returncode == 0:
            logger.info(f"ffmpeg 검증 성공: {ffmpeg_path}")
            return True
        else:
            logger.warning(f"ffmpeg 검증 실패 (반환 코드: {result.returncode}): {ffmpeg_path}")
            return False
    except Exception as e:
        logger.error(f"ffmpeg 검증 중 오류: {str(e)}")
        return False

def verify_ffprobe(ffprobe_path):
    """ffprobe 실행 파일의 무결성과 실행 가능성을 확인합니다."""
    if not os.path.exists(ffprobe_path):
        return False
    
    try:
        # 간단한 ffprobe 명령으로 실행 가능한지 테스트
        result = subprocess.run(
            [ffprobe_path, "-version"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            timeout=5  # 5초 타임아웃
        )
        
        if result.returncode == 0:
            logger.info(f"ffprobe 검증 성공: {ffprobe_path}")
            return True
        else:
            logger.warning(f"ffprobe 검증 실패 (반환 코드: {result.returncode}): {ffprobe_path}")
            return False
    except Exception as e:
        logger.error(f"ffprobe 검증 중 오류: {str(e)}")
        return False

def get_app_path():
    """패키지된 앱의 경로를 가져옵니다."""
    try:
        if getattr(sys, 'frozen', False):
            if platform.system() == 'Darwin':  # macOS
                # PyInstaller macOS bundle
                return os.path.normpath(os.path.join(os.path.dirname(sys.executable), '..', '..'))
            else:
                # PyInstaller Windows/Linux executable
                return os.path.dirname(sys.executable)
        return None
    except Exception as e:
        logger.error(f"앱 경로 확인 중 오류: {str(e)}")
        return None

def download_ffmpeg():
    """시스템에 맞는 FFmpeg을 다운로드하고 설치합니다."""
    system = platform.system().lower()
    if system == "darwin":
        return download_ffmpeg_macos()
    elif system == "windows":
        return download_ffmpeg_windows()
    elif system == "linux":
        return download_ffmpeg_linux()
    else:
        logger.error(f"지원되지 않는 운영체제: {system}")
        return None

def download_ffmpeg_macos():
    """macOS용 FFmpeg을 다운로드하고 설치합니다."""
    try:
        # 다운로드 URL
        url = "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"
        ffprobe_url = "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"
        
        # 다운로드 및 설치 경로
        download_dir = os.path.join(tempfile.gettempdir(), "ffmpeg_download")
        install_dir = os.path.join(os.path.expanduser("~"), ".batch_subs_gemini", "bin")
        
        # 디렉토리 생성
        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(install_dir, exist_ok=True)
        
        # ffmpeg 다운로드
        ffmpeg_zip = os.path.join(download_dir, "ffmpeg.zip")
        logger.info(f"FFmpeg 다운로드 중... URL: {url}")
        
        response = requests.get(url, timeout=60)
        with open(ffmpeg_zip, 'wb') as f:
            f.write(response.content)
        
        # ffmpeg 압축 해제
        with zipfile.ZipFile(ffmpeg_zip, 'r') as zip_ref:
            zip_ref.extractall(download_dir)
        
        # ffmpeg 설치
        ffmpeg_exec = os.path.join(download_dir, "ffmpeg")
        if os.path.exists(ffmpeg_exec):
            shutil.copy2(ffmpeg_exec, install_dir)
            os.chmod(os.path.join(install_dir, "ffmpeg"), 0o755)
        
        # ffprobe 다운로드
        ffprobe_zip = os.path.join(download_dir, "ffprobe.zip")
        logger.info(f"FFprobe 다운로드 중... URL: {ffprobe_url}")
        
        response = requests.get(ffprobe_url, timeout=60)
        with open(ffprobe_zip, 'wb') as f:
            f.write(response.content)
        
        # ffprobe 압축 해제
        with zipfile.ZipFile(ffprobe_zip, 'r') as zip_ref:
            zip_ref.extractall(download_dir)
        
        # ffprobe 설치
        ffprobe_exec = os.path.join(download_dir, "ffprobe")
        if os.path.exists(ffprobe_exec):
            shutil.copy2(ffprobe_exec, install_dir)
            os.chmod(os.path.join(install_dir, "ffprobe"), 0o755)
        
        # 임시 파일 정리
        shutil.rmtree(download_dir, ignore_errors=True)
        
        logger.info(f"FFmpeg/FFprobe가 성공적으로 설치되었습니다: {install_dir}")
        
        # 캐시 초기화 및 새 경로 반환
        global _ffmpeg_path_cache, _ffprobe_path_cache, _ffmpeg_verified
        _ffmpeg_path_cache = os.path.join(install_dir, "ffmpeg")
        _ffprobe_path_cache = os.path.join(install_dir, "ffprobe")
        _ffmpeg_verified = True
        
        return _ffmpeg_path_cache
        
    except Exception as e:
        logger.error(f"FFmpeg 다운로드 중 오류: {str(e)}")
        return None

def download_ffmpeg_windows():
    """Windows용 FFmpeg을 다운로드하고 설치합니다."""
    try:
        # 다운로드 URL - Windows용 (gyan.dev에서 제공하는 정적 빌드)
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        
        # 다운로드 및 설치 경로
        download_dir = os.path.join(tempfile.gettempdir(), "ffmpeg_download")
        install_dir = os.path.join(os.path.expanduser("~"), ".batch_subs_gemini", "bin")
        
        # 디렉토리 생성
        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(install_dir, exist_ok=True)
        
        # ffmpeg 다운로드
        ffmpeg_zip = os.path.join(download_dir, "ffmpeg.zip")
        logger.info(f"FFmpeg 다운로드 중... URL: {url}")
        
        response = requests.get(url, timeout=120)  # 더 긴 타임아웃 (파일이 클 수 있음)
        with open(ffmpeg_zip, 'wb') as f:
            f.write(response.content)
        
        # ffmpeg 압축 해제
        with zipfile.ZipFile(ffmpeg_zip, 'r') as zip_ref:
            zip_ref.extractall(download_dir)
        
        # 압축 해제 후 bin 폴더 찾기
        bin_dir = None
        for root, dirs, files in os.walk(download_dir):
            if "bin" in dirs:
                bin_dir = os.path.join(root, "bin")
                break
        
        if not bin_dir:
            logger.error("압축 해제된 파일에서 bin 디렉토리를 찾을 수 없습니다.")
            return None
        
        # ffmpeg, ffprobe 파일 찾아 복사
        ffmpeg_exec = os.path.join(bin_dir, "ffmpeg.exe")
        ffprobe_exec = os.path.join(bin_dir, "ffprobe.exe")
        
        if os.path.exists(ffmpeg_exec):
            shutil.copy2(ffmpeg_exec, install_dir)
        
        if os.path.exists(ffprobe_exec):
            shutil.copy2(ffprobe_exec, install_dir)
        
        # 임시 파일 정리
        shutil.rmtree(download_dir, ignore_errors=True)
        
        logger.info(f"FFmpeg/FFprobe가 성공적으로 설치되었습니다: {install_dir}")
        
        # 캐시 초기화 및 새 경로 반환
        global _ffmpeg_path_cache, _ffprobe_path_cache, _ffmpeg_verified
        _ffmpeg_path_cache = os.path.join(install_dir, "ffmpeg.exe")
        _ffprobe_path_cache = os.path.join(install_dir, "ffprobe.exe")
        _ffmpeg_verified = True
        
        return _ffmpeg_path_cache
        
    except Exception as e:
        logger.error(f"FFmpeg 다운로드 중 오류: {str(e)}")
        return None

def download_ffmpeg_linux():
    """Linux용 FFmpeg을 다운로드하고 설치합니다."""
    try:
        # 다운로드 URL - Linux용 (johnvansickle.com에서 제공하는 정적 빌드)
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        
        # 다운로드 및 설치 경로
        download_dir = os.path.join(tempfile.gettempdir(), "ffmpeg_download")
        install_dir = os.path.join(os.path.expanduser("~"), ".batch_subs_gemini", "bin")
        
        # 디렉토리 생성
        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(install_dir, exist_ok=True)
        
        # ffmpeg 다운로드
        ffmpeg_tar = os.path.join(download_dir, "ffmpeg.tar.xz")
        logger.info(f"FFmpeg 다운로드 중... URL: {url}")
        
        response = requests.get(url, timeout=120)  # 더 긴 타임아웃 (파일이 클 수 있음)
        with open(ffmpeg_tar, 'wb') as f:
            f.write(response.content)
        
        # tar.xz 압축 해제 (subprocess 사용)
        subprocess.run(["tar", "-xf", ffmpeg_tar, "-C", download_dir], check=True)
        
        # 압축 해제 후 ffmpeg, ffprobe 실행 파일 찾기
        ffmpeg_exec = None
        ffprobe_exec = None
        
        for root, dirs, files in os.walk(download_dir):
            for file in files:
                if file == "ffmpeg" and not ffmpeg_exec:
                    ffmpeg_exec = os.path.join(root, file)
                elif file == "ffprobe" and not ffprobe_exec:
                    ffprobe_exec = os.path.join(root, file)
        
        # 파일 복사 및 권한 설정
        if ffmpeg_exec and os.path.exists(ffmpeg_exec):
            shutil.copy2(ffmpeg_exec, install_dir)
            os.chmod(os.path.join(install_dir, "ffmpeg"), 0o755)
        
        if ffprobe_exec and os.path.exists(ffprobe_exec):
            shutil.copy2(ffprobe_exec, install_dir)
            os.chmod(os.path.join(install_dir, "ffprobe"), 0o755)
        
        # 임시 파일 정리
        shutil.rmtree(download_dir, ignore_errors=True)
        
        logger.info(f"FFmpeg/FFprobe가 성공적으로 설치되었습니다: {install_dir}")
        
        # 캐시 초기화 및 새 경로 반환
        global _ffmpeg_path_cache, _ffprobe_path_cache, _ffmpeg_verified
        _ffmpeg_path_cache = os.path.join(install_dir, "ffmpeg")
        _ffprobe_path_cache = os.path.join(install_dir, "ffprobe")
        _ffmpeg_verified = True
        
        return _ffmpeg_path_cache
        
    except Exception as e:
        logger.error(f"FFmpeg 다운로드 중 오류: {str(e)}")
        return None

def run_ffmpeg_command(cmd, timeout=None):
    """ffmpeg 명령을 안전하게 실행합니다."""
    try:
        # ffmpeg 경로 확인
        ffmpeg_path = get_ffmpeg_executable()
        if not ffmpeg_path:
            logger.error("ffmpeg을 찾을 수 없습니다.")
            return False, "ffmpeg을 찾을 수 없습니다."
        
        # 명령에 ffmpeg 경로 추가
        if isinstance(cmd, list) and len(cmd) > 0:
            cmd[0] = ffmpeg_path
        else:
            logger.error("잘못된 ffmpeg 명령 형식입니다.")
            return False, "잘못된 명령 형식입니다."
        
        # 명령 실행
        logger.debug(f"FFmpeg 명령 실행: {' '.join(cmd)}")
        process = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            timeout=timeout
        )
        
        # 결과 확인
        if process.returncode == 0:
            return True, process.stdout
        else:
            logger.warning(f"FFmpeg 명령 실패 (코드: {process.returncode}): {process.stderr}")
            return False, process.stderr
            
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg 명령 타임아웃 (시간: {timeout}초)")
        return False, "명령 실행 시간 초과"
    except Exception as e:
        logger.error(f"FFmpeg 명령 실행 중 오류: {str(e)}")
        return False, str(e)

def run_ffprobe_command(cmd, timeout=None):
    """ffprobe 명령을 안전하게 실행합니다."""
    try:
        # ffprobe 경로 확인
        ffprobe_path = get_ffprobe_executable()
        if not ffprobe_path:
            logger.error("ffprobe를 찾을 수 없습니다.")
            return False, "ffprobe를 찾을 수 없습니다."
        
        # 명령에 ffprobe 경로 추가
        if isinstance(cmd, list) and len(cmd) > 0:
            cmd[0] = ffprobe_path
        else:
            logger.error("잘못된 ffprobe 명령 형식입니다.")
            return False, "잘못된 명령 형식입니다."
        
        # 명령 실행
        logger.debug(f"FFprobe 명령 실행: {' '.join(cmd)}")
        process = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            timeout=timeout
        )
        
        # 결과 확인
        if process.returncode == 0:
            return True, process.stdout
        else:
            logger.warning(f"FFprobe 명령 실패 (코드: {process.returncode}): {process.stderr}")
            return False, process.stderr
            
    except subprocess.TimeoutExpired:
        logger.error(f"FFprobe 명령 타임아웃 (시간: {timeout}초)")
        return False, "명령 실행 시간 초과"
    except Exception as e:
        logger.error(f"FFprobe 명령 실행 중 오류: {str(e)}")
        return False, str(e)

def check_ffmpeg_integrity():
    """ffmpeg와 ffprobe의 무결성을 검사하고 필요시 다시 다운로드합니다."""
    # ffmpeg 확인
    ffmpeg_path = get_ffmpeg_executable()
    if not ffmpeg_path or not verify_ffmpeg(ffmpeg_path):
        logger.warning("FFmpeg 무결성 검사 실패, 다시 다운로드합니다.")
        download_ffmpeg()
        ffmpeg_path = get_ffmpeg_executable()
    
    # ffprobe 확인
    ffprobe_path = get_ffprobe_executable()
    if not ffprobe_path or not verify_ffprobe(ffprobe_path):
        logger.warning("FFprobe 무결성 검사 실패, 다시 다운로드합니다.")
        download_ffmpeg()  # ffmpeg와 ffprobe 모두 다운로드
        ffprobe_path = get_ffprobe_executable()
    
    return ffmpeg_path and ffprobe_path

# 모듈 로드 시 초기화
logger.info(f"FFmpeg 유틸리티 모듈 로드됨 (시스템: {platform.system()})") 