# NetClass Manager (도서관 공용 PC 중앙 관리 시스템)

## 📖 프로젝트 개요
**NetClass Manager**는 도서관과 같이 불특정 다수가 사용하는 공용 PC 환경에서 발생하는 데이터 무결성 훼손, 보안 취약점, 유지보수 비효율성 문제를 해결하기 위해 개발된 **중앙 집중형 PC 관리 시스템**입니다.

관리자가 웹 대시보드를 통해 원격으로 시스템을 제어하고, 재부팅 시 PC 상태를 특정 시점으로 자동 복구하는 기능을 핵심으로 합니다.

## 🛠 기술 스택 (Tech Stack)
* **Backend:** Python 3.14.0, Flask
* **Database:** MySQL 8.0 (InnoDB)
* **Frontend:** HTML5, CSS3, Bootstrap 5.3
* **Tools:** VS Code, MySQL Workbench

## ✨ 주요 기능 (Key Features)

### 1. 자동 복구 (Auto-Recovery) & 스냅샷 관리
* **Snapshot 기반 복원:** PC 재부팅 시 관리자가 지정한 'Active Snapshot' 시점 이후에 생성된 모든 데이터(설치된 소프트웨어 등)를 자동으로 삭제하여 초기 상태로 되돌립니다.
* **Transaction 보장:** 복구 과정은 `sp_ClientShutdownProcess` 프로시저 내에서 트랜잭션으로 처리되어 ACID를 보장합니다.

### 2. 관리자 대시보드 및 원격 제어
* **실시간 모니터링:** 층별/구역별 PC의 상태(Online/Offline), 현재 모드(Recovery/Maintenance), 건강 상태 점수를 한눈에 파악할 수 있습니다.
* **원격 명령:** 관리자는 웹 인터페이스를 통해 원격으로 PC를 종료(재부팅), 로그오프시키거나 운영 모드를 변경할 수 있습니다.

### 3. 데이터 분석 및 통계 (Analytics)
* **SW 설치 랭킹:** `DENSE_RANK()` 윈도우 함수를 사용하여 많이 설치된 소프트웨어 순위를 산출합니다.
* **구역별 현황:** `GROUP BY ... WITH ROLLUP`을 활용하여 층별, 장소별 PC 대수의 소계(Sub Total)와 총계를 제공합니다.

### 4. 자동 유지보수 및 감사
* **야간 자동 점검:** MySQL Event Scheduler(`ev_NightlyReset`)를 통해 매일 밤 23시에 모든 Recovery 모드 PC를 자동으로 초기화합니다.
* **감사 로그 (Audit Log):** 소프트웨어 설치 시 Trigger(`trg_AfterInstall`)가 작동하여 자동으로 로그를 남기며, 관리자의 모든 조작 행위도 기록됩니다.

## 🗄️ 데이터베이스 설계 (Database Design)

본 프로젝트는 고급 데이터베이스 객체를 적극 활용하여 비즈니스 로직을 DB 레벨에서 처리하였습니다.

### 주요 Database Objects
| 구분 | 이름 | 역할 |
| :--- | :--- | :--- |
| **View** | `View_PC_Full_Info` | 분산된 PC, 위치, 스냅샷 정보를 통합 조회하여 JOIN 연산 효율화 |
| **Procedure** | `sp_ClientShutdownProcess` | 시스템 종료 시 모드(Recovery/Maintenance)에 따라 데이터를 롤백하거나 보존하는 핵심 로직 (트랜잭션 포함) |
| **Procedure** | `sp_CalculateHealthScore` | Cursor를 사용하여 최근 에러 횟수와 SW 설치 수를 기반으로 PC 건강 점수 산출 |
| **Function** | `fn_GetSoftwareCount` | 특정 PC의 소프트웨어 설치 개수를 반환하는 스칼라 함수 |
| **Trigger** | `trg_AfterInstall` | `Installed_Software` 테이블 INSERT 시 자동으로 `Event_Log`에 기록 |
| **Event** | `ev_NightlyReset` | 매일 밤 23시에 야간 유지보수 프로시저 자동 실행 |

## 🚀 설치 및 실행 방법 (Installation)

1.  **데이터베이스 구축**
    * MySQL에 접속하여 `netclass_db` 데이터베이스를 생성합니다.
    * 제공된 `query.sql` 파일을 실행하여 테이블, 프로시저, 트리거, 초기 데이터를 생성합니다.
    ```bash
    mysql -u root -p < query.sql
    ```

2.  **환경 설정**
    * Python 필수 라이브러리를 설치합니다.
    ```bash
    pip install flask mysql-connector-python
    ```
    * `app.py` 파일의 `db_config` 부분에서 본인의 MySQL 계정 정보(user, password)로 수정합니다.

3.  **서버 실행**
    ```bash
    python app.py
    ```

4.  **접속**
    * 웹 브라우저에서 `http://localhost:5000`으로 접속합니다.
    * **초기 관리자 계정:** ID `admin` / PW `1234`

## 📂 프로젝트 구조

```text
NetClass-Manager/
├── app.py                  # Flask 메인 애플리케이션 (라우팅 및 DB 연동)
├── query.sql               # DB 초기화 스크립트 (DDL, DML, DCL)
├── templates/              # HTML 템플릿 (Bootstrap 적용)
│   ├── index.html          # 관리자 대시보드
│   ├── analytics.html      # 통계 분석 페이지
│   ├── login.html          # 관리자 로그인 페이지
│   ├── logs.html           # 시스템 로그 조회 페이지
│   ├── pc_detail.html      # PC 상세 정보 및 스냅샷 관리
│   ├── client_select.html  # 사용자 좌석 선택 시뮬레이션
│   └── client_desktop.html # 사용자 바탕화면 시뮬레이션
└── README.md               # 프로젝트 설명서
```

## 🎥 시연 영상
* [YouTube Link](https://youtu.be/2YgeneWXW4Y)
