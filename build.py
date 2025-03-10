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

def build_application():
    """Build the application using PyInstaller"""
    logger.info("Starting build...")
    
    # 환경 분석
    analyze_environment()
    
    # 이전 빌드 파일 정리
    clean_build()
    
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