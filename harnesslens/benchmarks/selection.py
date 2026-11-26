"""Freeze domain/count subsets at the benchmark boundary, never in the optimizer."""
from __future__ import annotations
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

ENV = 'HAI_BENCHMARK_SELECTION'
SCHEMA = 'rsi.benchmark-selection.v1'
ROOT = Path(__file__).resolve().parents[2]


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def normalize_dataset(raw):
    if not isinstance(raw,dict) or set(raw)-{'domain','train_count','test_count','frozen'}:
        raise ValueError('Unknown dataset settings')
    result={'domain':raw.get('domain','all'),'train_count':raw.get('train_count',0),'test_count':raw.get('test_count',0)}
    if not isinstance(result['domain'],str) or not result['domain']:
        raise ValueError('Dataset domain must be a nonempty string')
    for key in ('train_count','test_count'):
        if type(result[key]) is not int or result[key]<0:
            raise ValueError(f'{key} must be a non-negative integer (0 means all available)')
    return result


def base_and_groups(benchmark, repo_root=ROOT):
    from .benchmark_splits import load_benchmark_split
    from .jsonl_adapter import resolve_external
    root=Path(repo_root)
    split=load_benchmark_split(benchmark,apply_selection=False)
    external=resolve_external(root,benchmark)
    mapping={};kind='benchmark';evidence={}
    if split.cell=='fdabench':
        path=root/'configs/fdabench-task-groups.json'
        raw=json.loads(path.read_text());assets=json.loads((root/'configs/fdabench-assets.json').read_text())
        if raw.get('schema')!='rsi.benchmark-task-groups.v1' or raw.get('source_public_tasks_sha256')!=assets['public_tasks_canonical_sha256']:
            raise ValueError('FDABench task grouping does not match pinned public inputs')
        mapping=raw['task_domains'];kind='database';evidence={'grouping':digest(raw)}
        if set(mapping)!=set(split.train+split.test):raise ValueError('FDABench grouping must cover the frozen scored split')
    elif external and external.spec.get('domain_field'):
        field=external.spec['domain_field'];kind='domain'
        for task_id,row in external._tasks().items():
            if task_id not in set(split.train+split.test):continue
            value=row.get(field)
            if not isinstance(value,str) or not value.strip():raise ValueError('Every task needs a public domain value')
            mapping[task_id]=value
        evidence={'descriptor':digest(external.spec),'domains':digest(mapping)}
    else:
        mapping={task:split.cell for task in split.train+split.test}
    return split,mapping,kind,evidence


def dataset_options(benchmark, repo_root=ROOT):
    split,mapping,kind,_=base_and_groups(benchmark,repo_root)
    domains=[{'id':'all','label':'All task groups','train_available':len(split.train),'test_available':len(split.test)}]
    for domain in (sorted(set(mapping.values())) if kind!='benchmark' else []):
        domains.append({'id':'group:'+domain,'label':domain.replace('_',' ').capitalize(),
                        'train_available':sum(mapping[t]==domain for t in split.train),
                        'test_available':sum(mapping[t]==domain for t in split.test)})
    return {'benchmark':split.benchmark,'cell':split.cell,'grouping':kind,'domains':domains,
            'minimum_train_count':5,'train_available':len(split.train),'test_available':len(split.test),
            'selection_method':'Fixed seed 42; sampled separately inside the original TRAIN and TEST pools.'}


def resolve_dataset(benchmark, raw, *, repo_root=ROOT, mode=None, full_evaluation=False):
    settings=normalize_dataset(raw)
    split,mapping,kind,evidence=base_and_groups(benchmark,repo_root)
    domain=settings['domain']
    if domain!='all' and (not domain.startswith('group:') or domain[6:] not in mapping.values()):
        raise ValueError('Unknown dataset domain')
    train=tuple(t for t in split.train if domain=='all' or mapping[t]==domain[6:])
    test=tuple(t for t in split.test if domain=='all' or mapping[t]==domain[6:])
    source=digest({'benchmark':split.benchmark,'cell':split.cell,'train':split.train,'test':split.test,'domains':mapping,'evidence':evidence})
    def select(pool, scope, requested):
        count=requested or len(pool)
        if count>len(pool):raise ValueError(f'{scope} count {count} exceeds the {len(pool)} available tasks in this domain')
        if count==len(pool):return list(pool)
        return sorted(pool,key=lambda task:digest([42,split.cell,scope,task]))[:count]
    chosen_train=select(train,'TRAIN',settings['train_count']);chosen_test=select(test,'TEST',settings['test_count'])
    if mode=='train' and len(chosen_train)<5:
        raise ValueError('Evolution requires at least 5 TRAIN tasks in the selected domain')
    if ((mode=='train' and full_evaluation) or mode in {'test_baseline','test_candidate'}) and not chosen_test:
        raise ValueError('The selected domain has no TEST tasks; choose another domain or disable final TEST evaluation')
    result={'schema':SCHEMA,'benchmark':split.benchmark,'cell':split.cell,'domain':domain,'grouping':kind,
            'train':chosen_train,'test':chosen_test,'train_available':len(train),'test_available':len(test),'seed':42,'source_fingerprint':source}
    if 'frozen' in raw and raw['frozen']!=result:
        raise ValueError('Frozen dataset selection changed; create a new experiment')
    return result


def selected_split(split):
    value=os.environ.get(ENV)
    if not value:return split
    selection=json.loads(value)
    if selection.get('schema')!=SCHEMA or selection.get('cell')!=split.cell:
        raise ValueError('Dataset selection belongs to a different benchmark')
    train=selection.get('train');test=selection.get('test')
    for chosen,pool in ((train,split.train),(test,split.test)):
        if not isinstance(chosen,list) or any(not isinstance(t,str) for t in chosen) or len(chosen)!=len(set(chosen)) or set(chosen)-set(pool):
            raise ValueError('Dataset selection is outside the original split')
    if set(train)&set(test):raise ValueError('TRAIN and TEST selection overlap')
    return replace(split,train=tuple(train),test=tuple(test))


def configure_selection(benchmark, *, run_root=None, raw=None, mode='train', full_evaluation=False):
    """CLI/service receipt shared by TRAIN and frozen TEST child processes."""
    if raw is not None:
        chosen=resolve_dataset(benchmark,raw,mode=mode,full_evaluation=full_evaluation)
    elif os.environ.get(ENV):
        saved=json.loads(os.environ[ENV])
        chosen=resolve_dataset(benchmark,{'domain':saved.get('domain','all'),
            'train_count':len(saved.get('train',[])),'test_count':len(saved.get('test',[])),
            'frozen':saved},mode=mode,full_evaluation=full_evaluation)
    else:
        return None
    os.environ[ENV]=json.dumps(chosen,sort_keys=True)
    if run_root is not None:
        from harnesslens.core.artifacts import write_json
        path=Path(run_root)/'dataset_selection.json'
        if path.exists() and json.loads(path.read_text())!=chosen:
            raise ValueError('Dataset selection changed; create a new experiment')
        write_json(path,chosen)
    return chosen
