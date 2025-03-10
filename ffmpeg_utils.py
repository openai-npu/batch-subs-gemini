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
from pathlib import Path

logger = logging.getLogger(__name__)

def get_ffmpeg_executable():
    """현재 시스템에 맞는 ffmpeg 실행 파일 경로를 반환합니다.
    시스템에 설치된 ffmpeg를 먼저 찾고, 없으면 내장 ffmpeg를 사용합니다.
    """
    # 시스템 PATH에서 ffmpeg 찾기
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        logger.info(f"시스템에 설치된 ffmpeg를 사용합니다: {system_ffmpeg}")
        return system_ffmpeg
    
    # 내장 ffmpeg 경로 확인
    app_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
    
    if platform.system() == "Windows":
        embedded_ffmpeg = os.path.join(app_dir, "bin", "ffmpeg.exe")
    else:  # macOS, Linux
        embedded_ffmpeg = os.path.join(app_dir, "bin", "ffmpeg")
    
    if os.path.exists(embedded_ffmpeg):
        logger.info(f"내장 ffmpeg를 사용합니다: {embedded_ffmpeg}")
        # 실행 권한 확인 및 부여
        if platform.system() != "Windows":
            try:
                os.chmod(embedded_ffmpeg, 0o755)  # 실행 권한 부여
            except Exception as e:
                logger.warning(f"ffmpeg에 실행 권한을 부여하지 못했습니다: {e}")
        return embedded_ffmpeg
    
    # 개발 모드에서 다운로드 디렉토리 확인
    bin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
    if platform.system() == "Windows":
        dev_ffmpeg = os.path.join(bin_dir, "ffmpeg.exe")
    else:  # macOS, Linux
        dev_ffmpeg = os.path.join(bin_dir, "ffmpeg")
    
    if os.path.exists(dev_ffmpeg):
        logger.info(f"개발 환경 ffmpeg를 사용합니다: {dev_ffmpeg}")
        # 실행 권한 확인 및 부여
        if platform.system() != "Windows":
            try:
                os.chmod(dev_ffmpeg, 0o755)  # 실행 권한 부여
            except Exception as e:
                logger.warning(f"ffmpeg에 실행 권한을 부여하지 못했습니다: {e}")
        return dev_ffmpeg
    
    # 없으면 다운로드
    logger.warning("ffmpeg를 찾을 수 없습니다. 다운로드를 시도합니다.")
    try:
        downloaded_ffmpeg = download_ffmpeg()
        if downloaded_ffmpeg:
            logger.info(f"다운로드한 ffmpeg를 사용합니다: {downloaded_ffmpeg}")
            return downloaded_ffmpeg
    except Exception as e:
        logger.error(f"ffmpeg 다운로드 실패: {e}")
    
    logger.error("ffmpeg를 찾거나 다운로드할 수 없습니다. ffmpeg를 수동으로 설치하세요.")
    return None

def download_ffmpeg():
    """현재 OS에 맞는 ffmpeg를 다운로드하고 설치합니다."""
    os_name = platform.system()
    os_arch = platform.machine().lower()
    
    # ffmpeg 다운로드 URL 설정
    if os_name == "Windows":
        # Windows 용 ffmpeg 다운로드 URL (32비트와 64비트)
        if "64" in os_arch or "amd64" in os_arch or "x86_64" in os_arch:
            download_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        else:
            download_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win32-gpl.zip"
        
        # 파일 이름
        bin_dir = create_bin_directory()
        zip_path = os.path.join(bin_dir, "ffmpeg.zip")
        
        # 다운로드
        logger.info(f"ffmpeg 다운로드 중 (Windows): {download_url}")
        download_file(download_url, zip_path)
        
        # 압축 해제
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file in zip_ref.namelist():
                if file.endswith("ffmpeg.exe"):
                    with zip_ref.open(file) as source_file, open(os.path.join(bin_dir, "ffmpeg.exe"), "wb") as target_file:
                        shutil.copyfileobj(source_file, target_file)
                    break
        
        # 압축 파일 삭제
        os.remove(zip_path)
        
        # 설치된 ffmpeg 경로 반환
        ffmpeg_path = os.path.join(bin_dir, "ffmpeg.exe")
        if os.path.exists(ffmpeg_path):
            logger.info(f"ffmpeg 설치 완료: {ffmpeg_path}")
            return ffmpeg_path
        
    elif os_name == "Darwin":  # macOS
        # macOS용 ffmpeg 다운로드 URL
        if "arm64" in os_arch or "aarch64" in os_arch:  # Apple Silicon
            download_url = "https://evermeet.cx/ffmpeg/getrelease/zip"
        else:  # Intel
            download_url = "https://evermeet.cx/ffmpeg/getrelease/zip"
        
        # 파일 이름
        bin_dir = create_bin_directory()
        zip_path = os.path.join(bin_dir, "ffmpeg.zip")
        
        # 다운로드
        logger.info(f"ffmpeg 다운로드 중 (macOS): {download_url}")
        download_file(download_url, zip_path)
        
        # 압축 해제
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(bin_dir)
        
        # 압축 파일 삭제
        os.remove(zip_path)
        
        # 설치된 ffmpeg 경로 반환
        ffmpeg_path = os.path.join(bin_dir, "ffmpeg")
        if os.path.exists(ffmpeg_path):
            # 실행 권한 부여
            os.chmod(ffmpeg_path, 0o755)
            logger.info(f"ffmpeg 설치 완료: {ffmpeg_path}")
            return ffmpeg_path
        
    elif os_name == "Linux":
        # Linux용 ffmpeg 다운로드 URL
        if "arm" in os_arch or "aarch64" in os_arch:
            # ARM (Raspberry Pi 등)
            download_url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
        else:
            # x86_64
            download_url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        
        # 파일 이름
        bin_dir = create_bin_directory()
        tar_path = os.path.join(bin_dir, "ffmpeg.tar.xz")
        
        # 다운로드
        logger.info(f"ffmpeg 다운로드 중 (Linux): {download_url}")
        download_file(download_url, tar_path)
        
        # 압축 해제
        with tarfile.open(tar_path, 'r:xz') as tar_ref:
            # ffmpeg 바이너리만 추출
            for member in tar_ref.getmembers():
                if 'ffmpeg' in member.name and not member.name.endswith('/'):
                    member.name = os.path.basename(member.name)
                    tar_ref.extract(member, bin_dir)
        
        # 압축 파일 삭제
        os.remove(tar_path)
        
        # 설치된 ffmpeg 경로 반환
        ffmpeg_path = os.path.join(bin_dir, "ffmpeg")
        if os.path.exists(ffmpeg_path):
            # 실행 권한 부여
            os.chmod(ffmpeg_path, 0o755)
            logger.info(f"ffmpeg 설치 완료: {ffmpeg_path}")
            return ffmpeg_path
    
    logger.error(f"지원되지 않는 운영체제: {os_name}")
    return None

def create_bin_directory():
    """bin 디렉토리를 생성하고 경로를 반환합니다."""
    bin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
    os.makedirs(bin_dir, exist_ok=True)
    return bin_dir

def download_file(url, save_path):
    """파일을 다운로드합니다."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024  # 1 KB
        
        logger.info(f"다운로드 시작: {url}")
        
        with open(save_path, 'wb') as file:
            for data in response.iter_content(block_size):
                file.write(data)
        
        logger.info(f"다운로드 완료: {save_path}")
    except Exception as e:
        logger.error(f"다운로드 실패: {e}")
        raise
    
    return save_path

def check_ffmpeg_version(ffmpeg_path):
    """ffmpeg 버전을 확인합니다."""
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            check=True,
            capture_output=True,
            text=True
        )
        return result.stdout.split('\n')[0]
    except Exception as e:
        logger.error(f"ffmpeg 버전 확인 실패: {e}")
        return "Unknown"

def get_ffprobe_executable():
    """현재 시스템에 맞는 ffprobe 실행 파일 경로를 반환합니다."""
    # 시스템 PATH에서 ffprobe 찾기
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return system_ffprobe
    
    # 내장 ffprobe 경로 확인
    app_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
    
    if platform.system() == "Windows":
        embedded_ffprobe = os.path.join(app_dir, "bin", "ffprobe.exe")
    else:  # macOS, Linux
        embedded_ffprobe = os.path.join(app_dir, "bin", "ffprobe")
    
    if os.path.exists(embedded_ffprobe):
        return embedded_ffprobe
    
    # 개발 모드에서 다운로드 디렉토리 확인
    bin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
    if platform.system() == "Windows":
        dev_ffprobe = os.path.join(bin_dir, "ffprobe.exe")
    else:  # macOS, Linux
        dev_ffprobe = os.path.join(bin_dir, "ffprobe")
    
    if os.path.exists(dev_ffprobe):
        return dev_ffprobe
    
    # 없는 경우 (ffmpeg를 다운로드했으면 ffprobe도 있어야 함)
    logger.warning("ffprobe를 찾을 수 없습니다.")
    return None

# 테스트
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ffmpeg_path = get_ffmpeg_executable()
    if ffmpeg_path:
        version = check_ffmpeg_version(ffmpeg_path)
        print(f"ffmpeg 경로: {ffmpeg_path}")
        print(f"ffmpeg 버전: {version}")
    else:
        print("ffmpeg를 찾을 수 없습니다.")
    
    ffprobe_path = get_ffprobe_executable()
    if ffprobe_path:
        print(f"ffprobe 경로: {ffprobe_path}")
    else:
        print("ffprobe를 찾을 수 없습니다.") 