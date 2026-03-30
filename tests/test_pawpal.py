"""
Tests for PawPal+ core logic.
Run with: python -m pytest

Coverage areas:
  Task        — completion, recurrence logic, priority ordering
  Pet         — task management, due-today filtering
  Owner       — pet management, back-references, time budget
  Scheduler   — priority scheduling, time budget, sorting, filtering,
                recurring reschedule, conflict detection (overlap + edge cases)
"""

import datetime
import pytest
from pawpal_system import Owner, Pet, Task, Schedule, Scheduler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_task():
    return Task(title="Morning walk", task_type="walk", duration_minutes=30, priority=5)


@pytest.fixture
def sample_pet():
    return Pet(name="Buddy", species="Dog", age=3)


@pytest.fixture
def sample_owner():
    return Owner(name="Alex", available_minutes_per_day=90)


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------

def test_mark_complete_changes_status(sample_task):
    """mark_complete() should set is_completed to True."""
    assert sample_task.is_completed is False
    sample_task.mark_complete()
    assert sample_task.is_completed is True


def test_mark_complete_idempotent(sample_task):
    """Calling mark_complete() twice should leave task completed."""
    sample_task.mark_complete()
    sample_task.mark_complete()
    assert sample_task.is_completed is True


def test_non_recurring_task_is_always_due(sample_task):
    """A non-recurring task should always be due today."""
    assert sample_task.is_due_today() is True


def test_recurring_task_due_on_correct_day():
    """A recurring task is only due on its scheduled days."""
    import datetime
    today_abbr = datetime.date.today().strftime("%a")
    other_days = [d for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] if d != today_abbr]

    due_today = Task("Med", "medication", 5, 4, is_recurring=True, recurrence_days=[today_abbr])
    not_due = Task("Med", "medication", 5, 4, is_recurring=True, recurrence_days=other_days[:1])

    assert due_today.is_due_today() is True
    assert not_due.is_due_today() is False


def test_task_priority_ordering():
    """Higher priority tasks should sort before lower priority tasks."""
    low  = Task("Low",  "enrichment", 10, priority=1)
    high = Task("High", "walk",       30, priority=5)
    mid  = Task("Mid",  "feeding",    10, priority=3)

    sorted_tasks = sorted([low, mid, high])
    assert sorted_tasks[0].title == "High"
    assert sorted_tasks[-1].title == "Low"


# ---------------------------------------------------------------------------
# Pet tests
# ---------------------------------------------------------------------------

def test_add_task_increases_count(sample_pet, sample_task):
    """Adding a task to a Pet should increase the task count by one."""
    before = len(sample_pet.get_tasks())
    sample_pet.add_task(sample_task)
    assert len(sample_pet.get_tasks()) == before + 1


def test_add_multiple_tasks(sample_pet):
    """Adding three tasks should result in three tasks on the pet."""
    for i in range(3):
        sample_pet.add_task(Task(f"Task {i}", "walk", 10, priority=3))
    assert len(sample_pet.get_tasks()) == 3


def test_completed_task_excluded_from_due_today(sample_pet, sample_task):
    """A completed task should not appear in get_tasks_due_today()."""
    sample_task.mark_complete()
    sample_pet.add_task(sample_task)
    assert sample_task not in sample_pet.get_tasks_due_today()


# ---------------------------------------------------------------------------
# Owner tests
# ---------------------------------------------------------------------------

def test_add_pet_sets_back_reference(sample_owner, sample_pet):
    """add_pet() should set the pet's owner reference."""
    sample_owner.add_pet(sample_pet)
    assert sample_pet.owner is sample_owner


def test_owner_tracks_multiple_pets(sample_owner):
    """Owner should track all added pets."""
    p1 = Pet("Buddy", "Dog", 3)
    p2 = Pet("Luna",  "Cat", 5)
    sample_owner.add_pet(p1)
    sample_owner.add_pet(p2)
    assert len(sample_owner.get_pets()) == 2


def test_set_available_time(sample_owner):
    """set_available_time() should update the owner's time budget."""
    sample_owner.set_available_time(60)
    assert sample_owner.available_minutes_per_day == 60


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------

def test_generate_plan_respects_time_budget(sample_owner, sample_pet):
    """Scheduler should not exceed the owner's available time budget."""
    for i in range(5):
        sample_pet.add_task(Task(f"Task {i}", "walk", 30, priority=3))
    sample_owner.add_pet(sample_pet)
    sample_owner.set_available_time(60)

    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)
    schedule = scheduler.generate_plan()

    assert schedule.get_total_duration() <= sample_owner.available_minutes_per_day


def test_generate_plan_prioritises_high_priority(sample_owner, sample_pet):
    """Scheduler should include high-priority tasks before low-priority ones."""
    sample_pet.add_task(Task("Low task",  "enrichment", 40, priority=1))
    sample_pet.add_task(Task("High task", "walk",       40, priority=5))
    sample_owner.add_pet(sample_pet)
    sample_owner.set_available_time(50)  # only room for one 40-min task

    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)
    schedule = scheduler.generate_plan()

    titles = [t.title for t in schedule.planned_tasks]
    assert "High task" in titles
    assert "Low task" not in titles


def test_skipped_tasks_recorded(sample_owner, sample_pet):
    """Tasks that don't fit the budget should appear in skipped_tasks."""
    sample_pet.add_task(Task("Task A", "walk",    60, priority=5))
    sample_pet.add_task(Task("Task B", "feeding", 60, priority=3))
    sample_owner.add_pet(sample_pet)
    sample_owner.set_available_time(60)

    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)
    schedule = scheduler.generate_plan()

    assert len(schedule.skipped_tasks) == 1
    assert schedule.skipped_tasks[0].title == "Task B"


def test_detect_conflicts_finds_same_time_tasks(sample_owner, sample_pet):
    """detect_conflicts() should flag tasks sharing the same preferred time."""
    t1 = Task("Walk",    "walk",    30, priority=5, preferred_time="08:00")
    t2 = Task("Feeding", "feeding", 10, priority=4, preferred_time="08:00")
    sample_owner.add_pet(sample_pet)

    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)
    conflicts = scheduler.detect_conflicts([t1, t2])

    assert len(conflicts) == 1
    conflict_titles = {conflicts[0][0].title, conflicts[0][1].title}
    assert conflict_titles == {"Walk", "Feeding"}


# ---------------------------------------------------------------------------
# Sorting tests (Phase 5)
# ---------------------------------------------------------------------------

def test_sort_by_time_chronological_order(sample_owner, sample_pet):
    """sort_by_time() should return tasks ordered earliest to latest."""
    sample_owner.add_pet(sample_pet)
    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)

    tasks = [
        Task("Evening", "walk",    30, priority=3, preferred_time="18:00"),
        Task("Midday",  "feeding", 10, priority=3, preferred_time="12:00"),
        Task("Morning", "walk",    30, priority=3, preferred_time="07:00"),
    ]
    sorted_tasks = scheduler.sort_by_time(tasks)

    assert [t.preferred_time for t in sorted_tasks] == ["07:00", "12:00", "18:00"]


def test_sort_by_time_untimed_tasks_last(sample_owner, sample_pet):
    """Tasks without a preferred_time should be placed after all timed tasks."""
    sample_owner.add_pet(sample_pet)
    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)

    tasks = [
        Task("No time",  "enrichment", 15, priority=3),
        Task("Morning",  "walk",       30, priority=5, preferred_time="07:00"),
    ]
    sorted_tasks = scheduler.sort_by_time(tasks)

    assert sorted_tasks[0].title == "Morning"
    assert sorted_tasks[-1].title == "No time"


# ---------------------------------------------------------------------------
# Filtering tests (Phase 5)
# ---------------------------------------------------------------------------

def test_filter_tasks_by_type(sample_owner, sample_pet):
    """filter_tasks() with task_type should return only matching tasks."""
    sample_owner.add_pet(sample_pet)
    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)

    tasks = [
        Task("Walk A",   "walk",    30, priority=5),
        Task("Feeding",  "feeding", 10, priority=5),
        Task("Walk B",   "walk",    20, priority=3),
    ]
    walks = scheduler.filter_tasks(tasks, task_type="walk")

    assert len(walks) == 2
    assert all(t.task_type == "walk" for t in walks)


def test_filter_tasks_by_completion(sample_owner, sample_pet):
    """filter_tasks(completed=False) should exclude completed tasks."""
    sample_owner.add_pet(sample_pet)
    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)

    done    = Task("Done task",    "grooming", 10, priority=2)
    pending = Task("Pending task", "walk",     30, priority=5)
    done.mark_complete()

    incomplete = scheduler.filter_tasks([done, pending], completed=False)

    assert pending in incomplete
    assert done not in incomplete


# ---------------------------------------------------------------------------
# Recurring task rescheduling tests (Phase 5)
# ---------------------------------------------------------------------------

def test_recurring_daily_task_reschedules_to_tomorrow():
    """Completing a daily recurring task should set next_due_date to tomorrow."""
    all_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    task = Task(
        title="Daily walk", task_type="walk", duration_minutes=30, priority=5,
        is_recurring=True, recurrence_days=all_days,
    )
    task.mark_complete()

    expected = datetime.date.today() + datetime.timedelta(days=1)
    assert task.next_due_date == expected


def test_recurring_task_not_completed_permanently():
    """Completing a recurring task should NOT set is_completed to True."""
    all_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    task = Task(
        title="Daily meds", task_type="medication", duration_minutes=5, priority=5,
        is_recurring=True, recurrence_days=all_days,
    )
    task.mark_complete()

    assert task.is_completed is False


def test_recurring_task_not_due_after_completion():
    """After completing a recurring task, it should not be due again until next_due_date."""
    all_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    task = Task(
        title="Daily walk", task_type="walk", duration_minutes=30, priority=5,
        is_recurring=True, recurrence_days=all_days,
    )
    task.mark_complete()
    # next_due_date is tomorrow, so today it should NOT be due
    assert task.is_due_today() is False


# ---------------------------------------------------------------------------
# Conflict detection edge cases (Phase 5)
# ---------------------------------------------------------------------------

def test_detect_conflicts_overlap_not_exact_match(sample_owner, sample_pet):
    """Conflict detection should catch overlapping windows even when start times differ."""
    sample_owner.add_pet(sample_pet)
    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)

    # Feeding: 07:30–07:40 | Supplement: 07:35–07:40 → overlap
    feeding    = Task("Feeding",    "feeding",    10, priority=5, preferred_time="07:30")
    supplement = Task("Supplement", "medication",  5, priority=4, preferred_time="07:35")

    conflicts = scheduler.detect_conflicts([feeding, supplement])
    assert len(conflicts) == 1


def test_detect_conflicts_no_false_positives(sample_owner, sample_pet):
    """Non-overlapping tasks should produce zero conflicts."""
    sample_owner.add_pet(sample_pet)
    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)

    # Walk: 07:00–07:30 | Feeding: 08:00–08:10 → no overlap
    walk    = Task("Walk",    "walk",    30, priority=5, preferred_time="07:00")
    feeding = Task("Feeding", "feeding", 10, priority=4, preferred_time="08:00")

    conflicts = scheduler.detect_conflicts([walk, feeding])
    assert len(conflicts) == 0


def test_detect_conflicts_untimed_tasks_ignored(sample_owner, sample_pet):
    """Tasks without a preferred_time should never trigger a conflict."""
    sample_owner.add_pet(sample_pet)
    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)

    t1 = Task("Task A", "walk",    30, priority=5)   # no preferred_time
    t2 = Task("Task B", "feeding", 10, priority=4)   # no preferred_time

    conflicts = scheduler.detect_conflicts([t1, t2])
    assert len(conflicts) == 0


# ---------------------------------------------------------------------------
# Edge-case scheduler tests (Phase 5)
# ---------------------------------------------------------------------------

def test_schedule_pet_with_no_tasks(sample_owner, sample_pet):
    """Generating a plan for a pet with no tasks should produce an empty schedule."""
    sample_owner.add_pet(sample_pet)
    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)
    schedule = scheduler.generate_plan()

    assert schedule.planned_tasks == []
    assert schedule.skipped_tasks == []
    assert schedule.get_total_duration() == 0


def test_schedule_all_tasks_exceed_budget(sample_owner, sample_pet):
    """When every task exceeds the budget individually, all should be skipped."""
    sample_owner.add_pet(sample_pet)
    sample_owner.set_available_time(10)

    sample_pet.add_task(Task("Long walk A", "walk", 60, priority=5))
    sample_pet.add_task(Task("Long walk B", "walk", 60, priority=3))

    scheduler = Scheduler(owner=sample_owner, pet=sample_pet)
    schedule = scheduler.generate_plan()

    assert schedule.planned_tasks == []
    assert len(schedule.skipped_tasks) == 2
