import pytest


@pytest.fixture
def model_tables(monkeypatch):
    monkeypatch.setenv('TEST_EXECUTION_KEY', 'execution-test-only')
    monkeypatch.setenv('TEST_ANALYSIS_KEY', 'analysis-test-only')
    return '''
[models.execution]
model="test/execution"
api="chat_completions"
base_url="http://127.0.0.1:19001/v1"
api_key_env="TEST_EXECUTION_KEY"
[models.analysis]
model="test/analysis"
api="responses"
base_url="http://127.0.0.1:19002/v1"
api_key_env="TEST_ANALYSIS_KEY"
'''
