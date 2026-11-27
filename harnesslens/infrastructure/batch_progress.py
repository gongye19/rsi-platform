"""Small persisted batch counters shared by native and business runners."""
from contextlib import contextmanager
from pathlib import Path
import threading
import time
from harnesslens.core.artifacts import write_json


class BatchProgress:
    def __init__(self, output, scope, version, task_repeats):
        self.path = Path(output) / 'progress.json'
        self.lock = threading.Lock()
        self.value = dict(scope=scope, version=version, task_count=len(task_repeats),
                          total=sum(task_repeats.values()), completed=0, failed=0,
                          active=[], started_at=time.time(), updated_at=time.time())
        self._save()

    def _save(self):
        self.value['updated_at'] = time.time()
        write_json(self.path, self.value)

    @contextmanager
    def trial(self, task_id, trial):
        item = dict(task_id=task_id, trial=trial, started_at=time.time())
        with self.lock:
            self.value['active'].append(item)
            self._save()
        try:
            yield
        except BaseException:
            with self.lock:
                self.value['failed'] += 1
            raise
        else:
            with self.lock:
                self.value['completed'] += 1
        finally:
            with self.lock:
                self.value['active'].remove(item)
                self._save()
