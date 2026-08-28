"""Caption authorship and atomic metadata contract tests."""

from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("text", [None, "", "   "])
def test_blank_caption_clears_origin_and_provenance(text):
    from app.services.caption_origin import set_caption

    row = SimpleNamespace(
        caption="old",
        caption_origin="joycaption",
        caption_provenance='{"provider":"joycaption"}',
    )

    set_caption(
        row,
        text,
        origin="asserted",
        provenance='{"should":"clear"}',
    )

    assert row.caption == text
    assert row.caption_origin is None
    assert row.caption_provenance is None


def test_human_caption_is_asserted_and_clears_machine_provenance():
    from app.services.caption_origin import ASSERTED, set_human_caption

    row = SimpleNamespace(
        caption="old",
        caption_origin="joycaption",
        caption_provenance='{"provider":"joycaption"}',
    )

    set_human_caption(row, "Words chosen by the user")

    assert (row.caption, row.caption_origin, row.caption_provenance) == (
        "Words chosen by the user",
        ASSERTED,
        None,
    )


@pytest.mark.parametrize(
    ("engine", "expected"),
    [
        ("joycaption", "joycaption"),
        (" JOYCAPTION ", "joycaption"),
        ("ollama", "ollama"),
        ("auto", None),
        ("future-engine", None),
        (None, None),
    ],
)
def test_model_caption_records_only_the_engine_that_actually_wrote_it(engine, expected):
    from app.services.caption_origin import set_model_caption

    row = SimpleNamespace(caption=None, caption_origin=None, caption_provenance=None)
    set_model_caption(row, "Generated words", engine=engine)

    assert row.caption_origin == expected


def test_model_caption_replaces_the_complete_tuple_without_stale_provenance():
    from app.services.caption_origin import set_model_caption

    row = SimpleNamespace(
        caption="Joy words",
        caption_origin="joycaption",
        caption_provenance='{"provider":"joycaption","seed":7}',
    )

    set_model_caption(
        row,
        "Ollama words",
        engine="ollama",
        provenance='{"provider":"joycaption","seed":7}',
    )

    assert (row.caption, row.caption_origin, row.caption_provenance) == (
        "Ollama words",
        "ollama",
        None,
    )


def test_explicit_model_provenance_is_written_atomically():
    from app.services.caption_origin import set_model_caption

    row = SimpleNamespace(caption=None, caption_origin=None, caption_provenance=None)
    provenance = '{"provider":"joycaption","revision":"abc","seed":7}'

    set_model_caption(
        row,
        "Generated words",
        engine="joycaption",
        provenance=provenance,
    )

    assert (row.caption, row.caption_origin, row.caption_provenance) == (
        "Generated words",
        "joycaption",
        provenance,
    )


def test_unknown_engine_cannot_retain_provenance():
    from app.services.caption_origin import set_model_caption

    row = SimpleNamespace(
        caption="old",
        caption_origin="joycaption",
        caption_provenance='{"provider":"joycaption"}',
    )

    set_model_caption(
        row,
        "Unattributed model words",
        engine="auto",
        provenance='{"provider":"joycaption"}',
    )

    assert row.caption_origin is None
    assert row.caption_provenance is None


def test_unprotected_clause_includes_blank_machine_and_unknown_rows(app):
    from app.extensions import db
    from app.models import FaceDataset, FaceDatasetImage
    from app.services.caption_origin import unprotected_clause

    with app.app_context():
        dataset = FaceDataset(user_id="local", name="Origins", trigger_word="person")
        db.session.add(dataset)
        db.session.flush()
        rows = [
            FaceDatasetImage(dataset_id=dataset.id, caption=None, caption_origin=None),
            FaceDatasetImage(dataset_id=dataset.id, caption="", caption_origin="asserted"),
            FaceDatasetImage(dataset_id=dataset.id, caption="   ", caption_origin="asserted"),
            FaceDatasetImage(dataset_id=dataset.id, caption="Machine", caption_origin="joycaption"),
            FaceDatasetImage(dataset_id=dataset.id, caption="Legacy", caption_origin=None),
            FaceDatasetImage(dataset_id=dataset.id, caption="Human", caption_origin="asserted"),
        ]
        db.session.add_all(rows)
        db.session.commit()

        selected = FaceDatasetImage.query.filter(
            unprotected_clause(FaceDatasetImage)
        ).order_by(FaceDatasetImage.id).all()

        assert [row.caption for row in selected] == [None, "", "   ", "Machine", "Legacy"]
