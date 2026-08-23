"""Work Queue page listing active, pending, and recent background jobs."""

from __future__ import annotations

from nicegui import ui

from app.graphs.jobs import Job, QueuedScene, get_job_manager
from app.ui.layout import render_header


def _status_label(status: str) -> str:
    return {
        "pending": "Pending",
        "running": "Running",
        "finished": "Finished",
        "failed": "Failed",
        "blocked": "Blocked",
    }.get(status, status)


def _render_queue_item(item: QueuedScene) -> None:
    with (
        ui.row()
        .classes("w-full items-center gap-3 p-3 bg-grey-1 rounded")
        .mark(f"queue-item-{item.id}")
    ):
        if item.status == "running":
            ui.spinner(size="sm").mark(f"queue-item-spinner-{item.id}")
        elif item.status == "pending":
            ui.icon("hourglass_empty").classes("text-grey-7")
        elif item.status == "blocked":
            ui.icon("block").classes("text-orange-8")
        elif item.status == "failed":
            ui.icon("error").classes("text-negative")
        else:
            ui.icon("check_circle").classes("text-positive")
        with ui.column().classes("gap-0 flex-grow"):
            ui.label(item.label).classes("font-medium")
            detail = _status_label(item.status)
            if item.error:
                detail = f"{detail}: {item.error}"
            elif item.prerequisite_scene_ids and item.status == "pending":
                detail = f"{detail} (waiting on prerequisites)"
            ui.label(detail).classes("text-sm text-grey-7")


def _render_standalone_job(job: Job) -> None:
    with (
        ui.row()
        .classes("w-full items-center gap-3 p-3 bg-grey-1 rounded")
        .mark(f"job-item-{job.id}")
    ):
        if job.status == "running":
            ui.spinner(size="sm")
        elif job.status == "failed":
            ui.icon("error").classes("text-negative")
        else:
            ui.icon("check_circle").classes("text-positive")
        with ui.column().classes("gap-0 flex-grow"):
            ui.label(job.label).classes("font-medium")
            detail = _status_label(job.status)
            if job.error:
                detail = f"{detail}: {job.error}"
            ui.label(detail).classes("text-sm text-grey-7")


def _queue_page() -> None:
    render_header("/queue")
    manager = get_job_manager()

    with ui.column().classes("w-full gap-4 p-4 max-w-3xl"):
        ui.label("Work Queue").classes("text-2xl font-semibold").mark("work-queue-page-title")
        ui.label(
            "Background scene generation, intimacy interpretation, plot runs, and chat "
            "turns. Queued scenes wait until prerequisites finish, then run up to the "
            "parallel limit. Intimacy jobs run per character in parallel. A plot run "
            "claims the story bible until it commits or bails out."
        ).classes("text-grey-7")

        @ui.refreshable
        def work_list() -> None:
            queue_items = manager.queued_items()
            queue_job_ids = {item.job_id for item in queue_items if item.job_id}
            standalone_jobs = [
                job
                for job in [*manager.running_jobs(), *manager.finished_jobs()]
                if job.id not in queue_job_ids
            ]

            active_queue = [item for item in queue_items if item.status in ("pending", "running")]
            blocked_queue = [item for item in queue_items if item.status == "blocked"]
            recent_queue = [item for item in queue_items if item.status in ("finished", "failed")][
                -20:
            ]
            running_standalone = [job for job in standalone_jobs if job.status == "running"]
            finished_standalone = [
                job for job in standalone_jobs if job.status in ("finished", "failed")
            ][-20:]

            if not (
                active_queue
                or blocked_queue
                or recent_queue
                or running_standalone
                or finished_standalone
            ):
                ui.label("No active or recent workflows.").classes("text-grey-7").mark(
                    "work-queue-empty"
                )
                return

            if active_queue or running_standalone:
                ui.label("Active").classes("text-lg font-semibold")
                for item in active_queue:
                    _render_queue_item(item)
                for job in running_standalone:
                    _render_standalone_job(job)

            if blocked_queue:
                ui.label("Blocked").classes("text-lg font-semibold")
                for item in blocked_queue:
                    _render_queue_item(item)

            if recent_queue or finished_standalone:
                ui.label("Recent").classes("text-lg font-semibold")
                for item in reversed(recent_queue):
                    _render_queue_item(item)
                for job in reversed(finished_standalone):
                    _render_standalone_job(job)

        work_list()
        ui.timer(1.0, work_list.refresh)


@ui.page("/queue")
def queue() -> None:
    _queue_page()
