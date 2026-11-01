# 한국판 Winning Eleven 10 Liveware Evolution 지원

대상은 PS2 한국 정식발매판 **SLKA-25153**입니다. 제공된 ISO를 읽기 전용으로 분석해 juce/fiveserver에 **실험적 호환 서비스**를 추가했습니다.

2026-10-31 기준으로 사용자가 별도 PNACH 적용 후 게임 로그인 화면 도달과 기본 ID 로그인 성공을 확인했습니다. 실제 서버 로그에서도 인증·프로필·메뉴/메인 소켓 전환과 로비 선택 요청을 확인했습니다. 로비 진입 뒤 `308c`에서 멈추던 공통 상태 응답을 복원하고, 방 참가·퇴장·설정 저장의 공통 버그 및 한국판 고정 길이 응답을 보완했습니다.

자동 검증은 실제 서버 코드·모델·암호화·wire 프레임으로 합성 두 사용자의 로비, 방 생성/참가, 준비, 경기 시작, 점수/시계, 퇴장과 방 삭제까지 실행했습니다. **2026-11-01 사용자가 서로 다른 PC 두 대에서 실제 대전이 동작함을 확인했습니다.** 이는 사용자 보고에 따른 실기 확인이며 에이전트가 직접 경기를 관찰한 결과는 아닙니다. 최종 경기 기록의 DB 저장과 Docker 엔진 실행은 아직 검증하지 않았고, 모든 NAT 환경의 호환성을 뜻하지도 않습니다. 원본 ISO는 수정하지 않았습니다. 공통 코드와 PS2 전용 차이의 구분은 [공통 흐름 감사](WE10LE-COMMON-AUDIT-KO.md)에 정리했습니다.

## 추가한 동작

- 게이트웨이: gate.we10le.konami-asia.com, TCP **10881**. 기존 PES6의 XOR/MD5 전송과 Blowfish 키를 재사용합니다.
- 인증: 한국판 **0x3F01 → 0x3F02**. PC판 0x3003과 구분합니다.
- 기본 `AuthMode: username`은 **등록된 ID만 확인하고 비밀번호 해시는 검사하지 않습니다.** 기존 계정·프로필·중복 로그인 검사를 유지합니다. `AuthMode: password`는 기존 ID와 비밀번호 검증을 사용합니다. 컨테이너에서는 `WE10LE_AUTH_MODE=username|password`로 선택합니다. Login·Main·Network Menu가 같은 정책을 사용하며, PC판 인증은 변경하지 않았습니다.
- 0x3001 → 0x3002에서 16바이트 zero challenge를 제공하고, 등록 시 **MD5(username + 16*NUL + password)**를 계산합니다. PC판 시리얼 기반 해시와 다릅니다.
- 프로필 목록은 48바이트 이름/66바이트 레코드, 선택 응답 0x3042는 한국판의 396바이트 구조입니다.
- 0x3052는 75바이트, 0x3062는 4바이트 응답입니다. 0x3052의 부가 통계는 현재 0입니다.
- 로그인·메뉴·게임 서비스 모두 한국판 인증을 사용합니다. 확인된 핵심 로비·방·게임 명령은 PES6 구현을 재사용합니다.
- 공통 `PacketDispatcher`와 PES6의 로비·방·경기 상태 모델을 유지합니다. LOGIN·메뉴·게임 서비스의 기본 상태 응답도 upstream처럼 요청 ID+1 / zero4로 처리하며, `308c → 308d`를 별도로 막지 않습니다.
- PS2 전용 `4101`은 공통 41바이트 prefix를 유지하고 미지원 부가 필드 55바이트를 0으로 채워 총 96바이트를 보냅니다. `4402` 채팅은 발신자 58바이트와 메시지 영역 128바이트, 총 186바이트로 맞춥니다. PC 서비스의 해당 출력은 변경하지 않습니다.
- 공통 방 참가 오류는 오류 응답 후 종료합니다. 참가 성공 `4321`은 상태4+시간1이며 기본 시간 index는 0(5분)입니다. 퇴장한 사용자에게는 방 ID 0을 알립니다. Python 3의 방 이름 조회와 설정 조각 분류도 복원했습니다.
- `StoreSettings: false` 기본값은 유지합니다. 설정 저장을 켠 경로의 두 조각 압축·저장·복원은 자동 회귀에서 확인했습니다.
- 한국판은 프로필 처리 후 `0003` 요청에 `0004` 성공 상태 4바이트를 보낸 뒤 TCP 연결을 정상 종료합니다. PC판의 무응답 처리와 구분합니다. heartbeat는 송신 카운터에 맞춰 패킷 체크섬을 다시 계산합니다.
- PS2는 PC용 로스터 해시를 보내지 않아 검사를 끕니다. 한국판 전용 DB/서비스로 운영합니다.
- 원래 PC 서비스의 기본 폼과 실행 경로는 유지합니다.

## 서버 준비

저장소 루트에서 실행하세요. **MySQL/MariaDB 서버가 별도로 필요**합니다. 실제 DB 연결·저장은 이 작업 환경에서 시험하지 않았습니다.

1. sql/schema6.sql로 한국판 전용 DB를 만듭니다. 비밀번호를 정한 뒤 설정에도 같은 값을 넣으세요.

   ~~~sql
   CREATE DATABASE we10le CHARACTER SET utf8;
   CREATE USER 'we10le'@'127.0.0.1' IDENTIFIED BY 'your-db-password';
   GRANT SELECT, INSERT, UPDATE ON we10le.* TO 'we10le'@'127.0.0.1';
   USE we10le;
   SOURCE ./sql/schema6.sql;
   ~~~

2. **etc/conf/we10le.yaml**을 편집합니다.

   - ServerIP: PS2/PCSX2에서 접근 가능한 서버 IPv4. 같은 PC에서 돌린다면 해당 PC의 LAN IPv4를 사용하세요.
   - ListenOn: 기본 빈 문자열은 모든 로컬 인터페이스에 바인딩합니다.
   - DB: 위 DB 이름·계정·비밀번호.
   - 기본 TCP 포트: 게이트웨이 10881, 게임 20210, 메뉴 20211, 로그인 20212, 웹 등록 8195.

   **ServerIP의 127.0.0.1은 편집 전 기본값입니다. 게스트에 광고할 주소로 그대로 사용하지 마세요.** Sixserver도 TCP 10881을 사용하므로 같은 IP에서는 둘 중 하나만 실행하세요.

3. Python 3.12 환경에 한국판 서비스용 의존성을 설치합니다. 원래 PC용 pip.requirements는 변경하지 않았습니다.

   Linux:

   ~~~sh
   python3 -m venv .local
   .local/bin/python -m pip install -r pip.requirements-we10le
   ./service.sh we10le run
   ~~~

   mysqlclient 빌드가 필요한 Linux에서는 저장소 README의 MySQL 개발 라이브러리·컴파일러 준비도 필요합니다.

   Windows PowerShell:

   ~~~powershell
   py -3.12 -m venv .local
   .\.local\Scripts\python.exe -m pip install -r pip.requirements-we10le
   .\run-we10le.ps1
   ~~~

   가상환경 위치가 다르면 run-we10le.ps1의 -Venv 인자로 지정합니다.

4. **http://서버IPv4:8195/**에서 계정을 등록한 뒤 게임에 같은 ID를 입력합니다. 기본 `username` 모드에서는 기존 비밀번호와 달라도 됩니다. 게임 화면은 빈 비밀번호만 막으므로 임의의 패드 문자 한 글자 후 Start로 완료하면 충분합니다. `password` 모드에서는 등록 비밀번호와 같아야 합니다. Dockerfile 자체는 호스트의 웹 포트 공개 범위를 정하지 않습니다. 등록 웹을 로컬로 제한하려면 `-p 127.0.0.1:8195:8195`처럼 명시적으로 publish하고 원격 접근에는 SSH 터널을 사용하세요. ID는 영문·숫자 3~31자, 게임이 입력할 수 있는 비밀번호는 **대문자 A~L 1~31자**입니다. 비밀번호는 별도 키보드 창 없이 패드로 입력합니다. ↑A·↓B·←C·→D·L1E·L2F·R1G·R2H·○I·×J·△K·□L이며 Start가 완료입니다. PC판 시리얼은 넣지 않습니다. 최초 프로필/채팅은 영문으로 확인하세요.

한국판 전용 Dockerfile은 docker/we10le/Dockerfile입니다. 공식 Python Linux 이미지와 컨테이너 전용 requirements를 사용하며, DB 드라이버는 PyMySQL의 MySQLdb 호환 계층을 사용합니다. Docker entrypoint는 WE10LE_SERVER_IP, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD 환경변수로 실행 설정을 만들고 DB와 스키마가 준비될 때까지 기다립니다. 기존 docker/Dockerfile은 원래 PC 서비스용으로 유지합니다.

이 저장소 변경에는 Dockerfile과 entrypoint 소스만 포함하며, 사전 빌드 이미지 tar·Compose 키트·MariaDB 이미지·DNAS 서버·클라이언트 패치는 포함하지 않습니다. DB 배포와 DNAS 단계 완료는 별도로 준비해야 합니다. 레이어/아카이브 무결성 검증, 합성 서버 테스트, 실제 Docker 엔진 실행과 사용자 PCSX2 실행 결과는 서로 구분합니다. 실제 Docker 엔진 실행은 아직 검증하지 않았습니다.

## 필요한 DNS 설정 — PCSX2 2.8.2

게임 게이트웨이를 본인 서버로 보내는 현재 구성은 Sockets와 내부 DNS입니다. 아래 매핑은 원본 ISO의 호스트 문자열을 바꾸지 않고 접속 대상을 지정합니다.

1. **설정 → 네트워크 & HDD**에서 이더넷 활성화, **이더넷 장치 유형 → 소켓**.
2. **DHCP 인터셉트** 탭의 **DNS1·DNS2 주소** 목록에서 **내부** 선택.
3. **내부 DNS → 추가**에서 호스트 이름을 **gate.we10le.konami-asia.com**, 주소를 위 ServerIP와 같은 접근 가능한 서버 IPv4로 지정하고 **활성화** 체크.
4. 서버 실행 후 게임의 네트워크 접속을 시도합니다.

새 DNS 행은 기본 비활성이라 체크가 필요합니다. 호스트 목록은 내부 DNS **192.0.2.1**을 사용하는 질의에 적용됩니다. 게임의 메모리카드 설정이 수동 DNS라면 자동 DNS 또는 192.0.2.1을 사용해야 합니다. Windows 전체 DNS나 시스템 hosts를 바꿀 필요는 없습니다. 실제 PS2는 별도 로컬 DNS 서버에서 위 호스트를 매핑해야 합니다.

[PCSX2 2.8.2 DNS 라우팅](https://github.com/PCSX2/pcsx2/blob/v2.8.2/pcsx2/DEV9/net.cpp), [DNS 호스트 처리](https://github.com/PCSX2/pcsx2/blob/v2.8.2/pcsx2/DEV9/InternalServers/DNS_Server.cpp), [설정 UI](https://github.com/PCSX2/pcsx2/blob/v2.8.2/pcsx2-qt/Settings/DEV9SettingsWidget.ui)

## 외부 클라이언트 준비와 남은 확인

이 서버는 DNAS 인증을 구현하지 않으므로 클라이언트가 해당 단계를 완료할 수 있는 환경이 먼저 필요합니다. 조사에 사용한 디스크는 SLKA-25153 / CRC **3B36E890**, 에뮬레이터는 PCSX2 2.8.2입니다. 사용자가 외부 클라이언트 패치를 적용한 환경에서 DNAS 이후 로그인·프로필·로비·방 단계까지 진행한 것을 확인했습니다. 이 관측은 서버 자체에 DNAS 기능이 있다는 뜻이 아닙니다.

PNACH의 제작·배포·설치나 DNAS 응답 서버는 이 저장소 변경의 범위 밖입니다. 게임 ISO·BIOS·실행 파일·메모리카드·로스터 데이터도 포함하지 않습니다. 영어 유지보수/설치 안내는 [WE10LE.md](WE10LE.md)를 참고하세요.

실제 PCSX2에서 추가로 확인할 부분:

- 반복 경기·재접속과 아직 관찰하지 않은 클라이언트 경로. 로그인·로비·방 및 서로 다른 PC 두 대의 실제 대전은 사용자 확인이 있습니다.
- 실제 경기 종료와 기록의 DB 저장. 자동 검증의 경기 모델 생성·점수/시계·퇴장과 구분합니다.
- 한국판 전체 STUN/NAT 판정. 외부 STUN의 과거 기본 응답 확인은 전체 NAT 분류나 대전 성공을 의미하지 않습니다. 이 서버에는 UDP STUN 서비스를 추가하지 않았습니다.
- 한글 프로필·채팅 인코딩, 순위/그룹/대회 등 부가 기능과 아직 관찰하지 않은 Menu 전용 경로. 공통 상태 ACK를 유지하는 것만으로 모든 부가 기능이 구현됐다고 주장하지 않습니다.
- `3042` 마지막 4바이트와 `4101`의 미지원 부가 필드 의미. 현재 0을 보냅니다.

접속 진단에는 `TraceProtocol: true` 또는 컨테이너의 `WE10LE_PROTOCOL_TRACE=1`을 사용합니다. 서비스·패킷 ID·길이·인증 결과를 기록합니다. PCSX2의 **도구 → 로그 창 활성화 / 파일 로그 기록 활성화**와 서버 로그를 함께 확인합니다.

## STUN 추가 확인 — 2026-10-28

**2026-10-28 조사에서 `we9stun.winning-eleven.net`이 한국판에서 쓰이는 이름임을 확인하고, `46.101.172.11`로 시험했습니다.** 아래 주소와 응답은 당시 관측 기록이며 현재 가용성이나 전체 NAT 호환성을 보장하지 않습니다. 배포 시 운영할 legacy STUN 경로는 별도로 확인해야 합니다.

| 목적 | 호스트 | 설정 또는 당시 시험 주소 | 전송 |
| --- | --- | --- | --- |
| 한국판 게임 게이트웨이 | gate.we10le.konami-asia.com | 직접 실행하는 한국판 서버 IPv4 | TCP 10881 |
| 외부 STUN | we9stun.winning-eleven.net | 2026-10-28 시험: 46.101.172.11 | UDP 3478 |

- 원본 connect.ovl의 0xAE7510–0xAE7578이 호스트를 해석하고 netlib 0x8507A0에 포트 3478을 전달합니다.
- netlib 0x850F10/0x850B50은 구형 RFC3489의 16바이트 transaction ID, Binding Request/Response, MAPPED/SOURCE/CHANGED-ADDRESS를 사용합니다. CHANGE-REQUEST flags 6/2도 사용합니다.
- 이 PC에서 46.101.172.11:3478에 구형 Binding Request를 실제 전송해, transaction ID가 일치하는 0x0101 응답과 속성 0x0001/0x0004/0x0005를 받았습니다. 기본 응답 약 266ms.
- 포트 변경(flags2), IP+포트 변경(flags6) 요청은 이 경로에서 응답을 받지 못했습니다. 응답의 CHANGED-ADDRESS도 원래 46.101.172.11:3478과 같았습니다. 따라서 전체 NAT 분류와 한국판 대전 호환을 확인했다고 볼 수 없습니다. 타임아웃만으로 서버 장애 또는 NAT 필터 중 어느 쪽인지 단정하지 않습니다.
- 당시 참고한 외부 운영자 안내에도 해당 STUN 매핑이 있었습니다. [PES6.es hosts 안내](https://www.pes6.es/foro/Thread-TUTORIAL-Archivo-hosts-para-jugar-online-a-PES6-PES-2013-y-todos-los-PES)
- 당시 공개 DNS 조회에서는 원본 STUN 도메인이 SERVFAIL을 반환했습니다. 현재 DNS와 UDP 응답 상태는 이 기록만으로 판단할 수 없습니다.
- 게임 서버의 TCP 0x4345/0x4347 상대방 주소 전달과 외부 UDP STUN은 별개입니다. UDP STUN을 구현하지 않은 새 한국판 서버 IP로 STUN 주소까지 바꾸지 마세요.
- Google 등의 modern STUN으로 임의 대체하면 XOR-MAPPED만 제공하거나 legacy NAT 검사 기능이 빠질 수 있습니다. 대체 서버는 한국판의 구형 메시지와 주소/포트 변경 검사를 검증해야 합니다.

이번 확인에서도 ISO, Windows hosts, PCSX2 설정은 변경하지 않았습니다.

## 정적 분석 근거

원본 ISO 프로그램·게임 데이터는 이 저장소/배포물에 포함하지 않았습니다. 주소는 제공된 디스크의 분석 기준입니다.

| 항목 | 확인 위치 |
| --- | --- |
| 디스크 | Volume WE10LEK, SYSTEM.CNF: SLKA_251.53, VER=1.01, NTSC |
| netlib.ovl | OVER.AFS entry20, AFS offset 0x9A0800, load 0x7FE000 |
| 게이트웨이 문자열 | netlib file 0x869E0 / virtual 0x8849E0 |
| 연결 흐름 | lobby 0x93DDC8 → hostname getter 0x81D700; 0x93DDD0 → port getter 0x81D6F0 (10881); 0x93DDE4 → connect 0x862570; 성공 후 0x93DE50 → 0x2005 요청 |
| 서버 목록 파서 | netlib 0x864BE0, 61바이트, LOGIN type2 / MAIN type3 확인 |
| XOR 키 | main ELF file 0x2E3B90, A6 77 95 7C |
| Blowfish 키 | netlib file 0x85E10, 기존 서버의 전체 56바이트 키와 일치 |
| challenge 생성기/파서 | netlib 0x864480 / 0x8643F0, 0x3001 / 0x3002 |
| 인증 생성기/결과 파서 | netlib 0x8641B0 (ID literal 0x8642C8: 0x3F01) / 0x864130 (0x3F02) |
| 프로필 목록/선택 파서 | netlib 0x863F70 / 0x863D40 |
| 0x3052 / 0x3062 파서 | netlib 0x863A40 / 0x8638A0 |

인증 평문은 username32 + digest16 + 메타데이터10 = 58바이트, Blowfish 패딩 후 64바이트입니다. bytes58–63은 로스터 해시가 아닙니다. HTTP User-Agent는 별도 순위 페이지 요청 코드에 있었으며 초기 접속이 HTTP라는 근거로 사용하지 않았습니다.

## 검증

2026-11-01 최종 확인: **Python 회귀 205개와 등록 폼 Node 검증 통과**. 영어 안내와 현재 시즌 협상 범위는 [WE10LE.md](WE10LE.md), [v3 프로토콜 계약](WE10LE-SEASON-PROTOCOL.md)에 정리했습니다.

- 실제 Twisted transport·Blowfish와 독립 XOR/MD5 프레임을 사용한 인증·분할/병합·프로필·서버 목록·웹 등록·서비스 구성.
- 기본 ID 로그인과 선택적 ID+PW 검증, 사용자 정보 조회 및 기존 계정/프로필 보존.
- Trace on/off 양쪽에서 로그인 → 프로필/설정 교환 → Main/로비 → 두 사용자 방 생성·참가 → 준비/팀·설정 → 경기 시작·점수/시계 → 두 사용자 퇴장·빈 방 삭제·로그아웃을 연속 실행. 저장소 경계와 시간만 대체한 합성 테스트입니다.
- PES6/WE10 공통 방 오류 후 성공 응답이 없는지, 기본/설정 시간 byte, 퇴장 시 방 ID 0, 설정 두 조각의 실제 zlib 압축·DB 경계 저장·동일 bytes 복원을 확인했습니다. `StoreSettings: false`의 기본 ACK/미지원 응답도 유지했습니다.
- PS2 `4101` 96바이트, `4402` 186바이트 및 관련 공통 레코드의 고정 폭/체크섬을 검사했습니다.
- Node에서 패드 12버튼 매핑, 비밀번호 A–L 1–31자, 삭제·초기화·상한/잘못된 입력, MD5 식을 검사했습니다. 원래 PC 등록 폼의 기본 경로도 유지합니다.
- 실제 사용자는 외부 클라이언트 준비 후 로그인·계정/프로필·로비·방과 서로 다른 PC 두 대에서의 실제 대전을 확인했습니다. 사용자 보고에 따른 확인이며, 최종 경기 기록 DB 저장이나 Docker 엔진 실행까지 검증한 것으로 확대하지 않습니다.

개발용 검증:

~~~sh
python -m pip install pytest
PYTHONPATH=lib python -m pytest tests -q
node tests/test_we10le_form.js
~~~

PowerShell에서는 먼저 $env:PYTHONPATH = "$PWD\lib"를 설정한 뒤 python -m pytest tests -q를 실행합니다.

Upstream: [juce/fiveserver](https://github.com/juce/fiveserver), commit 83d191f9a541a31615fa5a2e4260941881b318b7.
