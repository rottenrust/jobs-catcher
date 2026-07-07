from pathlib import Path
import pytest
from jobs_catcher import sources
FIX=Path(__file__).parent/'fixtures'/'sources'
@pytest.mark.parametrize('source', sources.SOURCES)
def test_saved_source_search_detail_and_blocked_fixtures(source):
    search=(FIX/f'{source}_search.html').read_text(encoding='utf-8')
    rows=sources.parse_search(source, search)
    expected=(FIX/f'{source}_expected.txt').read_text(encoding='utf-8').splitlines()
    assert rows[0]['external_id']==expected[0]
    assert rows[0]['url']==__import__('jobs_catcher.sources', fromlist=['normalize_url']).normalize_url(expected[1])
    detail=(FIX/f'{source}_detail.html').read_text(encoding='utf-8')
    parsed=sources.parse_detail(source, detail)
    assert parsed['title']
    assert parsed['company']==f'ACME {source}'
    with pytest.raises(sources.BlockedSourceError):
        sources.parse_search(source, (FIX/f'{source}_blocked.html').read_text(encoding='utf-8'))
