#!/bin/sh
# =============================================================
# نسخة تعافٍ كاملة لنظام MOZAD ERP — ملف واحد يكفي للاستعادة
# الاستخدام:  sh scripts/backup-system.sh
# المخرجات:  backups/system-recovery-<تاريخ>.tar.gz
# ما بداخلها: الكود + .env (الأسرار) + docker-compose + كل نسخ
#             البيانات (التلقائية واليدوية) — بدون node_modules
#             و.venv (تُعاد بـ npm install / pip install)
# ⚠️ الملف يحوي أسراراً — خزّنه في مكان آمن (خارجي/مشفّر)
# =============================================================
set -e
cd "$(dirname "$0")/.."

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="backups/system-recovery-${STAMP}.tar.gz"

tar --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='frontend/dist' \
    --exclude='.DS_Store' \
    --exclude='*system-recovery-*' \
    --exclude='.git/fsmonitor--daemon.ipc' \
    -czf "$OUT" \
    -C .. \
    "$(basename "$(pwd)")"

SIZE=$(du -h "$OUT" | cut -f1)
echo "✅ نسخة التعافي: $OUT ($SIZE)"
echo "   المحتوى: الكود + .env + docker-compose + الترحيلات + كل نسخ البيانات"
echo "   ⚠️  خزّنها خارج الجهاز (iCloud/قرص خارجي) — تحوي أسرار التشغيل"
