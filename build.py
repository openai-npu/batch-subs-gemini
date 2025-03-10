#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import subprocess
import platform
from pathlib import Path

def clean_build():
    """Clean build directories"""
    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
    
    # Clean spec files
    for spec_file in Path('.').glob('*.spec'):
        spec_file.unlink()

def get_icon_path():
    """아이콘 경로 반환 (플랫폼에 맞는 형식으로)"""
    # 아이콘 기본 경로
    icon_dir = os.path.join(os.getcwd(), 'icons')
    
    # 플랫폼별 선호하는 아이콘 파일
    if platform.system() == 'Darwin':  # macOS
        # macOS는 .icns 파일 선호
        icns_path = os.path.join(icon_dir, 'icon.icns')
        if os.path.exists(icns_path):
            return icns_path
        
        # .icns가 없으면 .png 파일 선호
        png_path = os.path.join(icon_dir, 'icon.png')
        if os.path.exists(png_path):
            return png_path
    elif platform.system() == 'Windows':
        # Windows는 .ico 파일 선호
        ico_path = os.path.join(icon_dir, 'icon.ico')
        if os.path.exists(ico_path):
            return ico_path
        
        # .ico가 없으면 .png 파일 선호
        png_path = os.path.join(icon_dir, 'icon.png')
        if os.path.exists(png_path):
            return png_path
    else:  # Linux 또는 기타
        # .png 파일 선호
        png_path = os.path.join(icon_dir, 'icon.png')
        if os.path.exists(png_path):
            return png_path
    
    # SVG는 마지막 옵션으로 사용 (PyInstaller가 모든 플랫폼에서 SVG를 지원하진 않음)
    svg_path = os.path.join(icon_dir, 'icon.svg')
    if os.path.exists(svg_path):
        print("경고: SVG 아이콘은 일부 플랫폼에서 지원되지 않을 수 있습니다.")
        return svg_path
    
    # 아이콘 파일이 없으면 None 반환
    print("경고: 아이콘 파일을 찾을 수 없습니다. 아이콘 없이 빌드합니다.")
    return None

def build_application():
    """Build the application using PyInstaller"""
    print("빌드 시작...")
    
    # 이전 빌드 파일 정리
    clean_build()
    
    # 빌드 명령 구성
    cmd = [
        'pyinstaller',
        '--onedir',  # 단일 디렉토리로 빌드 (--onefile보다 시작 속도 빠름)
        '--windowed',  # GUI 애플리케이션
        '--clean',  # 임시 파일 정리
        '--name', 'batch_subs_gemini',
        '--add-data', 'icons:icons',
    ]
    
    # 필요한 모듈 추가
    hidden_imports = [
        'gemini_srt_translator',
        'google.generativeai',
        'google.api_core',
        'google.auth',
        'srt',
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
    ]
    
    for hidden_import in hidden_imports:
        cmd.extend(['--hidden-import', hidden_import])
    
    # 경로 추가
    import site
    site_packages = site.getsitepackages()[0]
    cmd.extend(['--paths', site_packages])
    
    # 패키지 수집
    packages_to_collect = [
        'gemini_srt_translator',
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
    print(f"실행 명령: {' '.join(cmd)}")
    
    # 명령 실행
    try:
        result = subprocess.run(cmd, check=True)
        print("빌드 성공!")
        
        # 추가 정보 출력
        if platform.system() == 'Darwin':
            print("\n애플리케이션 위치: dist/batch_subs_gemini.app")
        else:
            print("\n애플리케이션 위치: dist/batch_subs_gemini")
            
        return True
    except subprocess.CalledProcessError as e:
        print(f"빌드 실패: {str(e)}")
        return False

def main():
    """Main entry point"""
    if build_application():
        print("빌드 과정이 성공적으로 완료되었습니다.")
    else:
        print("빌드 과정 중 오류가 발생했습니다.")
        sys.exit(1)

if __name__ == '__main__':
    main() 