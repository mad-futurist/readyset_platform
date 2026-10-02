from app.knowledge.lexical import significant_query


def test_literals_quotes_and_no_query_expansion() -> None:
    assert significant_query('How does "least privilege" complement monitoring?') == (
        '"How" OR "does" OR "least privilege" OR "complement" OR "monitoring"')
    assert significant_query('S3 NOT foo -bar OR baz') == '"S3" OR "NOT" OR "foo" OR "bar" OR "OR" OR "baz"'
    assert significant_query('π 東京 π') == '"π" OR "東京"'
    assert significant_query('---') == ''


def test_query_alternatives_are_bounded_and_deterministic() -> None:
    query = ' '.join(f'term{i}' for i in range(100))
    assert significant_query(query) == significant_query(query)
    assert len(significant_query(query).split(' OR ')) == 64
