#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import subprocess
import platform
import logging
from pathlib import Path
import site

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('win_build.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

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

def create_runtime_hook():
    """Windows용 런타임 훅 스크립트 생성"""
    hook_content = """
import os
import sys
import ctypes

# Add the application directory to PATH
if hasattr(sys, 'frozen'):
    bundle_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(sys.executable)))
    os.environ['PATH'] = f"{bundle_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    
    # Add _internal directory to PATH
    internal_dir = os.path.join(os.path.dirname(sys.executable), '_internal')
    if os.path.exists(internal_dir):
        os.environ['PATH'] = f"{internal_dir}{os.pathsep}{os.environ['PATH']}"
    
    # Add bin directory to PATH if it exists
    bin_dir = os.path.join(bundle_dir, 'bin')
    if os.path.exists(bin_dir):
        os.environ['PATH'] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

# Ensure proper encoding
if hasattr(sys, 'frozen'):
    # Set UTF-8 encoding
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)

# Debug info
if hasattr(sys, 'frozen'):
    print(f"Python executable: {sys.executable}")
    print(f"Working directory: {os.getcwd()}")
    print(f"sys._MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}")
"""
    
    hook_path = 'windows_hook.py'
    with open(hook_path, 'w', encoding='utf-8') as f:
        f.write(hook_content)
    
    logger.info(f"Created Windows runtime hook at {hook_path}")
    return os.path.abspath(hook_path)

def prepare_binaries():
    """필요한 바이너리 파일 준비"""
    # bin 디렉토리가 없으면 생성
    bin_dir = Path('bin')
    bin_dir.mkdir(exist_ok=True)
    
    # ffmpeg 모듈 import 시도
    try:
        sys.path.append(os.getcwd())
        import ffmpeg_utils
        
        # ffmpeg 다운로드
        logger.info("Checking for FFmpeg...")
        ffmpeg_path = ffmpeg_utils.get_ffmpeg_executable()
        if ffmpeg_path:
            logger.info(f"FFmpeg found: {ffmpeg_path}")
            
            # ffmpeg가 bin 디렉토리에 없으면 복사
            if not str(ffmpeg_path).startswith(str(bin_dir)):
                target_name = "ffmpeg.exe"
                target_path = bin_dir / target_name
                shutil.copy2(ffmpeg_path, target_path)
                logger.info(f"FFmpeg copied to: {target_path}")
        
    except ImportError:
        logger.warning("ffmpeg_utils module not found, skipping FFmpeg preparation")
    except Exception as e:
        logger.error(f"Error preparing FFmpeg: {e}")
    
    return bin_dir

def copy_python_dlls():
    """Python DLL 파일 복사하기"""
    try:
        # Python 설치 디렉토리
        python_dir = os.path.dirname(sys.executable)
        logger.info(f"Python directory: {python_dir}")
        
        # DLL 파일을 저장할 디렉토리
        dll_dir = Path('dll_backup')
        dll_dir.mkdir(exist_ok=True)
        
        # 주요 DLL 파일 복사
        dlls_to_copy = [
            'python311.dll',
            'python3.dll',
            'vcruntime140.dll',
            'vcruntime140_1.dll'
        ]
        
        for dll in dlls_to_copy:
            src_path = os.path.join(python_dir, dll)
            if os.path.exists(src_path):
                dst_path = dll_dir / dll
                shutil.copy2(src_path, dst_path)
                logger.info(f"Copied {dll} to {dst_path}")
        
        return dll_dir
    except Exception as e:
        logger.error(f"Error copying Python DLLs: {e}")
        return None

def build_application():
    """Build the application using PyInstaller with Windows-specific settings"""
    logger.info("Starting Windows-specific build...")
    
    # 이전 빌드 파일 정리
    clean_build()
    
    # 런타임 훅 생성
    runtime_hook = create_runtime_hook()
    
    # 필요한 바이너리 준비
    bin_dir = prepare_binaries()
    
    # Python DLL 복사
    dll_dir = copy_python_dlls()
    
    # 빌드 명령 구성
    cmd = [
        'pyinstaller',
        '--onedir',             # 단일 디렉토리로 빌드
        '--windowed',           # GUI 애플리케이션
        '--clean',              # 임시 파일 정리
        '--noconfirm',          # 기존 출력 파일 덮어쓰기 확인 없음
        '--name', 'batch_subs_gemini',
        '--runtime-hook', runtime_hook,  # 런타임 훅 추가
        '--add-data', f'icons{os.pathsep}icons',  # 아이콘 포함
    ]
    
    # bin 디렉토리가 있으면 추가
    if bin_dir.exists() and any(bin_dir.iterdir()):
        cmd.extend(['--add-data', f'{bin_dir}{os.pathsep}bin'])
    
    # 숨겨진 모듈 추가
    hidden_imports = [
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'google.generativeai',
        'google.api_core',
        'google.auth',
        'srt',
        'win32api',            # Windows 전용 모듈
        'win32con',            # Windows 전용 모듈
        'requests',
        'ffmpeg_utils',
        'subtitle_utils',
        'logger_utils',        # 새 로깅 유틸리티
        'queue',               # 로깅에 필요한 모듈
        'threading',           # 로깅에 필요한 모듈
    ]
    
    for hidden_import in hidden_imports:
        cmd.extend(['--hidden-import', hidden_import])
    
    # 바이너리 수집 설정 (--collect-binary 대신 --collect-binaries 사용)
    cmd.extend(['--collect-all', 'google.generativeai'])
    cmd.extend(['--collect-all', 'google.api_core'])
    cmd.extend(['--collect-all', 'google.auth'])
    cmd.extend(['--collect-all', 'srt'])
    cmd.extend(['--collect-binaries', 'pywin32'])  # 올바른 옵션: collect-binaries
    
    # 기타 설정
    cmd.extend(['--exclude-module', 'tkinter'])  # 불필요한 모듈 제외
    cmd.extend(['--exclude-module', 'matplotlib'])  # 불필요한 모듈 제외
    cmd.extend(['--exclude-module', 'numpy'])  # 불필요한 모듈 제외
    
    # DLL 경로 추가
    if dll_dir and dll_dir.exists():
        cmd.extend(['--paths', str(dll_dir)])
    
    # site-packages 경로 추가
    try:
        site_packages = site.getsitepackages()[0]
        cmd.extend(['--paths', site_packages])
    except Exception as e:
        logger.warning(f"Failed to get site-packages path: {e}")
    
    # 메인 스크립트 추가
    cmd.append('batch_subs_gemini.py')
    
    # 명령 출력
    logger.info(f"Build command: {' '.join(cmd)}")
    
    # 명령 실행
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        logger.info("Build successful!")
        logger.debug(f"Build output: {result.stdout}")
        
        # 추가 패치: DLL 파일을 dist 디렉토리에 복사
        if dll_dir and dll_dir.exists():
            dist_dir = Path('dist') / 'batch_subs_gemini'
            for dll_file in dll_dir.glob('*.dll'):
                shutil.copy2(dll_file, dist_dir)
                logger.info(f"Patched: Copied {dll_file} to {dist_dir}")
        
        logger.info("\nApplication location: dist/batch_subs_gemini")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Build failed: {str(e)}")
        logger.error(f"Error output: {e.stderr}")
        return False

def main():
    """Main entry point"""
    try:
        logger.info("Windows build process started")
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