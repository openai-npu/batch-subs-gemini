# Batch Subs Gemini

Gemini API를 사용한 자막 일괄 번역 도구입니다.

## 기능

- 동영상 파일에서 자막 추출 (MKV 파일)
- Gemini API를 사용한 자막 번역
- 여러 파일을 일괄 처리
- 사용자 친화적인 인터페이스

## 설치

### 릴리스 다운로드

[릴리스 페이지](../../releases)에서 운영체제에 맞는 버전을 다운로드하세요.

### 소스에서 빌드

1. 저장소 클론:
   ```
   git clone https://github.com/your-username/batch-subs-gemini.git
   cd batch-subs-gemini
   ```

2. 의존성 설치:
   ```
   pip install -r requirements.txt
   ```

3. 실행:
   ```
   python batch_subs_gemini.py
   ```

## 개발자 정보

### 아이콘 변환

`convert_icons.py` 스크립트를 사용하여 SVG 아이콘을 다양한 플랫폼용 형식으로 변환할 수 있습니다.

필요한 의존성:
- MacOS: `brew install librsvg imagemagick`
- Linux: `sudo apt-get install librsvg2-bin imagemagick`
- Windows: [ImageMagick 다운로드](https://imagemagick.org/script/download.php)

실행:
```
python convert_icons.py
```

### 빌드

모든 플랫폼용 실행 파일을 빌드하려면:

```
python build.py
```

## 라이선스

MIT License 