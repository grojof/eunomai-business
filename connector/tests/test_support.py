"""What IT receives when the connector stops: the e-mail link is a mailto as RFC 6068 says, like a project request's."""

from urllib.parse import parse_qs, urlsplit

from eunomai_business import support


def test_one_function_builds_every_mail_link():
    link = support.mail_link("it@example.test", "a & b?", "one\ntwo #3 = 100%")
    parts = urlsplit(link)
    assert parts.scheme == "mailto" and parts.path == "it@example.test" and not parts.fragment
    fields = parse_qs(parts.query, strict_parsing=True)
    assert fields == {"subject": ["a & b?"], "body": ["one\r\ntwo #3 = 100%"]}


def test_a_stop_report_uses_crlf_line_breaks(monkeypatch):
    monkeypatch.setenv("EUNOMAI_SUPPORT_EMAIL", "it@example.test")
    answer = support.report(support.NeedsIT("Stopped.", "something & more", {"Workspace": "w", "Detail": "a b"}))
    link = answer["email_link"]
    assert "%0D%0A" in link and "%0A" not in link.replace("%0D%0A", "")
    fields = parse_qs(urlsplit(link).query, strict_parsing=True)
    assert set(fields) == {"subject", "body"} and fields["subject"] == ["eunomai-business: something & more"]
    assert fields["body"] == [answer["it_report"].replace("\n", "\r\n")]
