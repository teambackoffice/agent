from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from peewee import SqliteDatabase

from agent.job import Job, JobModel, StepModel, argument_names

SECRET = "s3cr3t-redis-password-value"


class FakeBench:
    def update_config_job(self, common_site_config, bench_config):
        pass

    def new_site(self, name, config, admin_password, *extra, **options):
        pass


class TestJobRecord(unittest.TestCase):
    def setUp(self):
        self.database = SqliteDatabase(":memory:")
        self.models = [JobModel, StepModel]
        self.database.bind(self.models)
        self.database.connect()
        self.database.create_tables(self.models)

    def tearDown(self):
        self.database.drop_tables(self.models)
        self.database.close()

    def test_enqueue_stores_argument_names_not_values(self):
        bench = FakeBench()
        config = {"redis_cache": f"redis://:{SECRET}@localhost:13000"}
        job = Job()
        job.enqueue("Update Bench Configuration", bench.update_config_job, (config, {"x": 1}), {}, "1")

        stored = JobModel.get(JobModel.id == job.model.id)
        self.assertNotIn(SECRET, stored.data)
        self.assertEqual(
            json.loads(stored.data),
            {"function": "update_config_job", "args": ["common_site_config", "bench_config"], "kwargs": []},
        )
        self.assertEqual(stored.status, "Pending")

    def test_extra_positional_and_keyword_arguments(self):
        bench = FakeBench()
        names = argument_names(
            bench.new_site, ("site", {}, SECRET, "a", "b"), {"mariadb_root_password": SECRET, "b": 1}
        )
        self.assertEqual(names["args"], ["name", "config", "admin_password", "arg3", "arg4"])
        self.assertEqual(names["kwargs"], ["b", "mariadb_root_password"])
        self.assertNotIn(SECRET, json.dumps(names))

    def test_success_still_writes_the_result(self):
        bench = FakeBench()
        job = Job()
        job.enqueue("Update Bench Configuration", bench.update_config_job, ({}, {}), {}, "1")
        job.start()
        job.success({"output": "done", "result": [1, 2]})

        stored = JobModel.get(JobModel.id == job.model.id)
        self.assertEqual(stored.status, "Success")
        self.assertEqual(json.loads(stored.data), {"output": "done", "result": [1, 2]})

    def test_stop_drops_the_call_and_its_description(self):
        bench = FakeBench()
        job = Job()
        job.enqueue("New Site", bench.new_site, ("site", {}, SECRET), {}, "1")
        job.start()
        job.redis = MagicMock()
        job.job = MagicMock()
        job.job.get_id.return_value = str(job.model.id)
        job.job.to_dict.return_value = {
            "status": "stopped",
            "description": f"new_site('site', {{}}, '{SECRET}')",
            "data": f"pickled {SECRET}",
            "origin": "high",
        }
        with patch("agent.job.send_stop_job_command"):
            job.stop()

        stored = JobModel.get(JobModel.id == job.model.id)
        self.assertNotIn(SECRET, stored.data)
        self.assertEqual(json.loads(stored.data), {"status": "stopped", "origin": "high"})
        self.assertEqual(stored.status, "Failure")


if __name__ == "__main__":
    unittest.main()
