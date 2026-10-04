"""Client reviews: written from a receipt's verify page, published by the owner."""

from tracker.models import Receipt, Review


def review_for(receipt: Receipt):
    """The review already written for this receipt's project, if any."""
    return Review.objects.filter(project_id=receipt.payment.project_id).first()


def submit_review(receipt: Receipt, rating: int, comment: str, display_name: str = "") -> Review:
    """Create or replace the review for the receipt's project.

    A new or edited review always waits for the owner's approval again, so
    nothing reaches the public site that the owner has not seen.
    """
    review, _ = Review.objects.update_or_create(
        project_id=receipt.payment.project_id,
        defaults={
            "receipt": receipt,
            "rating": rating,
            "comment": comment.strip(),
            "display_name": display_name.strip(),
            "status": Review.Status.PENDING,
        },
    )
    return review
