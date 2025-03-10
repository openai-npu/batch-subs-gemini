#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import subprocess
import platform
import logging
from pathlib import Path
import io

# Windows에서 UTF-8 출력을 강제로 설정
if platform.system() == 'Windows':
    # 표준 출력과 에러 출력을 UTF-8로 재정의
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    # Windows 콘솔에서 UTF-8 강제 활성화
    os.system('chcp 65001 > NUL')

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('build.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

def analyze_environment():
    """현재 환경 정보를 수집하여 로깅"""
    logger.info(f"OS: {platform.system()} {platform.release()}")
    logger.info(f"Python: {platform.python_version()}")
    logger.info(f"Working dir: {os.getcwd()}")
    
    try:
        pip_list = subprocess.check_output([sys.executable, '-m', 'pip', 'list']).decode('utf-8')
        logger.info(f"Installed packages:\n{pip_list}")
    except Exception as e:
        logger.warning(f"Error while checking package list: {e}")

def clean_build():
    """Clean build directories"""
    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            logger.info(f"Removing directory: {dir_name}")
            shutil.rmtree(dir_name)
    
    # Clean spec files
    for spec_file in Path('.').glob('*.spec'):
        logger.info(f"Removing spec file: {spec_file}")
        spec_file.unlink()

def get_icon_path():
    """플랫폼별 적절한 아이콘 파일 경로 반환"""
    icon_dir = Path('icons')
    
    # 아이콘 디렉토리 존재 확인
    if not icon_dir.exists():
        logger.warning(f"Icon directory not found: {icon_dir}")
        return None
    
    # 플랫폼별 기본 아이콘 확장자
    if platform.system() == 'Darwin':  # macOS
        icon_extensions = ['.icns', '.png', '.svg']
    elif platform.system() == 'Windows':  # Windows
        icon_extensions = ['.ico', '.png', '.svg']
    else:  # Linux
        icon_extensions = ['.png', '.svg']
    
    # 확장자별로 파일 존재 확인
    for ext in icon_extensions:
        icon_path = icon_dir / f"icon{ext}"
        if icon_path.exists():
            logger.info(f"Icon file found: {icon_path}")
            return str(icon_path)
    
    # 아이콘 파일이 없는 경우
    logger.warning("No icon file found. Building without an icon.")
    return None

def prepare_ffmpeg():
    """ffmpeg와 ffprobe를 준비하고 bin 디렉토리를 생성합니다.
    
    Returns:
        tuple: (성공 여부, 메시지)
    """
    try:
        # bin 디렉토리가 없으면 생성
        bin_dir = Path('bin')
        bin_dir.mkdir(exist_ok=True)
        
        # ffmpeg_utils 모듈 import 시도
        try:
            sys.path.append(os.getcwd())
            import ffmpeg_utils
            
            # ffmpeg 다운로드
            logger.info("FFmpeg 확인 및 다운로드 중...")
            ffmpeg_path = ffmpeg_utils.get_ffmpeg_executable()
            if not ffmpeg_path:
                logger.error("FFmpeg를 찾거나 다운로드할 수 없습니다.")
                return False, "FFmpeg 다운로드 실패"
            
            # ffmpeg가 bin 디렉토리에 없으면 복사
            if not str(ffmpeg_path).startswith(str(bin_dir)):
                target_name = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
                target_path = bin_dir / target_name
                shutil.copy2(ffmpeg_path, target_path)
                # 실행 권한 부여
                if platform.system() != "Windows":
                    os.chmod(target_path, 0o755)
                logger.info(f"FFmpeg 복사됨: {target_path}")
            
            # ffprobe도 동일하게 처리
            ffprobe_path = ffmpeg_utils.get_ffprobe_executable()
            if ffprobe_path:
                if not str(ffprobe_path).startswith(str(bin_dir)):
                    target_name = "ffprobe.exe" if platform.system() == "Windows" else "ffprobe"
                    target_path = bin_dir / target_name
                    shutil.copy2(ffprobe_path, target_path)
                    # 실행 권한 부여
                    if platform.system() != "Windows":
                        os.chmod(target_path, 0o755)
                    logger.info(f"FFprobe 복사됨: {target_path}")
            
            return True, "FFmpeg 준비 완료"
            
        except ImportError:
            logger.warning("ffmpeg_utils 모듈을 임포트할 수 없습니다. FFmpeg 자동 다운로드를 건너뜁니다.")
            return True, "FFmpeg 준비 생략됨"
            
    except Exception as e:
        logger.error(f"FFmpeg 준비 중 오류 발생: {e}")
        return False, f"FFmpeg 준비 오류: {e}"

def build_application():
    """Build the application using PyInstaller"""
    logger.info("Starting build...")
    
    # 환경 분석
    analyze_environment()
    
    # 이전 빌드 파일 정리
    clean_build()
    
    # FFmpeg 준비
    ffmpeg_success, ffmpeg_message = prepare_ffmpeg()
    logger.info(ffmpeg_message)
    
    # 아이콘 경로 찾기
    icon_path = get_icon_path()
    
    # 빌드 명령 구성
    cmd = [
        'pyinstaller',
        '--onedir',  # 단일 디렉토리로 빌드 (--onefile보다 시작 속도 빠름)
        '--windowed',  # GUI 애플리케이션
        '--clean',  # 임시 파일 정리
        '--name', 'batch_subs_gemini',
        '--add-data', f'icons{os.pathsep}icons',
    ]
    
    # bin 디렉토리가 있으면 추가
    bin_dir = Path('bin')
    if bin_dir.exists() and any(bin_dir.iterdir()):
        cmd.extend(['--add-data', f'bin{os.pathsep}bin'])
    
    # 아이콘이 있는 경우 추가
    if icon_path:
        logger.info(f"Using icon: {icon_path}")
        cmd.extend(['--icon', icon_path])
    
    # 필요한 모듈 추가
    hidden_imports = [
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'google.generativeai',
        'google.api_core',
        'google.auth',
        'srt',
        'requests',  # ffmpeg_utils에서 사용
        'ffmpeg_utils',  # 자체 모듈
        'subtitle_utils',  # 자체 모듈
        'logger_utils',  # 새로 추가된 로깅 유틸리티
        'queue',  # 필요한 기본 모듈
        'threading',  # 필요한 기본 모듈
    ]
    
    for hidden_import in hidden_imports:
        cmd.extend(['--hidden-import', hidden_import])
    
    # 경로 추가
    try:
        import site
        site_packages = site.getsitepackages()[0]
        cmd.extend(['--paths', site_packages])
    except Exception as e:
        logger.warning(f"Failed to get site-packages path: {e}")
    
    # 패키지 수집
    packages_to_collect = [
        'google.generativeai',
        'google.api_core',
        'google.auth',
        'srt',
    ]
    
    for package in packages_to_collect:
        cmd.extend(['--collect-all', package])
    
    # 최적화 옵션
    cmd.extend(['--noupx'])  # UPX 압축 비활성화 (더 빠른 빌드)
    cmd.extend(['--strip'])  # 바이너리에서 디버그 심볼 제거 (더 작은 크기)
    
    # 메인 스크립트 추가
    cmd.append('batch_subs_gemini.py')
    
    # 명령 출력
    logger.info(f"Build command: {' '.join(cmd)}")
    
    # 명령 실행
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        logger.info("Build successful!")
        logger.debug(f"Build output: {result.stdout}")
        
        # 추가 정보 출력
        if platform.system() == 'Darwin':
            logger.info("\nApplication location: dist/batch_subs_gemini.app")
        else:
            logger.info("\nApplication location: dist/batch_subs_gemini")
            
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Build failed: {str(e)}")
        logger.error(f"Error output: {e.stderr}")
        return False

def main():
    """Main entry point"""
    try:
        logger.info("Build process started")
        if build_application():
            logger.info("Build process completed successfully.")
        else:
            logger.error("Error occurred during build process.")
            sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main() 