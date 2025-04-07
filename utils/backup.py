# utils/backup.py
import os
import shutil
import time
from datetime import datetime
from glob import glob
from tinydb import TinyDB

def rolling_backup(file_path: str):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup_path = f"{file_path}.{timestamp}.bak"
    try:
        shutil.copyfile(file_path, backup_path)
        print(f"📦 롤링 백업 완료: {backup_path}")
    except Exception as e:
        print(f"[백업 실패] {file_path} → {backup_path} : {e}")

def cleanup_old_backups(directory="/data", keep_days=7):
    now = time.time()
    for fname in os.listdir(directory):
        if fname.endswith(".bak") and ("checklist" in fname or "quests" in fname):
            fpath = os.path.join(directory, fname)
            try:
                if os.stat(fpath).st_mtime < now - keep_days * 86400:
                    os.remove(fpath)
                    print(f"🧹 오래된 백업 삭제됨: {fname}")
            except Exception as e:
                print(f"[삭제 실패] {fname}: {e}")

def load_or_restore_db(path: str):
    try:
        return TinyDB(path)
    except Exception as e:
        print(f"[ERROR] TinyDB 로드 실패: {e}")
        backups = sorted(glob(f"{path}.*.bak"), reverse=True)
        for bpath in backups:
            try:
                shutil.copyfile(bpath, path)
                print(f"🛠️ 복구 성공: {bpath}")
                return TinyDB(path)
            except Exception as e2:
                print(f"[복구 실패] {bpath}: {e2}")
        raise RuntimeError("🚨 모든 백업 복구 실패: 수동 조치 필요")
