from app.services import suggested_questions as sq


def test_parse_questions_plain_json():
    result = sq._parse_questions('["What is X?", "How does Y work?"]')
    assert result == ["What is X?", "How does Y work?"]


def test_parse_questions_fenced_json():
    raw = '```json\n["What is model risk?", "How does validation work?"]\n```'
    result = sq._parse_questions(raw)
    assert "What is model risk?" in result
    assert "How does validation work?" in result


def test_parse_questions_malformed_json():
    assert sq._parse_questions("not json") == []


def test_parse_questions_strips_page_refs():
    result = sq._parse_questions('["Which sectors are listed under \'Sector\' on page 1?"]')
    assert result, "expected at least one question"
    assert not any("page" in q.lower() and any(c.isdigit() for c in q) for q in result)


def test_parse_questions_deduplicates():
    raw = '["What is model risk?", "What is model risk?", "What does section B.1 say about roles?"]'
    result = sq._parse_questions(raw)
    assert result.count("What is model risk?") == 1
    assert any("B.1" in q for q in result)


def test_parse_questions_caps_at_five():
    raw = '["Q1?", "Q2?", "Q3?", "Q4?", "Q5?", "Q6?", "Q7?"]'
    result = sq._parse_questions(raw)
    assert len(result) <= 5
