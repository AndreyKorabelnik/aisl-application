from pathlib import Path
from aisl_sql_restore import PublicSqlRestorer, ReconstructionError

class FakeResponse:
    status_code=200
    text=''
    def json(self):return {}

class FakeClient:
    def get(self,*args,**kwargs):return FakeResponse()

def test_revision_must_be_pinned():
    try:
        PublicSqlRestorer(FakeClient(),system_id='example',revision_id='active',repo_id='repo')
    except ValueError as exc:
        assert 'immutable' in str(exc)
    else:
        assert False,'Expected fail closed on unpinned revision'

def test_generated_relation_no_expr_fails_closed():
    s=PublicSqlRestorer(FakeClient(),system_id='example',revision_id='rev-123',repo_id='repo')
    try:
        s._render_relation('q',{'relation_kind':'generated','relation_name':'uid'})
    except ReconstructionError as exc:
        assert 'lacks generator expression' in str(exc)
    else:
        assert False,'Should not infer missing LATERAL VIEW EXPLODE'

def test_public_metadata_filename_not_source_content(tmp_path:Path):
    s=PublicSqlRestorer(FakeClient(),system_id='example',revision_id='rev-123',repo_id='repo')
    s.discover_queries=lambda:{'sql/targets/selected.sql':'q1'}
    s.render_query=lambda query_id: 'SELECT 1 AS attr\n'
    report=s.restore_all(tmp_path)
    assert report['restored_count']==1
    assert (tmp_path/'selected.sql').read_text()=='SELECT 1 AS attr\n'
    assert not (tmp_path/'unknown.sql').exists()

def test_failed_restoration_does_not_leave_old_sql(tmp_path:Path):
    s=PublicSqlRestorer(FakeClient(),system_id='example',revision_id='rev-123',repo_id='repo')
    s.discover_queries=lambda:{'sql/targets/unsafe.sql':'q1'}
    s.render_query=lambda q:(_ for _ in ()).throw(ReconstructionError('missing public fact'))
    (tmp_path/'unsafe.sql').write_text('OLD SQL')
    report=s.restore_all(tmp_path)
    assert report['unresolved_count']==1
    assert not (tmp_path/'unsafe.sql').exists()
