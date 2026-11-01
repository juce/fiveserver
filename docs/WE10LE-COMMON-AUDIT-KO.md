# WE10LE 공통 흐름과 PS2 전용 응답 감사

2026-10-31 코드 감사 기록이며 실기 확인 상태는 2026-11-01 사용자 보고를 반영했습니다. upstream은 [juce/fiveserver, 83d191f9a541a31615fa5a2e4260941881b318b7](https://github.com/juce/fiveserver/tree/83d191f9a541a31615fa5a2e4260941881b318b7)입니다. 실제 계정 정보나 원격 서비스 변경 없이 클래스 상속·handler 바인딩·합성 패킷 및 한국판 원본 파서를 대조했습니다.

## 공통 모델과 dispatch 유지

Fiveserver는 PES5 계열, Sixserver는 같은 저장소의 PES6 계열 서비스입니다. WE10LE는 Sixserver의 `data6`, `FiveServerConfig`, `ProfileLogic`, Lobby/Room/Match 모델과 PES6 상태 흐름을 재사용합니다.

upstream부터 `pes6.MainService`는 `RosterHandler, pes5.MainService`, `pes6.NetworkMenuService`는 `RosterHandler, pes5.NetworkMenuService`를 상속합니다. 공통 요청 처리가 PES5 파일에 있다는 사실만으로 잘못된 fallback이라고 판단하지 않습니다. `PacketDispatcher.packetReceived`가 등록된 bound method를 호출하며, PES6 Main은 공유 등록 뒤 방·경기 handler를 PES6 메서드로 덮어씁니다.

WE10LE는 확인된 PS2 차이만 mixin에서 처리합니다. 세 서비스의 `3010`은 PES6의 48바이트 이름 레코드를 명시적으로 사용합니다. Main의 `4100/4102` 요청 handler는 공유 코드지만 `self.formatProfileInfo`가 PES6로 바인딩되며 `4210`·방·경기 handler도 PES6입니다.

## 확인한 응답 폭

아래 길이는 XOR/MD5 전송 header를 제외한 payload 길이입니다.

| 응답 | 한국판 Main/로그인 흐름의 형식 |
| --- | --- |
| `3012` 프로필 목록 | 상태4 + 66바이트 × 프로필 수, 이름 영역48 |
| `3042` 선택 프로필 | 396바이트, PS2 전용 구성 |
| `3052` / `3062` | 75 / 4바이트 |
| `4101` Main 초기 정보 | 96바이트. 기존 공통41을 유지하고 zero55 추가 |
| `4103` Main 프로필 | 상태4 + PES6 레코드418 = 422바이트 |
| `4212` / `4220` / `4222` 사용자 | PES6 레코드127, payload offset106의 roomId는 퇴장 시0 |
| `4302` / `4306` 방 | 131바이트 |
| `4321` 방 참가 성공 | 상태4 + raw 시간 index1 = 5바이트; 기본0은5분 |
| `4321` 방 참가 오류 | 기존 오류 상태4, 이후 즉시 종료 |
| `4330` / `4347` 상대 연결 정보 | 79 / 75바이트 |
| `4362` / `4365` 시작·참가 목록 | 37 / 24바이트 |
| `4402` 채팅·기록·시스템 공지 | 발신자58 + 메시지 영역128 = 186바이트 |

`4101`의 기존 bytes0–40은 바꾸지 않았습니다. PS2가 추가로 읽는 scalar4·group name48·extras3은 아직 지원하지 않아 0으로 채웁니다. `4402`는 PS2 서비스의 `sendData`에서만 186바이트로 맞추므로 짧은 채팅 기록/공지에도 같은 폭을 적용합니다. 기존 PC 서비스의 두 응답 폭은 유지됩니다.

## 공통 버그 수정

- PS2의 미등록 요청 handler를 무응답으로 삼키지 않고 upstream의 요청 ID+1 / zero4 상태 응답으로 위임합니다. 실제 로비 진입의 `308c → 308d`가 포함됩니다.
- PES6 방 참가에서 없는 방·틀린 방 비밀번호는 오류 `4321` 직후 반환합니다. 잘못된 가입 뒤 성공 상태·주소 전달·방 변경을 이어가지 않습니다.
- 참가 성공의 시간은 `!B`로 직렬화하며 설정 전에도 기본 index0을 보냅니다. Python 3의 int/bytes 결합 오류와 성공 응답의 필드 누락을 함께 수정했습니다.
- 방 퇴장 후 `4222`에 기존 방 ID 대신0을 보내 양쪽 클라이언트가 사용자를 방 밖으로 표시하게 합니다. 마지막 퇴장 시 기존 빈 방 삭제·`4305` 흐름은 유지됩니다.
- `Lobby.isRoom`의 Python 2 `dict.has_key`를 같은 키의 membership 검사로 바꿨습니다.
- `do_3088`의 bytes index 비교를 정수3으로 고쳐 첫 번째/두 번째 설정 조각의 zlib 저장·복원 구분을 복원했습니다. `StoreSettings: false` 기본값은 바꾸지 않았습니다.

## PS2 전용 차이와 범위

인증 `3f01/3f02`, 기본 등록 ID 조회/선택적 비밀번호 검증, `3042/3052/3062`, 논리 종료의 `0004`와 TCP FIN, heartbeat 체크섬 재생성은 PS2 adapter에 한정합니다. 방·참가·준비·경기 상태 모델을 따로 복제하지 않습니다.

Menu의 일부 상속 경로에는 upstream과 같은 57바이트 프로필/31바이트 사용자 레코드가 남아 있습니다. Main/Menu의 `3070`도 기존 PES5 fallback을 유지합니다. 이 좁은 Menu 전용 경로는 실제 한국판 사용 여부·파서 의미가 아직 확인되지 않았으며, 이번 Main 경로 검증으로 호환을 주장하지 않습니다. 한글 이름/채팅과 순위·그룹·대회 전체를 지원한다고도 주장하지 않습니다.

## 검증 구분

2026-10-31 감사 당시 Python 회귀158개와 등록 폼 Node 검증이 통과했습니다. 합성 두 사용자의 인증·프로필·설정 업로드·Main/로비·방 생성/참가·준비/팀/게임 설정·경기 시작·점수/시계·퇴장·빈 방 삭제·로그아웃을 실제 production handler/model/wire로 연속 실행했습니다. 공통 방/설정 회귀는 PES6와 WE10LE 양쪽을 검사하며 SQL 경계만 대체합니다. 현재 전체 검증 결과는 [WE10LE-KR.md](WE10LE-KR.md)를 참고하세요.

2026-11-01 추가로 사용자가 서로 다른 PC 두 대에서 실제 대전이 동작함을 확인했습니다. 이는 사용자 보고이며 에이전트의 직접 경기 관찰과는 구분합니다. 모든 NAT 환경의 판정·최종 경기 기록 DB 저장·Docker 엔진 실행은 이 보고로 검증된 것이 아닙니다. 원본 ISO는 수정하지 않았습니다.

관련 소스: [PES5 공통 처리](../lib/fiveserver/protocol/pes5.py), [PES6 방·경기](../lib/fiveserver/protocol/pes6.py), [WE10LE adapter](../lib/fiveserver/protocol/we10le.py), [공통 모델](../lib/fiveserver/model/lobby.py).
