
# 🎮 Game Daily Quest Bot (Telegram)

텔레그램에서 여러 게임의 **일일/주간 숙제**를 체크하고, **이벤트 진행 상황**까지 추적할 수 있는 유저 맞춤형 게임 숙제 관리 봇입니다!

---

## ✅ 주요 기능

### 📅 일일/주간 숙제 관리
- `/daily`: 오늘의 숙제 체크리스트 표시
- `/weekly`: 이번 주의 숙제 리스트 표시
- 버튼으로 숙제 완료 체크 가능 ✅
- `/complete [게임명] [weekly(optional)]`: 해당 게임 숙제를 일괄 완료 처리
- `/done`: 모든 숙제 완료 시 `Day N 클리어` 처리
- `/progress`: 오늘의 숙제 진행 상황 확인

### 🎉 이벤트 관리
- `/addevent`: 대화형으로 이벤트 추가 (이름, 기간, 타입, 숙제 입력)
- `/event`: 현재 진행 중인 이벤트 숙제 확인 및 체크

### ➕ 숙제 추가 / 삭제
- `/addtask`: 대화형으로 숙제 항목 추가 (게임명, 기간, 숙제 목록)
- `/deltask`: 대화형으로 숙제 항목 삭제

### 📝 숙제/게임 정보 편집
- `/listtasks`: 등록된 게임 및 숙제 목록 확인
- `/renamegame`: 등록된 게임 이름 수정
- `/editquest`: 등록된 숙제 항목 이름 수정

### ℹ️ 기타
- `/start`: 봇 인사 + 게임 목록 안내
- `/help`: 전체 명령어 도움말 출력
- `/test`: 알림 테스트 전송

---

## 🕐 자동 기능 (Scheduler)

| 작업 내용           | 시간 (KST 기준)       |
|--------------------|------------------------|
| 숙제 초기화 (일일) | 매일 오전 5시         |
| 숙제 초기화 (주간) | 매주 월요일 오전 5시  |
| 알림 전송          | 매일 오전 8시         |
| 슬립 방지 ping     | 10분 간격              |

---

## ⚙️ 환경 변수 설정

- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `SELF_URL`: Fly.io에 배포된 본인 서버 주소 (슬립 방지용)

---

## 💾 데이터 경로

- `data/quests.json`: 게임별 숙제, 이벤트 정보 저장소 (자동 관리됨)

---

## 📦 실행 방법

```bash
# 필요한 라이브러리 설치
pip install -r requirements.txt

# 실행
python bot.py

## 🕓 스케줄 설정

- 일일 숙제 리마인더는 매일 **오전 5시 (UTC+9)** 에 전송됩니다.
- 주간 숙제는 **월요일 기준으로** 유지됩니다.
- Fly.io, Railway 등의 서버 플랫폼에서 24시간 구동 가능하도록 설정할 수 있습니다.

---

## 🗂 데이터 저장

- `data/quests.json`: 등록된 게임/숙제/이벤트 정보
- `data/checklist.json`: 유저별 숙제 체크 여부 기록

이 파일들은 로컬에서 유지되므로, 서버 재배포 시 **삭제되지 않도록 볼륨 설정**이 필요합니다.

---

## 💡 팁

- 하나의 봇 인스턴스만 실행하세요. 동시에 여러 인스턴스를 실행하면 `getUpdates Conflict` 오류가 발생합니다.
- Fly.io 배포 시 `volumes`를 사용해 `data/` 디렉터리를 지속시켜 주세요.
