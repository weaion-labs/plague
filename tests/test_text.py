from plague.text import html_to_text, html_to_title


def test_html_to_text_strips_scripts_and_styles():
    html = """
    <html><head><title>Hello</title><style>.x{color:red}</style></head>
    <body><script>alert('no')</script><h1>Title</h1><p>Body text</p></body></html>
    """
    text = html_to_text(html)
    assert "Title" in text
    assert "Body text" in text
    assert "alert" not in text
    assert "color:red" not in text


def test_html_to_text_collapses_whitespace():
    html = "<div>one</div><div>two</div><p>three   four</p>"
    text = html_to_text(html)
    assert "one" in text
    assert "two" in text
    assert "three four" in text
    assert "three   four" not in text


def test_title_extraction():
    assert html_to_title("<html><head><title> A  B </title></head></html>") == "A B"
    assert html_to_title("<html></html>") == ""
