import cancellation


def test_active_count_tracks_create_and_discard():
    cancellation.discard("active-count-a")
    cancellation.discard("active-count-b")
    before = cancellation.active_count()
    cancellation.create("active-count-a")
    cancellation.create("active-count-b")
    try:
        assert cancellation.active_count() == before + 2
    finally:
        cancellation.discard("active-count-a")
        cancellation.discard("active-count-b")
    assert cancellation.active_count() == before


def test_create_after_shutdown_is_cancelled():
    task_id = "shutdown-create-test"
    cancellation._shutdown_requested.clear()
    try:
        cancellation.begin_shutdown()
        token = cancellation.create(task_id)
        assert token.is_cancelled()
    finally:
        cancellation.discard(task_id)
        cancellation._shutdown_requested.clear()
