#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
import platform
import logging
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
        logging.FileHandler('icon_convert.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

def check_dependencies():
    """필요한 의존성이 설치되어 있는지 확인"""
    dependencies = {
        "Darwin": ["librsvg", "imagemagick"],
        "Windows": ["imagemagick"],
        "Linux": ["librsvg", "imagemagick"]
    }
    
    os_name = platform.system()
    if os_name not in dependencies:
        logger.error(f"Unsupported operating system: {os_name}")
        return False
    
    missing = []
    
    if os_name == "Darwin":
        # Homebrew로 설치된 패키지 확인
        for dep in dependencies[os_name]:
            try:
                subprocess.run(["brew", "list", dep], 
                               check=True, 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE)
                logger.info(f"{dep} found")
            except subprocess.CalledProcessError:
                missing.append(dep)
    elif os_name == "Linux":
        # Debian/Ubuntu 계열 확인
        for dep in dependencies[os_name]:
            if dep == "librsvg":
                check_cmd = ["dpkg", "-s", "librsvg2-bin"]
            else:
                check_cmd = ["dpkg", "-s", dep]
            
            try:
                subprocess.run(check_cmd, 
                               check=True, 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE)
                logger.info(f"{dep} found")
            except subprocess.CalledProcessError:
                missing.append(dep)
    elif os_name == "Windows":
        # Windows에서는 ImageMagick만 확인
        try:
            subprocess.run(["magick", "--version"], 
                           check=True, 
                           stdout=subprocess.PIPE, 
                           stderr=subprocess.PIPE)
            logger.info("ImageMagick found")
        except (subprocess.CalledProcessError, FileNotFoundError):
            missing.append("imagemagick")
    
    if missing:
        logger.warning(f"The following dependencies need to be installed: {', '.join(missing)}")
        install_message = ""
        if os_name == "Darwin":
            install_message = f"Install with: brew install {' '.join(missing)}"
        elif os_name == "Linux":
            install_message = f"Install with: sudo apt-get install {' '.join(missing)}"
        elif os_name == "Windows":
            install_message = "Download ImageMagick from https://imagemagick.org/script/download.php"
        
        logger.info(install_message)
        return False
    
    return True

def create_macos_icns(svg_path, output_path):
    """SVG를 macOS ICNS 파일로 변환"""
    logger.info(f"Creating macOS ICNS icon...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        iconset_path = Path(tmpdir) / "icon.iconset"
        os.makedirs(iconset_path, exist_ok=True)
        
        # 다양한 크기로 PNG 생성
        sizes = [16, 32, 64, 128, 256, 512, 1024]
        for size in sizes:
            for scale in [1, 2]:  # 1x and 2x (Retina)
                scaled_size = size * scale
                output_name = f"icon_{size}x{size}{'' if scale == 1 else '@2x'}.png"
                output_file = iconset_path / output_name
                
                cmd = [
                    "rsvg-convert",
                    "-w", str(scaled_size),
                    "-h", str(scaled_size),
                    "-o", str(output_file),
                    str(svg_path)
                ]
                
                try:
                    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    logger.info(f"  {output_name} created")
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to create PNG ({output_name}): {e.stderr.decode('utf-8')}")
                    return False
        
        # iconutil을 사용하여 ICNS 파일 생성
        try:
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset_path), "-o", str(output_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logger.info(f"ICNS file created: {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create ICNS: {e.stderr.decode('utf-8')}")
            return False

def create_windows_ico(svg_path, output_path):
    """SVG를 Windows ICO 파일로 변환"""
    logger.info(f"Creating Windows ICO icon...")
    
    # ImageMagick을 사용하여 변환
    try:
        # 다양한 크기 (16, 32, 48, 64, 128, 256)를 포함하는 ICO 파일 생성
        subprocess.run(
            ["magick", "convert", "-background", "none", str(svg_path),
             "-define", "icon:auto-resize=16,32,48,64,128,256", str(output_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        logger.info(f"ICO file created: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create ICO: {e.stderr.decode('utf-8') if hasattr(e.stderr, 'decode') else e.stderr}")
        return False

def create_linux_png(svg_path, output_path):
    """SVG를 고해상도 PNG 파일로 변환 (Linux용)"""
    logger.info(f"Creating Linux PNG icon...")
    
    try:
        # 512x512 PNG 생성
        subprocess.run(
            ["rsvg-convert", "-w", "512", "-h", "512", "-o", str(output_path), str(svg_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        logger.info(f"PNG file created: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create PNG: {e.stderr.decode('utf-8')}")
        return False

def main():
    """메인 함수"""
    # SVG 파일 확인
    icon_dir = Path("icons")
    svg_path = icon_dir / "icon.svg"
    
    if not svg_path.exists():
        logger.error(f"SVG icon file not found: {svg_path}")
        sys.exit(1)
    
    # 의존성 확인
    if not check_dependencies():
        logger.warning("Required dependencies are not installed. Do you want to continue? (y/n)")
        choice = input().lower()
        if choice != 'y':
            logger.info("Conversion cancelled.")
            sys.exit(0)
    
    # 출력 디렉토리 확인
    os.makedirs(icon_dir, exist_ok=True)
    
    # 아이콘 생성
    os_name = platform.system()
    
    # 모든 플랫폼용 아이콘 생성
    results = []
    
    if os_name == "Darwin" or os_name == "Linux":
        # macOS ICNS
        icns_path = icon_dir / "icon.icns"
        if create_macos_icns(svg_path, icns_path):
            results.append(f"macOS icon (ICNS): {icns_path}")
            
        # Linux PNG
        png_path = icon_dir / "icon.png"
        if create_linux_png(svg_path, png_path):
            results.append(f"Linux/other icon (PNG): {png_path}")
    
    if os_name == "Darwin" or os_name == "Windows":
        # Windows ICO
        ico_path = icon_dir / "icon.ico"
        if create_windows_ico(svg_path, ico_path):
            results.append(f"Windows icon (ICO): {ico_path}")
    
    # 결과 출력
    if results:
        logger.info("\nGenerated icons:")
        for result in results:
            logger.info(f"  - {result}")
        logger.info("\nIcon conversion completed!")
    else:
        logger.error("Icon conversion failed.")
        sys.exit(1)

if __name__ == "__main__":
    main() 