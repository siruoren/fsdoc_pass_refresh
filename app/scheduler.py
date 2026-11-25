# -*- coding: utf-8 -*-
"""每条目的定时刷新任务（cron 表达式，5 字段）。"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import db, service

log = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def validate_cron(expr: str) -> bool:
    if not expr or not expr.strip():
        return True  # 空 = 不启用定时
    try:
        CronTrigger.from_crontab(expr.strip())
        return True
    except ValueError:
        return False


def _job(entry_id: int):
    try:
        result = service.refresh_entry(entry_id)
        log.info("定时刷新条目 %s 完成: %s", entry_id, result["status"])
    except Exception as e:
        log.exception("定时刷新条目 %s 失败: %s", entry_id, e)


def schedule_entry(entry: dict):
    job_id = f"entry-{entry['id']}"
    remove_entry(entry["id"])
    expr = (entry.get("cron") or "").strip()
    if not expr:
        return
    scheduler.add_job(
        _job, CronTrigger.from_crontab(expr),
        args=[entry["id"]], id=job_id, replace_existing=True, misfire_grace_time=3600,
    )


def remove_entry(entry_id: int):
    job_id = f"entry-{entry_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def reschedule_all():
    for entry in db.list_entries():
        schedule_entry(entry)


def start():
    scheduler.start()
    reschedule_all()
    log.info("定时任务调度器已启动")


def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
