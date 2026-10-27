# Supabase 연결 준비

1. Dashboard → SQL Editor → New query에서 `001_chart_analysis.sql` 전체를 붙여넣고 Run.
2. 결과에 `chart_analysis`, `hts_editors` 두 행이 나오고 `rowsecurity`가 모두 true인지 확인.
3. Authentication → Users에서 HTS 업로드 전용 사용자를 생성. Supabase 대시보드 로그인 계정과 별개의 앱 사용자다.
4. 해당 사용자의 UUID를 `002_authorize_editor.sql`의 자리표시자에 넣고 별도 실행. UUID는 비밀번호가 아니지만 채팅으로 전달할 필요는 없다.
5. PC `my_hts/config/supabase_config.json`에 프로젝트 URL·Publishable Key·업로드 사용자 이메일·새 비밀번호를 입력한다. 이 파일은 Git에서 제외한다.
6. `my_hts`에서 `..\stock_env\Scripts\python.exe cloud_sync_cli.py check`로 접속을 확인하고, HTS를 종료한 상태에서 같은 명령의 `check`를 `push`로 바꾸어 초기 업로드한다. 보류 파일이 남으면 같은 명령으로 재시도할 수 있다.
7. Vercel 프로젝트 Settings → Environment Variables에 아래 세 값을 등록하고 재배포한다. Production에 적용해야 실제 봇에 반영된다. Preview에서도 테스트한다면 해당 환경에도 설정한다.

| 환경변수 | 값 |
|---|---|
| `HTS_DATA_SOURCE` | `supabase` |
| `SUPABASE_URL` | PC 설정의 `url`과 같은 프로젝트 URL |
| `SUPABASE_SECRET_KEY` | Supabase Settings → API Keys의 서버용 Secret Key |

Secret Key는 Vercel에 직접 등록하며 PC HTS 설정·SQL 파일·Git·채팅에 넣지 않는다. 새 Secret Key는 `apikey` 헤더에만 사용하고, 사용자 로그인 토큰과 혼동하지 않는다. 구형 `service_role` JWT를 사용하는 경우 `SUPABASE_SERVICE_ROLE_KEY`도 지원한다. Publishable Key만으로는 서버 읽기가 허용되지 않는다.

HTS를 재실행하면 저장·수정·전체 삭제를 자동으로 업로드한다. 먼저 로컬 저장을 완료하고, 실패한 변경은 `data/supabase_outbox.json`에 보관해 자동 재시도한다. 업로드 도중 새 변경이 생겨도 새 변경을 지우지 않는다. 재시작 시 로컬 파일과 마지막 업로드 기록을 비교해 미반영 수정을 다시 등록한다. 상태바 오른쪽에서 대기·완료·실패를 확인한다. 자동 작도 후보는 원래 수동선 저장에 포함되지 않으며 DB에도 업로드되지 않는다.

한 PC의 업로더 하나를 전제로 하며 같은 폴더의 여러 HTS/CLI 프로세스가 동시에 업로드하지 못하도록 잠근다. 아직 다른 PC·모바일 편집기와의 동시 편집 충돌 병합은 구현하지 않았다. DB는 마지막으로 도착한 저장이 우선하므로, 다중 편집기를 연결할 때는 `revision` 기반 조건부 저장을 추가해야 한다. 로컬 큐·마지막 업로드 기록 파일은 수동으로 지우지 않는다.

서버는 매 요청마다 DB의 최신 선을 읽는다. DB 모드에서 빈 배열·빈 테이블은 그대로 반영하고, DB 오류 시 오래된 Git 추세선으로 조용히 되돌아가지 않는다. 종목명·별칭 카탈로그는 기존 파일을 사용하며 추세선의 기준 저장소는 DB다. 별도의 이미지 요청 시점에 선이 다시 수정되면 이미지와 앞선 문장이 다른 버전을 볼 수 있으며, 아직 버전별 분석 이력 저장은 구현하지 않았다. 전체 종목 추천 시간과 5초 제한은 별도 문제이므로 기존 콜백 구성을 유지한다.

환경변수가 없으면 기존 스냅샷 모드가 유지된다. `HTS_DATA_SOURCE=snapshot`으로 명시하면 수동 스냅샷 방식으로 돌아갈 수 있으나, 이 모드에서는 DB 업데이트를 반영하지 않는다.

`chart_analysis`는 종목코드 하나당 수동선 JSON 배열을 저장한다. 선 전체 삭제도 `drawings=[]`로 저장한다. `revision`과 `updated_at`은 서버에서 갱신하지만 버전 필드 자체가 동시 수정 충돌을 막지는 않으며, 연동 코드에서 별도 처리가 필요하다. 미등록 로그인 사용자와 익명 사용자는 접근할 수 없다. 편집자 목록은 앱에서 스스로 등록할 수 없다.

권한 근거: [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [앱 사용자 관리](https://supabase.com/docs/guides/auth/users).
