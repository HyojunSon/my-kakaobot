# HTS 카카오 차트 봇

## 오픈빌더 종목 엔티티 일괄 업로드

`data/stock_name_all.csv`를 `stock_name` 엔티티에 업로드합니다. 공식 샘플과 같이 헤더가 없으며 첫 열은 종목명, 이후 열은 각각 동의어입니다. 종목코드와 일부 별칭을 포함한 UTF-8 파일입니다. Excel에서 열어 재저장하면 코드 앞의 0이 사라질 수 있으므로 생성한 파일을 그대로 업로드하세요. KOSPI/KOSDAQ/KONEX 주식(우선주·스팩 포함)과 국내 상장 ETF를 포함하며 ETN은 제외합니다. ETF는 코덱스/타이거/에이스/라이즈/솔/플러스 등 브랜드 한글 별칭을 지원합니다.

최신 목록으로 재생성: 워크스페이스 루트에서 `stock_env\Scripts\python.exe my-kakaobot\export_stock_entity.py --refresh`.

ETF 목록만 갱신: `stock_env\Scripts\python.exe my-kakaobot\export_stock_entity.py --refresh-etf`. `data/etf_listing.csv`와 서버용 카탈로그도 배포에 포함합니다.

`data/stock_aliases.json`에서 코드별 별칭을 관리합니다. `export_stock_entity.py` 실행 시 CSV와 서버용 `data/stock_catalog.json`을 함께 생성합니다. 서버는 전체 카탈로그와 HTS 목록을 합쳐 코드·정식 이름·별칭으로 조회하며, 선이 없는 종목은 캔들과 EMA만 표시합니다. CSV에는 별칭 하나당 한 열을 사용하고, 공백·대소문자 정규화 후 다른 종목과 충돌하는 별칭은 제외합니다. 삼전/하닉/엘전 등 약어를 추가했으며 CSV 재업로드와 서버 재배포가 모두 필요합니다. HTS 선 갱신은 종목 카탈로그와 독립적입니다.

`/차트 이뮨온시아`, `/차트 424870`, `/차트 삼전` 명령에 최근 6개월 일봉과 HTS 추세선/수평선 이미지를 응답합니다. 정식 종목명·코드·등록된 별칭을 사용할 수 있습니다.

## 실행

워크스페이스 루트에서:

```powershell
stock_env\Scripts\python.exe my-kakaobot\sync_hts.py
stock_env\Scripts\python.exe -m pip install -r my-kakaobot\requirements.txt
cd my-kakaobot
..\stock_env\Scripts\python.exe -m uvicorn api.index:app --port 8000
```

Vercel 프로젝트 루트는 `my-kakaobot`입니다. `PUBLIC_BASE_URL`을 공개 HTTPS 배포 주소로 설정하고 카카오 스킬 URL을 `https://배포주소/api/chat`으로 지정합니다. 이미지 URL은 로그인/배포 보호 없이 접근 가능해야 합니다. 기존 `vercel.json` 라우팅을 사용합니다.

## 데이터와 이미지 처리

`sync_hts.py`는 `my_hts/data`에서 종목명과 드로잉만 읽고 `data/hts_snapshot.json`에 내보냅니다. 메모와 텔레그램 설정은 포함하지 않습니다. JSON 파일을 배포에 포함하세요. HTS 선을 수정한 후 동기화와 재배포가 필요합니다. 자동 원격 동기화는 아직 없습니다.

웹훅은 요청별 고유 이미지 URL을 즉시 반환합니다. 카카오가 그 URL을 조회할 때 서버가 새 시세를 받아 PNG를 생성합니다. 다른 인스턴스에서도 동작하도록 이미지 메모리 캐시나 임시 파일에 의존하지 않습니다. 시세와 이미지는 요청마다 새로 생성합니다.

네이버 일봉 데이터의 최신 응답을 사용하며 거래소 실시간 피드가 아니므로 무지연 가격을 보장하지 않습니다. 이미지에 데이터 기준일과 조회 시각을 표시합니다. 과거 선의 거래일 좌표를 계산하기 위해 최대 10,000개 일봉을 받고, 화면에는 마지막 캔들 기준 6개월만 표시합니다. 데이터에 없는 선의 끝점은 추정하지 않고 제외하며 하단에 제외 수를 표시합니다. 이동평균은 HTS와 동일한 EMA 방식입니다. 제공처의 수정주가/과거 데이터 정책이 바뀌면 저장된 선과 차이가 생길 수 있습니다.

웹훅 응답 시간과 이미지 표시 시간은 다릅니다. 이미지 생성 실패 시 카카오에서 이미지가 표시되지 않을 수 있으며 이미지 URL과 서버 로그를 확인해야 합니다. 실제 Vercel/카카오 환경의 콜드 스타트와 다운로드 제한은 배포 후 검증해야 합니다. 이미지 표시까지 5초를 보장하지 않습니다.

한글 표시는 함께 포함된 나눔고딕 `assets/chart-font.ttf`를 파일 경로로 직접 지정합니다. `assets/OFL.txt` 라이선스와 함께 두 파일을 배포에 포함하세요. 출처: Google Fonts 저장소의 `ofl/nanumgothic`. Matplotlib 캐시는 Vercel에서 쓰기 가능한 임시 디렉터리를 사용합니다.

## 테스트

봇 프로젝트 폴더에서 `python -m unittest discover -s tests -v`를 실행합니다. 네트워크와 실제 메시지 전송 없이 시세 파싱, 거래일 계산, PNG 생성, FastAPI 응답을 확인합니다. FastAPI 미설치 시 HTTP 테스트는 건너뜁니다.
