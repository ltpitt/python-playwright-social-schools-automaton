from socialschools.digest.render import ABRIDGED_NOTE, render_digest_notification
from socialschools.models import Digest, Topic


def test_an_abridged_brief_says_so():
    """A newsletter digest drops most of the message; a parent must be told that

    Without this line there is no way to tell "nothing else happened" from
    "forty items did not fit".
    """
    data = Digest(translated_title="Newsletter", tldr="Sports day on 18 May.", topics=[])

    assert ABRIDGED_NOTE in render_digest_notification(data, abridged=True)
    assert ABRIDGED_NOTE not in render_digest_notification(data)


def test_the_abridged_note_sits_before_the_footer():
    """It explains the brief, so it belongs with the brief, not after the sign-off"""
    data = Digest(translated_title="Newsletter", tldr="Sports day on 18 May.", topics=[])

    rendered = render_digest_notification(data, abridged=True, original_title="Nieuwsbrief")
    assert rendered.index(ABRIDGED_NOTE) < rendered.index("Nieuwsbrief")


def test_render_digest_notification_with_items():
    """A topic renders as a heading, its actions, a single bring line, then its notes"""
    data = Digest(
        translated_title="School Event",
        tldr="Summary of event.",
        topics=[Topic(
            heading="School trip",
            actions=["15 Aug - be at school by 08:20"],
            bring=["gym shoes", "towel"],
            notes=["16 Jul - studiedag, no school"],
        )],
    )
    result = render_digest_notification(data)
    assert result == (
        "Summary of event.\n\n"
        "\u2501 School trip\n"
        "\u25b8 15 Aug - be at school by 08:20\n"
        "\U0001F392 Bring: gym shoes, towel\n"
        "\u00b7 16 Jul - studiedag, no school"
    )


def test_render_digest_notification_separates_topics():
    """Distinct subjects stay visually separated instead of merging into one list"""
    data = Digest(
        translated_title="Class Letter",
        tldr="Two subjects.",
        topics=[
            Topic(heading="School supplies", actions=[], bring=["blue pen"], notes=[]),
            Topic(heading="Tests", actions=[], bring=[], notes=["07 Sep - topography"]),
        ],
    )
    result = render_digest_notification(data)
    assert "\u2501 School supplies\n\U0001F392 Bring: blue pen" in result
    assert "\u2501 Tests\n\u00b7 07 Sep - topography" in result
    assert result.count("\u2501") == 2


def test_render_digest_notification_lifts_a_shared_date_into_the_heading():
    """One day repeated down every line is noise; state it once, above them"""
    data = Digest(
        translated_title="Class Letter",
        tldr="One day out.",
        topics=[Topic(
            heading="School trip",
            actions=["01 Sep - be at school by 08:20", "01 Sep - inform after-school care"],
            bring=["towel"],
            notes=["01 Sep - the bus returns around 14:30"],
        )],
    )

    result = render_digest_notification(data)

    assert "\u2501 01 Sep \u00b7 School trip" in result
    assert "\u25b8 be at school by 08:20" in result
    assert "\u00b7 the bus returns around 14:30" in result
    assert result.count("01 Sep") == 1


def test_render_digest_notification_keeps_dates_when_a_topic_spans_days():
    """Lifting a date only works when there is one; differing dates stay per entry"""
    data = Digest(
        translated_title="Class Letter",
        tldr="Two days.",
        topics=[Topic(
            heading="Tests",
            actions=[],
            bring=[],
            notes=["07 Sep - topography test", "11 Sep - English test"],
        )],
    )

    result = render_digest_notification(data)

    assert "\u2501 Tests" in result
    assert "\u00b7 07 Sep - topography test" in result
    assert "\u00b7 11 Sep - English test" in result


def test_render_digest_notification_tldr_fallback():
    """Test rendering emits 'No action needed' when no topic carries an action or bring item"""
    data = Digest(
        translated_title="School Info",
        tldr="The school will be closed for renovation.",
        topics=[],
    )
    result = render_digest_notification(data)
    assert result == "The school will be closed for renovation.\n\nNo action needed"


def test_render_digest_notification_notes_only_needs_no_action():
    """An informational post with only notes still tells the parent there is nothing to do"""
    data = Digest(
        translated_title="Newsletter",
        tldr="This week's newsletter.",
        topics=[Topic(heading="", actions=[], bring=[], notes=["16 Jul - studiedag"])],
    )
    result = render_digest_notification(data)
    assert "No action needed" in result
    assert "\u00b7 16 Jul - studiedag" in result


def test_render_digest_notification_with_attachments():
    """Test rendering shows no filename lines for successful attachments"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[Topic(heading="", actions=["15 Aug - sign form"], bring=[], notes=[])],
    )
    result = render_digest_notification(data)
    assert result == "\u25b8 15 Aug - sign form"


def test_render_digest_notification_with_failed_attachments():
    """Test that failed attachments appear as a generic warning without filename or URL"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[Topic(heading="", actions=["15 Aug - sign form"], bring=[], notes=[])],
    )
    result = render_digest_notification(
        data,
        failed_attachments=["broken.pdf"],
    )
    assert "\u26a0" in result
    assert "broken.pdf" not in result
    assert "socialschools" not in result


def test_render_digest_notification_with_original_title_and_date():
    """Test that the post date/time is shown prominently at the top, and the footer has no date"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[Topic(heading="", actions=["15 Aug - sign form"], bring=[], notes=[])],
    )
    result = render_digest_notification(data, original_title="Formulier reis", post_date="1 Jul 10:00")
    assert result == (
        "\U0001F4C5 1 Jul 10:00\n\n"
        "\u25b8 15 Aug - sign form\n\n"
        "To find this post in Social Schools, look for: \"Formulier reis\""
    )


def test_render_digest_notification_with_original_title_no_date():
    """Test that no date line is rendered when no post date is available"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[],
    )
    result = render_digest_notification(data, original_title="Formulier reis")
    assert result == (
        "No action needed\n\n"
        "To find this post in Social Schools, look for: \"Formulier reis\""
    )


def test_render_digest_notification_with_date_no_original_title():
    """Test that the date line still renders even when there is no footer"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[Topic(heading="", actions=["15 Aug - sign form"], bring=[], notes=[])],
    )
    result = render_digest_notification(data, post_date="23 Jun 15:00")
    assert result == "\U0001F4C5 23 Jun 15:00\n\n\u25b8 15 Aug - sign form"


def test_render_digest_notification_without_original_title_omits_footer():
    """Test that no footer is rendered when original_title is not provided"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[Topic(heading="", actions=["15 Aug - sign form"], bring=[], notes=[])],
    )
    result = render_digest_notification(data)
    assert "To find this post" not in result
