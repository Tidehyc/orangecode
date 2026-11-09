"""Cron 定时任务调度器与持久化作业存储。"""

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from croniter import croniter
from loguru import logger

from orangecode.config import settings
from orangecode.spine.scheduler import SpineScheduler
from orangecode.spine.turn import BusyPolicy, Origin, TurnRequest


@dataclass
class CronJob:
    """Cron 定时作业实体。"""

    job_id: str
    name: str
    cron_expr: str
    prompt: str
    conversation_id: str
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    next_run_at: float = 0.0

    def compute_next_run(self, from_time: float | None = None) -> float:
        base = from_time or datetime.now().timestamp()
        itr = croniter(self.cron_expr, base)
        self.next_run_at = float(itr.get_next())
        return self.next_run_at


class CronService:
    """管理 Cron 任务的增删查改与到期唤醒轮询。"""

    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or (settings.state_dir / "cron_jobs.json")
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, CronJob] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self.load()

    def load(self) -> None:
        """从磁盘加载作业列表。"""
        if not self.store_path.exists():
            return
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            self._jobs.clear()
            for item in data:
                job = CronJob(**item)
                if job.next_run_at <= 0.0:
                    job.compute_next_run()
                self._jobs[job.job_id] = job
        except Exception as e:
            logger.error(f"Error loading cron jobs from {self.store_path}: {e}")

    def save(self) -> None:
        """原子落盘保存作业列表。"""
        tmp_path = self.store_path.with_suffix(".tmp")
        payload = [asdict(j) for j in self._jobs.values()]
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.store_path)

    def add_job(
        self,
        name: str,
        cron_expr: str,
        prompt: str,
        conversation_id: str | None = None,
    ) -> CronJob:
        """添加新 Cron 任务并计算首次触发时间。"""
        if not croniter.is_valid(cron_expr):
            raise ValueError(f"Invalid cron expression: '{cron_expr}'")

        job_id = f"cron_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self._jobs) + 1}"
        cid = conversation_id or f"cron_{job_id}"
        job = CronJob(
            job_id=job_id,
            name=name,
            cron_expr=cron_expr,
            prompt=prompt,
            conversation_id=cid,
        )
        job.compute_next_run()
        self._jobs[job_id] = job
        self.save()
        logger.info(f"Added CronJob [{name}] (id: {job_id}, next: {datetime.fromtimestamp(job.next_run_at)})")
        return job

    def remove_job(self, job_id: str) -> bool:
        """删除指定作业。"""
        if job_id in self._jobs:
            del self._jobs[job_id]
            self.save()
            logger.info(f"Removed CronJob {job_id}")
            return True
        return False

    def list_jobs(self) -> list[CronJob]:
        """列出全部作业。"""
        return list(self._jobs.values())

    def check_due_jobs(self) -> list[CronJob]:
        """检查并返回当前所有已到期的作业，并自动顺延更新其下次运行时间。"""
        now = datetime.now().timestamp()
        due: list[CronJob] = []
        for job in self._jobs.values():
            if job.enabled and job.next_run_at <= now:
                due.append(job)
                # 计算下一次运行时间
                job.compute_next_run(from_time=now)
        if due:
            self.save()
        return due

    async def start(self, scheduler: SpineScheduler, check_interval: float = 1.0) -> None:
        """启动后台常驻轮询服务，到期任务自动以 Origin.CRON 提交给 Spine 调度器。"""
        self._running = True
        logger.info("CronService started background ticker.")
        while self._running:
            due_jobs = self.check_due_jobs()
            for job in due_jobs:
                logger.info(f"CronJob [{job.name}] triggered! Submitting to Spine with Origin.CRON...")
                scheduler.submit(
                    TurnRequest(
                        prompt=job.prompt,
                        conversation_id=job.conversation_id,
                        origin=Origin.CRON,
                        busy_policy=BusyPolicy.APPEND,
                        metadata={"cron_job_id": job.job_id, "cron_job_name": job.name},
                    )
                )
            await asyncio.sleep(check_interval)

    def stop(self) -> None:
        """停止轮询服务。"""
        self._running = False
