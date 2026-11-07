"""Testes dos comentários e menções do Instagram e do campo feed da Página."""

from typing import Any

import pytest

from apps.core.models import Channel, ChannelIdentity, Contact, Event
from apps.webhooks.models import DeliveryStatus, WebhookDelivery

IG_ID = "17840000000000001"
IGSID = "2860000000000001"
PAGE_ID = "111"
PSID = "3970000000000001"
TIME = 1_794_047_906_777


def _ig_change(field: str, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "instagram",
        "entry": [{"id": IG_ID, "time": TIME, "changes": [{"field": field, "value": value}]}],
    }


def _ig_comment(
    comment_id: str = "17865799348089039",
    *,
    from_id: str = IGSID,
    text: str = "Quero saber o preço",
) -> dict[str, Any]:
    return _ig_change(
        "comments",
        {
            "from": {"id": from_id, "username": "ana.souza", "self_ig_scoped_id": from_id},
            "media": {"id": "1800000000000001", "media_product_type": "FEED"},
            "id": comment_id,
            "parent_id": "",
            "text": text,
        },
    )


def _feed(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "page",
        "entry": [
            {"id": PAGE_ID, "time": 1794008719, "changes": [{"field": "feed", "value": value}]}
        ],
    }


def _fb_comment(*, verb: str = "add", from_id: str = "5550000000000001") -> dict[str, Any]:
    return _feed(
        {
            "from": {"id": from_id, "name": "Bia Lima"},
            "post_id": f"{PAGE_ID}_222",
            "comment_id": f"{PAGE_ID}_222_333",
            "parent_id": f"{PAGE_ID}_222",
            "message": "Como funciona?",
            "item": "comment",
            "verb": verb,
            "created_time": 1794008719,
        }
    )


@pytest.mark.django_db
def test_instagram_comment_creates_event_and_contact_with_handle(meta_post: Any) -> None:
    meta_post(_ig_comment())

    assert WebhookDelivery.objects.get().status == DeliveryStatus.PROCESSED
    event = Event.objects.get(event_type="instagram.comment_received")
    assert event.external_id == "17865799348089039"
    assert event.summary == "@ana.souza: Quero saber o preço"
    assert event.data["media_id"] == "1800000000000001"
    contact = event.contact
    assert contact.instagram_handle == "ana.souza"
    assert contact.source == "instagram_comment"
    identity = ChannelIdentity.objects.get()
    assert (identity.account_id, identity.external_id, identity.handle) == (
        IG_ID,
        IGSID,
        "ana.souza",
    )


@pytest.mark.django_db
def test_instagram_comment_and_dm_from_same_person_share_contact(meta_post: Any) -> None:
    dm = {
        "sender": {"id": IGSID},
        "recipient": {"id": IG_ID},
        "timestamp": TIME,
        "message": {"mid": "aWdfZAG1", "text": "Oi"},
    }
    meta_post({"object": "instagram", "entry": [{"id": IG_ID, "time": TIME, "messaging": [dm]}]})
    meta_post(_ig_comment())

    assert Contact.objects.count() == 1
    contact = Contact.objects.get()
    assert contact.instagram_handle == "ana.souza"
    assert set(contact.events.values_list("event_type", flat=True)) == {
        "instagram.message_received",
        "instagram.comment_received",
    }


@pytest.mark.django_db
def test_instagram_comment_is_idempotent(meta_post: Any) -> None:
    meta_post(_ig_comment())
    payload = _ig_comment()
    payload["entry"][0]["time"] = TIME + 1
    meta_post(payload)

    assert Event.objects.filter(event_type="instagram.comment_received").count() == 1


@pytest.mark.django_db
def test_own_account_comment_has_no_contact(meta_post: Any) -> None:
    meta_post(_ig_comment(from_id=IG_ID, text="Obrigado!"))

    event = Event.objects.get(event_type="instagram.comment_received")
    assert event.contact is None
    assert event.data["own_account"] is True
    assert not Contact.objects.exists()


@pytest.mark.django_db
def test_instagram_mention_becomes_event(meta_post: Any) -> None:
    meta_post(
        _ig_change("mentions", {"media_id": "1800000000000009", "comment_id": "1790000000000009"})
    )

    event = Event.objects.get(event_type="instagram.mention_received")
    assert event.external_id == "1790000000000009"
    assert event.channel == Channel.INSTAGRAM


@pytest.mark.django_db
def test_facebook_comment_without_known_identity_has_no_contact(meta_post: Any) -> None:
    meta_post(_fb_comment())

    assert WebhookDelivery.objects.get().status == DeliveryStatus.PROCESSED
    event = Event.objects.get(event_type="facebook.comment_received")
    assert event.external_id == f"{PAGE_ID}_222_333"
    assert event.summary == "Bia Lima: Como funciona?"
    assert event.contact is None
    assert not Contact.objects.exists()


@pytest.mark.django_db
def test_facebook_comment_links_to_existing_identity(meta_post: Any) -> None:
    contact = Contact.objects.create(name="Bia")
    ChannelIdentity.objects.create(
        contact=contact, channel=Channel.FACEBOOK, account_id=PAGE_ID, external_id=PSID
    )
    meta_post(_fb_comment(from_id=PSID))

    assert Event.objects.get(event_type="facebook.comment_received").contact == contact


@pytest.mark.django_db
def test_facebook_comment_edit_and_remove_are_separate_events(meta_post: Any) -> None:
    meta_post(_fb_comment())
    meta_post(_fb_comment(verb="edited"))
    meta_post(_fb_comment(verb="remove"))

    types = sorted(Event.objects.values_list("event_type", flat=True))
    assert types == [
        "facebook.comment_edited",
        "facebook.comment_received",
        "facebook.comment_removed",
    ]


@pytest.mark.django_db
def test_page_status_post_becomes_post_published(meta_post: Any) -> None:
    meta_post(
        _feed(
            {
                "item": "status",
                "post_id": f"{PAGE_ID}_444",
                "verb": "add",
                "published": 1,
                "created_time": 1794008719,
                "message": "Novo vídeo no canal",
                "from": {"name": "Brave2Grow", "id": PAGE_ID},
            }
        )
    )

    event = Event.objects.get(event_type="facebook.post_published")
    assert (event.external_id, event.summary) == (f"{PAGE_ID}_444", "Novo vídeo no canal")


@pytest.mark.django_db
def test_panel_feed_sample_is_processed_without_events(meta_post: Any) -> None:
    payload = _feed(
        {
            "item": "status",
            "post_id": "44444444_444444444",
            "verb": "add",
            "published": 1,
            "created_time": 1794008719,
            "message": "Example post content.",
            "from": {"name": "Test Page", "id": "1067280970047460"},
        }
    )
    payload["entry"][0]["id"] = "0"
    meta_post(payload)

    assert WebhookDelivery.objects.get().status == DeliveryStatus.PROCESSED
    assert not Event.objects.exists()
