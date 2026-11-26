"""Frozen subsets must govern both TRAIN and TEST without admitting held-out data."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from harnesslens.benchmarks.selection import ENV,configure_selection,dataset_options,resolve_dataset
from harnesslens.benchmarks.benchmark_splits import load_benchmark_split
from harnesslens.benchmarks.cell_config import benchmark_config
from harnesslens.service.config import load_profile,invocation
from harnesslens.service.settings import snapshot_profile,profile_preview

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(autouse=True)
def isolate_selection(monkeypatch):
    monkeypatch.setenv(ENV,'')
    monkeypatch.setenv('HAI_BENCHMARK_CONFIG','')


def test_fdabench_groups_are_database_pools_not_a_new_split():
    options=dataset_options('fdabench')
    assert options['grouping']=='database' and (options['train_available'],options['test_available'])==(70,35)
    bank=next(d for d in options['domains'] if d['id']=='group:bank_sales_trading')
    assert (bank['train_available'],bank['test_available'])==(19,7)
    assert len(options['domains'])==16  # all + 15 scored database groups
    assert all('query' not in d and 'answer' not in d for d in options['domains'])


def test_selection_is_repeatable_and_never_moves_test_into_train(monkeypatch):
    raw={'domain':'group:bank_sales_trading','train_count':10,'test_count':5}
    chosen=resolve_dataset('fdabench',raw,mode='train',full_evaluation=True)
    assert chosen==resolve_dataset('fdabench',raw)
    base=load_benchmark_split('fdabench',apply_selection=False)
    assert len(chosen['train'])==10 and len(chosen['test'])==5
    assert set(chosen['train'])<=set(base.train) and set(chosen['test'])<=set(base.test)
    assert not set(chosen['train'])&set(chosen['test'])
    monkeypatch.setenv(ENV,json.dumps(chosen))
    assert load_benchmark_split('fdabench').train==tuple(chosen['train'])
    assert load_benchmark_split('fdabench').test==tuple(chosen['test'])
    assert benchmark_config(ROOT,'fdabench').train_task_ids==tuple(chosen['train'])
    assert load_benchmark_split('fdabench',apply_selection=False)==base
    from harnesslens.benchmarks.adapters import benchmark_adapter
    assert benchmark_adapter(ROOT,'fdabench').split().test==tuple(chosen['test'])


@pytest.mark.parametrize('raw',[
    {'train_count':True},{'train_count':-1},{'test_count':1.5},{'train_count':71},{'test_count':36},
    {'domain':'group:made-up'},
    {'domain':'group:bank_sales_trading','train_count':20},
    {'domain':'group:bank_sales_trading','test_count':8},
    {'domain':'group:genes','train_count':4},
])
def test_invalid_or_insufficient_selections_fail_before_a_model_call(raw):
    with pytest.raises(ValueError):resolve_dataset('fdabench',raw,mode='train',full_evaluation=True)


def test_defaults_preserve_original_full_split():
    chosen=resolve_dataset('fdabench',{})
    split=load_benchmark_split('fdabench',apply_selection=False)
    assert chosen['train']==list(split.train) and chosen['test']==list(split.test)


def test_frozen_ids_cannot_be_changed_or_leaked_from_test(monkeypatch,tmp_path):
    chosen=configure_selection('fdabench',run_root=tmp_path,raw={'train_count':12,'test_count':8})
    assert json.loads((tmp_path/'dataset_selection.json').read_text())==chosen
    with pytest.raises(ValueError,match='changed'):
        configure_selection('fdabench',run_root=tmp_path,raw={'train_count':13,'test_count':8})
    modified={**chosen,'train':[chosen['test'][0],*chosen['train'][1:]]}
    monkeypatch.setenv(ENV,json.dumps(modified))
    with pytest.raises(ValueError,match='original split'):load_benchmark_split('fdabench')
    with pytest.raises(ValueError,match='Frozen'):configure_selection('fdabench',run_root=tmp_path)


def test_job_profile_freezes_both_scopes_and_rejects_edits(tmp_path,model_tables,monkeypatch):
    source=tmp_path/'runtime.toml';source.write_text('schema="harnesslens.experiment.v1"\nbenchmark="fdabench"\n'+model_tables)
    path=snapshot_profile(source,{'dataset':{'domain':'group:bank_sales_trading','train_count':10,'test_count':5},'full_evaluation':True},tmp_path/'job',tmp_path)
    profile=load_profile(path);preview=profile_preview(path,tmp_path)
    assert preview['dataset']['train_count']==10
    assert '[dataset.frozen]' in path.read_text() and 'test-only' not in path.read_text()
    argv,env=invocation(profile,'selected')
    assert 'harnesslens.service.experiment' in argv
    selected=json.loads(env[ENV]);assert (len(selected['train']),len(selected['test']))==(10,5)
    monkeypatch.setenv(ENV,env[ENV])
    configure_selection('fdabench',run_root=tmp_path/'train')
    configure_selection('fdabench',mode='test_baseline',run_root=tmp_path/'test')
    assert json.loads((tmp_path/'train/dataset_selection.json').read_text())==json.loads((tmp_path/'test/dataset_selection.json').read_text())
    path.write_text(path.read_text().replace('train_count = 10','train_count = 11'))
    with pytest.raises(ValueError,match='Frozen'):load_profile(path)


def test_jsonl_can_declare_a_public_domain_field(tmp_path,monkeypatch):
    monkeypatch.delenv(ENV,raising=False)
    from harnesslens.benchmarks.jsonl_adapter import JsonlAdapter
    tasks=[{'id':str(i),'question':'q','answer':'private','domain':'finance' if i<8 else 'sales'} for i in range(12)]
    path=tmp_path/'tasks.jsonl';path.write_text(''.join(json.dumps(t)+'\n' for t in tasks))
    descriptor=tmp_path/'benchmark.toml';descriptor.write_text('schema="harnesslens.business-benchmark.v1"\nid="domain_selection_fixture"\ntasks="tasks.jsonl"\ntrain=["0","1","2","3","4","8","9"]\ntest=["5","6","7","10","11"]\npublic_fields=["question","domain"]\ndomain_field="domain"\n')
    adapter=JsonlAdapter(ROOT,descriptor)
    chosen=resolve_dataset(str(descriptor),{'domain':'group:finance','train_count':5,'test_count':2},mode='train')
    monkeypatch.setenv(ENV,json.dumps(chosen))
    assert len(adapter.split().train)==5 and len(adapter.split().test)==2
    assert 'private' not in json.dumps(dataset_options(str(descriptor)))
    descriptor.write_text(descriptor.read_text().replace('domain_field="domain"','domain_field="answer"'))
    with pytest.raises(ValueError,match='public'):JsonlAdapter(ROOT,descriptor)


def test_cli_dry_run_honors_selected_test_count_without_provider_or_data(tmp_path):
    result=subprocess.run([sys.executable,str(ROOT/'run_test_baseline.py'),'--benchmark','fdabench','--run-id','subset-dry','--domain','group:bank_sales_trading','--train-count','10','--test-count','5','--dry-run'],cwd=ROOT,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    output=json.loads(result.stdout)
    assert output['test_task_count']==5 and len(output['selected_test_task_ids'])==5
    assert not (ROOT/'runs/test_baselines/subset-dry/dataset_selection.json').exists()
