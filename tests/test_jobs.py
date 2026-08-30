import time

from supermarkt.jobs import SearchJobStore


def test_job_progress_never_exceeds_total_sources():
    store = SearchJobStore(object())
    store._jobs["audit"] = {"updated_at": 0, "processed_sources": 0, "total_sources": 7}
    store._progress("audit", processed_sources=12)
    job = store.get("audit")
    assert job is not None
    assert job["processed_sources"] == 7


class ProgressEngine:
    def snapshot(self, postal_code, aldi_region, refresh, progress=None, retailers=(), rewe_market_id="", netto_market_id=""):
        progress(status="loading", progress=35, source="Testquelle", retailer="Lidl",
                 category="Backwaren", step="Laden", processed_sources=2,
                 total_sources=6, processed_products=42)
        return {"search_id": "job-result", "offers": [{}, {}]}, False


def test_search_job_reports_real_progress_and_completion():
    jobs = SearchJobStore(ProgressEngine())
    job_id = jobs.start("01067")
    for _ in range(100):
        job = jobs.get(job_id)
        if job["status"] == "completed":
            break
        time.sleep(0.01)
    assert job["progress"] == 100
    assert job["processed_products"] == 2
    assert job["search_id"] == "job-result"


def test_search_job_forwards_manual_aldi_choice():
    class RecordingEngine(ProgressEngine):
        seen = None

        def snapshot(self, postal_code, aldi_region, refresh, progress=None, retailers=(), rewe_market_id="", netto_market_id=""):
            self.seen = (postal_code, aldi_region)
            return super().snapshot(postal_code, aldi_region, refresh, progress, retailers)

    engine = RecordingEngine()
    jobs = SearchJobStore(engine)
    job_id = jobs.start("51643", "both")
    for _ in range(100):
        if jobs.get(job_id)["status"] == "completed":
            break
        time.sleep(0.01)
    assert engine.seen == ("51643", "both")


def test_search_job_reports_failures():
    class BrokenEngine:
        def snapshot(self, *args, **kwargs):
            raise RuntimeError("synthetic failure")

    jobs = SearchJobStore(BrokenEngine())
    job_id = jobs.start("01067")
    for _ in range(100):
        job = jobs.get(job_id)
        if job["status"] == "failed":
            break
        time.sleep(0.01)
    assert job["status"] == "failed"
    assert job["error"] == "synthetic failure"


def test_search_job_forwards_refresh_request():
    """Der Haken auf der Startseite muss den Servercache wirklich übergehen."""
    class RecordingEngine(ProgressEngine):
        seen = None

        def snapshot(self, postal_code, aldi_region, refresh, progress=None, retailers=(), rewe_market_id="", netto_market_id=""):
            self.seen = refresh
            return super().snapshot(postal_code, aldi_region, refresh, progress, retailers)

    for requested in (True, False):
        engine = RecordingEngine()
        jobs = SearchJobStore(engine)
        job_id = jobs.start("51377", "auto", requested)
        for _ in range(100):
            if jobs.get(job_id)["status"] == "completed":
                break
            time.sleep(0.01)
        assert engine.seen is requested


def test_search_job_forwards_retailer_selection():
    class RecordingEngine(ProgressEngine):
        seen = None

        def snapshot(self, postal_code, aldi_region, refresh, progress=None, retailers=(), rewe_market_id="", netto_market_id=""):
            self.seen = retailers
            return super().snapshot(postal_code, aldi_region, refresh, progress, retailers)

    engine = RecordingEngine()
    jobs = SearchJobStore(engine)
    job_id = jobs.start("50677", retailers=("REWE", "Globus"))
    for _ in range(100):
        if jobs.get(job_id)["status"] == "completed":
            break
        time.sleep(0.01)
    assert engine.seen == ("REWE", "Globus")
