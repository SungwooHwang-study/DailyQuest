
# DailyQuest Telegram Bot

🎮 **DailyQuest**는 여러 게임의 일일/주간 숙제를 편리하게 관리할 수 있는 텔레그램 봇입니다.  
사용자는 직접 숙제를 등록하고, 매일 아침 숙제를 자동으로 알림받을 수 있으며, 숙제를 완료 체크하고 Day 클리어도 기록할 수 있습니다.

---

## 📦 주요 기능

- `/start` - 봇 시작 및 유저 등록
- `/daily` - 오늘의 일일 숙제 확인 및 체크
- `/weekly` - 이번 주 주간 숙제 확인 및 체크
- `/complete [게임명] [weekly(optional)]` - 특정 게임 숙제 전체 완료 처리
- `/done` - 오늘 숙제 전부 완료 시 Day 클리어 기록
- `/progress` - 오늘의 숙제 진행 상황 요약
- `/addevent` - 게임 이벤트 숙제 등록 (대화형)
- `/event` - 진행 중인 이벤트 숙제 확인 및 체크
- `/help` - 명령어 목록 확인
- `/test` - 알람 테스트

---

## 🛠️ 실행 방법

1. `.env` 파일에 다음을 설정합니다:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
SELF_URL=https://your-app-name.fly.dev
```

2. 프로젝트 실행:

```bash
python main.py
```

---

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
